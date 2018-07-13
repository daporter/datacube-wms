import datacube
import pytest
import datetime

import xml.etree.ElementTree as et

from datacube_wms.data import get_map
import flask


# def test_map_zoomedout(cube, release_cube_dummy, mocker):
#     mocker.patch('datacube_wms.data.get_cube', cube)
#     mocker.patch('datacube_wms.wms_layers.get_cube', cube)
#     mocker.patch('datacube_wms.data.release_cube', release_cube_dummy)
#     mocker.patch('datacube_wms.wms_layers.release_cube', release_cube_dummy)

#     app = flask.Flask("test", root_path="/Users/robbie/dev/datacube-wms/datacube_wms")
#     with app.test_request_context('/?GetMap'):
#         args = {}
#         resp = get_map(None)
#         root = et.fromstring(resp[0])

#         query_layers = root.findall(".//{http://www.opengis.net/wms}Layer[@queryable]")
#         assert len(query_layers) == 1
#         names = [t.find("{http://www.opengis.net/wms}Name").text for t in query_layers]
#         assert "ls8_nbart_geomedian_annual" in names
#         assert query_layers[0].find("./{http://www.opengis.net/wms}EX_GeographicBoundingBox/{http://www.opengis.net/wms}westBoundLongitude").text == "117.38198877598595"
#         assert query_layers[0].find("./{http://www.opengis.net/wms}EX_GeographicBoundingBox/{http://www.opengis.net/wms}eastBoundLongitude").text == "118.45187549676838"
#         assert query_layers[0].find("./{http://www.opengis.net/wms}EX_GeographicBoundingBox/{http://www.opengis.net/wms}southBoundLatitude").text == "-21.625127734743167"
#         assert query_layers[0].find("./{http://www.opengis.net/wms}EX_GeographicBoundingBox/{http://www.opengis.net/wms}northBoundLatitude").text == "-20.63475508625344"
#         boundingbox_3577 = query_layers[0].find("./{http://www.opengis.net/wms}BoundingBox[@CRS='EPSG:3577']")
#         assert boundingbox_3577.get("minx") == "-1500000.0"
#         assert boundingbox_3577.get("maxx") == "-1400000.0"
#         assert boundingbox_3577.get("miny") == "-2400000.0"
#         assert boundingbox_3577.get("maxy") == "-2300000.0"
#         boundingbox_3857 = query_layers[0].find("./{http://www.opengis.net/wms}BoundingBox[@CRS='EPSG:3857']")
#         assert boundingbox_3857.get("minx") == "13066903.218844512"
#         assert boundingbox_3857.get("maxx") == "13186002.4638085"
#         assert boundingbox_3857.get("miny") == "-2466576.4072137373"
#         assert boundingbox_3857.get("maxy") == "-2348379.93955229"
#         boundingbox_4326 = query_layers[0].find("./{http://www.opengis.net/wms}BoundingBox[@CRS='EPSG:4326']")
#         assert boundingbox_4326.get("minx") == "117.38198877598595"
#         assert boundingbox_4326.get("maxx") == "118.45187549676838"
#         assert boundingbox_4326.get("miny") == "-21.625127734743167"
#         assert boundingbox_4326.get("maxy") == "-20.63475508625344"
#         time = query_layers[0].find("./{http://www.opengis.net/wms}Dimension[@name='time']")
#         assert time.get("units") == "ISO8601"
#         assert "2015-01-01" in time.text


zoomedin_testdata = [
    (1,
    {"srs": "EPSG:3857",
        "styles": "",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "256",
        "height": "256",
        "bbox": "13149614.84995544,-2387281.2674026266,13188750.608437452,-2348145.5089206137"},
    "data/get_map_zoomedin/zoomedin_1.png"),
    (2,
    {"srs": "EPSG:3857",
        "styles": "",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "256",
        "height": "256",
        "bbox": "13032207.574509412,-2426417.0258846357,13071343.332991421,-2387281.2674026266"},
    "data/get_map_zoomedin/zoomedin_2.png"),
    (3,
    {"srs": "EPSG:3857",
        "styles": "infra_red",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "256",
        "height": "256",
        "bbox": "13071343.332991421,-2387281.2674026266,13110479.09147343,-2348145.5089206137"},
    "data/get_map_zoomedin/zoomedin_3.png"),
    (4,
    {"srs": "EPSG:3857",
        "styles": "infrared_green",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "256",
        "height": "256",
        "bbox": "13071343.332991421,-2387281.2674026266,13110479.09147343,-2348145.5089206137"},
    "data/get_map_zoomedin/zoomedin_4.png"),
    (5,
    {"srs": "EPSG:3857",
        "styles": "infrared_green",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "512",
        "height": "256",
        "bbox": "13071343.332991421,-2387281.2674026266,13110479.09147343,-2348145.5089206137"},
    "data/get_map_zoomedin/zoomedin_5.png"),
    (5,
    {"srs": "EPSG:3857",
        "styles": "infrared_green",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "1017",
        "height": "257",
        "bbox": "13071343.332991421,-2387281.2674026266,13110479.09147343,-2348145.5089206137"},
    "data/get_map_zoomedin/zoomedin_6.png"),
    (5,
    {"srs": "EPSG:3577",
        "styles": "infrared_green",
        "tiled": True,
        "feature_count": 101,
        "version": "1.1.1",
        "layers": "ls8_nbart_geomedian_annual",
        "format": "image/png",
        "width": "1017",
        "height": "257",
        "bbox": "-1503093.67,-2336982.04,-1471065.71,-2296511.45"},
    "data/get_map_zoomedin/zoomedin_7.png")
]

# -20.9614396,117.421875,-20.6327842,117.7734375
# -20.9614396%2C117.421875%2C-20.6327842%2C117.7734375
# 117.421875%2C-20.9614396%2C117.7734375%2C-20.6327842

@pytest.mark.parametrize("id, test_args, expect_png", zoomedin_testdata)
def test_map_zoomedin(cube, release_cube_dummy, mocker, id, test_args, expect_png):
    app = flask.Flask("test", root_path="/Users/robbie/dev/datacube-wms/datacube_wms")
    with app.test_request_context('/?GetMap'):
        args = {}
        resp = get_map(test_args)
        with open(expect_png) as png:
            resp == png
