"""Cyclist approach-flow model for the three University of Auckland campuses.

Question it answers: on which paths and streets do cyclists arrive at each UoA building, and how much
of the campus's cycling demand ends at each part of each campus?

Method (destination-constrained gravity model routed on the perceived-cost cycling network):
  1. Destinations j = UoA buildings (not halls of residence). Weight W_j = gross floor area x use factor
     (teaching/library/student-facing 1.0, research/office 0.7, recreation 0.8). Each campus's daily
     cyclist arrivals A_campus are split across its buildings in proportion to W_j.
     Entrances (entry_nodes) are the bike-network nodes within 25 m of the footprint, nearest first; they
     set walking distances (coverage) in site_model.py. Riders are routed to the first entrance that lies
     on the main cycling network (its largest connected part), else to the main-network node nearest the
     building: the nearest entrance is sometimes a short detached stub (a service lane or footway island of
     2-10 nodes) that no origin can reach, and routing there would silently drop that building's arrivals.
  2. Origins i are of two kinds:
     - residential buildings inside the study window (GFA as a population proxy; halls of residence x1.5
       because students cycle more than the average resident), snapped to the nearest main-network node
       within 150 m (an island node would strand the residents' trips);
     - "portals": points where the main cycling corridors enter the window, weighted by Auckland
       Transport counter volumes for those corridors (config/portals.json). They stand for the riders who
       live beyond the window (most of them: the median Auckland cycle commute is 4-6 km). Each portal snaps
       to the nearest node of the main network (within 400 m); a portal that fails to snap, or that no
       campus can be reached from, stops the run.
     Any destination arrivals or origin weight that still cannot be routed is printed as a warning with totals.
     A share `portal_share` (default 0.6) of arrivals is attributed to portals, the rest to residents.
  3. Perceived cost c_ij = shortest path on the directed cycling graph (length x LTS stress x grade).
     Origins are allocated to each destination in proportion to O_i x exp(-c_ij / lambda), lambda = 3000 m
     perceived (a 3 km perceived trip is e^-1 as likely as a 0 km one; sensitivity in docs).
  4. Flows are pushed down the shortest-path trees and accumulated on edges (Brandes-style dependency
     accumulation), giving cyclists/day on every edge and arrivals/day at every network node.

Outputs: data/derived/flow_edges.parquet, flow_nodes.parquet, destinations.parquet, origins.parquet,
and a JSON with the scenario parameters actually used.
"""

import json
import pathlib
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import Point

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import DERIVED, HERE, require_derived

CFG = json.loads((HERE / "config" / "model.json").read_text())

USE_FACTOR_DEFAULT = 1.0


def use_factor(name, cls):
    n = (name if isinstance(name, str) else "").lower()
    if cls == "dormitory":
        return 0.0
    if any(
        w in n
        for w in (
            "underpass",
            "overpass",
            "bridge",
            "car park",
            "carpark",
            "parking",
            "substation",
            "plant room",
        )
    ):
        return 0.0
    if any(
        w in n
        for w in (
            "press",
            "house",
            "annex",
            "workshop",
            "test hall",
            "structures",
            "building 9",
            "ray meyer",
            "carlton pines",
            "geothermal",
            "french",
        )
    ):
        return 0.7
    if any(w in n for w in ("hiwa", "recreation", "sport")):
        return 0.8
    return USE_FACTOR_DEFAULT


def build_graph(edges, nodes):
    """Directed cycling graph. Each edge gives an arc u->v and an arc v->u with its own cost; a direction closed by a
    one-way rule has no cost (NaN) and so no arc. Where parallel edges join the same two nodes, the cheaper arc is kept
    (and flows are credited to that edge). Returns the graph, the bike edges, the node index and, for every arc,
    the row of the edge it runs along."""
    nid = {k: i for i, k in enumerate(nodes.index)}
    e = edges[edges.bike_ok].copy().reset_index(drop=True)
    u = e.u.map(nid)
    v = e.v.map(nid)
    ok = (u.notna() & v.notna()).values
    e = e[ok].reset_index(drop=True)
    u = u[ok].astype(int).values
    v = v[ok].astype(int).values
    n = len(nodes)
    rows = np.concatenate([u, v])
    cols = np.concatenate([v, u])
    cost = np.concatenate([e.bike_cost_uv.values, e.bike_cost_vu.values]).astype(float)
    erow = np.concatenate([np.arange(len(e)), np.arange(len(e))])
    arcs = pd.DataFrame({"a": rows, "b": cols, "c": cost, "r": erow})
    arcs = arcs[np.isfinite(arcs.c) & (arcs.a != arcs.b)]
    # cheapest arc per ordered node pair
    arcs = arcs.sort_values("c").drop_duplicates(["a", "b"], keep="first")
    G = coo_matrix(
        (np.maximum(arcs.c.values, 0.1), (arcs.a.values, arcs.b.values)), shape=(n, n)
    ).tocsr()
    arc_edge = dict(
        zip(
            zip(arcs.a.values.tolist(), arcs.b.values.tolist(), strict=True),
            arcs.r.values.tolist(),
            strict=True,
        )
    )
    return G, e, nid, arc_edge


def main():
    require_derived(
        "build_demand.py", "network_edges", "network_nodes", "uoa_buildings", "buildings"
    )
    edges = gpd.read_parquet(DERIVED / "network_edges.parquet")
    nodes = gpd.read_parquet(DERIVED / "network_nodes.parquet")
    G, be, nid, arc_edge = build_graph(edges, nodes)
    xy = np.c_[nodes.geometry.x.values, nodes.geometry.y.values]
    # bike-reachable nodes only (nodes touched by a bike edge)
    bike_nodes = np.unique(np.concatenate([be.u.map(nid).values, be.v.map(nid).values]))
    btree = cKDTree(xy[bike_nodes])
    # The main cycling network: the largest strongly connected part of the bike graph, so every node on it can
    # reach, and be reached from, every other one even where one-way links apply. The other parts are islands of a
    # few nodes (short service lanes and footway stubs cut off by excluded links, or one-way stubs you cannot ride
    # back out of); nothing routed to or from one reaches the rest.
    _, comp = connected_components(G, directed=True, connection="strong")
    main_comp = np.bincount(comp).argmax()
    on_main = comp == main_comp
    main_nodes = bike_nodes[on_main[bike_nodes]]
    mtree = cKDTree(xy[main_nodes])
    n_islands = len(np.unique(comp[bike_nodes])) - 1
    print(
        f"cycling network: {len(bike_nodes)} nodes; main network {len(main_nodes)} nodes; {n_islands} detached islands "
        f"({len(bike_nodes) - len(main_nodes)} nodes)",
        flush=True,
    )

    def snap(pts, maxd=120, tree=btree, pool=bike_nodes):
        d, k = tree.query(np.c_[pts.x.values, pts.y.values], distance_upper_bound=maxd)
        idx = np.where(np.isfinite(d), pool[np.minimum(k, len(pool) - 1)], -1)
        return idx, d

    # ---- destinations ----
    ub = gpd.read_parquet(DERIVED / "uoa_buildings.parquet")
    ub = ub[ub.campus.notna()].copy()
    ub["use_factor"] = [use_factor(n, c) for n, c in zip(ub.name, ub["class"], strict=True)]
    ub = ub[ub.use_factor > 0].copy()
    ub["W"] = ub.gfa_m2 * ub.use_factor
    if "label" not in ub.columns:
        ub["label"] = ub.name.fillna("UoA building")
    # entrance nodes: walkable/bikeable network nodes within 25 m of the footprint (up to 8), else the nearest node to the polygon
    ntree_all = cKDTree(xy[bike_nodes])
    entries, prim, snapd = [], [], []
    for g in ub.geometry:
        cx, cy = g.centroid.x, g.centroid.y
        rad = max(
            40.0, float(np.hypot(*(np.array(g.bounds[2:]) - np.array(g.bounds[:2])))) / 2 + 30
        )
        idx = ntree_all.query_ball_point([cx, cy], rad)
        cand = [(g.distance(Point(xy[bike_nodes[i]])), int(bike_nodes[i])) for i in idx]
        cand.sort()
        near = [n for d, n in cand if d <= 25][:8]
        if not near and cand:
            near = [cand[0][1]]
        if not near:
            d, k = ntree_all.query([cx, cy])
            near = [int(bike_nodes[k])]
        entries.append(near)
        prim.append(near[0])
        snapd.append(float(min(d for d, n in cand if n == near[0])) if cand else 0.0)
    ub["entry_nodes"] = [json.dumps(e) for e in entries]
    ub["snap_m"] = snapd
    arrivals = CFG["arrivals_per_day"]  # per campus, from config (documented assumptions)
    ub["A_j"] = ub.groupby("campus").W.transform(lambda w: w / w.sum()) * ub.campus.map(arrivals)
    # Routing node: the first entrance on the main network, else the main-network node nearest the building.
    # entry_nodes stay as they are (walking distances and coverage do not change); only where riders are routed to does.
    route, how = [], []
    for ens, g in zip(entries, ub.geometry, strict=True):
        m = [n for n in ens if on_main[n]]
        if m:
            route.append(m[0])
            how.append("entrance" if m[0] == ens[0] else "later_entrance")
        else:
            _, k = mtree.query([g.centroid.x, g.centroid.y])
            route.append(int(main_nodes[k]))
            how.append("nearest_main_node")
    ub["entrance_node"] = prim  # nearest entrance, which may be on an island
    ub["node"] = route
    ub["route_via"] = how
    ub["route_m"] = [
        float(g.distance(Point(xy[n]))) for g, n in zip(ub.geometry, route, strict=True)
    ]
    isl = ~on_main[np.array(prim)]
    print(
        f"destinations: {len(ub)}; nearest entrance on an island for {int(isl.sum())} ({ub.A_j[isl].sum():.1f} of {ub.A_j.sum():.1f} arrivals/day, "
        f"{ub.A_j[isl].sum() / ub.A_j.sum():.1%}); routed instead from a later entrance: {int((ub.route_via == 'later_entrance').sum())}, "
        f"from the nearest main-network node: {int((ub.route_via == 'nearest_main_node').sum())}; on an island after rerouting: {int((~on_main[ub.node.values]).sum())}",
        flush=True,
    )
    for r in ub[isl].sort_values("A_j", ascending=False).itertuples():
        print(
            f"  {r.campus:9s} {str(r.label)[:48]:48s} {r.A_j:6.1f}/day  island of {int(np.sum(comp == comp[r.entrance_node]))} nodes -> {r.route_via} {r.route_m:.0f} m from the footprint"
        )
    ub.to_parquet(DERIVED / "destinations.parquet")

    # ---- origins: residents ----
    b = gpd.read_parquet(DERIVED / "buildings.parquet")
    res = b[
        (b.subtype == "residential")
        | (
            b["class"].isin(
                ["house", "apartments", "terrace", "detached", "dormitory", "residential"]
            )
        )
    ].copy()
    res["O"] = res.gfa_m2 * np.where(res["class"] == "dormitory", 1.5, 1.0)
    RES_MAX_SNAP_M = 150
    # the nearest bike node of any part (the old rule), for the report
    any_node, _ = snap(res.geometry.centroid, RES_MAX_SNAP_M)
    res["node"], _ = snap(res.geometry.centroid, RES_MAX_SNAP_M, mtree, main_nodes)
    O_all = res.O.sum()
    was = any_node >= 0
    was_isl = was & ~on_main[np.maximum(any_node, 0)]
    old_nodes = pd.Series(res.O.values[was], index=any_node[was]).groupby(level=0).sum()
    old_isl = old_nodes[~on_main[old_nodes.index.values]]
    print(
        f"resident origins: {len(res)} buildings; nearest bike node within {RES_MAX_SNAP_M} m: {int(was.sum())} buildings on {len(old_nodes)} nodes, "
        f"of which {int(was_isl.sum())} buildings on {len(old_isl)} island nodes ({old_isl.sum() / old_nodes.sum():.1%} of resident weight); "
        f"snapped to the main network instead: {int((res.node >= 0).sum())} buildings on {res.node[res.node >= 0].nunique()} nodes; "
        f"no main-network node within {RES_MAX_SNAP_M} m: {int((res.node < 0).sum())} buildings ({res.O[res.node < 0].sum() / O_all:.1%} of resident weight; "
        f"{int((any_node < 0).sum())} buildings, {res.O[any_node < 0].sum() / O_all:.1%}, under the old rule)",
        flush=True,
    )
    res_dropped = {
        "buildings": int((res.node < 0).sum()),
        "weight_share": round(float(res.O[res.node < 0].sum() / O_all), 4),
    }
    res_island_before = {
        "buildings": int(was_isl.sum()),
        "nodes": int(len(old_isl)),
        "of_nodes": int(len(old_nodes)),
        "weight_share": round(float(old_isl.sum() / old_nodes.sum()), 4),
    }
    res = res[res.node >= 0]
    org = res.groupby("node").O.sum().reset_index()
    org["kind"] = "resident"
    # ---- origins: portals ----
    # A portal stands for hundreds of riders a day, so it must land on the part of the cycling network that
    # reaches the campuses: portals snap only to nodes of the largest connected component (a two-node stub of
    # carriageway or a footway island next to the portal would silently strand its riders). A portal that
    # does not snap within PORTAL_MAX_SNAP_M is a configuration error, not something to drop quietly.
    PORTAL_MAX_SNAP_M = 400
    portals = json.loads((HERE / "config" / "portals.json").read_text())
    pdf = gpd.GeoDataFrame(
        portals, geometry=[Point(p["lon"], p["lat"]) for p in portals], crs="EPSG:4326"
    ).to_crs(nodes.crs)
    d, k = mtree.query(
        np.c_[pdf.geometry.x.values, pdf.geometry.y.values], distance_upper_bound=PORTAL_MAX_SNAP_M
    )
    pdf["node"] = np.where(np.isfinite(d), main_nodes[np.minimum(k, len(main_nodes) - 1)], -1)
    pdf["snap_m"] = np.where(
        np.isfinite(d), d, mtree.query(np.c_[pdf.geometry.x.values, pdf.geometry.y.values])[0]
    )
    near_names = []
    for nd in pdf.node:
        if nd < 0:
            near_names.append("")
            continue
        inc = be[(be.u.map(nid) == nd) | (be.v.map(nid) == nd)]
        near_names.append("; ".join(sorted(set(inc.name.dropna())) or sorted(set(inc.cls))))
    pdf["snap_to"] = near_names
    print("portal snaps (largest connected component of the cycling network):")
    for r in pdf.itertuples():
        print(
            f"  {r.id:20s} {r.weight_per_day:5d}/day  snap {r.snap_m:7.1f} m  node {r.node:6d}  {r.snap_to}"
        )
    dropped = pdf[pdf.node < 0]
    if len(dropped):
        where = ", ".join(f"{r.id} ({r.snap_m:.0f} m)" for r in dropped.itertuples())
        raise SystemExit(
            f"portals do not snap to the cycling network within {PORTAL_MAX_SNAP_M} m "
            f"(move them in config/portals.json): {where}"
        )
    pdf["O"] = pdf.weight_per_day
    porg = pdf.groupby("node").O.sum().reset_index()
    porg["kind"] = "portal"
    share = CFG["portal_share"]
    org["O_norm"] = org.O / org.O.sum() * (1 - share)
    porg["O_norm"] = porg.O / porg.O.sum() * share
    origins = pd.concat([org, porg], ignore_index=True)
    # For the record: what the old rule (route to the nearest entrance; residents to the nearest bike node of any
    # part) would have lost. Two nodes connect exactly when they share a part, so this needs no routing.
    old_o = pd.concat(
        [
            pd.DataFrame(
                {
                    "node": old_nodes.index.values,
                    "w": old_nodes.values / old_nodes.sum() * (1 - share),
                }
            ),
            pd.DataFrame({"node": porg.node.values, "w": porg.O_norm.values}),
        ]
    )
    oc, dc = set(comp[old_o.node.values]), set(comp[ub.entrance_node.values])
    old_lost_A = float(ub.A_j[[comp[n] not in oc for n in ub.entrance_node]].sum())
    old_lost_w = float(old_o.w[[comp[n] not in dc for n in old_o.node]].sum())
    print(
        f"under the old rule {old_lost_A:.1f} of {ub.A_j.sum():.1f} arrivals/day could not be routed and {old_lost_w:.1%} of origin weight "
        f"reached no destination; with main-network routing every destination and origin is on one network",
        flush=True,
    )
    origins_g = gpd.GeoDataFrame(
        origins, geometry=[Point(xy[i]) for i in origins.node], crs=nodes.crs
    )
    origins_g.to_parquet(DERIVED / "origins.parquet")
    pdf.to_parquet(DERIVED / "portals.parquet")

    # ---- gravity + accumulation ----
    lam = CFG["lambda_perceived_m"]
    n = G.shape[0]
    GT = G.T.tocsr()  # reverse graph: dijkstra from destination gives origin->destination costs
    edge_flow = np.zeros(len(be))
    node_arrivals = np.zeros(n)
    # map each directed arc to the edge row it runs along (the cheaper of any parallel edges), for accumulation
    arc_index = arc_edge
    o_nodes = origins.node.values
    o_w = origins.O_norm.values
    dest_nodes = ub.node.values
    dest_A = ub.A_j.values
    # group destinations by node to reduce dijkstra runs
    dgroups = pd.DataFrame({"node": dest_nodes, "A": dest_A}).groupby("node").A.sum()
    print("dijkstra runs:", len(dgroups), "origins:", len(o_nodes), flush=True)
    reached = np.zeros(len(o_nodes), bool)
    unrouted = {}  # destination node -> arrivals/day that no origin could be routed to
    for dnode, A in dgroups.items():
        dist, pred = dijkstra(GT, directed=True, indices=dnode, return_predecessors=True)
        c = dist[o_nodes]
        reach = np.isfinite(c)
        reached |= reach
        if not reach.any():
            unrouted[dnode] = A
            continue
        p = o_w[reach] * np.exp(-c[reach] / lam)
        if p.sum() <= 0:
            unrouted[dnode] = A
            continue
        T = A * p / p.sum()  # trips from each reachable origin to this destination
        # accumulate along predecessor chain on the REVERSE graph: pred[i] is the next hop from i toward dnode
        flow = np.zeros(n)
        flow[o_nodes[reach]] += T
        order = np.argsort(-dist[np.isfinite(dist)])  # process far nodes first
        idx_fin = np.where(np.isfinite(dist))[0][order]
        for i in idx_fin:
            f = flow[i]
            if f <= 0 or i == dnode:
                continue
            j = pred[i]
            if j < 0:
                continue
            r = arc_index.get((i, j))
            if r is not None:
                edge_flow[r] += f
            flow[j] += f
        node_arrivals[dnode] += A
    stranded = sorted(
        set(pdf.id[pdf.node.isin(origins.node[(origins.kind == "portal").values & ~reached])])
    )
    if stranded:
        raise SystemExit(f"portals that no campus destination can be reached from: {stranded}")
    A_tot = float(dest_A.sum())
    A_un = float(sum(unrouted.values()))
    ow_un = float(o_w[~reached].sum())
    print(
        f"routed: {A_tot - A_un:.1f} of {A_tot:.1f} arrivals/day; origin weight reaching no destination: {ow_un:.4f} of {o_w.sum():.4f}",
        flush=True,
    )
    if A_un > 0:
        names = ub[ub.node.isin(list(unrouted))]
        print(
            f"WARNING: {A_un:.1f} arrivals/day ({A_un / A_tot:.1%}) at {len(names)} destinations could not be routed from any origin: "
            + "; ".join(f"{r.label} ({r.A_j:.1f})" for r in names.itertuples()),
            flush=True,
        )
    if ow_un > 0:
        print(
            f"WARNING: {int((~reached).sum())} origins ({ow_un / o_w.sum():.1%} of origin weight: resident {o_w[~reached & (origins.kind == 'resident').values].sum():.4f}, "
            f"portal {o_w[~reached & (origins.kind == 'portal').values].sum():.4f}) reach no destination; their share goes to the origins that do",
            flush=True,
        )
    be = be.copy()
    be["flow_per_day"] = edge_flow
    be[
        [
            "seg_id",
            "u",
            "v",
            "cls",
            "subclass",
            "name",
            "lts",
            "lts_source",
            "grade_uv_pct",
            "length_m",
            "flow_per_day",
            "geometry",
        ]
    ].to_parquet(DERIVED / "flow_edges.parquet")
    fn = nodes.copy()
    fn["arrivals_per_day"] = node_arrivals
    # also: incoming flow at each node (sum of flows on incident edges / 2 as a 'passing' measure)
    eu = be.u.map(nid).values
    ev = be.v.map(nid).values
    inc = np.zeros(n)
    np.add.at(inc, eu, edge_flow)
    np.add.at(inc, ev, edge_flow)
    fn["passing_flow"] = inc / 2.0
    fn.to_parquet(DERIVED / "flow_nodes.parquet")
    summ = {
        "destinations": int(len(ub)),
        "origins_resident_nodes": int(len(org)),
        "portals": int(len(pdf)),
        "portal_nodes": int(len(porg)),
        "routing": {
            "main_network_nodes": int(len(main_nodes)),
            "bike_nodes": int(len(bike_nodes)),
            "islands": int(n_islands),
            "destinations_nearest_entrance_on_island": int(isl.sum()),
            "arrivals_nearest_entrance_on_island": round(float(ub.A_j[isl].sum()), 1),
            "destinations_routed_via": ub.route_via.value_counts().to_dict(),
            "resident_on_island_under_nearest_node_rule": res_island_before,
            "resident_no_main_node_within_150m": res_dropped,
            "old_rule_unrouted_arrivals_per_day": round(old_lost_A, 1),
            "old_rule_unreached_origin_weight": round(old_lost_w, 4),
            "unrouted_arrivals_per_day": round(A_un, 3),
            "unreached_origin_weight": round(ow_un, 6),
        },
        "portal_snap_m": {r.id: round(float(r.snap_m), 1) for r in pdf.itertuples()},
        "portal_share": share,
        "lambda_perceived_m": lam,
        "arrivals_per_day": arrivals,
        "total_flow_edge_km": float((be.flow_per_day * be.length_m).sum() / 1000),
        "top_edges": be.sort_values("flow_per_day", ascending=False)
        .head(12)[["name", "cls", "lts", "flow_per_day"]]
        .round(1)
        .astype(object)
        .where(lambda t: t.notna(), None)
        .to_dict("records"),
    }
    with open(DERIVED / "build_demand_summary.json", "w") as f:
        json.dump(summ, f, indent=1, default=str)
    print(json.dumps(summ, indent=1, default=str))


if __name__ == "__main__":
    main()
