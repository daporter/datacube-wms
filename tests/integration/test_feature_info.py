import datacube
import pytest

from datacube_wms.data import DataStacker

def test_compose(cube, release_cube_dummy, mocker):
    mocker.patch('datacube_wms.data.get_cube', cube)
    mocker.patch('datacube_wms.wms_layers.get_cube', cube)
    mocker.patch('datacube_wms.data.release_cube', release_cube_dummy)
    mocker.patch('datacube_wms.wms_layers.release_cube', release_cube_dummy)

    stacker = DataStacker('s2b_nrt_granule', None, '2008-01-01')