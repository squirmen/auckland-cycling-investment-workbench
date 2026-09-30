"""Read LINZ 1 m LiDAR DEM/DSM (Auckland Part 1, 2024) COG windows for the study area via HTTPS range reads,
mosaic, and derive slope (degrees and percent). Output GeoTIFFs in NZTM2000 (EPSG:2193)."""

import json
import os
import pathlib
import sys

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import BIG, RAW_LINZ, ca_bundle

OUT = str(RAW_LINZ)  # $STAND_DATA/linz (pipeline/paths.py)
# LINZ STAC tile list for the window, kept beside the data
tiles = json.loads((BIG / "linz_elevation_tiles.json").read_text())
XMIN, XMAX, YMIN, YMAX = 174.735, 174.800, -36.890, -36.835
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


def pull(coll, name):
    srcs = []
    with env:
        for t in tiles[coll]:
            url = t["asset"]
            print("open", url, flush=True)
            ds = rasterio.open(url)
            b = transform_bounds("EPSG:4326", ds.crs, XMIN, YMIN, XMAX, YMAX)
            win = from_bounds(*b, transform=ds.transform).round_offsets().round_lengths()
            win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
            if win.width <= 0 or win.height <= 0:
                continue
            arr = ds.read(1, window=win)
            tr = ds.window_transform(win)
            prof = ds.profile.copy()
            prof.update(
                height=arr.shape[0],
                width=arr.shape[1],
                transform=tr,
                driver="GTiff",
                compress="deflate",
                tiled=True,
            )
            p = f"{OUT}/{name}_{t['item'].replace('.json', '')}.tif"
            with rasterio.open(p, "w", **prof) as dst:
                dst.write(arr, 1)
            srcs.append(p)
            print("  wrote", p, arr.shape, "nodata", ds.nodata, flush=True)
    ds_list = [rasterio.open(p) for p in srcs]
    mosaic, tr = merge(ds_list, nodata=ds_list[0].nodata)
    prof = ds_list[0].profile.copy()
    prof.update(
        height=mosaic.shape[1], width=mosaic.shape[2], transform=tr, compress="deflate", tiled=True
    )
    mp = f"{OUT}/{name}_study_1m.tif"
    with rasterio.open(mp, "w", **prof) as dst:
        dst.write(mosaic)
    for d in ds_list:
        d.close()
    for p in srcs:
        os.remove(p)
    print("mosaic", mp, mosaic.shape, flush=True)
    return mp


dem = pull("auckland/auckland-part-1_2024/dem_1m/2193", "dem")
dsm = pull("auckland/auckland-part-1_2024/dsm_1m/2193", "dsm")
# slope from DEM
with rasterio.open(dem) as ds:
    z = ds.read(1).astype("float64")
    nd = ds.nodata
    tr = ds.transform
    prof = ds.profile.copy()
z[z == nd] = np.nan
dy, dx = np.gradient(z, abs(tr.e), tr.a)
slope_pct = np.sqrt(dx**2 + dy**2) * 100.0
slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
for arr, nm in [(slope_pct, "slope_pct"), (slope_deg, "slope_deg")]:
    prof.update(dtype="float32", nodata=-9999.0)
    a = np.where(np.isnan(arr), -9999.0, arr).astype("float32")
    with rasterio.open(f"{OUT}/{nm}_study_1m.tif", "w", **prof) as dst:
        dst.write(a, 1)
    print(
        nm, "median", float(np.nanmedian(arr)), "p90", float(np.nanpercentile(arr, 90)), flush=True
    )
# normalised height (DSM-DEM) = canopy/buildings, useful for visibility/enclosure
with rasterio.open(dsm) as d2:
    s = d2.read(1).astype("float64")
    s[s == d2.nodata] = np.nan
nh = np.clip(s - z, 0, None)
prof.update(dtype="float32", nodata=-9999.0)
with rasterio.open(f"{OUT}/nheight_study_1m.tif", "w", **prof) as dst:
    dst.write(np.where(np.isnan(nh), -9999.0, nh).astype("float32"), 1)
print("done", flush=True)
