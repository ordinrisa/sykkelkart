#!/bin/bash
# Reduce the Norway OSM extract to candidate cycling ways, as line GeoJSON.
# Classification happens later in merge.py.
set -euo pipefail
cd "$(dirname "$0")/.."
RAW=data/raw/osm

osmium tags-filter --overwrite -o "$RAW/bike.osm.pbf" "$RAW/norway.osm.pbf" \
  w/highway=cycleway w/bicycle=designated,yes,permissive
osmium export --overwrite -f geojsonseq --geometry-types=linestring \
  -o "$RAW/bike.geojsonseq" "$RAW/bike.osm.pbf"
wc -l "$RAW/bike.geojsonseq"
