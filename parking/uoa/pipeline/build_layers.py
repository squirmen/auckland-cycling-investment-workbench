"""Build the derived campus layers from the Overture pull.

Reads the Overture GeoParquet extracts (see fetch_overture.py) and writes analysis-ready
GeoParquet layers in NZTM2000 (EPSG:2193) to data/derived, plus a summary JSON.

Study areas are generous rectangles around each campus (WGS84). The campus "footprint" used
for demand is derived from the data, not hand drawn: Overture/OSM buildings tagged
education/university whose name or location ties them to Waipapa Taumata Rau, unioned with the
OSM university land-use relation, buffered 20 m and dissolved.
"""

import json
import pathlib
import sys
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkb
from shapely.geometry import box

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from access_rules import edge_rules
from paths import DERIVED, INPUTS, RAW_OVERTURE, duckdb_connect, require_raw

warnings.filterwarnings("ignore")
NZTM = "EPSG:2193"

ANCHORS = {
    "city": (174.7695, -36.8520),
    "grafton": (174.7685, -36.8615),
    "newmarket": (174.7735, -36.8660),
}  # lon, lat campus centres


def nearest_campus(gdf):
    """Campus label by nearest anchor, for geometries inside any study area (the boxes overlap)."""
    from shapely.geometry import Point

    anc = gpd.GeoSeries(
        [Point(v) for v in ANCHORS.values()], index=list(ANCHORS), crs="EPSG:4326"
    ).to_crs(NZTM)
    cen = gdf.geometry.centroid
    d = np.c_[[cen.distance(a).values for a in anc]]
    return np.array(list(ANCHORS))[d.argmin(axis=0)]


STUDY = {  # lon_min, lon_max, lat_min, lat_max
    "city": dict(
        label="City Campus (Waipapa Taumata Rau)", bbox=(174.7625, 174.7775, -36.8585, -36.8460)
    ),
    "grafton": dict(
        label="Grafton Campus (Medical & Health Sciences)",
        bbox=(174.7630, 174.7745, -36.8672, -36.8575),
    ),
    "newmarket": dict(
        label="Newmarket Campus (Engineering & Science)",
        bbox=(174.7690, 174.7805, -36.8712, -36.8618),
    ),
}


def aslist(x):
    """DuckDB -> pandas gives python lists, numpy arrays, None or pd.NA for list columns."""
    if x is None:
        return []
    try:
        if x is pd.NA:
            return []
    except Exception:
        pass
    if isinstance(x, np.ndarray):
        if x.ndim == 0:
            return [] if pd.isna(x.item()) else [x.item()]
        return [v for v in x.tolist() if v is not None]
    if isinstance(x, list | tuple):
        return [v for v in x if v is not None]
    return []


def load(name, cols="*", where="1=1"):
    con = duckdb_connect("spatial")
    df = con.execute(
        f"SELECT {cols}, ST_AsWKB(geometry) AS wkb FROM '{RAW_OVERTURE}/{name}.parquet' WHERE {where}"
    ).df()
    geom = [wkb.loads(bytes(b)) if b is not None else None for b in df.pop("wkb")]
    if "geometry" in df:
        df = df.drop(columns=["geometry"])
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326").to_crs(NZTM)


def main():
    require_raw(
        "build_layers.py",
        *[
            RAW_OVERTURE / f"{t}.parquet"
            for t in (
                "buildings",
                "addresses",
                "land_use",
                "infrastructure",
                "places",
                "segments",
                "connectors",
            )
        ],
    )
    summary = {}
    study = gpd.GeoDataFrame(
        [
            {
                "campus": k,
                "label": v["label"],
                "geometry": box(v["bbox"][0], v["bbox"][2], v["bbox"][1], v["bbox"][3]),
            }
            for k, v in STUDY.items()
        ],
        crs="EPSG:4326",
    ).to_crs(NZTM)
    study.to_parquet(DERIVED / "study_areas.parquet")
    allstudy = study.union_all()

    # ---- buildings -------------------------------------------------------------------------
    b = load("buildings", "id, subtype, class, name, height, num_floors, src_dataset, src_id")
    b = b[b.intersects(allstudy.buffer(400))].copy()
    b["footprint_m2"] = b.area
    # LiDAR building height: median normalised height (DSM - DEM, 2024) over the footprint, for buildings with no floor count
    import rasterio
    from rasterio.mask import mask as rmask

    from paths import RAW_LINZ

    nh_path = RAW_LINZ / "nheight_study_1m.tif"
    if nh_path.exists():
        nh = rasterio.open(nh_path)
        hts = []
        for g in b.geometry:
            try:
                arr, _ = rmask(
                    nh,
                    [
                        g.buffer(-1.5).__geo_interface__
                        if g.buffer(-1.5).area > 20
                        else g.__geo_interface__
                    ],
                    crop=True,
                    filled=True,
                    nodata=-9999,
                )
                v = arr[0][(arr[0] != -9999) & np.isfinite(arr[0])]
                hts.append(float(np.nanpercentile(v, 60)) if v.size else np.nan)
            except Exception:
                hts.append(np.nan)
        b["lidar_height_m"] = hts
    else:
        b["lidar_height_m"] = np.nan
    # floors: observed, else height/3.5, else LiDAR height/3.6, else defaults by subtype (documented assumption)
    default_floors = {
        "education": 3,
        "commercial": 3,
        "residential": 2,
        "medical": 3,
        "civic": 2,
        "industrial": 1,
        "outbuilding": 1,
        "service": 1,
        None: 2,
    }
    est = b["num_floors"].astype("float")
    est = est.where(est.notna(), (b["height"].astype("float") / 3.5).round())
    lidar_floors = (b["lidar_height_m"] / 3.6).round().where(b["lidar_height_m"] >= 2.5)
    est = est.where(est.notna(), lidar_floors)
    est = est.where(est.notna(), b["subtype"].map(lambda s: default_floors.get(s, 2)))
    b["floors_est"] = est.clip(lower=1)
    b["floors_source"] = np.where(
        b["num_floors"].notna(),
        "observed",
        np.where(
            b["height"].notna(),
            "from_height",
            np.where(lidar_floors.notna(), "lidar_dsm_2024", "default_by_subtype"),
        ),
    )
    b["gfa_m2"] = b["footprint_m2"] * b["floors_est"]
    uoa_words = (
        "university of auckland",
        "waipapa",
        "engineering 4",
        "science centre",
        "owen g",
        "kate edger",
        "general library",
        "clock tower",
        "social sciences 2",
        "grafton hall",
        "university hall",
        "bioengineering",
        "fine arts",
        "davis law",
        "auckland university press",
        "structures 9",
        "building 9",
        "ray meyer",
        "structures test",
        "school of exercise",
        "te ako o te t",
        "philson",
        "building 5",
        "building 6",
        "geothermal",
        "waipārūrū",
        "o'rorke",
        "hiwa",
        "recreation centre",
        "old choral",
        "fale pasifika",
        "waipapa marae",
        "elam",
        "8 grafton",
    )
    b["uoa_named"] = (
        b["name"].fillna("").str.lower().apply(lambda n: any(w in n for w in uoa_words))
    )
    b["campus"] = None
    inside = b.intersects(allstudy)
    b.loc[inside, "campus"] = nearest_campus(b[inside])
    # address label for unnamed buildings (nearest Overture address point within 40 m)
    ad = load("addresses", "number, street")
    ad = ad[ad.intersects(allstudy.buffer(100))]
    from scipy.spatial import cKDTree

    at = cKDTree(np.c_[ad.geometry.x, ad.geometry.y])
    cen = b.geometry.centroid
    d, k = at.query(np.c_[cen.x, cen.y], distance_upper_bound=60)
    lab = [
        f"{ad.number.iloc[j]} {ad.street.iloc[j]}"
        if np.isfinite(dd) and pd.notna(ad.street.iloc[j])
        else None
        for dd, j in zip(d, np.minimum(k, len(ad) - 1), strict=True)
    ]
    b["address"] = lab
    # nearest named street for labels of unnamed buildings
    segn = load(
        "segments",
        "name AS sname, class",
        "name IS NOT NULL AND subtype = 'road' AND class NOT IN ('motorway','trunk')",
    )
    segn = segn[segn.intersects(allstudy.buffer(200))]
    sidx = segn.sindex
    ROADS = {
        "primary",
        "secondary",
        "tertiary",
        "residential",
        "unclassified",
        "living_street",
        "service",
        "pedestrian",
    }

    def near_street(g):
        """Nearest named street: real streets within 40 m first, then any named way within 40 m, then streets within 120 m."""
        for r, only_roads in ((40, True), (40, False), (120, True), (120, False)):
            h = segn.iloc[list(sidx.query(g.buffer(r)))]
            h = h[h.distance(g) <= r]
            if only_roads:
                h = h[h["class"].isin(ROADS)]
            if len(h):
                return h.assign(d=h.distance(g)).sort_values("d").sname.iloc[0]
        return None

    streets = [near_street(g) for g in b.geometry]
    b["street"] = streets
    fl = b["floors_est"].astype(int).astype(str)
    b["label"] = np.where(
        b["name"].notna(),
        b["name"],
        np.where(
            pd.notna(lab),
            "Building at " + pd.Series(lab, index=b.index).fillna(""),
            np.where(
                pd.notna(streets),
                fl + "-storey building off " + pd.Series(streets, index=b.index).fillna(""),
                "Unnamed building",
            ),
        ),
    )
    ov = INPUTS / "building_labels.csv"
    if ov.exists():
        o = pd.read_csv(ov)
        for r in o.itertuples():
            m = (b["address"] == r.match_address) & b["name"].isna()
            b.loc[m, "label"] = r.label
    b.to_parquet(DERIVED / "buildings.parquet")
    summary["buildings"] = int(len(b))

    # ---- university land use (OSM relation) -----------------------------------------------
    lu = load("land_use", "id, subtype, class, name, src_id")
    lu = lu[lu.intersects(allstudy.buffer(200))].copy()
    lu.to_parquet(DERIVED / "land_use.parquet")
    uni_lu = lu[
        (lu["subtype"] == "education")
        & (lu["class"] == "university")
        & (
            lu["name"].fillna("").str.contains("Auckland")
            & ~lu["name"].fillna("").str.contains("Technology")
        )
    ]

    # ---- campus footprint: UoA buildings (education/university within study areas, or named) + land use ----
    edu = b[
        (b["subtype"] == "education")
        & (b["class"].isin(["university", "library"]))
        & b["campus"].notna()
    ]
    # exclude other institutions by name
    other = (
        "aut",
        "auckland university of technology",
        "massey",
        "otago",
        "victoria",
        "uunz",
        "yoobee",
        "nzma",
        "whitireia",
        "college of law",
        "mind lab",
        "wesley",
        "hotel and chefs",
        "st peter",
        "saint peter",
        "auckland grammar",
        "newmarket school",
        "mondrian",
    )
    edu = edu[~edu["name"].fillna("").str.lower().apply(lambda n: any(w in n for w in other))]
    named_extra = b[
        b["uoa_named"]
        & b["campus"].notna()
        & ~b.index.isin(edu.index)
        & ~b["name"].fillna("").str.lower().str.contains("stand|nutrition|press")
    ]
    edu = pd.concat([edu, named_extra])
    # AUT sits immediately north-west of the City campus; drop buildings inside the AUT relation
    aut = lu[lu["name"].fillna("").str.contains("Technology")]
    if len(aut):
        edu = edu[~edu.intersects(aut.union_all().buffer(-5))]
    parts = [edu.buffer(20).union_all()]
    if len(uni_lu):
        parts.append(uni_lu.union_all().buffer(5))
    foot = gpd.GeoSeries(parts, crs=NZTM).union_all().buffer(0)
    fp = gpd.GeoDataFrame(geometry=[g for g in getattr(foot, "geoms", [foot])], crs=NZTM)
    fp["area_m2"] = fp.area
    fp = fp[fp.area_m2 > 1500].copy()
    fp["campus"] = nearest_campus(fp)
    fp.to_parquet(DERIVED / "campus_footprint.parquet")
    edu.to_parquet(DERIVED / "uoa_buildings.parquet")
    summary["uoa_buildings"] = int(len(edu))
    summary["uoa_gfa_m2_by_campus"] = edu.groupby("campus")["gfa_m2"].sum().round().to_dict()

    # ---- infrastructure points: bike parking, lamps, stops, crossings, signals, benches, entrances ----
    inf = load("infrastructure", "id, subtype, class, name, level, src_id")
    inf = inf[inf.intersects(allstudy.buffer(600))].copy()
    inf["geometry"] = inf.geometry.centroid
    keep = {
        "bicycle_parking": "bike_parking",
        "street_lamp": "lamp",
        "bus_stop": "bus_stop",
        "crossing": "crossing",
        "traffic_signals": "signals",
        "bench": "bench",
        "parking_entrance": "parking_entrance",
        "parking": "car_parking",
        "parking_space": "car_space",
        "platform": "platform",
        "bollard": "bollard",
        "gate": "gate",
        "information": "information",
        "drinking_water": "drinking_water",
        "toilets": "toilets",
        "artwork": "artwork",
    }
    inf = inf[inf["class"].isin(keep)].copy()
    inf["kind"] = inf["class"].map(keep)
    nm = inf["name"].fillna("").str.lower()
    inf["is_locky_dock"] = nm.str.contains("lock") & nm.str.contains("dock")
    inf["is_uoa_cage"] = nm.str.contains("bike cage")
    inf["is_scooter_bay"] = nm.str.contains("scooter")
    inf.to_parquet(DERIVED / "infrastructure_points.parquet")
    bp = inf[inf.kind == "bike_parking"]
    summary["bike_parking_points"] = int(len(bp))
    summary["locky_docks_in_osm"] = int(bp.is_locky_dock.sum())
    summary["uoa_cages_in_osm"] = int(bp.is_uoa_cage.sum())

    # ---- places (POIs) ---------------------------------------------------------------------
    pl = load(
        "places", "id, name, category, basic_category, confidence, operating_status, src_dataset"
    )
    pl = pl[pl.intersects(allstudy.buffer(600))].copy()
    pl.to_parquet(DERIVED / "places.parquet")
    summary["places"] = int(len(pl))

    # ---- segments + connectors -> edge list ------------------------------------------------
    con = duckdb_connect("spatial")
    seg = con.execute(f"""
      SELECT id, subtype, class, subclass, name,
             list_transform(list_filter(sources, s -> s.record_id LIKE 'w%'), s -> s.record_id) AS osm_ways,
             list_transform(connectors, c -> c.connector_id) AS conn_ids,
             list_transform(connectors, c -> c.at) AS conn_at,
             speed_limits[1].max_speed.value AS maxspeed,
             list_transform(road_flags, f -> f.values) AS flags,
             array_to_string(list_transform(access_restrictions, a -> concat(a.access_type, ':', coalesce(array_to_string(a."when"."mode", ','), '*'))), ';') AS access,
             to_json(list_transform(access_restrictions, a -> {{'t': a.access_type, 'h': a."when".heading, 'm': a."when"."mode",
                     'u': a."when"."using", 'r': a."when".recognized, 'd': a."when".during,
                     'v': coalesce(len(a."when".vehicle), 0) > 0, 'b': a."between"}})) AS access_rules,
             list_transform(level_rules, l -> l.value) AS levels,
             ST_AsWKB(geometry) AS wkb
      FROM '{RAW_OVERTURE}/segments.parquet'
    """).df()
    seg["geometry"] = [wkb.loads(bytes(x)) for x in seg.pop("wkb")]
    seg = gpd.GeoDataFrame(seg, crs="EPSG:4326").to_crs(NZTM)
    seg = seg[seg.intersects(allstudy.buffer(900))].copy()
    seg["osm_way_id"] = seg["osm_ways"].apply(
        lambda vals: int(str(aslist(vals)[0]).split("@")[0][1:]) if len(aslist(vals)) else None
    )
    seg["all_osm_way_ids"] = seg["osm_ways"].apply(
        lambda vals: ";".join(str(x).split("@")[0][1:] for x in aslist(vals))
    )
    seg["flags"] = seg["flags"].apply(
        lambda vals: ";".join(sorted({str(f) for sub in aslist(vals) for f in aslist(sub)}))
    )
    seg["level"] = seg["levels"].apply(
        lambda vals: int(aslist(vals)[0]) if len(aslist(vals)) else 0
    )
    seg["length_m"] = seg.length
    seg = seg.drop(columns=["osm_ways", "levels"])
    seg_out = seg.drop(columns=["conn_ids", "conn_at"]).copy()
    seg_out["maxspeed"] = pd.to_numeric(seg_out["maxspeed"], errors="coerce")
    seg_out.to_parquet(DERIVED / "segments.parquet")
    summary["segments"] = int(len(seg))
    # explode to edges between consecutive connectors (Overture 'at' = fraction along the segment). Each edge keeps
    # the access rules that cover it: a rule with 'between' applies only to that fraction of the segment. The edge
    # runs u -> v in the segment's own direction, so Overture's heading 'forward' is u -> v and 'backward' is v -> u.
    from shapely.ops import substring

    rows = []
    seg = seg.rename(columns={"class": "cls"})
    for r in seg.itertuples():
        ids, ats = aslist(r.conn_ids), aslist(r.conn_at)
        if len(ids) < 2:
            continue
        L = r.geometry.length
        rules = (
            json.loads(r.access_rules)
            if isinstance(r.access_rules, str) and r.access_rules not in ("", "null")
            else []
        )
        for i in range(len(ids) - 1):
            a, bfrac = ats[i], ats[i + 1]
            if bfrac <= a:
                continue
            g = substring(r.geometry, a * L, bfrac * L)
            rows.append(
                dict(
                    seg_id=r.id,
                    u=ids[i],
                    v=ids[i + 1],
                    subtype=r.subtype,
                    cls=r.cls,
                    subclass=r.subclass,
                    name=r.name,
                    osm_way_id=r.osm_way_id,
                    maxspeed=(None if pd.isna(r.maxspeed) else float(r.maxspeed)),
                    flags=r.flags,
                    access=r.access,
                    access_rules=edge_rules([dict(x) for x in rules], a, bfrac),
                    level=r.level,
                    length_m=g.length,
                    geometry=g,
                )
            )
    edges = gpd.GeoDataFrame(rows, crs=NZTM)
    edges.to_parquet(DERIVED / "edges.parquet")
    summary["edges"] = int(len(edges))
    cn = load("connectors", "id")
    cn = cn[cn.intersects(allstudy.buffer(900))]
    cn.to_parquet(DERIVED / "connectors.parquet")
    summary["connectors"] = int(len(cn))

    with open(DERIVED / "build_layers_summary.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
