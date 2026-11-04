# Sykkelkart

Interactive map of cycle paths in Norway, with normal, satellite and 3D views.
The default layer shows only paths built for bikes. Painted lanes and pavements are left out.

## Refresh the data

```bash
python3 -m venv .venv && .venv/bin/pip install shapely certifi
brew install tippecanoe osmium-tool
.venv/bin/python scripts/fetch_nvdb.py
.venv/bin/python scripts/fetch_routes.py
mkdir -p data/raw/osm && curl -L -o data/raw/osm/norway.osm.pbf https://download.openstreetmap.fr/extracts/europe/norway-latest.osm.pbf
scripts/filter_osm.sh
.venv/bin/python scripts/merge.py
scripts/build_tiles.sh
```

## Run locally

```bash
npx http-server@14.1.1 web -p 8127 -c-1
```

## Data and credits

- Statens vegvesen NVDB (NLOD)
- OpenStreetMap contributors (ODbL)
- Kartverket: topo map and Turrutebasen (CC BY 4.0)
- Esri World Imagery
- Terrain: Mapzen, AWS Open Data
