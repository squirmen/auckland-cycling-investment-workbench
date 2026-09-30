"""Export the model results as compact GeoJSON (EPSG:4326) for the web map, plus a results JSON.

Everything the map needs is written to web/data so the map can be hosted as a static folder.
Geometry is simplified and coordinates rounded to 6 dp to keep files small.

Street names that carry a raw OpenStreetMap note ("Library ( service lane - 26 Princes Street )") are tidied here
("Princes Street service lane"), on the candidates, the flow lines and the stress network alike (tidy_street).
Each AT counter carries the first and last month of its record (period_start, period_end, "YYYY-MM") and the number
of months with counts in between (months_counted), from the Cycleway dashboard's monthly series (counter_months).
"""

import json
import pathlib
import re
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import (
    BIG,
    DERIVED,
    INPUTS,
    RAW_LINZ,
    RAW_OVERTURE,
    WEB_DATA,
    require_derived,
    require_raw,
)
from site_model import study_footprint

# An OSM name with a note in brackets: "Library ( service lane - 26 Princes Street )" -> "Princes Street service lane".
# Only a bracketed "<what> - [number] <street>" is rewritten; "(campus path)" and other names pass unchanged.
_OSM_NOTE = re.compile(
    r"^[^()]*\(\s*(?P<what>[^()\-\u2013]+?)\s*[-\u2013]\s*(?:\d+[A-Za-z]?\s+)?(?P<street>[^()]+?)\s*\)\s*(?P<rest>.*)$"
)


def tidy_street(s):
    if not isinstance(s, str):
        return s
    m = _OSM_NOTE.match(s)
    return f"{m['street']} {m['what']}" + (f" {m['rest']}" if m["rest"] else "") if m else s


# The Cycleway dashboard's monthly counts per counter ({name: [{"date": "YYYY-MM", "count": n}, ...]}), the same
# extract (July 2026) as cycleway_stats.json. Looked for in data/inputs first, then in $STAND_DATA or one folder down.
MONTHLY = "cycleway_data_monthly.json"


def counter_months():
    """{counter name: (first month, last month, months with counts)} over the months with a count above zero."""
    src = next(
        (
            p
            for p in [INPUTS / MONTHLY, BIG / MONTHLY, *sorted(BIG.glob(f"*/{MONTHLY}"))]
            if p.is_file()
        ),
        None,
    )
    if src is None:
        print(
            f"WARNING: no {MONTHLY} in data/inputs or $STAND_DATA: counters.geojson is written without period_start/period_end",
            flush=True,
        )
        return {}
    out = {}
    for name, rows in json.loads(src.read_text()).items():
        months = sorted(str(r["date"])[:7] for r in rows if (r.get("count") or 0) > 0)
        if months:
            out[name] = (months[0], months[-1], len(set(months)))
    print(f"counter months: {len(out)} counters from {src.name}", flush=True)
    return out


def dump(gdf, name, cols=None, simplify=None, precision=6):
    g = gdf.copy()
    if simplify:
        g["geometry"] = g.geometry.simplify(simplify, preserve_topology=True)
    g = g.to_crs(4326)
    if cols:
        g = g[[c for c in cols if c in g.columns] + ["geometry"]]
    for c in g.columns:
        if c == "geometry":
            continue
        if g[c].dtype.kind == "f":
            g[c] = g[c].round(3)
        elif g[c].dtype == object or str(g[c].dtype).startswith("string"):
            g[c] = g[c].where(g[c].notna(), None)
        elif str(g[c].dtype) in ("Int64", "Int32", "boolean"):
            g[c] = g[c].astype(object).where(g[c].notna(), None)
    g = g.set_geometry("geometry")
    txt = g.to_json(na="null", drop_id=True, to_wgs84=False)
    # coordinate rounding
    txt = re.sub(rf"(\d+\.\d{{{precision}}})\d+", r"\1", txt)
    (WEB_DATA / f"{name}.geojson").write_text(txt)
    print(f"{name}: {len(g)} features, {len(txt) / 1e6:.2f} MB")


def load_raw_stations(study):
    """Rail stations from Overture infrastructure (OSM railway=station), within 800 m of the study areas."""
    from shapely import wkb

    from paths import duckdb_connect

    con = duckdb_connect("spatial")
    df = con.execute(
        f"SELECT name, class AS category, ST_AsWKB(ST_Centroid(geometry)) AS wkb FROM '{RAW_OVERTURE}/infrastructure.parquet' WHERE class = 'railway_station' AND name IS NOT NULL"
    ).df()
    g = gpd.GeoDataFrame(
        df.drop(columns=["wkb"]), geometry=[wkb.loads(bytes(x)) for x in df.wkb], crs="EPSG:4326"
    ).to_crs(study.crs)
    g = g[
        g.intersects(study.union_all().buffer(800))
        & ~g.name.str.contains("Old |Scenic|Siding", regex=True)
    ]
    g["category"] = "train_station"
    return g[["name", "category", "geometry"]]


def main():
    require_derived(
        "export_web.py",
        "study_areas",
        "campus_footprint",
        "destinations",
        "uoa_buildings",
        "buildings",
        "flow_edges",
        "network_edges",
        "candidates",
        "hex_suitability_r11",
        "infrastructure_points",
        "places",
        "portals",
    )
    require_raw("export_web.py", RAW_OVERTURE / "infrastructure.parquet")
    study = gpd.read_parquet(DERIVED / "study_areas.parquet")
    fp = gpd.read_parquet(DERIVED / "campus_footprint.parquet")
    fp = study_footprint(fp, study)  # the parts inside the study areas, as site_model.py uses them
    dump(study, "study_areas", ["campus", "label"])
    dump(fp, "campus_footprint", ["campus", "area_m2"], simplify=1)
    dest = gpd.read_parquet(DERIVED / "destinations.parquet")
    ub = gpd.read_parquet(DERIVED / "uoa_buildings.parquet").merge(
        dest[["id", "A_j", "use_factor"]], on="id", how="left"
    )
    dump(
        ub,
        "uoa_buildings",
        [
            "id",
            "name",
            "campus",
            "subtype",
            "class",
            "floors_est",
            "floors_source",
            "gfa_m2",
            "A_j",
            "use_factor",
        ],
        simplify=0.5,
    )
    bld = gpd.read_parquet(DERIVED / "buildings.parquet")
    bld = bld[~bld.id.isin(ub.id) & bld.intersects(study.union_all().buffer(250))]
    dump(bld, "buildings_context", ["name", "subtype", "floors_est"], simplify=1, precision=5)
    fe = gpd.read_parquet(DERIVED / "flow_edges.parquet")
    fe["name"] = fe["name"].map(tidy_street)
    dump(
        fe[fe.flow_per_day >= 1].copy(),
        "flow_edges",
        ["name", "cls", "lts", "flow_per_day", "grade_uv_pct"],
        simplify=1,
        precision=5,
    )
    ne = gpd.read_parquet(DERIVED / "network_edges.parquet")
    ne = ne[ne.bike_ok & ne.intersects(study.union_all().buffer(150))].copy()
    ne["name"] = ne["name"].map(tidy_street)
    dump(
        ne,
        "network_lts",
        ["name", "cls", "subclass", "lts", "lts_source", "maxspeed", "grade_uv_pct"],
        simplify=1,
        precision=5,
    )
    cand = gpd.read_parquet(DERIVED / "candidates.parquet")
    tidied = sorted(
        {(a, b) for a, b in zip(cand.street, cand.street.map(tidy_street), strict=True) if a != b}
    )
    for a, b in tidied:
        print(f"street name tidied: {a!r} -> {b!r}")
    cand["street"] = cand.street.map(tidy_street)
    dump(
        cand,
        "candidates",
        [
            "cid",
            "campus",
            "kind",
            "street",
            "nearest_building",
            "nearest_building_m",
            "n_buildings_150m",
            "coverage",
            "arrival_flow",
            "approach_lts",
            "surveillance",
            "lighting",
            "space",
            "power",
            "space_power",
            "slope_pct",
            "slope_score",
            "openness",
            "overlooked",
            "lamps_30m",
            "racks_40m",
            "store_60m",
            "store_m",
            "store_name",
            "store_approx",
            "revealed_demand",
            "active_75m",
            "bus_stops_100m",
            "footway_len_50m",
            "s_coverage",
            "s_arrival_flow",
            "suitability",
            "rank",
            "selected",
            "phase",
            "marginal_arrivals",
            "serves",
            "covers",
        ],
    )
    hx = gpd.read_parquet(DERIVED / "hex_suitability_r11.parquet")
    dump(
        hx,
        "hex_suitability",
        [
            "h3",
            "campus",
            "coverage",
            "arrival_flow",
            "lamps_30m",
            "slope_pct",
            "openness",
            "surveillance",
            "suitability",
        ],
        precision=6,
    )
    inf = gpd.read_parquet(DERIVED / "infrastructure_points.parquet")
    bp = inf[inf.kind == "bike_parking"].copy()
    bp["type"] = np.select(
        [bp.is_locky_dock, bp.is_uoa_cage, bp.is_scooter_bay],
        ["locky_dock", "uoa_store", "scooter_bay"],
        "open_rack",
    )
    dump(bp, "bike_parking_existing", ["name", "type", "src_id"])
    dump(inf[inf.kind == "lamp"], "lamps", ["src_id"], precision=5)
    dump(inf[inf.kind == "bus_stop"], "bus_stops", ["name"], precision=5)
    pl = gpd.read_parquet(DERIVED / "places.parquet")
    inf_all = gpd.read_parquet(DERIVED / "infrastructure_points.parquet")
    rail = load_raw_stations(study)
    st = pd.concat(
        [
            rail,
            pl[pl.category.isin(["bus_station"]) & pl.intersects(study.union_all().buffer(800))][
                ["name", "category", "geometry"]
            ],
        ],
        ignore_index=True,
    )
    st = gpd.GeoDataFrame(st, geometry="geometry", crs=inf_all.crs)
    dump(st, "stations", ["name", "category"])
    po = gpd.read_parquet(DERIVED / "portals.parquet")
    dump(po, "portals", ["id", "name", "weight_per_day", "basis", "source"])
    # AT cycle counters (Cycleway dashboard extract, updated July 2026: 86 sites with coordinates; each daily average
    # is over that counter's whole record, January 2016 to July 2026 for most, July 2016 to December 2018 for Quay St Totem).
    # period_start / period_end: the first and last month with counts; months_counted: how many months in between have
    # counts (fewer than the span where a counter has gaps).
    locs = json.loads((INPUTS / "cycleway_locations.json").read_text())
    stats = json.loads((INPUTS / "cycleway_stats.json").read_text())
    cdf = pd.DataFrame(locs)
    cdf["daily_avg"] = cdf["name"].map(stats.get("dailyAverages", {}))
    cdf["peak_month"] = cdf["name"].map(
        lambda n: (stats.get("peakRidership", {}).get(n) or {}).get("month")
        if isinstance(stats.get("peakRidership", {}).get(n), dict)
        else None
    )
    per = counter_months()
    cdf["period_start"] = cdf["name"].map(lambda n: per[n][0] if n in per else None)
    cdf["period_end"] = cdf["name"].map(lambda n: per[n][1] if n in per else None)
    cdf["months_counted"] = (
        cdf["name"].map(lambda n: per[n][2] if n in per else None).astype("Int64")
    )
    cg = gpd.GeoDataFrame(cdf, geometry=gpd.points_from_xy(cdf.lng, cdf.lat), crs=4326).to_crs(
        study.crs
    )
    cg = cg[cg.intersects(study.union_all().buffer(2500))]
    if per and cg.period_start.isna().any():
        print(
            f"WARNING: no monthly counts for counters {sorted(cg.name[cg.period_start.isna()])}",
            flush=True,
        )
    dump(
        cg,
        "counters",
        ["name", "daily_avg", "peak_month", "period_start", "period_end", "months_counted"],
    )
    # AT cycle facility network (existing and planned facilities by type)
    atn = gpd.read_file(INPUTS / "at_cycling_network.geojson").to_crs(study.crs)
    atn = atn[atn.intersects(study.union_all().buffer(600))]
    atn["facility"] = atn["TYPEOFFACILITY"].fillna("unknown")
    atn["status"] = atn["STATUS"].fillna("")
    atn["road"] = atn["ROADNAME"].fillna("")
    dump(
        atn,
        "at_cycle_facilities",
        ["road", "facility", "status", "CONSTRUCTIONYEAR"],
        simplify=1,
        precision=5,
    )
    ld = pd.read_csv(INPUTS / "locky_docks_existing.csv")
    ldg = gpd.GeoDataFrame(ld, geometry=gpd.points_from_xy(ld.lon, ld.lat), crs=4326)
    ldg.to_file(WEB_DATA / "locky_docks_existing.geojson", driver="GeoJSON")
    # UoA bike stores from the University's own list (its website), approximate positions from building ids
    stores = pd.read_csv(INPUTS / "uoa_bike_stores.csv")
    gpd.GeoDataFrame(stores, geometry=gpd.points_from_xy(stores.lon, stores.lat), crs=4326).to_file(
        WEB_DATA / "uoa_bike_stores.geojson", driver="GeoJSON"
    )
    res = json.loads((DERIVED / "site_model_results.json").read_text())
    # "built": when site_model.py ran (ISO 8601, New Zealand time); kept first in results.json, where the lab's page
    # reads its "Built" date. null if the model output predates the key.
    res = {"built": res.pop("built", None), **res}
    d4 = dest.to_crs(4326)
    res["destinations"] = [
        {
            "id": str(r.id),
            "label": (
                r.label
                if "label" in dest.columns and isinstance(r.label, str)
                else (r.name if isinstance(r.name, str) else "UoA building")
            ),
            "campus": r.campus,
            "A_j": round(float(r.A_j), 2),
            "gfa_m2": round(float(r.gfa_m2)),
            "lon": round(float(g.centroid.x), 6),
            "lat": round(float(g.centroid.y), 6),
        }
        for r, g in zip(d4.itertuples(), d4.geometry, strict=True)
    ]
    res["summaries"] = {
        k: json.loads((DERIVED / f"{k}_summary.json").read_text())
        for k in ["build_layers", "build_network", "build_demand"]
        if (DERIVED / f"{k}_summary.json").exists()
    }
    imgb = RAW_LINZ / "imagery_bounds.json"
    if imgb.exists():
        res["imagery"] = json.loads(imgb.read_text())
        import shutil

        for v in res["imagery"].values():
            src = RAW_LINZ / v["file"]
            if src.exists():
                shutil.copy(src, WEB_DATA / v["file"])
    # own-data basemap (pipeline/build_basemap.py writes the images straight to web/data/basemap); the app reads the manifest here
    bmj = WEB_DATA / "basemap" / "basemap.json"
    if bmj.exists():
        res["basemap"] = json.loads(bmj.read_text())

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
            return None
        return o

    with open(WEB_DATA / "results.json", "w") as f:
        json.dump(clean(res), f, indent=1, default=str, allow_nan=False)
    print("results.json written")


if __name__ == "__main__":
    main()
