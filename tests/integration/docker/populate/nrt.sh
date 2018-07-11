#! /usr/bin/env bash

# Populate the db with nrt data
datacube system init

# Add products
wget https://raw.githubusercontent.com/GeoscienceAustralia/dea-config/master/prod/products/nrt/sentinel/products.yaml
datacube product add products.yaml

pip3 install ruamel.yaml
# get indexer
wget https://raw.githubusercontent.com/opendatacube/datacube-ecs/b6779c5e3bb480914aeb38f4ac127d61346d58f3/indexer/ls_s2_cog.py

# Set data
python3 ls_s2_cog.py dea-public-data --prefix "projects/2018-04-MDBA/Section_4_Louth_to_Menindee/SENTINEL-L2/2018-07-06/" --suffix ".yaml"