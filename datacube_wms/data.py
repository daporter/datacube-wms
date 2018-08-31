from __future__ import absolute_import, division, print_function
import json
from datetime import timedelta, datetime

import numpy
import xarray
from affine import Affine
import rasterio as rio
from rasterio.io import MemoryFile
from skimage.draw import polygon as skimg_polygon
from itertools import chain
import re

import datacube
from datacube.utils import geometry

from datacube_wms.cube_pool import get_cube, release_cube

from datacube_wms.wms_layers import get_service_cfg
from datacube_wms.wms_utils import img_coords_to_geopoint, int_trim, \
        bounding_box_to_geom, GetMapParameters, GetFeatureInfoParameters, \
        solar_correct_data
from datacube_wms.ogc_utils import resp_headers

import logging
import math
from datacube.utils import clamp

from datacube.drivers import new_datasource
import multiprocessing
from multiprocessing import cpu_count
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, wait, as_completed

from datacube_wms.rasterio_env import preauthenticate_s3, get_boto_session, get_rio_geotiff_georeference_source

_LOG = logging.getLogger(__name__)

# Calculates the approximate output shape and transform
# for loading data from src into geobox
def _calculate_transform(src, geobox):

    dc_crs = geometry.CRS(src.crs.to_string())
    geobox_transform = geobox.transform

    # Convert geobox transform to
    # src's crs if needed.
    # We allow rasterio to calculate resolution of geobox.
    if geobox.crs != dc_crs:
        bb = geobox.extent.boundingbox
        geobox_transform, _, _ = rio.warp.calculate_default_transform(
            str(geobox.crs),
            src.crs,
            geobox.width,
            geobox.height,
            left=bb.left,
            right=bb.right,
            top=bb.top,
            bottom=bb.bottom)

    # Calculate the output shape and corresponding transform
    # Always round up to ensure we do not miss data
    scale_affine = (~src.transform * geobox_transform)
    scale_a = math.ceil(abs(geobox_transform.a / src.transform.a))
    scale_e = math.ceil(abs(geobox_transform.e / src.transform.e))
    scale = min(scale_a, scale_e)

    out_shape = (math.ceil(src.shape[0] / scale), math.ceil(src.shape[1] / scale))
    out_shape_affine = Affine(
        (src.transform.a * scale),
        0,
        src.transform.c,
        0,
        (src.transform.e * scale),
        src.transform.f)

    return (out_shape, out_shape_affine)

def _calculate_and_load(filename, geobox, band_index):
    with rio.open(filename, sharing=False) as src:
        out_shape, out_shape_affine = _calculate_transform(src, geobox)
        data = src.read(out_shape=out_shape, indexes=band_index)
    return (out_shape_affine, src.crs, data)


def _get_measurement(datasources, geobox, no_data, dtype):
    #pylint: disable=broad-except
    dest = numpy.full(geobox.shape, no_data, dtype=dtype)
    sources = {(d.filename, d.get_bandnumber()) for d in datasources}
    try:
        for f, band_index in sources:
            src_transform, src_crs, data = _calculate_and_load(f, geobox, band_index)
            rio.warp.reproject(
                data,
                dest,
                init_dest_nodata=False,
                src_nodata=no_data,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=geobox.transform,
                dst_crs=str(geobox.crs),
                resampling=rio.warp.Resampling.nearest)
    except Exception as e:
        _LOG.error("Error getting measurement! %s", e)

    return dest


# Read data for given datasets and mesaurements per the output_geobox
# If use_overviews is true
# Do not use this function to load data where accuracy is important
# may have errors when reprojecting the data
def read_data(datasets, measurements, geobox, use_overviews=False, **kwargs):
    #pylint: disable=too-many-locals, dict-keys-not-iterating
    session = get_boto_session()
    geotiff_src = get_rio_geotiff_georeference_source()
    with rio.Env(session=session, GDAL_GEOREF_SOURCES=geotiff_src) as rio_env:
        if use_overviews:
            if not hasattr(datasets, "__iter__"):
                datasets = [datasets]
            all_bands = xarray.Dataset()
            with ThreadPoolExecutor(max_workers=min(len(measurements), cpu_count() * 2)) as executor:
                futures = dict()
                for measurement in measurements:
                    datasources = {new_datasource(d, measurement['name']) for d in datasets}
                    future = executor.submit(_get_measurement,
                                             datasources,
                                             geobox,
                                             measurement['nodata'],
                                             measurement['dtype']
                                            )
                    futures[future] = measurement

                for f in as_completed(futures.keys()):
                    measurement = futures[f]
                    final = xarray.DataArray(f.result(),
                                             dims=('x', 'y'),
                                             attrs=measurement.dataarray_attrs()
                                            )
                    all_bands[measurement['name']] = final
            all_bands.attrs['crs'] = geobox.crs
            return all_bands
        else:
            holder = numpy.empty(shape=tuple(), dtype=object)
            holder[()] = [datasets]
            sources = xarray.DataArray(holder)
            return datacube.Datacube.load_data(sources, geobox, measurements, **kwargs)


class DataStacker():
    def __init__(self, product, geobox, time, style=None, bands=None, **kwargs):
        super(DataStacker, self).__init__(**kwargs)
        self._product = product
        self._geobox = geobox
        if style:
            self._needed_bands = style.needed_bands
        elif bands:
            self._needed_bands = bands
        else:
            self._needed_bands = self._product.product.measurements.keys()
        start_time = datetime(time.year, time.month, time.day) - timedelta(hours=product.time_zone)
        self._time = [start_time, start_time + timedelta(days=1)]

    def needed_bands(self):
        return self._needed_bands

    def point_in_dataset_by_extent(self, point, dataset):
        # Return true if dataset contains point
        compare_geometry = dataset.extent.to_crs(self._geobox.crs)
        return compare_geometry.contains(point)

    def datasets(self, index, mask=False, all_time=False, point=None):
        # Setup
        if all_time:
            # Use full available time range
            times = self._product.ranges["times"]
            time = [times[0], times[-1] + timedelta(days=1)]
        else:
            time = self._time
        if mask and self._product.pq_name:
            # Use PQ product
            prod_name = self._product.pq_name
        elif mask:
            # No PQ product, so no PQ datasets.
            return []
        else:
            # Use band product
            prod_name = self._product.product_name

        # ODC Dataset Query
        query = datacube.api.query.Query(product=prod_name, geopolygon=self._geobox.extent, time=time)
        _LOG.debug("query start %s", datetime.now().time())
        datasets = index.datasets.search_eager(**query.search_terms)
        _LOG.debug("query stop %s", datetime.now().time())
        # And sort by date
        try:
            datasets = sorted(datasets, key=lambda d: d.center_time)
        except:
            msg = ""
            for ds in datasets:
                msg += str(ds.id) + ":" + str(ds.center_time) + str(ds.center_time.utcoffset()) + ", "
            raise Exception("Yes we have inconsistent offset state: " + msg)

        # datasets.sort(key=lambda d: d.center_time)

        if point:
            # Interested in a single point (i.e. GetFeatureInfo)
            def filt_func(dataset):
                # Cleanup Note. Previously by_bounds was used for PQ data
                return self.point_in_dataset_by_extent(point, dataset)
            return list(filter(filt_func, iter(datasets)))
        else:
            # Interested in a larger tile (i.e. GetMap)
            if not mask and self._product.data_manual_merge:
                # Band-data manual merge, do no further filtering of datasets.
                return datasets
            elif mask and self._product.pq_manual_merge:
                # PQ manual merge, do no further filtering of datasets.
                return datasets
            else:
                # Remove un-needed or redundant datasets
                return self.filter_datasets_by_extent(datasets)

    def filter_datasets_by_extent(self, datasets):
        #pylint: disable=too-many-branches, dict-keys-not-iterating
        date_index = {}
        for dataset in iter(datasets):
            # Build a date-index of intersecting datasets
            if dataset.extent.to_crs(self._geobox.crs).intersects(self._geobox.extent):
                if dataset.center_time in date_index:
                    date_index[dataset.center_time].append(dataset)
                else:
                    date_index[dataset.center_time] = [dataset]
        if not date_index:
            # No datasets intersect geobox
            return []

        date_extents = {}
        for dt, dt_dss in date_index.items():
            # Loop over dates in the date index

            # Build up a net extent of all datasets for this date
            geom = None
            for ds in dt_dss:
                if geom is None:
                    geom = ds.extent.to_crs(self._geobox.crs)
                else:
                    geom = geom.union(ds.extent.to_crs(self._geobox.crs))
            if geom.contains(self._geobox.extent):
                # This date fully overs the tile bounding box, just return it.
                return dt_dss
            date_extents[dt] = geom

        dates = date_extents.keys()

        # Sort by size of geometry
        biggest_geom_first = sorted(dates, key=lambda x: [date_extents[x].area, x], reverse=True)

        accum_geom = None
        filtered = []
        for d in biggest_geom_first:
            geom = date_extents[d]
            if accum_geom is None:
                accum_geom = geom
                filtered.extend(date_index[d])
            elif not accum_geom.contains(geom):
                accum_geom = accum_geom.union(geom)
                filtered.extend(date_index[d])
        return filtered

    def data(self, datasets, mask=False, manual_merge=False, skip_corrections=False, use_overviews=False, **kwargs):
        #pylint: disable=too-many-locals, consider-using-enumerate
        if mask:
            prod = self._product.pq_product
            measurements = [prod.measurements[self._product.pq_band].copy()]
        else:
            prod = self._product.product
            measurements = [prod.measurements[name].copy() for name in self.needed_bands()]

        with datacube.set_options(reproject_threads=1, fast_load=True):
            if manual_merge:
                return self.manual_data_stack(datasets, measurements, mask, skip_corrections, use_overviews, **kwargs)
            elif self._product.solar_correction and not mask and not skip_corrections:
                # Merge performed already by dataset extent, but we need to
                # process the data for the datasets individually to do solar correction.
                merged = None
                for i in range(0, len(datasets)):
                    holder = numpy.empty(shape=tuple(), dtype=object)
                    ds = datasets[i]
                    d = read_data(ds, measurements, self._geobox, use_overviews, **kwargs)
                    for band in self.needed_bands():
                        if band != self._product.pq_band:
                            d[band] = solar_correct_data(d[band], ds)
                    if merged is None:
                        merged = d
                    else:
                        merged = merged.combine_first(d)
                return merged
            else:
                # Merge performed already by dataset extent
                if isinstance(datasets, xarray.DataArray):
                    sources = datasets
                else:
                    holder = numpy.empty(shape=tuple(), dtype=object)
                    holder[()] = datasets
                    sources = xarray.DataArray(holder)
                data = read_data(datasets, measurements, self._geobox, use_overviews, **kwargs)
                return data

    def manual_data_stack(self, datasets, measurements, mask, skip_corrections, use_overviews, **kwargs):
        #pylint: disable=too-many-locals, too-many-branches, consider-using-enumerate
        # manual merge
        merged = None
        if mask:
            bands = [self._product.pq_band]
        else:
            bands = self.needed_bands()
        for i in range(0, len(datasets)):
            holder = numpy.empty(shape=tuple(), dtype=object)
            ds = datasets[i]
            d = read_data(ds, measurements, self._geobox, use_overviews, **kwargs)
            extent_mask = None
            for band in bands:
                for f in self._product.extent_mask_func:
                    if extent_mask is None:
                        extent_mask = f(d, band)
                    else:
                        extent_mask &= f(d, band)
            dm = d.where(extent_mask)
            if self._product.solar_correction and not mask and not skip_corrections:
                for band in bands:
                    if band != self._product.pq_band:
                        dm[band] = solar_correct_data(dm[band], ds)
            if merged is None:
                merged = dm
            else:
                merged = merged.combine_first(dm)
        if mask:
            merged = merged.astype('uint8', copy=True)
            for band in bands:
                merged[band].attrs = d[band].attrs
        return merged

def get_map(args):
    # pylint: disable=too-many-nested-blocks, too-many-branches, too-many-statements, too-many-locals
    # Parse GET parameters
    params = GetMapParameters(args)

    dc = get_cube()
     # Tiling.
    stacker = DataStacker(params.product, params.geobox, params.time, style=params.style)
    try:
        datasets = stacker.datasets(dc.index)
        zoomed_out = params.zf < params.product.min_zoom
        too_many_datasets = (params.product.max_datasets_wms > 0 and len(datasets) > params.product.max_datasets_wms)
        if not datasets:
            body = _write_empty(params.geobox)
        elif zoomed_out or too_many_datasets:
            # Zoomed out to far to properly render data.
            # Construct a polygon which is the union of the extents of the matching datasets.
            extent = None
            extent_crs = None
            for ds in datasets:
                if extent:
                    new_extent = ds.extent
                    if new_extent.crs != extent_crs:
                        new_extent = new_extent.to_crs(extent_crs)
                    extent = extent.union(new_extent)
                else:
                    extent = ds.extent
                    extent_crs = extent.crs
            extent = extent.to_crs(params.crs)

            body = _write_polygon(params.geobox, extent, params.product.zoom_fill)
        else:
            _LOG.debug("load start %s %s", datetime.now().time(), args["requestid"])
            data = stacker.data(datasets, manual_merge=params.product.data_manual_merge, use_overviews=True)
            _LOG.debug("load stop %s %s", datetime.now().time(), args["requestid"])
            if params.style.masks:
                if params.product.pq_name == params.product.name:
                    pq_band_data = (data[params.product.pq_band].dims, data[params.product.pq_band].astype("uint16"))
                    pq_data = xarray.Dataset({params.product.pq_band: pq_band_data},
                                             coords=data[params.product.pq_band].coords
                                            )
                    flag_def = data[params.product.pq_band].flags_definition
                    pq_data[params.product.pq_band].attrs["flags_definition"] = flag_def
                else:
                    pq_datasets = stacker.datasets(dc.index, mask=True)
                    if pq_datasets:
                        pq_data = stacker.data(pq_datasets,
                                               mask=True,
                                               manual_merge=params.product.pq_manual_merge,
                                               use_overviews=True)
                    else:
                        pq_data = None
            else:
                pq_data = None
            extent_mask = None
            if not params.product.data_manual_merge:
                for band in params.style.needed_bands:
                    for f in params.product.extent_mask_func:
                        if extent_mask is None:
                            extent_mask = f(data, band)
                        else:
                            extent_mask &= f(data, band)

            if data is not None:
                body = _write_png(data, pq_data, params.style, extent_mask)
            else:
                body = _write_empty(params.geobox)
        release_cube(dc)
    except Exception as e:
        release_cube(dc)
        raise e
    return body, 200, resp_headers({"Content-Type": "image/png"})


def _write_png(data, pq_data, style, extent_mask):
    width = data[data.crs.dimensions[1]].size
    height = data[data.crs.dimensions[0]].size

    img_data = style.transform_data(data, pq_data, extent_mask)

    with MemoryFile() as memfile:
        with memfile.open(driver='PNG',
                          width=width,
                          height=height,
                          count=3,
                          transform=Affine.identity(),
                          nodata=0,
                          dtype='uint8') as thing:
            scaled = None
            for idx, band in enumerate(img_data.data_vars, start=1):
                thing.write_band(idx, img_data[band].values)

        return memfile.read()


def _write_empty(geobox):
    with MemoryFile() as memfile:
        with memfile.open(driver='PNG',
                          width=geobox.width,
                          height=geobox.height,
                          count=1,
                          transform=Affine.identity(),
                          nodata=0,
                          dtype='uint8') as thing:
            pass
        return memfile.read()


def _write_polygon(geobox, polygon, zoom_fill):
    geobox_ext = geobox.extent
    if geobox_ext.within(polygon):
        data = numpy.full([geobox.height, geobox.width], fill_value=1, dtype="uint8")
    else:
        data = numpy.zeros([geobox.height, geobox.width], dtype="uint8")
        if not geobox_ext.disjoint(polygon):
            intersection = geobox_ext.intersection(polygon)
            if intersection.type == 'Polygon':
                coordinates_list = [intersection.json["coordinates"]]
            elif intersection.type == 'MultiPolygon':
                coordinates_list = intersection.json["coordinates"]
            else:
                raise Exception("Unexpected extent/geobox intersection geometry type: %s" % intersection.type)
            for polygon_coords in coordinates_list:
                pixel_coords = [~geobox.transform * coords for coords in polygon_coords[0]]
                rs, cs = skimg_polygon([int_trim(c[1], 0, geobox.height - 1) for c in pixel_coords],
                                       [int_trim(c[0], 0, geobox.width - 1) for c in pixel_coords])
                data[rs, cs] = 1
    with MemoryFile() as memfile:
        with memfile.open(driver='PNG',
                          width=geobox.width,
                          height=geobox.height,
                          count=len(zoom_fill),
                          transform=Affine.identity(),
                          nodata=0,
                          dtype='uint8') as thing:
            for idx, fill in enumerate(zoom_fill, start=1):
                thing.write_band(idx, data * fill)
        return memfile.read()


def get_s3_browser_uris(datasets):
    uris = [d.uris for d in datasets]
    uris = list(chain.from_iterable(uris))
    unique_uris = set(uris)

    # convert to browsable link
    def convert(uri):
        regex = re.compile(r"s3:\/\/(?P<bucket>[a-zA-Z0-9_\-]+)\/(?P<prefix>[\S]+)ARD-METADATA.yaml")
        uri_format = "http://{bucket}.s3-website-ap-southeast-2.amazonaws.com/?prefix={prefix}"
        result = regex.match(uri)
        if result is not None:
            new_uri = uri_format.format(bucket=result.group("bucket"),
                                        prefix=result.group("prefix"))
        else:
            new_uri = uri
        return new_uri

    formatted = [convert(uri) for uri in unique_uris]

    return formatted


def feature_info(args):
    # pylint: disable=too-many-nested-blocks, too-many-branches, too-many-statements, too-many-locals
    # Parse GET parameters
    params = GetFeatureInfoParameters(args)

    # Prepare to extract feature info
    stacker = DataStacker(params.product, params.geobox, params.time)
    feature_json = {}

    # --- Begin code section requiring datacube.
    service_cfg = get_service_cfg()
    dc = get_cube()
    try:
        geo_point = img_coords_to_geopoint(params.geobox, params.i, params.j)
        datasets = stacker.datasets(dc.index,
                                    all_time=True,
                                    point=geo_point
                                   )
        pq_datasets = stacker.datasets(dc.index,
                                       mask=True,
                                       all_time=False,
                                       point=geo_point
                                      )

        h_coord = service_cfg.published_CRSs[params.crsid]["horizontal_coord"]
        v_coord = service_cfg.published_CRSs[params.crsid]["vertical_coord"]
        isel_kwargs = {
            h_coord: [params.i],
            v_coord: [params.j]
        }
        if not datasets:
            pass
        else:
            available_dates = set()
            drill = {}
            for d in datasets:
                idx_date = (d.center_time + timedelta(hours=params.product.time_zone)).date()
                available_dates.add(idx_date)
                pixel_ds = None
                if idx_date == params.time and "lon" not in feature_json:
                    data = stacker.data([d], skip_corrections=True)

                    # Use i,j image coordinates to extract data pixel from dataset, and
                    # convert to lat/long geographic coordinates
                    if service_cfg.published_CRSs[params.crsid]["geographic"]:
                        # Geographic coordinate systems (e.g. EPSG:4326/WGS-84) are already in lat/long
                        feature_json["lat"] = data.latitude[params.j].item()
                        feature_json["lon"] = data.longitude[params.i].item()
                        pixel_ds = data.isel(**isel_kwargs)
                    else:
                        # Non-geographic coordinate systems need to be projected onto a geographic
                        # coordinate system.  Why not use EPSG:4326?
                        # Extract coordinates in CRS
                        data_x = getattr(data, h_coord)
                        data_y = getattr(data, v_coord)

                        x = data_x[params.i].item()
                        y = data_y[params.j].item()
                        pt = geometry.point(x, y, params.crs)

                        # Project to EPSG:4326
                        crs_geo = geometry.CRS("EPSG:4326")
                        ptg = pt.to_crs(crs_geo)

                        # Capture lat/long coordinates
                        feature_json["lon"], feature_json["lat"] = ptg.coords[0]

                    # Extract data pixel
                    pixel_ds = data.isel(**isel_kwargs)

                    # Get accurate timestamp from dataset
                    feature_json["time"] = d.center_time.strftime("%Y-%m-%d %H:%M:%S UTC")

                    # Collect raw band values for pixel
                    feature_json["bands"] = {}
                    for band in stacker.needed_bands():
                        band_val = pixel_ds[band].item()
                        if band_val == -999:
                            feature_json["bands"][band] = "n/a"
                        else:
                            feature_json["bands"][band] = pixel_ds[band].item()
                if params.product.band_drill:
                    if pixel_ds is None:
                        data = stacker.data([d], skip_corrections=True)
                        pixel_ds = data.isel(**isel_kwargs)
                    drill_section = {}
                    for band in params.product.band_drill:
                        band_val = pixel_ds[band].item()
                        if band_val == -999:
                            drill_section[band] = "n/a"
                        else:
                            drill_section[band] = pixel_ds[band].item()
                    drill[idx_date.strftime("%Y-%m-%d")] = drill_section
            if drill:
                feature_json["time_drill"] = drill
                feature_json["datasets_read"] = len(datasets)
            my_flags = 0
            pqdi = -1
            for pqd in pq_datasets:
                pqdi += 1
                idx_date = (pqd.center_time + timedelta(hours=params.product.time_zone)).date()
                if idx_date == params.time:
                    pq_data = stacker.data([pqd], mask=True)
                    pq_pixel_ds = pq_data.isel(**isel_kwargs)
                    # PQ flags
                    m = params.product.pq_product.measurements[params.product.pq_band]
                    flags = pq_pixel_ds[params.product.pq_band].item()
                    if not flags & ~params.product.info_mask:
                        my_flags = my_flags | flags
                    else:
                        continue
                    feature_json["flags"] = {}
                    for mk, mv in m["flags_definition"].items():
                        if mk in params.product.ignore_flags_info:
                            continue
                        bits = mv["bits"]
                        values = mv["values"]
                        if not isinstance(bits, int):
                            continue
                        flag = 1 << bits
                        if my_flags & flag:
                            val = values['1']
                        else:
                            val = values['0']
                        feature_json["flags"][mk] = val

            lads = list(available_dates)
            lads.sort()
            feature_json["data_available_for_dates"] = [d.strftime("%Y-%m-%d") for d in lads]
            feature_json["data_links"] = sorted(get_s3_browser_uris(datasets))
        release_cube(dc)
    except Exception as e:
        release_cube(dc)
        raise e
    # --- End code section requiring datacube.

    result = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": feature_json
            }
        ]
    }
    return json.dumps(result), 200, resp_headers({"Content-Type": "application/json"})
