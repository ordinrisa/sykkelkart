#!/usr/bin/env python3
"""Download signed cycle routes: NVDB object types 705 and 907, and Turrutebasen.

These routes often follow car roads, so the map keeps them on separate layers.
"""
import http.client
import json
import pathlib
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import certifi

NVDB = "https://nvdbapiles.atlas.vegvesen.no/vegobjekter/api/v4/vegobjekter"
WFS = "https://wfs.geonorge.no/skwms1/wfs.turogfriluftsruter"
HEADERS = {"Accept": "application/json", "X-Client": "sykkelkart"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "routes"
SSL = ssl.create_default_context(cafile=certifi.where())
APP = "{http://skjema.geonorge.no/SOSI/produktspesifikasjon/TurOgFriluftsruter/20171210}"
GML = "{http://www.opengis.net/gml/3.2}"
WFS_PAGE = 1000


def get(url, headers=None, attempts=6):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=300, context=SSL) as resp:
                return resp.read()
        except (OSError, http.client.HTTPException) as err:
            if attempt == attempts - 1:
                raise
            wait = 5 * 2**attempt
            print(f"  retry in {wait}s: {err}", flush=True)
            time.sleep(wait)


def fetch_nvdb(type_id):
    target = OUT / f"nvdb_{type_id}.json"
    if target.exists():
        print(f"{type_id}: already downloaded", flush=True)
        return
    objects, start = [], None
    while True:
        params = {"inkluder": "egenskaper,geometri", "srid": "4326", "antall": 1000}
        if start:
            params["start"] = start
        page = json.loads(get(f"{NVDB}/{type_id}?{urllib.parse.urlencode(params)}", HEADERS))
        objects += page["objekter"]
        meta = page["metadata"]
        print(f"{type_id}: {len(objects)} objects", flush=True)
        next_start = meta.get("neste", {}).get("start")
        if meta["returnert"] == 0 or not next_start or next_start == start:
            break
        start = next_start
    target.write_text(json.dumps(objects))


def fetch_wfs():
    target = OUT / "turrutebasen.geojsonseq"
    if target.exists():
        print("turrutebasen: already downloaded", flush=True)
        return
    tmp = target.with_suffix(".tmp")
    total, index = 0, 0
    with tmp.open("w") as out:
        while True:
            params = {
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": "app:Sykkelrute", "count": WFS_PAGE, "startIndex": index,
            }
            root = ET.fromstring(get(f"{WFS}?{urllib.parse.urlencode(params)}"))
            members = root.findall("{http://www.opengis.net/wfs/2.0}member")
            for member in members:
                feature = member[0]
                name = feature.findtext(f".//{APP}rutenavn") or feature.findtext(f".//{APP}navn")
                info = feature.findtext(f"{APP}informasjon")
                for pos in feature.iter(f"{GML}posList"):
                    # EPSG:4258 lists lat lon
                    values = [float(v) for v in pos.text.split()]
                    coords = [[values[i + 1], values[i]] for i in range(0, len(values), 2)]
                    if len(coords) > 1:
                        out.write(json.dumps({
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": coords},
                            "properties": {"name": name, "info": info},
                        }) + "\n")
                        total += 1
            print(f"turrutebasen: {index + len(members)} features", flush=True)
            if len(members) < WFS_PAGE:
                break
            index += WFS_PAGE
    tmp.rename(target)
    print(f"turrutebasen: wrote {total} lines", flush=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fetch_nvdb(705)
    fetch_nvdb(907)
    fetch_wfs()
