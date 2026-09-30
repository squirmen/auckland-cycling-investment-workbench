"""Assemble STAND's part of span.tfwelch.com: the /parking/ folder, with STAND at /parking/uoa/.

Usage: python3 pipeline/build_deploy.py   (make site runs it)
  parking/build/site/                   the /parking/ folder of span.tfwelch.com:
    uoa/                                STAND: index.html, ld.css, js/, data/, assets/, docs/, oembed.json and
                                        .htaccess (from deploy/htaccess)
    index.html                          the /parking/ page, copied from parking/index.html when that file exists
  parking/build/span-parking-site.zip   the same files; extracted into span.tfwelch.com's parking/ folder, it
                                        deploys them

SPAN's web build picks up parking/build/site as its parking/ folder. The one-file map (web/*_standalone.html)
is not part of it.

The build first regenerates web/docs from docs/*.md (pipeline/build_docs.py) and checks that the map has every
file it loads. It then runs the privacy guard (build_docs.scan_tree) over every text file in the tree before it
writes the zip. On a hit it stops, names the file and the term, and removes the tree and the zip, so nothing
unchecked is left to upload.
"""

import json
import pathlib
import re
import shutil
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_docs
from paths import HERE

WEB = HERE / "web"
PARKING = HERE.parent  # parking/ (STAND is parking/uoa), kept for SPAN's planned bike parking tool
OUT = PARKING / "build" / "site"  # served at https://span.tfwelch.com/parking/
UOA = OUT / "uoa"
ZIP = PARKING / "build" / "span-parking-site.zip"
SITE = "https://span.tfwelch.com/parking/uoa/"
# oEmbed: lets WordPress's Embed block (or [embed]) on the lab's CampusPress site show the live map.
# WordPress keeps only the iframe's src, width, height and title for a provider it does not know, and
# sandboxes it with allow-scripts; deploy/htaccess opens CORS on the data files for that case.
OEMBED = {
    "version": "1.0",
    "type": "rich",
    "provider_name": "Better Places Lab",
    "provider_url": build_docs.LAB,
    "title": "STAND: where secure bike parking should stand",
    "width": 1200,
    "height": 760,
    "html": f'<iframe src="{SITE}" width="1200" height="760" title="STAND: secure bike parking siting map" frameborder="0"></iframe>',
}
OEMBED_LINK = (
    f'<link rel="alternate" type="application/json+oembed" href="{SITE}oembed.json" title="STAND">'
)
# What uoa/ must hold besides the data files the map loads (see missing_files)
REQUIRED = [
    "index.html",
    "ld.css",
    "js/app.js",
    "js/embed-shim.js",
    "assets/stand-mark.svg",
    "assets/span-mark.svg",
    "assets/bpl-mark.svg",
    "docs/methodology.html",
    "docs/recommendations.html",
    "oembed.json",
    ".htaccess",
]


def missing_files(uoa):
    """The files the map needs that uoa/ lacks: REQUIRED, the GeoJSON layers js/app.js loads, results.json and the
    images results.json names (the campus aerial patches and the own-data basemap)."""
    need = [*REQUIRED, "data/results.json"]
    layers = re.search(r"const files = \[([^\]]*)\]", (uoa / "js" / "app.js").read_text())
    need += (
        [f"data/{n}.geojson" for n in re.findall(r'"([\w-]+)"', layers.group(1))]
        if layers
        else ["(the layer list in js/app.js)"]
    )
    res = uoa / "data" / "results.json"
    if res.is_file():
        r = json.loads(res.read_text())
        bm = r.get("basemap") or {}
        imgs = list((r.get("imagery") or {}).values())
        if bm.get("plain"):
            imgs += [bm["plain"]["overview"], *bm["plain"].get("detail", [])]
        imgs += (bm.get("aerial") or {}).get("images", [])
        need += [f"data/{v['file']}" for v in imgs]
    return [n for n in need if not (uoa / n).is_file()]


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    ZIP.unlink(missing_ok=True)  # a failed build leaves nothing behind to upload
    build_docs.main()  # web/docs from docs/*.md now, never a stale copy (it refuses private text itself)
    shutil.copytree(
        WEB,
        UOA,
        ignore=lambda d, names: [
            n for n in names if n.endswith("_standalone.html") or n.startswith(".")
        ],
    )
    shutil.copy(HERE / "deploy" / "htaccess", UOA / ".htaccess")
    (UOA / "oembed.json").write_text(json.dumps(OEMBED, indent=1) + "\n")
    idx = UOA / "index.html"
    page = idx.read_text()
    if "json+oembed" not in page:
        assert page.count("</head>") == 1, "index.html needs exactly one </head>"
        idx.write_text(page.replace("</head>", OEMBED_LINK + "\n</head>"))
    missing = missing_files(UOA)
    if missing:
        shutil.rmtree(OUT, ignore_errors=True)
        sys.exit(
            f"build_deploy: the map would be incomplete: uoa/ has no {', '.join(missing[:6])}"
            f"{f' and {len(missing) - 6} more' if len(missing) > 6 else ''}.\n"
            "Run make export first (make all in a fresh checkout)."
        )
    if (PARKING / "index.html").is_file():  # the /parking/ page; STAND does not write it
        shutil.copy(PARKING / "index.html", OUT / "index.html")
    try:
        build_docs.scan_tree(OUT, "build_deploy")
    except SystemExit:
        shutil.rmtree(OUT, ignore_errors=True)
        raise
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(OUT.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(OUT).as_posix())
    files = [f for f in OUT.rglob("*") if f.is_file()]
    print(
        f"{OUT}: {len(files)} files, {sum(f.stat().st_size for f in files) / 1e6:.1f} MB"
        f"{'' if (OUT / 'index.html').is_file() else ' (parking/index.html does not exist yet, so there is no /parking/ page)'}; "
        f"{ZIP.name} {ZIP.stat().st_size / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    main()
