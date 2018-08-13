FROM opendatacube/wms:0.3.1

RUN pip3 install \
    ruamel.yaml \
    && rm -rf $HOME/.cache/pip

WORKDIR indexing

COPY assets/update_ranges.sh update_ranges.sh
COPY assets/update_ranges_wrapper.sh update_ranges_wrapper.sh
RUN wget https://raw.githubusercontent.com/daporter/prepare_script_landsat/master/ls_public_bucket.py

WORKDIR ..

CMD /bin/bash -c indexing/update_ranges_wrapper.sh
