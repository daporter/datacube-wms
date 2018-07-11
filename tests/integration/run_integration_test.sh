#! /usr/bin/env bash

pushd docker
POPULATE=$1 docker-compose up -d
popd
sleep 30
pytest --db_hostname="localhost" --db_port=54321
pushd docker
POPULATE=$1 docker-compose down
popd