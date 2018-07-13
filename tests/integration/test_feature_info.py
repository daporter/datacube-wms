import datacube
import pytest

from datacube_wms.data import feature_info
import flask
import json

def test_compose(cube, release_cube_dummy, mocker):
    mocker.patch('datacube_wms.data.get_cube', cube)
    mocker.patch('datacube_wms.wms_layers.get_cube', cube)
    mocker.patch('datacube_wms.data.release_cube', release_cube_dummy)
    mocker.patch('datacube_wms.wms_layers.release_cube', release_cube_dummy)

    # stacker = DataStacker('s2b_nrt_granule', None, '2008-01-01')
    app = flask.Flask("test", root_path="/Users/robbie/dev/datacube-wms/datacube_wms")
    with app.test_request_context('/?GetFeatureInfo'):
        args = {}
        args["query_layers"] = "ls8_nbart_geomedian_annual"
        args["version"] = "1.1.1"
        args["x"] = "210"
        args["y"] = "109"
        args["srs"] = "EPSG:3857"
        args["time"] = "2015-01-01"
        args["width"] = "256"
        args["height"] = "256"
        args["bbox"] ="12993071.8160274,-2504688.542848654,13149614.84995544,-2348145.5089206137"
        args["info_format"] = "application/json"
        args["feature_count"] = "101"
        result = json.loads(feature_info(args)[0])

        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) == 1
        feature = result["features"][0]
        properties = feature["properties"]
        bands = properties["bands"]
        assert properties["lon"] == 117.87506103515621
        assert properties["lat"] == -21.194655303138624
        assert properties["time"] == "2015-01-01 00:00:00 UTC"
        assert bands["blue"] == 632
        assert bands["green"] == 1098
        assert bands["red"] == 1706
        assert bands["nir"] == 2618
        assert bands["swir1"] == 3353
        assert bands["swir2"] == 2685
        assert properties["data_available_for_dates"][0] == "2015-01-01"
        assert properties["data_links"][0] == "s3://dea-test-store/geomedian-australia/v2.1.0/L8/x_-15/y_-24/2015/01/01/ls8_gm_nbart_-15_-24_20150101.yaml"