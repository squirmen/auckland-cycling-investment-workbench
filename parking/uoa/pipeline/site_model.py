"""Locky Dock siting model: candidates, suitability indicators, and coverage optimisation.

For each campus:
  1. Candidate sites = walkable network nodes and long-edge midpoints inside the campus footprint (+80 m),
     existing open bike racks (upgrade candidates) and car-parking polygon centroids (a 5-bike Locky Dock
     fits in one car space). Candidates on steps, inside buildings, on arterial carriageways or on
     grades > 8 % are excluded.
  2. Eight indicators per candidate (all also computed on an H3 resolution-11 hex grid for the map):
       coverage       cyclist arrivals/day at UoA buildings within walking reach, credit 1.0 at <=50 m
                      network walk falling linearly to 0 at 250 m (config walk_decay)
       arrival_flow   modelled cyclists/day passing on the approach network within 25 m (desire line)
       approach_lts   share of that passing flow that arrives on LTS 1-2 (low-stress) links
       surveillance   footway density (50 m), active frontage/POIs and bus stops (75 m), and openness of
                      sightlines from the LiDAR DSM (share of non-building ground within 20 m under 2.5 m)
       lighting       street lamps within 30 m (OSM; incomplete, so a soft signal)
       space_power    room for a 4.8 x 2.2 m station (car space, plaza, service road within 15 m) and mains
                      power (building within 30 m)
       slope          1.0 at <=2 %, 0 at 8 % (LINZ 1 m DEM)
       revealed_demand open racks within 40 m (people already park here) minus a penalty for a card-access
                      University bike store within 60 m (lower marginal value). The stores are the 14 in
                      data/inputs/uoa_bike_stores.csv (the University's own list; OSM tags only four cages).
                      store_m / store_name record the straight-line distance to, and name of, the nearest.
     Indicators are scaled 0-1 per campus and combined with the weights in config/model.json.
  3. Optimisation: choose k sites maximising covered arrivals (each building credited once, to its best
     chosen dock with walk decay) plus a suitability bonus, with a minimum spacing between docks.
     Solved exactly as a mixed-integer programme with CBC (PuLP). k is swept 1..8 to show diminishing
     returns; a greedy order gives a phasing sequence.

The campus footprint is data-derived (build_layers.py) and the University's OSM land-use relation has parts well
away from the three campuses (the Epsom campus, a small site near Mt Eden). Footprint parts that lie outside the
study areas (buffered FOOTPRINT_STUDY_BUFFER_M) are dropped here and in export_web.py, so they add no candidates,
no suitability hexes and nothing to a campus's hex scaling.

Outputs are deterministic: hexes are sorted by H3 id, so a rerun on the same inputs writes the same files whatever
PYTHONHASHSEED is. site_model_results.json carries a "built" timestamp (ISO 8601, New Zealand time), which
export_web.py copies into results.json.
"""

import json
import pathlib
import sys
import warnings

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pulp
import rasterio
from rasterio.mask import mask as rmask
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import Polygon

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import DERIVED, HERE, INPUTS, RAW_LINZ, require_derived, require_raw

warnings.filterwarnings("ignore")
CFG = json.loads((HERE / "config" / "model.json").read_text())
# a footprint part must lie mostly within this distance of the study areas
FOOTPRINT_STUDY_BUFFER_M = 100


def study_footprint(fp, study, buffer_m=FOOTPRINT_STUDY_BUFFER_M, quiet=False):
    """The campus footprint parts that lie in the study areas: at least half of each part's area within buffer_m of
    them. Parts outside every study area (the Epsom campus and a site near Mt Eden, from the University's OSM
    relation) are not part of the three campuses and are dropped."""
    zone = study.to_crs(fp.crs).union_all().buffer(buffer_m)
    share = fp.geometry.intersection(zone).area / fp.geometry.area
    keep = (share >= 0.5).values
    if not quiet and (~keep).any():
        out = fp[~keep]
        for campus, area_m2, c in zip(
            out.campus,
            out.geometry.area,
            out.geometry.representative_point().to_crs(4326),
            strict=True,
        ):
            print(
                f"campus footprint: dropped a {area_m2:,.0f} m2 '{campus}' part at {c.x:.4f}, {c.y:.4f}, outside the study areas",
                flush=True,
            )
    return fp[keep].copy()


def built_now():
    """The build time, ISO 8601 in New Zealand time (for the "built" key)."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo("Pacific/Auckland")).isoformat(timespec="seconds")


def minmax(s, lo=5, hi=95):
    a, b = np.nanpercentile(s, lo), np.nanpercentile(s, hi)
    if b - a <= 0:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return ((s - a) / (b - a)).clip(0, 1).fillna(0)


def walk_credit(d):
    f, z = CFG["walk_decay"]["full_credit_m"], CFG["walk_decay"]["zero_credit_m"]
    return np.clip((z - d) / (z - f), 0, 1)


def raster_stat(ds, pts, radius, fn, mask_geom=None):
    out = np.full(len(pts), np.nan)
    for i, p in enumerate(pts):
        try:
            geom = p.buffer(radius)
            if mask_geom is not None:
                geom = geom.difference(mask_geom)
            if geom.is_empty:
                continue
            arr, _ = rmask(ds, [geom.__geo_interface__], crop=True, filled=True, nodata=-9999)
            v = arr[0][(arr[0] != -9999) & np.isfinite(arr[0])]
            if v.size:
                out[i] = fn(v)
        except Exception:
            pass
    return out


def main():
    require_derived(
        "site_model.py",
        "network_edges",
        "network_nodes",
        "flow_edges",
        "flow_nodes",
        "destinations",
        "uoa_buildings",
        "buildings",
        "infrastructure_points",
        "land_use",
        "campus_footprint",
        "study_areas",
        "places",
    )
    require_raw(
        "site_model.py", RAW_LINZ / "slope_pct_study_1m.tif", RAW_LINZ / "nheight_study_1m.tif"
    )
    edges = gpd.read_parquet(DERIVED / "network_edges.parquet")
    nodes = gpd.read_parquet(DERIVED / "network_nodes.parquet")
    fe = gpd.read_parquet(DERIVED / "flow_edges.parquet")
    dest = gpd.read_parquet(DERIVED / "destinations.parquet")
    bld = gpd.read_parquet(DERIVED / "buildings.parquet")
    inf = gpd.read_parquet(DERIVED / "infrastructure_points.parquet")
    lu = gpd.read_parquet(DERIVED / "land_use.parquet")
    fp = gpd.read_parquet(DERIVED / "campus_footprint.parquet")
    study = gpd.read_parquet(DERIVED / "study_areas.parquet")
    places = gpd.read_parquet(DERIVED / "places.parquet")
    fp = study_footprint(fp, study)
    crs = nodes.crs
    nid = {k: i for i, k in enumerate(nodes.index)}
    xy = np.c_[nodes.geometry.x.values, nodes.geometry.y.values]
    # ---- walk graph ----
    w = edges[edges.walk_ok]
    u = w.u.map(nid)
    v = w.v.map(nid)
    ok = u.notna() & v.notna()
    w = w[ok]
    u = u[ok].astype(int).values
    v = v[ok].astype(int).values
    n = len(nodes)
    Gw = coo_matrix(
        (np.r_[w.walk_cost.values, w.walk_cost.values], (np.r_[u, v], np.r_[v, u])), shape=(n, n)
    ).tocsr()
    walk_nodes = np.unique(np.r_[u, v])
    wtree = cKDTree(xy[walk_nodes])

    def snap_walk(pts, maxd=80):
        d, k = wtree.query(np.c_[[p.x for p in pts], [p.y for p in pts]], distance_upper_bound=maxd)
        return np.where(np.isfinite(d), walk_nodes[np.minimum(k, len(walk_nodes) - 1)], -1), d

    # ---- context layers ----
    slope = rasterio.open(RAW_LINZ / "slope_pct_study_1m.tif")
    nh = rasterio.open(RAW_LINZ / "nheight_study_1m.tif")
    lamps = inf[inf.kind == "lamp"]
    racks = inf[
        (inf.kind == "bike_parking") & ~inf.is_uoa_cage & ~inf.is_locky_dock & ~inf.is_scooter_bay
    ]
    stops = inf[inf.kind == "bus_stop"]
    # University card-access bike stores: the University's list (14 stores on the three campuses), not the four
    # cages OSM happens to tag. Positions come from OSM where the store is mapped and are otherwise approximate
    # (the building it is in, or its address). Every store is used: the 60 m test asks whether a store is "next
    # door", and an approximate position is still at the right building. The quality flag travels with the
    # nearest-store fields so the map can say "about" where the position is approximate.
    sdf = pd.read_csv(INPUTS / "uoa_bike_stores.csv")
    stores = gpd.GeoDataFrame(sdf, geometry=gpd.points_from_xy(sdf.lon, sdf.lat), crs=4326).to_crs(
        crs
    )
    stores["mapped"] = stores.coord_quality.fillna("").str.startswith("osm_")
    print(
        f"University bike stores: {len(stores)} ({int(stores.mapped.sum())} at OSM positions, {int((~stores.mapped).sum())} approximate)",
        flush=True,
    )
    carpark = inf[inf.kind.isin(["car_parking", "car_space", "parking_entrance"])]
    plazas = lu[lu.subtype.isin(["pedestrian"]) | lu["class"].isin(["plaza", "pedestrian"])]
    active = places[
        places.basic_category.fillna("").str.contains(
            "eat_and_drink|retail|food|shopping|grocery|bar|cafe|restaurant", regex=True
        )
        | places.category.fillna("").str.contains(
            "cafe|restaurant|bar|coffee|bakery|grocery|convenience|supermarket|bookstore|pharmacy|bank|library|gym|fitness",
            regex=True,
        )
    ]
    footways = edges[edges.cls.isin(["footway", "pedestrian", "path", "cycleway"])]
    lamp_t = cKDTree(np.c_[lamps.geometry.x, lamps.geometry.y]) if len(lamps) else None
    rack_t = cKDTree(np.c_[racks.geometry.x, racks.geometry.y]) if len(racks) else None
    store_t = cKDTree(np.c_[stores.geometry.x, stores.geometry.y]) if len(stores) else None
    stop_t = cKDTree(np.c_[stops.geometry.x, stops.geometry.y]) if len(stops) else None
    act_t = cKDTree(np.c_[active.geometry.x, active.geometry.y]) if len(active) else None
    cp_t = cKDTree(np.c_[carpark.geometry.x, carpark.geometry.y]) if len(carpark) else None
    fe_sidx = fe.sindex
    fw_sidx = footways.sindex
    bld_sidx = bld.sindex
    plaza_sidx = plazas.sindex
    seg_named = edges[
        edges.name.notna()
        & ~edges.cls.isin(["motorway", "trunk"])
        & (edges.subclass.fillna("") != "link")
    ]
    seg_sidx = seg_named.sindex
    dest_nodes = dest.node.values.astype(int)
    dest_A = dest.A_j.values
    dest_entries = (
        [json.loads(e) for e in dest.entry_nodes]
        if "entry_nodes" in dest.columns
        else [[n] for n in dest_nodes]
    )
    dest_label = (
        dest.label.values if "label" in dest.columns else dest.name.fillna("UoA building").values
    )
    results, hexes, sweeps, selected = [], [], {}, {}
    for campus in ["city", "grafton", "newmarket"]:
        foot = fp[fp.campus == campus].union_all()
        area = foot.buffer(80)
        dmask = (dest.campus == campus).values
        dA = dest_A[dmask]
        dnames = dest_label[dmask]
        dent = [dest_entries[i] for i in np.where(dmask)[0]]

        def min_over_entries(Dm, offs):
            """Dm: candidates x all nodes distance matrix; returns candidates x destinations min walk over entrance nodes."""
            out = np.full((Dm.shape[0], len(dent)), np.inf)
            for j, ens in enumerate(dent):
                out[:, j] = np.min(Dm[:, ens], axis=1)
            return out + offs[:, None]

        # ---- candidates ----
        cand = []
        nd_in = nodes[nodes.intersects(area)]
        for k_, g in nd_in.geometry.items():
            i = nid[k_]
            inc = edges[(edges.u == k_) | (edges.v == k_)]
            if not len(inc) or not inc.walk_ok.any():
                continue
            cls = set(inc.cls)
            if cls <= set(CFG["exclusions"]["classes_excluded"]) or cls == {"steps"}:
                continue
            if inc.cls.isin(["primary", "secondary", "trunk", "motorway"]).all():
                continue
            cand.append(dict(kind="network_node", geometry=g, node=i))
        long_w = w[
            w.intersects(area)
            & (w.length_m > 60)
            & w.cls.isin(
                [
                    "footway",
                    "pedestrian",
                    "path",
                    "service",
                    "residential",
                    "living_street",
                    "cycleway",
                ]
            )
        ]
        cand.extend(
            dict(
                kind="edge_midpoint",
                geometry=r.geometry.interpolate(0.5, normalized=True),
                node=-1,
            )
            for r in long_w.itertuples()
        )
        cand.extend(
            dict(kind="existing_rack", geometry=r.geometry, node=-1)
            for r in racks[racks.intersects(area)].itertuples()
        )
        cand.extend(
            dict(kind="car_park", geometry=r.geometry, node=-1)
            for r in carpark[
                carpark.intersects(area) & (carpark.kind == "car_parking")
            ].itertuples()
        )
        c = gpd.GeoDataFrame(cand, crs=crs)
        # dedupe within 12 m (keep first: nodes first)
        t = cKDTree(np.c_[c.geometry.x, c.geometry.y])
        keep = np.ones(len(c), bool)
        for i, j in t.query_pairs(12):
            if keep[i] and keep[j]:
                keep[j] = False
        c = c[keep].reset_index(drop=True)
        # snap non-node candidates to the walk graph
        sn, sd = snap_walk(list(c.geometry), 60)
        c["walk_node"] = np.where(c.node >= 0, c.node, sn)
        c["snap_m"] = np.where(c.node >= 0, 0, sd)
        c = c[c.walk_node >= 0].reset_index(drop=True)
        # exclusions: inside a building, steep
        inside = np.array(
            [any(bld.geometry.iloc[j].contains(p) for j in bld_sidx.query(p)) for p in c.geometry]
        )
        c["slope_pct"] = raster_stat(slope, list(c.geometry), 4, np.nanmedian)
        c = c[~inside & (c.slope_pct.fillna(0) <= CFG["exclusions"]["max_slope_pct"])].reset_index(
            drop=True
        )
        # ---- indicators ----
        # coverage via walk dijkstra from each candidate node (limit 300 m)
        cn = c.walk_node.values.astype(int)
        D = dijkstra(Gw, directed=False, indices=cn, limit=CFG["walk_decay"]["zero_credit_m"] + 60)
        # candidates x destinations: shortest walk to any entrance node
        dd = min_over_entries(D, c.snap_m.values)
        credit = walk_credit(np.where(np.isfinite(dd), dd, 1e9))
        c["coverage"] = (credit * dA[None, :]).sum(axis=1)
        c["n_buildings_150m"] = (np.where(np.isfinite(dd), dd, 1e9) <= 150).sum(axis=1)
        c["nearest_building"] = [
            dnames[np.argmin(row)] if np.isfinite(row).any() else "" for row in dd
        ]
        c["nearest_building_m"] = [
            float(np.min(row)) if np.isfinite(row).any() else np.nan for row in dd
        ]
        # passing flow within 25 m: max edge flow; approach LTS share of flow within 40 m
        pf, al = [], []
        for p in c.geometry:
            hits = fe.iloc[list(fe_sidx.query(p.buffer(25)))]
            hits = hits[hits.distance(p) <= 25]
            pf.append(float(hits.flow_per_day.max()) if len(hits) else 0.0)
            h2 = fe.iloc[list(fe_sidx.query(p.buffer(40)))]
            h2 = h2[h2.distance(p) <= 40]
            tot = h2.flow_per_day.sum()
            al.append(float(h2[h2.lts <= 2].flow_per_day.sum() / tot) if tot > 0 else 0.5)
        c["arrival_flow"] = pf
        c["approach_lts"] = al
        # surveillance components
        fwd = []
        for p in c.geometry:
            h = footways.iloc[list(fw_sidx.query(p.buffer(50)))]
            fwd.append(float(h.intersection(p.buffer(50)).length.sum()))
        c["footway_len_50m"] = fwd
        c["active_75m"] = (
            act_t.query_ball_point(np.c_[c.geometry.x, c.geometry.y], 75, return_length=True)
            if act_t
            else 0
        )
        c["bus_stops_100m"] = (
            stop_t.query_ball_point(np.c_[c.geometry.x, c.geometry.y], 100, return_length=True)
            if stop_t
            else 0
        )
        bl_union = bld[bld.intersects(area.buffer(60))].union_all()
        c["openness"] = raster_stat(
            nh, list(c.geometry), 20, lambda v: float((v < 2.5).mean()), mask_geom=bl_union
        )
        c["overlooked"] = [
            min(
                len(
                    [
                        j
                        for j in bld_sidx.query(p.buffer(25))
                        if bld.geometry.iloc[j].distance(p) <= 25
                    ]
                ),
                3,
            )
            / 3
            for p in c.geometry
        ]
        c["lamps_30m"] = (
            lamp_t.query_ball_point(np.c_[c.geometry.x, c.geometry.y], 30, return_length=True)
            if lamp_t
            else 0
        )
        # space & power
        near_cp = cp_t.query(np.c_[c.geometry.x, c.geometry.y])[0] if cp_t else np.full(len(c), 1e9)
        near_plaza = np.array(
            [
                min(
                    [plazas.geometry.iloc[j].distance(p) for j in plaza_sidx.query(p.buffer(15))]
                    or [1e9]
                )
                for p in c.geometry
            ]
        )
        on_service = np.array(
            [
                any(
                    edges.iloc[j].cls in ("service", "living_street", "pedestrian")
                    for j in edges.sindex.query(p.buffer(6))
                )
                for p in c.geometry
            ]
        )
        c["space"] = np.where(
            (near_cp <= 15) | (near_plaza <= 15) | on_service | (c.kind == "car_park"), 1.0, 0.5
        )
        c["power"] = np.where([len(bld_sidx.query(p.buffer(30))) > 0 for p in c.geometry], 1.0, 0.4)
        c["space_power"] = 0.5 * c.space + 0.5 * c.power
        c["slope_score"] = np.clip((8 - c.slope_pct.fillna(4)) / 6, 0, 1)
        c["racks_40m"] = (
            rack_t.query_ball_point(np.c_[c.geometry.x, c.geometry.y], 40, return_length=True)
            if rack_t
            else 0
        )
        c["store_60m"] = (
            store_t.query_ball_point(np.c_[c.geometry.x, c.geometry.y], 60, return_length=True)
            if store_t
            else 0
        )
        # straight-line metres to the nearest store (NZTM)
        sd_, si_ = store_t.query(np.c_[c.geometry.x, c.geometry.y])
        c["store_m"] = np.round(sd_, 2)
        c["store_name"] = stores.name.values[si_]
        c["store_id"] = stores.id.values[si_]
        c["store_approx"] = ~stores.mapped.values[si_]
        c["revealed_demand"] = np.clip(
            np.minimum(c.racks_40m, 3) / 3 - 0.5 * (c.store_60m > 0), 0, 1
        )
        c["surveillance"] = (
            0.4 * minmax(c.footway_len_50m)
            + 0.3 * minmax(c.active_75m + 0.5 * c.bus_stops_100m)
            + 0.2 * c.openness.fillna(0.5)
            + 0.1 * c.overlooked
        )
        c["lighting"] = np.clip(c.lamps_30m / 3, 0, 1)
        W = CFG["suitability_weights"]
        c["s_coverage"] = minmax(c.coverage)
        c["s_arrival_flow"] = minmax(np.log1p(c.arrival_flow))
        c["s_approach_lts"] = c.approach_lts
        c["suitability"] = (
            W["coverage"] * c.s_coverage
            + W["arrival_flow"] * c.s_arrival_flow
            + W["approach_lts"] * c.s_approach_lts
            + W["surveillance"] * c.surveillance
            + W["lighting"] * c.lighting
            + W["space_power"] * c.space_power
            + W["slope"] * c.slope_score
            + W["revealed_demand"] * c.revealed_demand
        )
        # names: nearest named street
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

        def street_of(p):
            """Nearest named street (streets first, then named paths), within 30 m, else within 80 m marked as a campus path."""
            for r, only_roads in ((30, True), (30, False), (80, True), (80, False)):
                h = seg_named.iloc[list(seg_sidx.query(p.buffer(r)))]
                h = h[h.distance(p) <= r]
                if only_roads:
                    h = h[h.cls.isin(ROADS)]
                if len(h):
                    return h.assign(d=h.distance(p)).sort_values("d").name.iloc[0] + (
                        "" if r == 30 else " (campus path)"
                    )
            return "campus path"

        c["street"] = [street_of(p) for p in c.geometry]
        c["campus"] = campus
        c["cid"] = [f"{campus[:3].upper()}-{i:03d}" for i in range(len(c))]
        # ---- optimisation ----
        A_tot = dA.sum()
        cred = credit
        nC, nD = cred.shape
        pairs = [
            (i, j)
            for i, j in cKDTree(np.c_[c.geometry.x, c.geometry.y]).query_pairs(CFG["min_spacing_m"])
        ]

        def solve(k, gamma=0.3, fixed=None):
            """Exact k-dock set: maximise covered share plus a small suitability bonus (gamma / k x sum of the chosen
            sites' suitability), so a larger k can occasionally cover slightly less than a smaller one."""
            prob = pulp.LpProblem(f"ld_{campus}_{k}", pulp.LpMaximize)
            x = [pulp.LpVariable(f"x{i}", cat="Binary") for i in range(nC)]
            z = {
                (i, j): pulp.LpVariable(f"z{i}_{j}", lowBound=0, upBound=1)
                for i in range(nC)
                for j in range(nD)
                if cred[i, j] > 0
            }
            prob += pulp.lpSum(dA[j] / A_tot * cred[i, j] * z[(i, j)] for (i, j) in z) + (
                gamma / k
            ) * pulp.lpSum(c.suitability.iloc[i] * x[i] for i in range(nC))
            for j in range(nD):
                prob += pulp.lpSum(z[(i, jj)] for (i, jj) in z if jj == j) <= 1
            for (i, _j), zv in z.items():
                prob += zv <= x[i]
            prob += pulp.lpSum(x) == k
            for i, j in pairs:
                prob += x[i] + x[j] <= 1
            if fixed:
                for i in fixed:
                    prob += x[i] == 1
            prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))
            chosen = [i for i in range(nC) if x[i].value() and x[i].value() > 0.5]
            cov = sum(dA[j] * cred[i, j] * z[(i, j)].value() for (i, j) in z if z[(i, j)].value())
            return chosen, cov

        sweep, sols = [], {}
        for k in CFG["k_sweep"]:
            if k > nC:
                break
            ch, cov = solve(k)
            sols[k] = (ch, cov)
            sweep.append(
                {
                    "k": k,
                    "covered_arrivals": round(cov, 1),
                    "covered_share": round(cov / A_tot, 6),
                    "sites": [c.cid.iloc[i] for i in ch],
                }
            )
            print(campus, "k", k, "covered share", round(cov / A_tot, 4), flush=True)
        sweeps[campus] = sweep
        # the recommended set IS the sweep's solution at the recommended k (never a second solve that could differ)
        krec = CFG["k_per_campus"][campus]
        chosen, cov = sols[krec] if krec in sols else solve(krec)
        # greedy phasing order among the chosen set: repeatedly pick the site with largest marginal covered arrivals
        remaining, order, covered_best = list(chosen), [], np.zeros(nD)
        while remaining:
            gains = [
                ((np.maximum(covered_best, cred[i]) * dA).sum() - (covered_best * dA).sum(), i)
                for i in remaining
            ]
            g, i = max(gains)
            order.append((i, g))
            covered_best = np.maximum(covered_best, cred[i])
            remaining.remove(i)
        c["selected"] = False
        c["phase"] = 0
        c["marginal_arrivals"] = 0.0
        for ph, (i, g) in enumerate(order, 1):
            c.loc[i, ["selected", "phase", "marginal_arrivals"]] = [True, ph, g]
        # rank of every candidate by suitability, and which buildings each selected site serves
        c["rank"] = c.suitability.rank(ascending=False, method="first").astype(int)
        serves = []
        for i in range(nC):
            if not c.selected.iloc[i]:
                serves.append("")
                continue
            js = np.argsort(-cred[i] * dA)[:4]
            serves.append(
                "; ".join(f"{dnames[j]} ({dd[i, j]:.0f} m)" for j in js if cred[i, j] > 0)
            )
        c["serves"] = serves
        dids = dest.id.values[dmask]
        c["covers"] = [
            json.dumps(
                [
                    [str(dids[j]), round(float(cred[i, j]), 3), round(float(dd[i, j]))]
                    for j in np.where(cred[i] > 0)[0]
                ]
            )
            for i in range(nC)
        ]
        selected[campus] = {
            "k": krec,
            "covered_arrivals": round(cov, 1),
            "covered_share": round(cov / A_tot, 6),
            "arrivals_total": round(A_tot, 1),
            "sites": c[c.selected]
            .sort_values("phase")[
                [
                    "cid",
                    "phase",
                    "kind",
                    "street",
                    "nearest_building",
                    "nearest_building_m",
                    "coverage",
                    "marginal_arrivals",
                    "arrival_flow",
                    "approach_lts",
                    "surveillance",
                    "lighting",
                    "space",
                    "power",
                    "space_power",
                    "slope_pct",
                    "racks_40m",
                    "store_60m",
                    "store_m",
                    "store_name",
                    "suitability",
                    "serves",
                ]
            ]
            .round(3)
            .to_dict("records"),
        }
        sw = next((x for x in sweep if x["k"] == krec), None)
        assert sw is None or sorted(sw["sites"]) == sorted(
            x["cid"] for x in selected[campus]["sites"]
        ), f"{campus}: selected set differs from k_sweep at k={krec}"
        results.append(c)
        # ---- H3 r11 hex surface ----
        hex_ids = set()
        poly4326 = gpd.GeoSeries([area.buffer(70)], crs=crs).to_crs(4326).iloc[0]
        for g in getattr(poly4326, "geoms", [poly4326]):
            hex_ids |= set(h3.geo_to_cells(g, 11))
        # a set's order follows PYTHONHASHSEED; sorted, every run writes the same rows
        hex_ids = sorted(hex_ids)
        hx = gpd.GeoDataFrame(
            {"h3": hex_ids},
            geometry=[
                Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(h)]) for h in hex_ids
            ],
            crs=4326,
        ).to_crs(crs)
        cen = hx.geometry.centroid
        hn, hd = snap_walk(list(cen), 120)
        hx["walk_node"] = hn
        hx["snap_m"] = hd
        okh = hx.walk_node >= 0
        Dh = dijkstra(
            Gw,
            directed=False,
            indices=hx.walk_node[okh].values.astype(int),
            limit=CFG["walk_decay"]["zero_credit_m"] + 80,
        )
        ddh = min_over_entries(Dh, hx.snap_m[okh].values)
        hx["coverage"] = 0.0
        hx.loc[okh, "coverage"] = (
            walk_credit(np.where(np.isfinite(ddh), ddh, 1e9)) * dA[None, :]
        ).sum(axis=1)
        hpf = []
        for p in cen:
            hits = fe.iloc[list(fe_sidx.query(p.buffer(25)))]
            hits = hits[hits.distance(p) <= 25]
            hpf.append(float(hits.flow_per_day.max()) if len(hits) else 0.0)
        hx["arrival_flow"] = hpf
        hx["lamps_30m"] = (
            lamp_t.query_ball_point(np.c_[cen.x, cen.y], 30, return_length=True) if lamp_t else 0
        )
        hx["slope_pct"] = raster_stat(slope, list(cen), 6, np.nanmedian)
        hx["openness"] = raster_stat(
            nh, list(cen), 20, lambda v: float((v < 2.5).mean()), mask_geom=bl_union
        )
        fwh = []
        for p in cen:
            h = footways.iloc[list(fw_sidx.query(p.buffer(50)))]
            fwh.append(float(h.intersection(p.buffer(50)).length.sum()))
        hx["footway_len_50m"] = fwh
        hx["inside_building"] = [
            any(bld.geometry.iloc[j].contains(p) for j in bld_sidx.query(p)) for p in cen
        ]
        hx["s_coverage"] = minmax(hx.coverage)
        hx["s_arrival_flow"] = minmax(np.log1p(hx.arrival_flow))
        hx["surveillance"] = 0.6 * minmax(hx.footway_len_50m) + 0.4 * hx.openness.fillna(0.5)
        hx["lighting"] = np.clip(hx.lamps_30m / 3, 0, 1)
        hx["slope_score"] = np.clip((8 - hx.slope_pct.fillna(4)) / 6, 0, 1)
        hx["suitability"] = (
            W["coverage"] * hx.s_coverage
            + W["arrival_flow"] * hx.s_arrival_flow
            + (W["approach_lts"] + W["space_power"] + W["revealed_demand"]) * 0.5
            + W["surveillance"] * hx.surveillance
            + W["lighting"] * hx.lighting
            + W["slope"] * hx.slope_score
        )
        hx.loc[hx.inside_building, "suitability"] = np.nan
        hx["campus"] = campus
        hexes.append(hx)
        print(
            campus,
            "candidates",
            nC,
            "hexes",
            len(hx),
            "selected",
            selected[campus]["covered_share"],
            flush=True,
        )
    C = pd.concat(results, ignore_index=True)
    C.to_parquet(DERIVED / "candidates.parquet")
    H = pd.concat(hexes, ignore_index=True)
    H.to_parquet(DERIVED / "hex_suitability_r11.parquet")
    with open(DERIVED / "site_model_results.json", "w") as f:
        json.dump(
            {"built": built_now(), "selected": selected, "k_sweep": sweeps, "config": CFG},
            f,
            indent=1,
            default=str,
        )
    for campus, s in selected.items():
        print(
            f"\n=== {campus}: k={s['k']} covers {s['covered_share']:.0%} of {s['arrivals_total']:.0f} arrivals/day ==="
        )
        for r in s["sites"]:
            print(
                f"  {r['phase']}. {r['cid']} {r['kind']} @ {r['street']} near {r['nearest_building']} ({r['nearest_building_m']:.0f} m) cov={r['coverage']:.0f} flow={r['arrival_flow']:.0f} S={r['suitability']:.2f}"
            )


if __name__ == "__main__":
    main()
