#!/usr/bin/env bash
# Convenience script for running Travis-like checks.

set -eu
set -x

pylint -j 2 --reports no datacube_wms

# Run tests, taking coverage.
# Users can specify extra folders as arguments.
# pytest -r sx --cov datacube_wms --doctest-ignore-import-errors --durations=5 --ignore=tests/integration datacube_wms tests

cd tests/integration; ./run_integration_test.sh "geomedian.sh" "geomedian_cfg.py"

set +x
