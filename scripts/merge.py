#!/usr/bin/env python3
"""Combine NVDB, OSM and route data into one line file plus a coverage report.

Classes:
  dedicated       Paths built for bikes (on by default in the map)
  trail           OSM paths, footways and tracks where cycling is allowed
  route_national  National cycle routes (may follow car roads)
  route_urban     Main urban cycle networks (may follow car roads)
  route_local     Turrutebasen cycle routes (may follow car roads)
"""
import collections
import json
import math
import pathlib

import numpy as np
import shapely

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "sykkel.geojsonseq"
REPORT = ROOT / "web" / "data" / "report.json"

BBOX = (-10.0, 57.0, 36.0, 81.0)  # Includes Svalbard and Jan Mayen
DEDUP_METERS = 15
DEDUP_SHARE = 0.7
SAMPLE_METERS = 20
EARTH = 6378137.0

NVDB_TYPES = {"gangOgSykkelveg": "Gang- og sykkelveg", "sykkelveg": "Sykkelveg"}
FYLKER = {
    3: "Oslo", 11: "Rogaland", 15: "Møre og Romsdal", 18: "Nordland", 31: "Østfold",
    32: "Akershus", 33: "Buskerud", 34: "Innlandet", 39: "Vestfold", 40: "Telemark",
    42: "Agder", 46: "Vestland", 50: "Trøndelag", 55: "Troms", 56: "Finnmark",
}
SURFACES = {
    "asphalt": "Asphalt", "paved": "Paved", "concrete": "Concrete",
    "paving_stones": "Paving stones", "gravel": "Gravel", "fine_gravel": "Fine gravel",
    "compacted": "Compacted gravel", "ground": "Ground", "dirt": "Dirt",
    "earth": "Dirt", "unpaved": "Unpaved", "grass": "Grass", "wood": "Wood",
    "sand": "Sand", "pebblestone": "Pebbles", "rock": "Rock", "mud": "Mud",
}


def length_m(coords):
    lon, lat = np.radians(coords[:, 0]), np.radians(coords[:, 1])
    a = (np.sin(np.diff(lat) / 2) ** 2
         + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(np.diff(lon) / 2) ** 2)
    return float((2 * EARTH * np.arcsin(np.sqrt(a))).sum())


def lines_from_wkt(wkt):
    """NVDB WKT in EPSG:4326 lists lat lon, so swap it to lon lat."""
    geom = shapely.force_2d(shapely.from_wkt(wkt))
    geom = shapely.transform(geom, lambda c: c[:, ::-1])
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "LineString"]
    return []


def inside_bbox(coords):
    return (coords[:, 0].min() >= BBOX[0] and coords[:, 1].min() >= BBOX[1]
            and coords[:, 0].max() <= BBOX[2] and coords[:, 1].max() <= BBOX[3])


def to_mercator(coords):
    x = np.radians(coords[:, 0]) * EARTH
    y = np.log(np.tan(np.pi / 4 + np.radians(coords[:, 1]) / 2)) * EARTH
    return np.column_stack([x, y])


def make(line, cls, source, kind, name=None, surface=None, fylke=None):
    coords = shapely.get_coordinates(line)
    return {
        "line": line, "class": cls, "source": source, "kind": kind,
        "name": name, "surface": surface, "fylke": fylke,
        "length_m": length_m(coords),
    }


def load_nvdb():
    items, skipped = [], collections.Counter()
    seen = set()
    for sosi, kind in NVDB_TYPES.items():
        for page in sorted((RAW / "nvdb" / sosi).glob("page_*.json")):
            for row in json.loads(page.read_text())["objekter"]:
                if row.get("metadata", {}).get("sluttdato"):
                    skipped["ended"] += 1
                    continue
                if "KONNEKTERING" in (row.get("type") or ""):
                    skipped["connector"] += 1
                    continue
                key = row.get("referanse")
                if key in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(key)
                for line in lines_from_wkt(row["geometri"]["wkt"]):
                    if not inside_bbox(shapely.get_coordinates(line)):
                        skipped["outside_bbox"] += 1
                        continue
                    items.append(make(line, "dedicated", "NVDB", kind, fylke=row.get("fylke")))
    return items, skipped


def classify_osm(tags):
    highway = tags.get("highway")
    bicycle = tags.get("bicycle")
    if bicycle in ("no", "dismount", "use_sidepath"):
        return None
    if tags.get("access") in ("no", "private") and bicycle not in ("yes", "designated", "permissive"):
        return None
    if tags.get("footway") == "sidewalk" or tags.get("path") == "sidewalk":
        return None
    if tags.get("cycleway") in ("lane", "sidewalk", "shared_lane"):
        return None
    if tags.get("motor_vehicle") in ("yes", "designated", "destination"):
        return None
    if highway == "cycleway":
        return "dedicated"
    if highway in ("path", "footway", "bridleway") and bicycle == "designated":
        return "dedicated"
    if highway == "track" and bicycle in ("designated", "yes", "permissive"):
        return "trail"
    if highway in ("path", "footway", "pedestrian") and bicycle in ("yes", "permissive"):
        return "trail"
    return None


def load_osm():
    items = []
    path = RAW / "osm" / "bike.geojsonseq"
    if not path.exists():
        print("WARNING: no OSM data, continuing without it", flush=True)
        return items
    with path.open() as src:
        for raw in src:
            feature = json.loads(raw.lstrip("\x1e"))
            tags = feature["properties"]
            cls = classify_osm(tags)
            if not cls or feature["geometry"]["type"] != "LineString":
                continue
            line = shapely.linestrings(feature["geometry"]["coordinates"])
            if not inside_bbox(shapely.get_coordinates(line)):
                continue
            kind = {"dedicated": "Cycle path", "trail": "Shared path or track, cycling allowed"}[cls]
            surface = SURFACES.get(tags.get("surface"), None)
            items.append(make(line, cls, "OpenStreetMap", kind, tags.get("name"), surface))
    return items


def remove_overlaps(osm, nvdb):
    """Drop OSM lines that mostly run alongside an NVDB path."""
    if not osm or not nvdb:
        return osm, 0
    tree = shapely.STRtree([shapely.linestrings(to_mercator(shapely.get_coordinates(i["line"]))) for i in nvdb])
    kept, dropped = [], 0
    for start in range(0, len(osm), 5000):
        chunk = osm[start:start + 5000]
        points, owners, tolerances = [], [], []
        for index, item in enumerate(chunk):
            coords = shapely.get_coordinates(item["line"])
            merc = shapely.linestrings(to_mercator(coords))
            scale = 1 / math.cos(math.radians(coords[:, 1].mean()))
            count = max(2, int(item["length_m"] / SAMPLE_METERS))
            distances = np.linspace(0, shapely.length(merc), count)
            points.append(shapely.line_interpolate_point(merc, distances))
            owners.append(np.full(count, index))
            tolerances.append(np.full(count, DEDUP_METERS * scale))
        points = np.concatenate(points)
        owners = np.concatenate(owners)
        tolerances = np.concatenate(tolerances)
        hits = np.unique(tree.query(points, predicate="dwithin", distance=tolerances)[0])
        near = np.bincount(owners[hits], minlength=len(chunk))
        total = np.bincount(owners, minlength=len(chunk))
        for index, item in enumerate(chunk):
            if near[index] / total[index] >= DEDUP_SHARE:
                dropped += 1
            else:
                kept.append(item)
    return kept, dropped


def nvdb_route_name(obj):
    for prop in obj.get("egenskaper", []):
        if prop.get("navn") in ("Nasjonal sykkelrute", "Rutenavn", "Navn"):
            return str(prop.get("verdi"))
    return None


def load_routes():
    items = []
    groups = (
        (705, "route_national", "National cycle route"),
        (907, "route_urban", "Main urban cycle network"),
    )
    for type_id, cls, kind in groups:
        path = RAW / "routes" / f"nvdb_{type_id}.json"
        if not path.exists():
            print(f"WARNING: missing {path.name}", flush=True)
            continue
        for obj in json.loads(path.read_text()):
            for line in lines_from_wkt(obj["geometri"]["wkt"]):
                if inside_bbox(shapely.get_coordinates(line)):
                    items.append(make(line, cls, "NVDB", kind, nvdb_route_name(obj)))
    path = RAW / "routes" / "turrutebasen.geojsonseq"
    if path.exists():
        with path.open() as src:
            for raw in src:
                feature = json.loads(raw)
                line = shapely.linestrings(feature["geometry"]["coordinates"])
                if inside_bbox(shapely.get_coordinates(line)):
                    items.append(make(line, "route_local", "Kartverket Turrutebasen", "Cycle route",
                                      feature["properties"].get("name")))
    else:
        print("WARNING: missing Turrutebasen data", flush=True)
    return items


def main():
    nvdb, skipped = load_nvdb()
    print(f"NVDB: {len(nvdb)} lines, skipped {dict(skipped)}", flush=True)
    osm_all = load_osm()
    print(f"OSM: {len(osm_all)} candidate lines", flush=True)
    osm, dropped = remove_overlaps(osm_all, nvdb)
    print(f"OSM: dropped {dropped} overlaps, kept {len(osm)}", flush=True)
    routes = load_routes()
    print(f"Routes: {len(routes)} lines", flush=True)

    report = {
        "km_by_class": collections.Counter(), "km_by_source": collections.Counter(),
        "km_by_kind": collections.Counter(), "nvdb_km_by_fylke": collections.Counter(),
        "lines_by_class": collections.Counter(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    lon_min, lat_min, lon_max, lat_max = 180, 90, -180, -90
    with tmp.open("w") as out:
        for fid, item in enumerate(nvdb + osm + routes, start=1):
            km = item["length_m"] / 1000
            report["km_by_class"][item["class"]] += km
            report["km_by_source"][item["source"]] += km
            report["km_by_kind"][item["kind"]] += km
            report["lines_by_class"][item["class"]] += 1
            if item["source"] == "NVDB" and item["class"] == "dedicated":
                report["nvdb_km_by_fylke"][FYLKER.get(item["fylke"], str(item["fylke"]))] += km
            coords = np.round(shapely.get_coordinates(item["line"]), 6)
            lon_min, lat_min = min(lon_min, coords[:, 0].min()), min(lat_min, coords[:, 1].min())
            lon_max, lat_max = max(lon_max, coords[:, 0].max()), max(lat_max, coords[:, 1].max())
            props = {"class": item["class"], "source": item["source"], "kind": item["kind"],
                     "length_m": round(item["length_m"])}
            if item["name"]:
                props["name"] = item["name"]
            if item["surface"]:
                props["surface"] = item["surface"]
            out.write(json.dumps({
                "type": "Feature", "id": fid, "properties": props,
                "geometry": {"type": "LineString", "coordinates": coords.tolist()},
            }, ensure_ascii=False) + "\n")
    tmp.rename(OUT)

    rounded = {}
    for key, value in report.items():
        rounded[key] = {k: round(v, 1) if key != "lines_by_class" else v for k, v in sorted(value.items())}
    rounded["bbox"] = [float(lon_min), float(lat_min), float(lon_max), float(lat_max)]
    rounded["osm_overlaps_removed"] = dropped
    REPORT.write_text(json.dumps(rounded, ensure_ascii=False, indent=2))
    print(json.dumps(rounded, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
