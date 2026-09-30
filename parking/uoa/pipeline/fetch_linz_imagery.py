"""Per-campus aerial imagery mosaics from LINZ Auckland 0.075 m Urban Aerial Photos (2024-2025) COGs,
read at overview resolution, reprojected to EPSG:3857 (web mercator) at ~0.4 m for the web map + bounds JSON."""

import json
import os
import pathlib
import sys

import numpy as np
import rasterio
from PIL import Image
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import BIG, RAW_LINZ, ca_bundle

OUT = str(RAW_LINZ)  # $STAND_DATA/linz (pipeline/paths.py)
# LINZ STAC tile list for the window, kept beside the data
tiles = json.loads((BIG / "linz_imagery_tiles.json").read_text())
coll = "auckland/auckland_2024_0.075m/rgb/2193"
wins = {
    "city": (174.760, 174.778, -36.859, -36.845),
    "grafton": (174.760, 174.777, -36.868, -36.855),
    "newmarket": (174.767, 174.784, -36.872, -36.859),
}
TARGET_RES = 0.4  # metres
_gdal = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
)
if os.environ.get("HTTPS_PROXY"):
    _gdal["GDAL_HTTP_PROXY"] = os.environ["HTTPS_PROXY"]
if ca_bundle():  # a proxy that inspects TLS; otherwise GDAL uses the system store
    _gdal["CURL_CA_BUNDLE"] = ca_bundle()
env = rasterio.Env(**_gdal)
# need all BA32 tiles intersecting each generous window: re-derive from the per-campus lists (union) and filter by bbox
alltiles = {t["item"]: t for k in tiles[coll] for t in tiles[coll][k]}


def inter(b, w):
    return not (b[2] < w[0] or b[0] > w[1] or b[3] < w[2] or b[1] > w[3])


bounds_out = {}
with env:
    for name, w in wins.items():
        sel = [t for t in alltiles.values() if inter(t["bbox"], w)]
        print(name, len(sel), "tiles", flush=True)
        srcs = []
        for t in sel:
            ds = rasterio.open(t["asset"])
            b = transform_bounds("EPSG:4326", ds.crs, w[0], w[2], w[1], w[3])
            win = (
                from_bounds(*b, transform=ds.transform)
                .round_offsets()
                .round_lengths()
                .intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
            )
            if win.width <= 0 or win.height <= 0:
                ds.close()
                continue
            scale = ds.res[0] / TARGET_RES
            oh, ow = max(1, int(win.height * scale)), max(1, int(win.width * scale))
            arr = ds.read(
                [1, 2, 3], window=win, out_shape=(3, oh, ow), resampling=Resampling.average
            )
            tr = rasterio.transform.from_bounds(*ds.window_bounds(win), ow, oh)
            prof = ds.profile.copy()
            prof.update(
                count=3,
                dtype="uint8",
                height=oh,
                width=ow,
                transform=tr,
                driver="GTiff",
                compress="deflate",
                tiled=True,
                photometric="RGB",
            )
            for k in ("nodata",):
                prof.pop(k, None)
            p = f"{OUT}/img_{name}_{t['item'].replace('.json', '')}.tif"
            with rasterio.open(p, "w", **prof) as dst:
                dst.write(arr)
            srcs.append(p)
            ds.close()
            print("  ", t["item"], arr.shape, flush=True)
        dss = [rasterio.open(p) for p in srcs]
        mosaic, tr = merge(dss, res=TARGET_RES)
        prof = dss[0].profile.copy()
        prof.update(height=mosaic.shape[1], width=mosaic.shape[2], transform=tr)
        for d in dss:
            d.close()
        for p in srcs:
            os.remove(p)
        # reproject to EPSG:3857
        src_crs = prof["crs"]
        dst_crs = "EPSG:3857"
        dtr, dw, dh = calculate_default_transform(
            src_crs,
            dst_crs,
            mosaic.shape[2],
            mosaic.shape[1],
            *rasterio.transform.array_bounds(mosaic.shape[1], mosaic.shape[2], tr),
        )
        dst = np.zeros((3, dh, dw), dtype="uint8")
        for i in range(3):
            reproject(
                mosaic[i],
                dst[i],
                src_transform=tr,
                src_crs=src_crs,
                dst_transform=dtr,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
        gt = f"{OUT}/imagery_{name}_3857.tif"
        with rasterio.open(
            gt,
            "w",
            driver="GTiff",
            count=3,
            dtype="uint8",
            height=dh,
            width=dw,
            crs=dst_crs,
            transform=dtr,
            compress="jpeg",
            photometric="YCBCR",
            tiled=True,
        ) as o:
            o.write(dst)
        img = Image.fromarray(np.moveaxis(dst, 0, -1))
        jp = f"{OUT}/imagery_{name}.jpg"
        img.save(jp, quality=82, optimize=True)
        b3857 = rasterio.transform.array_bounds(dh, dw, dtr)
        b4326 = transform_bounds(dst_crs, "EPSG:4326", *b3857)
        # MapLibre image source coordinates: TL, TR, BR, BL in lon/lat
        bounds_out[name] = {
            "coordinates": [
                [b4326[0], b4326[3]],
                [b4326[2], b4326[3]],
                [b4326[2], b4326[1]],
                [b4326[0], b4326[1]],
            ],
            "width": dw,
            "height": dh,
            "res_m": TARGET_RES,
            "source": "LINZ Auckland 0.075m Urban Aerial Photos (2024-2025), CC BY 4.0, via nz-imagery AWS open data",
            "file": os.path.basename(jp),
            "bytes": os.path.getsize(jp),
        }
        print(name, "->", jp, dw, dh, os.path.getsize(jp) / 1e6, "MB", flush=True)
with open(f"{OUT}/imagery_bounds.json", "w") as f:
    json.dump(bounds_out, f, indent=1)
print("done")
