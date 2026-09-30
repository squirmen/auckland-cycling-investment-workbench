"""Pull Overture Maps themes for the UoA three-campus study window via DuckDB httpfs.
Study window: lon 174.735..174.800, lat -36.890..-36.835 (covers City, Grafton, Newmarket + ~1.5 km).

Usage:
  python3 pipeline/fetch_overture.py [THEME ...]                      # the study window, as before
  python3 pipeline/fetch_overture.py --bbox 174.700,-36.925,174.840,-36.828 \
      --out $STAND_DATA/overture_wide --lite buildings segments water land land_use divisions
--bbox is xmin,ymin,xmax,ymax in lon/lat; --out is the directory for <theme>.parquet; --lite keeps only the
columns the cartographic basemap needs (pipeline/build_basemap.py). With no options the behaviour is unchanged.

A theme whose <theme>.parquet already exists is skipped. Each theme is written to <theme>.parquet.part and
renamed only when the pull succeeds, so a failed or interrupted pull never leaves a partial file that a later
run would skip. If any theme fails the script says which and exits with status 1.
"""

import argparse
import os
import pathlib
import re
import sys
import time

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import RAW_OVERTURE, ca_bundle, duckdb_connect

HOST = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"


def list_keys(prefix):
    keys, token = [], None
    while True:
        url = f"{HOST}/?list-type=2&prefix={prefix}/" + (
            f"&continuation-token={requests.utils.quote(token)}" if token else ""
        )
        x = requests.get(url, timeout=60).text
        keys += re.findall(r"<Key>([^<]+)</Key>", x)
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m:
            break
        token = m.group(1)
    return [f"{HOST}/{k}" for k in keys if k.endswith(".parquet")]


REL = "2026-09-23.1"
STUDY_BBOX = (174.735, -36.890, 174.800, -36.835)  # xmin, ymin, xmax, ymax


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("themes", nargs="*")
    ap.add_argument(
        "--bbox", default=None, help="xmin,ymin,xmax,ymax (lon/lat); default is the study window"
    )
    ap.add_argument(
        "--out",
        default=None,
        help="output directory; default is $STAND_DATA/overture, the study-window data folder",
    )
    ap.add_argument(
        "--lite", action="store_true", help="basemap column subset for the themes that have one"
    )
    a = ap.parse_args(argv)
    bad = [t for t in a.themes if t not in THEMES]
    if bad:
        ap.error(f"unknown theme {', '.join(bad)} (choose from {', '.join(THEMES)})")
    return a


def connect():
    """DuckDB with httpfs and spatial (pipeline/paths.py), set up for Overture's public S3 bucket: anonymous,
    through HTTPS_PROXY and its CA bundle where the environment has them."""
    for k in list(os.environ):
        if k.startswith("AWS_"):
            os.environ.pop(k)
    con = duckdb_connect("httpfs", "spatial")
    proxy = os.environ.get("HTTPS_PROXY", "")
    if proxy:
        hp = proxy.replace("http://", "")
        con.execute(f"SET http_proxy='{hp}'")
    con.execute("SET s3_region='us-west-2'")
    ca = ca_bundle()
    if ca:
        try:
            con.execute(f"SET ca_cert_file='{ca}'")
        except Exception as e:
            print("ca_cert_file setting unavailable:", str(e)[:80])
    con.execute("SET http_keep_alive=true; SET http_retries=5; SET http_timeout=120000;")
    return con


THEMES = {
    "buildings": (
        "theme=buildings/type=building",
        "id, geometry, subtype, class, names.primary AS name, height, num_floors, num_floors_underground, roof_shape, level, has_parts, sources[1].dataset AS src_dataset, sources[1].record_id AS src_id",
    ),
    "building_parts": (
        "theme=buildings/type=building_part",
        "id, geometry, building_id, height, num_floors, level",
    ),
    "segments": (
        "theme=transportation/type=segment",
        "id, geometry, subtype, class, subclass, names.primary AS name, connectors, routes, speed_limits, access_restrictions, road_flags, road_surface, level_rules, width_rules, subclass_rules, sources",
    ),
    "connectors": ("theme=transportation/type=connector", "id, geometry"),
    "places": (
        "theme=places/type=place",
        "id, geometry, names.primary AS name, taxonomy.primary AS category, taxonomy.alternates AS alt_categories, basic_category, confidence, websites, addresses, brand.names.primary AS brand, operating_status, sources[1].dataset AS src_dataset",
    ),
    "land_use": (
        "theme=base/type=land_use",
        "id, geometry, subtype, class, names.primary AS name, surface, sources[1].record_id AS src_id",
    ),
    "infrastructure": (
        "theme=base/type=infrastructure",
        "id, geometry, subtype, class, names.primary AS name, level, sources[1].record_id AS src_id",
    ),
    "addresses": (
        "theme=addresses/type=address",
        "id, geometry, number, street, unit, postcode, address_levels",
    ),
    "land": (
        "theme=base/type=land",
        "id, geometry, subtype, class, names.primary AS name, elevation, sources[1].record_id AS src_id",
    ),
    "water": ("theme=base/type=water", "id, geometry, subtype, class, names.primary AS name"),
    # divisions: place-name points (neighbourhood, suburb, locality ...) and their areas, for basemap labels
    "divisions": (
        "theme=divisions/type=division",
        "id, geometry, subtype, class, names.primary AS name, admin_level, population, cartography.prominence AS prominence, cartography.min_zoom AS min_zoom, cartography.sort_key AS sort_key, parent_division_id",
    ),
    "division_areas": (
        "theme=divisions/type=division_area",
        "id, geometry, subtype, class, names.primary AS name, division_id, is_land",
    ),
}
# --lite: only what the cartographic basemap draws (keeps the wide-window pull small)
LITE = {
    "buildings": "id, geometry, subtype, class, height",
    "segments": "id, geometry, subtype, class, subclass, names.primary AS name, road_flags",
    "land_use": "id, geometry, subtype, class, names.primary AS name",
    "land": "id, geometry, subtype, class, names.primary AS name",
}


def main(argv=None):
    args = parse_args(argv)
    xmin, ymin, xmax, ymax = [float(v) for v in args.bbox.split(",")] if args.bbox else STUDY_BBOX
    out = args.out or str(RAW_OVERTURE)  # $STAND_DATA/overture (pipeline/paths.py)
    os.makedirs(out, exist_ok=True)
    order = args.themes or [
        "segments",
        "connectors",
        "buildings",
        "places",
        "land_use",
        "infrastructure",
        "building_parts",
        "addresses",
        "land",
        "water",
    ]
    todo = [k for k in order if not os.path.exists(f"{out}/{k}.parquet")]
    for key in order:
        if key not in todo:
            print("skip", key)
    if not todo:
        return 0
    con = connect()
    failed = []
    for key in todo:
        part, cols = THEMES[key]
        if args.lite and key in LITE:
            cols = LITE[key]
        dst = f"{out}/{key}.parquet"
        tmp = dst + ".part"
        t = time.time()
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            files = list_keys(f"release/{REL}/{part}")
            if not files:
                raise RuntimeError(f"no parquet files listed under release/{REL}/{part}")
            print(key, len(files), "files", flush=True)
            con.execute(f"""
            COPY (
              SELECT {cols}
              FROM read_parquet({files!r}, filename=true, hive_partitioning=0)
              WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}
            ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD);
            """)
            n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
            os.replace(tmp, dst)
            print(
                f"{key}: {n} rows in {time.time() - t:.0f}s -> {os.path.getsize(dst) / 1e6:.1f} MB",
                flush=True,
            )
        except Exception as e:
            failed.append(key)
            print(f"{key}: FAILED {e}", flush=True)
            if os.path.exists(tmp):
                os.remove(tmp)
    if failed:
        print(
            f"fetch_overture: {len(failed)} of {len(todo)} theme(s) failed: {', '.join(failed)}. Nothing partial was kept; rerun to retry them.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
