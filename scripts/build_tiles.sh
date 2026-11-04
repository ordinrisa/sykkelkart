#!/bin/bash
# Build the map's vector tiles from the merged data: a light overview for low
# zooms, and every line from zoom 10 upward.
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

tippecanoe -o "$TMP/overview.pmtiles" --force -l paths -n "Sykkelkart" \
  -Z4 -z9 -r1 --read-parallel --quiet \
  --simplification=12 \
  --minimum-detail=8 --full-detail=10 --low-detail=9 \
  --maximum-tile-bytes=90000 \
  --drop-smallest-as-needed \
  -y class -y kind -y source -y length_m \
  data/sykkel.geojsonseq

tippecanoe -o "$TMP/detail.pmtiles" --force -l paths -n "Sykkelkart" \
  -Z10 -z14 -r1 --read-parallel --quiet \
  --simplification=4 \
  data/sykkel.geojsonseq

tile-join -o web/data/sykkel.pmtiles --force --no-tile-size-limit --quiet \
  "$TMP/overview.pmtiles" "$TMP/detail.pmtiles"
ls -lh web/data/sykkel.pmtiles
