import sys
import os
from datacube_wms.ogc import app

# This is the directory of the source code that the web app will run from
sys.path.append("/home/phaesler/src/datacube/wms")

# The location of the datcube config file.
os.environ.setdefault(
    "DATACUBE_CONFIG_PATH",
    "/home/phaesler/.datacube.conf.local")

# pylint: disable=invalid-name
application = app
