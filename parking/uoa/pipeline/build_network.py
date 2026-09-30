"""Turn the Overture edge list into a routable walking + cycling network with Level of Traffic Stress
(LTS), grade from the LINZ 1 m LiDAR DEM, and perceived-cost weights.

LTS comes from two places, in order of preference:
  1. SPAN's way-level LTS table (data/inputs/span_lts_by_way.csv, columns osm_way_id, lts) - the same
     classification the Better Places Lab uses in the cycling investment workbench. Joined on the OSM way
     id that Overture keeps in `sources`, and used on road and cycleway links.
  2. A documented fallback from Overture class + posted speed (Furth/Mekuria-style, table below), used
     where SPAN has no value (new ways, service roads, paths).

Perceived cycling cost per edge and direction = length x stress multiplier(LTS) x grade multiplier x dismount (SPAN's form).
  stress multiplier (STRESS_MULT, SPAN's stress.py): LTS1 1.0, LTS2 1.25, LTS3 1.8, LTS4 3.0. Motorway and trunk links
    at LTS 4 are closed to bikes.
  grade multiplier (grade_mult, SPAN's grade term): 1 + 4.0 x max(0, g) + 0.5 x max(0, -g), with g the grade as a
    fraction in the direction of travel (DEM grade clipped to +-30 %, 0 on bridges and tunnels). A 5 % climb costs
    x1.2 and a 10 % climb x1.4; a 10 % descent x1.05. No other cap. This is gentler than the route-choice evidence
    (Broach, Dill & Gliebe 2012 find riders weigh 2-4 % climbs at about 1.4x distance and 4-6 % at about 2x or more),
    so the model will send some riders up short steep links.
  dismount: footway and pedestrian x1.6 (slow, shared), steps x4.0.
Walking cost = length x 1.5 on steps, x1.0 on footways, pedestrian streets, paths, cycleways, living streets and
service lanes, x1.2 on other roads. Walking is undirected; motorways and trunks are closed to walking unless their access rules allow people on foot.

Access rules (Overture access_restrictions, kept whole by build_layers.py as `access_rules`) are evaluated per mode
and, for bikes, per direction (see access_open in access_rules.py):
  - a rule applies to a mode if it names no mode, names that mode, or (for bikes) names 'vehicle';
  - a rule with a heading applies only in that direction, and never to walking (one-way streets bind vehicles, not
    people on foot);
  - rules limited to a time window, to certain users ('using', 'recognized') or to vehicle dimensions do not bind
    the daytime commuters modelled here;
  - among the rules that apply, the most specific wins (a heading counts 2 and a named mode 1; ties go to the later
    rule), so "no vehicles, pedestrians allowed" leaves a path open to walking, and "one-way except bicycles" (a
    rule naming both the heading and bicycles) leaves the contraflow open to bikes. OpenStreetMap's bicycle=yes or
    bicycle=designated reaches Overture as a rule naming bicycles with no heading: it gives bikes access but does not
    lift a one-way, so one-way cycle lanes and one-way streets that bikes may use stay one-way for bikes.
"""

import json
import pathlib
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from access_rules import access_open
from paths import DERIVED, INPUTS, RAW_LINZ, require_derived, require_raw


# SPAN's segment stress table for mixed traffic, with SPAN's class imputation of lanes and daily volume
# (arterial 4 lanes/15,000; collector 2/7,000; local 2/3,000; service 1/1,000) and Overture's posted speed
# where present (else SPAN's imputed speed: arterial 60, collector 50, local 40, service 30).
def _mixed(speed, lanes, vol):
    if speed <= 30 and lanes <= 2 and vol <= 2000:
        return 1
    if speed <= 40 and lanes <= 2 and vol <= 4000:
        return 2
    if speed <= 50 and lanes <= 3 and vol <= 12000:
        return 3
    return 4


def _cls(imp_speed, lanes, vol):
    return lambda v: _mixed(v if v else imp_speed, lanes, vol)


SPAN_FALLBACK = {
    "primary": _cls(60, 4, 15000),
    "secondary": _cls(60, 4, 15000),
    "tertiary": _cls(50, 2, 7000),
    "unclassified": _cls(50, 2, 7000),
    "residential": _cls(40, 2, 3000),
    "living_street": lambda v: 1 if (v or 30) <= 30 else 2,
    "service": _cls(30, 1, 1000),
    "unknown": _cls(40, 2, 3000),
    "cycleway": lambda v: 1,
    "footway": lambda v: 1,
    "path": lambda v: 1,
    "pedestrian": lambda v: 1,
    "steps": lambda v: 1,
    "track": lambda v: 1,
    "trunk": lambda v: 4,
    "motorway": lambda v: 4,
}
FALLBACK_LTS = SPAN_FALLBACK
_OLD_FALLBACK = {  # (class) -> function of maxspeed (earlier, gentler table kept for reference)
    "cycleway": lambda v: 1,
    "footway": lambda v: 1,
    "path": lambda v: 1,
    "pedestrian": lambda v: 1,
    "steps": lambda v: 1,
    "track": lambda v: 1,
    "living_street": lambda v: 1,
    "service": lambda v: 1 if (v or 50) <= 30 else 2,
    "residential": lambda v: 1 if (v or 50) <= 30 else 2,
    "unclassified": lambda v: 2 if (v or 50) <= 50 else 3,
    "tertiary": lambda v: 2 if (v or 50) <= 40 else 3,
    "secondary": lambda v: 3 if (v or 50) <= 50 else 4,
    "primary": lambda v: 3 if (v or 50) <= 40 else 4,
    "trunk": lambda v: 4,
    "motorway": lambda v: 4,
    "unknown": lambda v: 2,
}
BIKE_ALLOWED = {
    "cycleway",
    "footway",
    "path",
    "pedestrian",
    "living_street",
    "service",
    "residential",
    "unclassified",
    "tertiary",
    "secondary",
    "primary",
    "unknown",
    "track",
}
STRESS_MULT = {
    1: 1.0,
    2: 1.25,
    3: 1.8,
    4: 3.0,
}  # SPAN's multipliers (auckland-cycling-investment-workbench, stress.py)


def main():
    require_derived("build_network.py", "edges", "connectors")
    require_raw("build_network.py", RAW_LINZ / "dem_study_1m.tif")
    e = gpd.read_parquet(DERIVED / "edges.parquet")
    e = e[e.subtype == "road"].copy()
    e = e[
        ~e["flags"].str.contains("is_under_construction|is_abandoned", regex=True, na=False)
    ].copy()
    # --- elevations at edge ends from the DEM ---
    dem = rasterio.open(RAW_LINZ / "dem_study_1m.tif")

    def z_at(pts):
        vals = np.array([v[0] for v in dem.sample([(p.x, p.y) for p in pts])], dtype="float64")
        vals[vals == dem.nodata] = np.nan
        return vals

    p0 = e.geometry.apply(lambda g: g.coords[0])
    p1 = e.geometry.apply(lambda g: g.coords[-1])
    from shapely.geometry import Point

    e["z_u"] = z_at([Point(c) for c in p0])
    e["z_v"] = z_at([Point(c) for c in p1])
    e["grade_uv_pct"] = ((e.z_v - e.z_u) / e.length_m.clip(lower=1)) * 100
    e["grade_uv_pct"] = e["grade_uv_pct"].clip(-30, 30).fillna(0)
    # bridges/tunnels: DEM is ground, so force flat
    e.loc[e["flags"].str.contains("is_bridge|is_tunnel", regex=True, na=False), "grade_uv_pct"] = 0
    # --- LTS ---
    e["lts_fallback"] = [
        FALLBACK_LTS.get(c, lambda v: 2)(v if pd.notna(v) else None)
        for c, v in zip(e.cls, e.maxspeed, strict=True)
    ]
    e["lts"] = e["lts_fallback"]
    e["lts_source"] = "span_rules_class_speed"
    span_path = INPUTS / "span_lts_by_way.csv"
    if span_path.exists():
        span = pd.read_csv(span_path)
        idcol = next(c for c in span.columns if "way" in c.lower() or c.lower() in ("id", "osm_id"))
        ltscol = next(c for c in span.columns if c.lower().startswith("lts"))
        span = (
            span[[idcol, ltscol]].dropna().rename(columns={idcol: "osm_way_id", ltscol: "lts_span"})
        )
        span["osm_way_id"] = pd.to_numeric(
            span["osm_way_id"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"
        )
        span["lts_span"] = pd.to_numeric(
            span["lts_span"].astype(str).str.extract(r"(\d)")[0], errors="coerce"
        )
        span = span.dropna()
        # SPAN lists one row per (way, LTS): keep the class covering most length, ties to the higher class
        if "share_of_length" in pd.read_csv(span_path, nrows=1).columns:
            sh = pd.read_csv(span_path)[["way_id", "lts", "share_of_length"]].rename(
                columns={"way_id": "osm_way_id"}
            )
            sh = sh.sort_values(
                ["osm_way_id", "share_of_length", "lts"], ascending=[True, False, False]
            ).drop_duplicates("osm_way_id")
            span = sh.rename(columns={"lts": "lts_span"})[["osm_way_id", "lts_span"]]
        span = span.drop_duplicates("osm_way_id")
        e = e.merge(span, on="osm_way_id", how="left")
        m = e.lts_span.notna() & e.cls.isin(
            [
                "residential",
                "unclassified",
                "tertiary",
                "secondary",
                "primary",
                "trunk",
                "motorway",
                "living_street",
                "service",
                "cycleway",
                "unknown",
            ]
        )
        e.loc[m, "lts"] = e.loc[m, "lts_span"].astype(int)
        e.loc[m, "lts_source"] = "span_lts_by_way"
        print("SPAN LTS applied to", int(m.sum()), "of", len(e), "edges")
    e["lts"] = e["lts"].astype(int)
    # --- permissions: class defaults, then the segment's own access rules per mode and direction ---
    bike_default = e.cls.isin(BIKE_ALLOWED)
    walk_default = ~e.cls.isin(["motorway", "trunk"])
    rules = [
        json.loads(x) if isinstance(x, str) and x else []
        for x in e.get("access_rules", pd.Series([None] * len(e), index=e.index))
    ]
    if "access_rules" not in e:
        print(
            "WARNING: edges.parquet has no access_rules column; rerun build_layers.py. Falling back to class defaults only."
        )
    e["bike_ok_uv"] = [
        access_open(r, "bicycle", "forward", d) for r, d in zip(rules, bike_default, strict=True)
    ]
    e["bike_ok_vu"] = [
        access_open(r, "bicycle", "backward", d) for r, d in zip(rules, bike_default, strict=True)
    ]
    closed = e.cls.isin(["trunk", "motorway"]) & (e.lts >= 4)
    e.loc[closed, ["bike_ok_uv", "bike_ok_vu"]] = False
    e["bike_ok"] = e.bike_ok_uv | e.bike_ok_vu  # open in at least one direction
    e["bike_oneway"] = e.bike_ok_uv != e.bike_ok_vu
    e["walk_ok"] = [
        access_open(r, "foot", None, d) for r, d in zip(rules, walk_default, strict=True)
    ]

    # --- costs (direction u->v and v->u) ---
    def grade_mult(g):
        """SPAN's grade term: 1 + 4.0*max(0,g) + 0.5*max(0,-g), g as a fraction (uphill positive)."""
        gf = np.asarray(g, dtype=float) / 100.0
        return 1 + 4.0 * np.clip(gf, 0, None) + 0.5 * np.clip(-gf, 0, None)

    e["stress_mult"] = e.lts.map(STRESS_MULT)
    # slow/shared, steps worse
    dismount = np.where(e.cls.isin(["footway", "pedestrian", "steps"]), 1.6, 1.0)
    dismount = np.where(e.cls == "steps", 4.0, dismount)
    e["bike_cost_uv"] = np.where(
        e.bike_ok_uv, e.length_m * e.stress_mult * grade_mult(e.grade_uv_pct) * dismount, np.nan
    )
    e["bike_cost_vu"] = np.where(
        e.bike_ok_vu, e.length_m * e.stress_mult * grade_mult(-e.grade_uv_pct) * dismount, np.nan
    )
    walk_mult = np.where(
        e.cls == "steps",
        1.5,
        np.where(
            e.cls.isin(["footway", "pedestrian", "path", "cycleway", "living_street", "service"]),
            1.0,
            1.2,
        ),
    )
    e["walk_cost"] = e.length_m * walk_mult
    e.to_parquet(DERIVED / "network_edges.parquet")
    nodes = (
        pd.concat(
            [
                e[["u"]].rename(columns={"u": "id"}).assign(z=e.z_u),
                e[["v"]].rename(columns={"v": "id"}).assign(z=e.z_v),
            ]
        )
        .groupby("id")
        .z.mean()
    )
    cn = gpd.read_parquet(DERIVED / "connectors.parquet").set_index("id")
    nd = cn.join(nodes, how="inner")
    nd.to_parquet(DERIVED / "network_nodes.parquet")
    summ = {
        "edges": int(len(e)),
        "bike_edges": int(e.bike_ok.sum()),
        "bike_oneway_edges": int(e.bike_oneway.sum()),
        "walk_edges": int(e.walk_ok.sum()),
        "lts_share": e.groupby("lts").length_m.sum().div(e.length_m.sum()).round(3).to_dict(),
        "lts_source": e.lts_source.value_counts().to_dict(),
        "grade_p50_abs": float(e.grade_uv_pct.abs().median()),
        "grade_p90_abs": float(e.grade_uv_pct.abs().quantile(0.9)),
    }
    with open(DERIVED / "build_network_summary.json", "w") as f:
        json.dump(summ, f, indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
