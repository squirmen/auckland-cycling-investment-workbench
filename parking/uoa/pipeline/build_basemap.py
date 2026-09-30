"""Own-data basemap for the STAND map: no third-party tiles, so it also works where tile hosts cannot be reached
(an offline build, see pipeline/build_standalone.py --offline).

Writes web/data/basemap/:
  plain_ov.png            the whole wide window (lon 174.700..174.840, lat -36.925..-36.828) at ~6 m/px
  plain_d_<row>_<col>.png the study window (lon 174.735..174.800, lat -36.890..-36.835) at ~1.2 m/px, tiles <= 2048 px
  aerial_<row>_<col>.jpg  LINZ Auckland 0.075 m urban aerials 2024-25 over the wide window at ~2.5 m/px, tiles <= 2048 px
  labels_suburbs.geojson  suburb names (Overture divisions) with a size rank
  labels_roads.geojson    named trunk/primary/secondary/tertiary roads, merged by name, simplified to ~5 m
  basemap.json            for every image: MapLibre image-source corners (TL, TR, BR, BL; lon/lat) from the exact
                          EPSG:3857 extent, pixel size, bytes, ground m/px and a minzoom hint

Every image is rendered in EPSG:3857 on a grid snapped to a multiple of its pixel size, so the corners are exact
and adjacent tiles share edges to the bit. The cartographic images carry no text; labels are GeoJSON drawn by
MapLibre with the map's self-hosted glyphs.

Inputs: the wide-window Overture pull (pipeline/fetch_overture.py --bbox ... --out $STAND_DATA/overture_wide --lite)
and the LINZ nz-imagery open bucket (read over HTTPS, overview level only).

Usage: python3 pipeline/build_basemap.py [plain] [labels] [aerial] [--dry-run]   (default: all three)
"""

import argparse
import concurrent.futures as cf
import json
import math
import os
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import BIG, WEB_DATA, ca_bundle

OUT = WEB_DATA / "basemap"
WIDE_SRC = BIG / "overture_wide"
WIDE = (174.700, -36.925, 174.840, -36.828)  # lon0, lat0, lon1, lat1
DETAIL = (174.735, -36.890, 174.800, -36.835)  # the study window
LAT_MID = -36.8765
COS = math.cos(math.radians(LAT_MID))  # 3857 units per ground metre = 1/COS
R = 6378137.0
MAX_TILE = 2048

# --------------------------------------------------------------------------- web mercator grid


def lon2x(lon):
    return math.radians(lon) * R


def lat2y(lat):
    return R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def x2lon(x):
    return math.degrees(x / R)


def y2lat(y):
    return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


def grid(bbox, ground_m, max_px=MAX_TILE):
    """A 3857 raster grid over bbox at ~ground_m metres per pixel (at the window's mid latitude), split into
    tiles of at most max_px. The extent is snapped outward to whole pixels so corner coordinates are exact."""
    res = round(ground_m / COS, 4)
    x0 = math.floor(lon2x(bbox[0]) / res) * res
    x1 = math.ceil(lon2x(bbox[2]) / res) * res
    y0 = math.floor(lat2y(bbox[1]) / res) * res
    y1 = math.ceil(lat2y(bbox[3]) / res) * res
    W = int(round((x1 - x0) / res))
    H = int(round((y1 - y0) / res))
    nx, ny = math.ceil(W / max_px), math.ceil(H / max_px)
    cs = [round(i * W / nx) for i in range(nx + 1)]
    rs = [round(j * H / ny) for j in range(ny + 1)]
    tiles = []
    for j in range(ny):
        for i in range(nx):
            c0, c1, r0, r1 = cs[i], cs[i + 1], rs[j], rs[j + 1]
            tiles.append(
                {
                    "row": j,
                    "col": i,
                    "c0": c0,
                    "c1": c1,
                    "r0": r0,
                    "r1": r1,
                    "left": x0 + c0 * res,
                    "right": x0 + c1 * res,
                    "top": y1 - r0 * res,
                    "bottom": y1 - r1 * res,
                }
            )
    return {
        "res": res,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "W": W,
        "H": H,
        "nx": nx,
        "ny": ny,
        "tiles": tiles,
    }


def corners(t):
    """MapLibre image-source order: top-left, top-right, bottom-right, bottom-left, as [lon, lat]."""
    L, Rr, T, B = x2lon(t["left"]), x2lon(t["right"]), y2lat(t["top"]), y2lat(t["bottom"])

    def r(v):
        return round(v, 8)

    return [[r(L), r(T)], [r(Rr), r(T)], [r(Rr), r(B)], [r(L), r(B)]]


def entry(path, t, g, ground_m, minzoom, **extra):
    return {
        "file": f"basemap/{path.name}",
        "coordinates": corners(t),
        "width": t["c1"] - t["c0"],
        "height": t["r1"] - t["r0"],
        "bytes": path.stat().st_size,
        "m_per_px": round(ground_m, 2),
        "res_3857": g["res"],
        "minzoom": minzoom,
        "extent_3857": [
            round(t["left"], 4),
            round(t["bottom"], 4),
            round(t["right"], 4),
            round(t["top"], 4),
        ],
        **extra,
    }


def update_manifest(part, value):
    p = OUT / "basemap.json"
    m = json.loads(p.read_text()) if p.exists() else {}
    m[part] = value
    m["wide_bbox"] = list(WIDE)
    m["detail_bbox"] = list(DETAIL)
    m["note"] = (
        "Own-data basemap built by pipeline/build_basemap.py. Coordinates are MapLibre image-source corners "
        "(TL, TR, BR, BL) computed from each image's exact EPSG:3857 extent."
    )
    p.write_text(json.dumps(m, indent=1))


# --------------------------------------------------------------------------- plain (cartographic, own data)

# Better Places Lab palette (TEAM / SPAN): quiet, cool neutral
PAL = {
    "land": "#eef0ee",
    "water": "#cfdde4",
    "shore": "#b9ccd5",
    "green": "#dfe7da",
    "sand": "#efeee8",
    "plaza": "#f6f7f5",
    "building": "#d7dad7",
    "building_edge": "#c9cdc9",
    "road": "#ffffff",
    "casing": "#e1e4e1",
    "major": "#f3efe6",
    "major_casing": "#e3dccd",
    "rail": "#b9bec2",
    "path": "#ffffff",
}
PLAIN_OV_M, PLAIN_D_M = 6.0, 1.2
DPI = 64  # a power of two, so figure size in inches * dpi is exactly the pixel size
PT = 72.0 / DPI  # matplotlib line widths are in points; this converts pixels to points
# road classes, bottom to top: (name, Overture classes, width in metres at the detail level, width in px on the overview, colour)
ROADS = [
    ("service", {"service", "track", "unknown"}, 4.0, 0.0, "road"),
    ("pedestrian", {"pedestrian"}, 4.5, 0.0, "road"),
    ("minor", {"residential", "living_street", "unclassified"}, 8.5, 1.0, "road"),
    ("tertiary", {"tertiary"}, 10.5, 1.5, "road"),
    ("secondary", {"secondary"}, 12.5, 2.0, "road"),
    ("primary", {"primary"}, 13.5, 2.3, "road"),
    ("trunk", {"trunk"}, 15.0, 2.7, "major"),
    ("motorway", {"motorway"}, 17.0, 3.1, "major"),
]
PATHS = {"footway", "path", "cycleway", "bridleway"}
GREEN_LU_SUB = {
    "park",
    "golf",
    "cemetery",
    "protected",
    "recreation",
    "managed",
    "horticulture",
    "agriculture",
}
GREEN_LU_SKIP = {"marina", "stadium", "plant_nursery", "farmyard", "track"}
GREEN_LAND_SUB = {"forest", "grass", "shrub", "wetland", "tree"}


def _flag_spans(flags, names):
    """Fractions of a segment carrying any of the given road flags ([(a, b)], whole segment = (0, 1))."""
    out = []
    if flags is None:
        return out
    for f in flags:
        if any(v in names for v in f["values"]):
            b = f["between"]
            out.append((0.0, 1.0) if b is None else (float(b[0]), float(b[1])))
    return out


def load_plain_layers():
    import geopandas as gpd
    import shapely
    from shapely.geometry import box
    from shapely.ops import substring

    t0 = time.time()
    g = grid(WIDE, PLAIN_OV_M)
    frame = box(g["x0"] - 500, g["y0"] - 500, g["x1"] + 500, g["y1"] + 500)

    def rd(name):
        d = gpd.read_parquet(WIDE_SRC / f"{name}.parquet").to_crs(3857)
        return d[d.intersects(frame)]

    def polys(d):
        return d[d.geom_type.isin(["Polygon", "MultiPolygon"])]

    water = rd("water")
    land = rd("land")
    lu = rd("land_use")
    seg = rd("segments")
    bld = polys(rd("buildings"))
    L = {}
    oc = water[water.subtype == "ocean"]
    L["ocean"] = [oc.union_all().intersection(frame)] if len(oc) else []
    iw = polys(
        water[
            water.subtype.isin(["lake", "pond", "reservoir", "river", "water", "canal", "physical"])
        ]
    )
    L["water"] = list(iw.geometry)
    gl = polys(land[land.subtype.isin(GREEN_LAND_SUB)])
    gu = polys(lu[lu.subtype.isin(GREEN_LU_SUB) & ~lu["class"].isin(GREEN_LU_SKIP)])
    L["green"] = list(gl.geometry) + list(gu.geometry)
    L["sand"] = list(polys(land[land.subtype == "sand"]).geometry)
    L["plaza"] = list(polys(lu[lu.subtype == "pedestrian"]).geometry)
    L["buildings"] = list(bld.geometry)
    # transport: drop tunnels, indoor, abandoned and under-construction parts
    keep = []
    for geom, flags in zip(seg.geometry, seg.road_flags, strict=True):
        drop = sorted(
            _flag_spans(flags, {"is_tunnel", "is_indoor", "is_abandoned", "is_under_construction"})
        )
        if not drop:
            keep.append(geom)
            continue
        if any(a <= 0.001 and b >= 0.999 for a, b in drop):
            keep.append(None)
            continue
        parts, cur = [], 0.0
        for a, b in drop:
            if a > cur + 1e-4:
                parts.append(substring(geom, cur, a, normalized=True))
            cur = max(cur, b)
        if cur < 0.9999:
            parts.append(substring(geom, cur, 1.0, normalized=True))
        parts = [q for q in parts if q.geom_type == "LineString" and q.length > 0]
        keep.append(shapely.MultiLineString(parts) if parts else None)
    seg = seg.assign(geometry=keep)
    seg = seg[seg.geometry.notna()].set_crs(3857, allow_override=True)
    link = seg.subclass.eq("link") | seg.road_flags.apply(
        lambda f: bool(_flag_spans(f, {"is_link"}))
    )
    road = seg[seg.subtype == "road"]
    L["roads"] = {}
    for name, classes, _wm, _wo, _col in ROADS:
        r = road[road["class"].isin(classes)]
        if name == "service":
            r = r[~r.subclass.isin(["driveway"])]
            L["driveways"] = list(road[road.subclass.eq("driveway")].geometry)
        L["roads"][name] = (
            list(r[~link.loc[r.index]].geometry),
            list(r[link.loc[r.index]].geometry),
        )
    L["paths"] = list(
        road[
            road["class"].isin(PATHS)
            & ~road.subclass.isin(["sidewalk", "crosswalk", "cycle_crossing"])
        ].geometry
    )
    L["rail"] = list(seg[seg.subtype == "rail"].geometry)
    print(
        f"plain: layers loaded in {time.time() - t0:.0f}s: {len(L['buildings'])} buildings, {sum(len(a) + len(b) for a, b in L['roads'].values())} roads, "
        f"{len(L['green'])} green, {len(L['water'])} water, {len(L['rail'])} rail",
        flush=True,
    )
    return L


def _paths(geoms, clip):
    """shapely (multi)polygons -> matplotlib Paths (holes kept), clipped to the render frame."""
    import shapely
    from matplotlib.path import Path

    out = []
    for g0 in geoms:
        if g0 is None or g0.is_empty:
            continue
        g1 = shapely.clip_by_rect(g0, *clip)
        if g1.is_empty:
            continue
        for poly in shapely.get_parts(g1):
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            verts, codes = [], []
            for ring in [poly.exterior, *poly.interiors]:
                c = np.asarray(ring.coords)[:, :2]
                if len(c) < 4:
                    continue
                verts.append(c)
                k = np.full(len(c), Path.LINETO, dtype=np.uint8)
                k[0] = Path.MOVETO
                k[-1] = Path.CLOSEPOLY
                codes.append(k)
            if verts:
                out.append(Path(np.concatenate(verts), np.concatenate(codes)))
    return out


def _lines(geoms, clip):
    import shapely

    out = []
    for g0 in geoms:
        if g0 is None or g0.is_empty:
            continue
        g1 = shapely.clip_by_rect(g0, *clip)
        out.extend(
            np.asarray(ln.coords)[:, :2]
            for ln in shapely.get_parts(g1)
            if ln.geom_type == "LineString" and not ln.is_empty
        )
    return out


def render_plain(L, t, res, ground_m, overview):
    """Render one image of the Plain basemap for tile t of a 3857 grid; returns an RGB uint8 array."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import LineCollection, PathCollection
    from matplotlib.figure import Figure

    w, h = t["c1"] - t["c0"], t["r1"] - t["r0"]
    fig = Figure(figsize=(w / DPI, h / DPI), dpi=DPI, facecolor=PAL["land"])
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor(PAL["land"])
    ax.set_xlim(t["left"], t["right"])
    ax.set_ylim(t["bottom"], t["top"])
    m = 60 * res
    clip = (t["left"] - m, t["bottom"] - m, t["right"] + m, t["top"] + m)

    def px(metres):  # ground metres -> pixels
        return metres / ground_m

    def fill(geoms, fc, ec="none", lw=0.0, z=0):
        ps = _paths(geoms, clip)
        if ps:
            ax.add_collection(
                PathCollection(
                    ps,
                    facecolors=fc,
                    edgecolors=ec,
                    linewidths=lw * PT,
                    zorder=z,
                    snap=False,
                    antialiased=True,
                )
            )

    def stroke(geoms, col, lw_px, z, dashes=None, alpha=1.0, cap="round"):
        ls = _lines(geoms, clip)
        if ls and lw_px > 0:
            kw = {"linestyles": [(0, dashes)]} if dashes else {}
            ax.add_collection(
                LineCollection(
                    ls,
                    colors=col,
                    linewidths=lw_px * PT,
                    zorder=z,
                    capstyle=cap,
                    joinstyle="round",
                    alpha=alpha,
                    snap=False,
                    antialiased=True,
                    **kw,
                )
            )

    fill(L["sand"], PAL["sand"], z=1)
    fill(L["green"], PAL["green"], z=2)
    fill(L["plaza"], PAL["plaza"], z=3)
    shore = 0.7 if overview else 1.3
    fill(L["ocean"] + L["water"], PAL["water"], PAL["shore"], shore, z=4)
    if overview:
        fill(L["buildings"], PAL["building"], z=5)
    else:
        fill(L["buildings"], PAL["building"], PAL["building_edge"], 0.45, z=5)
    # roads: casings first (so junctions merge), then fills, minor to major
    z = 10
    widths = {}
    for name, _classes, wm, wo, _col in ROADS:
        wpx = wo if overview else px(wm)
        widths[name] = wpx
    if not overview:
        stroke(L["driveways"], PAL["road"], px(2.6), z)
        z += 1
        stroke(L["paths"], PAL["path"], 1.1, z, dashes=(1.0, 2.2), alpha=0.95, cap="butt")
        z += 1
    for name, _classes, _wm, _wo, col in ROADS:
        wpx = widths[name]
        if wpx <= 0 and overview:
            continue
        main, links = L["roads"][name]
        cw = 1.2 if overview else 1.8
        if name in ("trunk", "motorway") or not overview:
            ccol = PAL["major_casing"] if col == "major" else PAL["casing"]
            stroke(main, ccol, wpx + cw, z)
            stroke(links, ccol, wpx * 0.6 + cw, z)
        z += 1
    for name, _classes, _wm, _wo, col in ROADS:
        wpx = widths[name]
        if wpx <= 0 and overview:
            continue
        main, links = L["roads"][name]
        stroke(links, PAL[col], wpx * 0.6, z)
        stroke(main, PAL[col], wpx, z + 0.5)
        z += 1
    stroke(L["rail"], PAL["rail"], 0.9 if overview else 1.5, z + 1)
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())
    assert buf.shape[:2] == (h, w), (buf.shape, w, h)
    return buf[..., :3].copy()


def plain():
    from PIL import Image

    t0 = time.time()
    L = load_plain_layers()
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("plain_*.png"):
        f.unlink()
    go = grid(WIDE, PLAIN_OV_M, max_px=2400)
    assert go["nx"] == 1 and go["ny"] == 1, "overview must be a single image"
    gd = grid(DETAIL, PLAIN_D_M)
    imgs = [("plain_ov.png", go["tiles"][0], go, PLAIN_OV_M, True)] + [
        (f"plain_d_{t['row']}_{t['col']}.png", t, gd, PLAIN_D_M, False) for t in gd["tiles"]
    ]
    rgbs = []
    for name, t, g, gm, ov in imgs:
        a = render_plain(L, t, g["res"], gm, ov)
        rgbs.append(a)
        print(
            f"  rendered {name} {a.shape[1]} x {a.shape[0]} ({time.time() - t0:.0f}s)", flush=True
        )
    # one shared palette for every image, so a colour never shifts across a tile seam
    rng = np.random.default_rng(0)
    sample = np.concatenate(
        [a.reshape(-1, 3)[rng.integers(0, a.shape[0] * a.shape[1], 400_000)] for a in rgbs]
    )
    pal = Image.fromarray(sample.reshape(-1, 1000, 3)).quantize(
        colors=PLAIN_COLOURS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    ents = []
    for (name, t, g, gm, ov), a in zip(imgs, rgbs, strict=True):
        p = OUT / name
        Image.fromarray(a).quantize(palette=pal, dither=Image.Dither.NONE).save(p, optimize=True)
        ents.append(entry(p, t, g, gm, 0 if ov else 13.5, level="overview" if ov else "detail"))
    tot = sum(e["bytes"] for e in ents)
    update_manifest(
        "plain",
        {
            "source": "Overture Maps 2026-09-23.1 (OpenStreetMap and others; ODbL): land, water, land use, buildings, "
            "transportation segments; rendered by pipeline/build_basemap.py, no text",
            "overview": ents[0],
            "detail": ents[1:],
            "detail_grid": [gd["ny"], gd["nx"]],
            "detail_size_px": [gd["W"], gd["H"]],
            "m_per_px": {"overview": PLAIN_OV_M, "detail": PLAIN_D_M},
            "colours": PLAIN_COLOURS,
            "bytes": tot,
        },
    )
    print(
        f"plain: overview {go['W']} x {go['H']} px at {PLAIN_OV_M} m, detail {gd['W']} x {gd['H']} px at {PLAIN_D_M} m "
        f"({gd['ny']} x {gd['nx']} tiles), {tot / 1e6:.2f} MB, {time.time() - t0:.0f}s",
        flush=True,
    )


PLAIN_COLOURS = 64

# --------------------------------------------------------------------------- labels (GeoJSON, drawn with the map's glyphs)


def _write_geojson(path, feats, dp=5):
    import re

    txt = json.dumps(
        {"type": "FeatureCollection", "features": feats}, separators=(",", ":"), ensure_ascii=False
    )
    txt = re.sub(rf"(-?\d+\.\d{{{dp}}})\d+", r"\1", txt)
    path.write_text(txt, encoding="utf-8")
    return len(txt.encode("utf-8"))


def labels():
    import geopandas as gpd
    import shapely
    from shapely.geometry import box, mapping

    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    # keep names off the very edge
    inner = box(WIDE[0] + 0.004, WIDE[1] + 0.003, WIDE[2] - 0.004, WIDE[3] - 0.003)
    d = gpd.read_parquet(WIDE_SRC / "divisions.parquet")
    d = d[
        d.subtype.isin(["macrohood", "neighborhood", "microhood"])
        & d.name.notna()
        & d.geometry.within(inner)
    ].copy()
    d["pop"] = d.population.fillna(0)
    d = d.sort_values("pop", ascending=False).drop_duplicates("name")
    feats = []
    for r in d.itertuples():
        rank = 1 if r.pop >= 15000 or r.name == "Auckland Central" else 2 if r.pop >= 4000 else 3
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(r.geometry),
                "properties": {
                    "name": r.name,
                    "rank": rank,
                    "kind": r.subtype,
                    "population": int(r.pop) or None,
                },
            }
        )
    nb_s = _write_geojson(OUT / "labels_suburbs.geojson", feats, dp=5)
    # named roads, merged by name
    s = gpd.read_parquet(WIDE_SRC / "segments.parquet")
    order = {"motorway": 1, "trunk": 2, "primary": 3, "secondary": 4, "tertiary": 5}
    s = s[
        (s.subtype == "road") & s["class"].isin(order) & s.name.notna() & ~s.subclass.eq("link")
    ].copy()
    s = s[s.intersects(box(*WIDE))].to_crs(3857)
    rf = []
    wb = gpd.GeoSeries([box(*WIDE)], crs=4326).to_crs(3857).total_bounds
    for name, grp in s.groupby("name"):
        geom = shapely.clip_by_rect(
            shapely.line_merge(shapely.unary_union(list(grp.geometry))), *wb
        )
        geom = geom.simplify(5.0 / COS)
        if geom.is_empty or geom.length < 60:
            continue
        best = min(order[c] for c in grp["class"])
        g4 = gpd.GeoSeries([geom], crs=3857).to_crs(4326).iloc[0]
        rf.append(
            {
                "type": "Feature",
                "geometry": mapping(g4),
                "properties": {
                    "name": name,
                    "cls": next(k for k, v in order.items() if v == best),
                    "rank": best,
                },
            }
        )
    nb_r = _write_geojson(OUT / "labels_roads.geojson", rf, dp=5)
    update_manifest(
        "labels",
        {
            "suburbs": {
                "file": "basemap/labels_suburbs.geojson",
                "features": len(feats),
                "bytes": nb_s,
                "source": "Overture divisions (macrohood) 2026-09-23.1; rank 1 = population 15 000+, 2 = 4 000+, 3 = other",
            },
            "roads": {
                "file": "basemap/labels_roads.geojson",
                "features": len(rf),
                "bytes": nb_r,
                "source": "Overture transportation segments, named motorway/trunk/primary/secondary/tertiary, merged by name, simplified to 5 m",
            },
        },
    )
    print(
        f"labels: {len(feats)} suburbs ({nb_s / 1e3:.0f} kB), {len(rf)} named roads ({nb_r / 1e3:.0f} kB), {time.time() - t0:.0f}s",
        flush=True,
    )


# --------------------------------------------------------------------------- aerial (LINZ)

LINZ = "https://nz-imagery.s3.ap-southeast-2.amazonaws.com"
URBAN = "auckland/auckland_2024_0.075m/rgb/2193"
RURAL = "auckland/auckland_2024_0.25m/rgb/2193"
AERIAL_M = 2.5
READ_M = 2.4  # the COGs' 1/32 overview of 0.075 m; each 480 x 720 m sheet reads as 200 x 300 px


def gdal_env():
    import rasterio

    proxy = os.environ.get("HTTPS_PROXY", "")
    for k, v in {
        "GDAL_HTTP_PROXY": proxy,
        "CURL_CA_BUNDLE": ca_bundle() or "",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_MULTIPLEX": "YES",
        "VSI_CACHE": "FALSE",
    }.items():
        if v:
            os.environ[k] = v
    return rasterio.Env()


def collection_items(coll):
    import requests

    cache = BIG / "linz" / f"{coll.replace('/', '_')}_collection.json"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(
            f"{LINZ}/{coll}/collection.json",
            timeout=120,
            verify=ca_bundle() or True,
        )
        r.raise_for_status()
        cache.write_bytes(r.content)
    c = json.loads(cache.read_text())
    return [link["href"][2:-5] for link in c["links"] if link["rel"] == "item"]


# LINZ 1:1000 sheet grid in NZTM2000 (EPSG:2193): Topo50 sheets are 24 x 36 km, split 50 x 50 into 480 x 720 m tiles
# named <sheet>_1000_<row><col>. Calibrated on BA32_1000_3603 (left 1 756 960, top 5 920 800).
ROWS = [a + b for a in "ABC" for b in "ABCDEFGHJKLMNPQRSTUVWXYZ"]  # no I or O


def sheet_bounds(name):
    sheet, scale, rc = name.split("_")
    scale = int(scale)
    n = 50000 // scale
    tw, th = 24000 / n, 36000 / n
    row = ROWS.index(sheet[:2])
    col = int(sheet[2:])
    left0 = 1756000 + (col - 32) * 24000
    top0 = 5946000 - (row - ROWS.index("BA")) * 36000
    r, c = int(rc[:-2]), int(rc[-2:])
    left = left0 + (c - 1) * tw
    top = top0 - (r - 1) * th
    return left, top - th, left + tw, top


def aerial():
    import rasterio
    from PIL import Image
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject, transform_bounds

    t0 = time.time()
    g = grid(WIDE, AERIAL_M)
    # NZTM bounds of the output extent (densified), plus a margin for the resampling kernel
    nb = transform_bounds(
        "EPSG:3857", "EPSG:2193", g["x0"], g["y0"], g["x1"], g["y1"], densify_pts=41
    )
    nb = (nb[0] - 50, nb[1] - 50, nb[2] + 50, nb[3] + 50)
    items = collection_items(URBAN)
    sel = []
    for it in items:
        b = sheet_bounds(it)
        if b[2] > nb[0] and b[0] < nb[2] and b[3] > nb[1] and b[1] < nb[3]:
            sel.append((it, b))
    # mosaic grid aligned to the sheet grid: every sheet lands on whole pixels
    L = math.floor((nb[0] - 1756000) / 480) * 480 + 1756000
    T = 5946000 - math.floor((5946000 - nb[3]) / 720) * 720
    Rr = math.ceil((nb[2] - 1756000) / 480) * 480 + 1756000
    B = 5946000 - math.ceil((5946000 - nb[1]) / 720) * 720
    MW, MH = int(round((Rr - L) / READ_M)), int(round((T - B) / READ_M))
    mos = np.zeros((4, MH, MW), dtype=np.uint8)
    cache = BIG / "linz" / f"aerial_wide_nztm_{int(L)}_{int(T)}_{MW}x{MH}.npy"
    if cache.exists() and not os.environ.get("BASEMAP_REFRESH"):
        mos = np.load(cache)
        print(f"aerial: mosaic from cache {cache.name}", flush=True)
        sel = []
    print(
        f"aerial: {len(sel)} urban sheets over the wide window; mosaic {MW} x {MH} px at {READ_M} m (NZTM)",
        flush=True,
    )

    def read(job):
        coll, it, b, rm = job
        url = f"{LINZ}/{coll}/{it}.tiff"
        w, h = int(round((b[2] - b[0]) / rm)), int(round((b[3] - b[1]) / rm))
        for attempt in range(4):
            try:
                with rasterio.Env(), rasterio.open(url) as ds:
                    arr = ds.read(out_shape=(ds.count, h, w), resampling=Resampling.average)
                    db = ds.bounds
                if arr.shape[0] == 3:
                    arr = np.concatenate([arr, np.full((1, h, w), 255, np.uint8)])
                return it, b, (db.left, db.bottom, db.right, db.top), arr[:4]
            except Exception as e:
                err = e
                time.sleep(1 + attempt * 2)
        return it, b, None, str(err)

    done = 0
    failed = []
    with gdal_env(), cf.ThreadPoolExecutor(max_workers=24) as ex:
        for it, _b, db, arr in ex.map(read, [(URBAN, it, b, READ_M) for it, b in sel]):
            done += 1
            if db is None:
                failed.append((it, arr))
                continue
            c0 = int(round((db[0] - L) / READ_M))
            r0 = int(round((T - db[3]) / READ_M))
            h, w = arr.shape[1:]
            rr0, cc0 = max(0, r0), max(0, c0)
            rr1, cc1 = min(MH, r0 + h), min(MW, c0 + w)
            if rr1 > rr0 and cc1 > cc0:
                sub = arr[:, rr0 - r0 : rr1 - r0, cc0 - c0 : cc1 - c0]
                m = sub[3] > 0
                for k in range(4):
                    mos[k, rr0:rr1, cc0:cc1][m] = sub[k][m]
            if done % 50 == 0 or done == len(sel):
                print(f"  {done}/{len(sel)} sheets read ({time.time() - t0:.0f}s)", flush=True)
    if failed:
        print("  failed:", failed[:5], flush=True)
    cover = (mos[3] > 0).mean()
    print(f"  urban coverage of the mosaic: {cover:.1%}", flush=True)
    # fallback for holes: the 0.25 m rural 2024 capture (it covers the region outside the urban capture)
    fallback_used = 0
    try:
        ritems = collection_items(RURAL)
        rsel = []
        for it in ritems:
            b = sheet_bounds(it)
            if b[2] > L and b[0] < Rr and b[3] > B and b[1] < T:
                rsel.append((it, b))
        # only sheets over holes
        need = []
        for it, b in rsel:
            c0 = int(max(0, (b[0] - L) / READ_M))
            c1 = int(min(MW, (b[2] - L) / READ_M))
            r0 = int(max(0, (T - b[3]) / READ_M))
            r1 = int(min(MH, (T - b[1]) / READ_M))
            if c1 > c0 and r1 > r0 and (mos[3, r0:r1, c0:c1] == 0).mean() > 0.02:
                need.append((it, b))
        print(f"  rural 0.25 m fallback: {len(need)} of {len(rsel)} sheets touch holes", flush=True)
        with gdal_env(), cf.ThreadPoolExecutor(max_workers=16) as ex:
            for _it, _b, db, arr in ex.map(read, [(RURAL, it, b, READ_M) for it, b in need]):
                if db is None:
                    continue
                # rural sheets are larger (1:5000 etc.); resample to the mosaic grid by placing at READ_M
                c0 = int(round((db[0] - L) / READ_M))
                r0 = int(round((T - db[3]) / READ_M))
                h, w = arr.shape[1:]
                rr0, cc0 = max(0, r0), max(0, c0)
                rr1, cc1 = min(MH, r0 + h), min(MW, c0 + w)
                if rr1 <= rr0 or cc1 <= cc0:
                    continue
                sub = arr[:, rr0 - r0 : rr1 - r0, cc0 - c0 : cc1 - c0]
                m = (sub[3] > 0) & (mos[3, rr0:rr1, cc0:cc1] == 0)
                fallback_used += int(m.sum())
                for k in range(4):
                    mos[k, rr0:rr1, cc0:cc1][m] = sub[k][m]
    except Exception as e:
        print("  rural fallback skipped:", str(e)[:200], flush=True)
    print(
        f"  coverage after fallback: {(mos[3] > 0).mean():.1%} ({fallback_used} px from the rural capture)",
        flush=True,
    )
    if sel:
        np.save(cache, mos)
    # open sea beyond the capture (and the dark, partly transparent fringe of the sheets that border it): fill with a
    # smooth continuation of the neighbouring water colour, in NZTM before reprojection, so the JPEGs need no alpha
    rgb_n, valid = fill_holes(
        np.moveaxis(mos[:3], 0, -1),
        mos[3],
        ocean_mask(mos.shape[1:], from_origin(L, T, READ_M, READ_M)),
    )
    # reproject NZTM mosaic -> 3857 output grid
    src_tr = from_origin(L, T, READ_M, READ_M)
    dst_tr = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    dst = np.zeros((4, g["H"], g["W"]), dtype=np.uint8)
    for k in range(3):
        reproject(
            np.ascontiguousarray(rgb_n[..., k]),
            dst[k],
            src_transform=src_tr,
            src_crs="EPSG:2193",
            dst_transform=dst_tr,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
        )
    reproject(
        valid.astype(np.uint8) * 255,
        dst[3],
        src_transform=src_tr,
        src_crs="EPSG:2193",
        dst_transform=dst_tr,
        dst_crs="EPSG:3857",
        resampling=Resampling.nearest,
    )
    alpha = dst[3] > 127
    rgb = np.moveaxis(dst[:3], 0, -1).copy()
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("aerial_*.jpg"):
        f.unlink()
    ents = []
    for t in g["tiles"]:
        p = OUT / f"aerial_{t['row']}_{t['col']}.jpg"
        Image.fromarray(rgb[t["r0"] : t["r1"], t["c0"] : t["c1"]]).save(
            p, quality=72, optimize=True, progressive=True
        )
        ents.append(entry(p, t, g, AERIAL_M, 0))
    tot = sum(e["bytes"] for e in ents)
    update_manifest(
        "aerial",
        {
            "source": "LINZ Auckland 0.075m Urban Aerial Photos (2024-2025), CC BY 4.0, read at the 2.4 m overview"
            + (
                " with gaps filled from Auckland 0.25m Rural Aerial Photos (2024)"
                if fallback_used
                else ""
            )
            + "; open sea beyond the capture filled by extending the neighbouring water colour",
            "grid": [g["ny"], g["nx"]],
            "size_px": [g["W"], g["H"]],
            "m_per_px": AERIAL_M,
            "bytes": tot,
            "coverage": round(float(alpha.mean()), 4),
            "images": ents,
        },
    )
    print(
        f"aerial: {len(ents)} JPEGs {g['W']} x {g['H']} px ({g['ny']} x {g['nx']}), {tot / 1e6:.2f} MB, coverage {alpha.mean():.1%}, {time.time() - t0:.0f}s",
        flush=True,
    )


def ocean_mask(shape, transform):
    """Overture ocean polygon rasterised on the NZTM mosaic grid (None if the wide Overture pull is missing)."""
    try:
        import geopandas as gpd
        from rasterio.features import rasterize

        w = gpd.read_parquet(WIDE_SRC / "water.parquet")
        oc = w[w.subtype == "ocean"].to_crs(2193)
        return (
            rasterize(
                list(oc.geometry), out_shape=shape, transform=transform, fill=0, default_value=1
            ).astype(bool)
            if len(oc)
            else None
        )
    except Exception as e:
        print("  no ocean mask:", str(e)[:120], flush=True)
        return None


def fill_holes(rgb, a8, sea=None):
    """Fill pixels outside the capture with a smooth local average of the imaged pixels around them (normalised
    convolution at coarse scales), feathered over ~30 m at the edge. The partly transparent fringe of edge sheets is
    premultiplied toward black in the overviews, so it is treated as a hole too. Returns (rgb, valid mask)."""
    from scipy import ndimage

    valid = ndimage.binary_erosion(a8 == 255, iterations=3)
    if valid.all():
        return rgb.copy(), valid
    # sample water only, where known
    src = valid & sea if sea is not None and (valid & sea).sum() > 10000 else valid
    H, W = valid.shape
    f = 8
    hs, ws = -(-H // f) * f, -(-W // f) * f

    def pad(x):
        return np.pad(x, [(0, hs - H), (0, ws - W)] + [(0, 0)] * (x.ndim - 2), mode="edge")

    v = pad(src.astype(np.float32)).reshape(hs // f, f, ws // f, f).mean((1, 3))
    c = pad(rgb.astype(np.float32) * src[..., None]).reshape(hs // f, f, ws // f, f, 3).sum(
        (1, 3)
    ) / (f * f)
    glob = np.array([np.median(rgb[..., k][src]) for k in range(3)], np.float32)
    field = np.zeros((*v.shape, 3), np.float32)
    done = np.zeros(v.shape, bool)
    for sigma in (3, 8, 20, 50):  # coarse cells: 3 = ~58 m ... 50 = ~1 km
        wv = ndimage.gaussian_filter(v, sigma)
        ok = (wv > 0.05) & ~done
        for k in range(3):
            field[..., k][ok] = ndimage.gaussian_filter(c[..., k], sigma)[ok] / wv[ok]
        done |= ok
    field[~done] = glob
    up = np.stack([ndimage.zoom(field[..., k], f, order=1)[:H, :W] for k in range(3)], -1)
    # feather on the imaged side: fill colour at the edge, fading into the photo over ~12 px (~30 m)
    w = np.clip(1.0 - ndimage.distance_transform_edt(valid) / 12.0, 0, 1)[..., None]
    out = rgb.astype(np.float32) * (1 - w) + up * w
    return out.round().clip(0, 255).astype(np.uint8), valid


PARTS = ["plain", "labels", "aerial"]


def parse_args(argv=None):
    """The parts to build, in order; none named means all three. The names are checked here rather than with
    choices=: argparse (3.11) checks an empty nargs="*" list, or a list default, against choices as one value and
    rejects it, which made a bare `build_basemap.py` (and so make basemap) always fail."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "parts",
        nargs="*",
        metavar="{" + ",".join(PARTS) + "}",
        help="parts to build (default: all three)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the parts that would be built and the output folder, then stop",
    )
    a = ap.parse_args(argv)
    bad = [x for x in a.parts if x not in PARTS]
    if bad:
        ap.error(f"unknown part {', '.join(map(repr, bad))} (choose from {', '.join(PARTS)})")
    a.parts = a.parts or list(PARTS)
    return a


if __name__ == "__main__":
    a = parse_args()
    if a.dry_run:
        print(f"build_basemap: would build {', '.join(a.parts)} into {OUT} from {WIDE_SRC}")
        sys.exit(0)
    OUT.mkdir(parents=True, exist_ok=True)
    for part in a.parts:
        globals()[part]()
