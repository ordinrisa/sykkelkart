#!/usr/bin/env python3
"""Download cycle paths from NVDB (Statens vegvesen).

Every API page is saved to disk, so an interrupted run resumes where it stopped.
Usage: fetch_nvdb.py [typeveg ...]
"""
import http.client
import json
import pathlib
import ssl
import sys
import time
import urllib.parse
import urllib.request

import certifi

BASE = "https://nvdbapiles.atlas.vegvesen.no/vegnett/api/v4/veglenkesekvenser/segmentert"
HEADERS = {"Accept": "application/json", "X-Client": "sykkelkart"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw" / "nvdb"
PAGE_SIZE = 1000
SSL = ssl.create_default_context(cafile=certifi.where())


def get(url, attempts=6):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=180, context=SSL) as resp:
                return json.load(resp)
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as err:
            if attempt == attempts - 1:
                raise
            wait = 5 * 2**attempt
            print(f"  retry in {wait}s: {err}", flush=True)
            time.sleep(wait)


def fetch(typeveg):
    folder = OUT / typeveg
    folder.mkdir(parents=True, exist_ok=True)
    pages = sorted(folder.glob("page_*.json"))
    start, number = None, 0
    if pages:
        last = json.loads(pages[-1].read_text())
        if last["metadata"]["returnert"] == 0 or "neste" not in last["metadata"]:
            print(f"{typeveg}: already complete ({len(pages)} pages)", flush=True)
            return
        start, number = last["metadata"]["neste"]["start"], len(pages)

    while True:
        params = {"typeveg": typeveg, "srid": "4326", "antall": PAGE_SIZE}
        if start:
            params["start"] = start
        page = get(f"{BASE}?{urllib.parse.urlencode(params)}")
        meta = page["metadata"]
        tmp = folder / f"page_{number:05d}.tmp"
        tmp.write_text(json.dumps(page))
        tmp.rename(folder / f"page_{number:05d}.json")
        print(f"{typeveg}: page {number}, {meta['returnert']} rows", flush=True)
        number += 1
        next_start = meta.get("neste", {}).get("start")
        if meta["returnert"] == 0 or not next_start or next_start == start:
            print(f"{typeveg}: done, {number} pages", flush=True)
            return
        start = next_start


if __name__ == "__main__":
    for typeveg in sys.argv[1:] or ["sykkelveg", "gangOgSykkelveg"]:
        fetch(typeveg)
