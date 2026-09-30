"""Trim the black no-data borders off the per-campus aerial patches (EPSG:3857 GeoTIFFs written by
fetch_linz_imagery.py), re-save the JPEGs and rewrite imagery_bounds.json with the trimmed extents.

The patches are NZTM mosaics reprojected to web mercator, so their no-data is not a neat frame: the corners
are slightly rotated wedges and a patch can have a no-data band down one side (the City patch has one on its
right). Keeping only rows that are almost fully valid across the whole width would throw away nearly all of
such a patch, so the trim peels edges instead: it repeatedly drops the single edge line (top row, bottom row,
left column or right column) with the largest share of no-data until every edge line is at least 98 % valid,
then crops to what is left. A pixel is no-data when its three bands sum to 30 or less (the black fill).

Run after fetch_linz_imagery.py (make fetch does); export_web.py then copies the JPEGs and bounds to web/data.
"""

import json
import os
import pathlib
import sys

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform_bounds

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import RAW_LINZ

MIN_VALID = 0.98


def peel(valid, min_valid=MIN_VALID):
    """Half-open window (r0, r1, c0, c1) left after peeling the worst edge line until all four are >= min_valid."""
    inv = ~valid
    r0, r1, c0, c1 = 0, valid.shape[0], 0, valid.shape[1]
    while r1 - r0 > 1 and c1 - c0 > 1:
        edges = {
            "top": inv[r0, c0:c1].mean(),
            "bottom": inv[r1 - 1, c0:c1].mean(),
            "left": inv[r0:r1, c0].mean(),
            "right": inv[r0:r1, c1 - 1].mean(),
        }
        side = max(edges, key=edges.get)
        if edges[side] <= 1 - min_valid:
            break
        if side == "top":
            r0 += 1
        elif side == "bottom":
            r1 -= 1
        elif side == "left":
            c0 += 1
        else:
            c1 -= 1
    return r0, r1, c0, c1


def main():
    bounds = json.loads((RAW_LINZ / "imagery_bounds.json").read_text())
    for name, v in bounds.items():
        gt = RAW_LINZ / f"imagery_{name}_3857.tif"
        with rasterio.open(gt) as ds:
            arr = ds.read()
            tr = ds.transform
        valid = arr[:3].astype(np.int32).sum(axis=0) > 30  # not black
        r0, r1, c0, c1 = peel(valid)
        sub = arr[:, r0:r1, c0:c1]
        x0, y0 = tr * (c0, r0)
        x1, y1 = tr * (c1, r1)
        b4326 = transform_bounds(
            "EPSG:3857", "EPSG:4326", min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        )
        jp = RAW_LINZ / v["file"]
        Image.fromarray(np.moveaxis(sub, 0, -1)).save(jp, quality=82, optimize=True)
        v.update(
            {
                "coordinates": [
                    [b4326[0], b4326[3]],
                    [b4326[2], b4326[3]],
                    [b4326[2], b4326[1]],
                    [b4326[0], b4326[1]],
                ],
                "width": int(c1 - c0),
                "height": int(r1 - r0),
                "bytes": os.path.getsize(jp),
                "trimmed": True,
            }
        )
        print(
            f"{name}: {arr.shape[2]} x {arr.shape[1]} px trimmed to {c1 - c0} x {r1 - r0} (rows {r0}:{r1}, cols {c0}:{c1}), "
            f"{(~valid[r0:r1, c0:c1]).mean():.2%} no-data left, lon {b4326[0]:.5f} to {b4326[2]:.5f}, lat {b4326[1]:.5f} to {b4326[3]:.5f}, "
            f"{os.path.getsize(jp) / 1e6:.1f} MB"
        )
    with open(RAW_LINZ / "imagery_bounds.json", "w") as f:
        json.dump(bounds, f, indent=1)


if __name__ == "__main__":
    main()
