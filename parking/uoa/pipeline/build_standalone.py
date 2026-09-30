"""Bundle the web map into one HTML file that opens by double-click (no server needed).

Inlines ld.css, js/, the SVG marks and every data file as JSON inside <script> tags; the campus aerial patches are
inlined as base64 JPEG unless --no-imagery is given. The own-data basemaps (web/data/basemap: the Plain overview and
detail PNGs, the suburb and road labels, and the wide LINZ aerial mosaic) are inlined too, so Plain and Aerial work
from the file, as on the hosted map. MapLibre and the Inter font still load from their CDNs, and the optional Streets
basemap from OpenStreetMap's tile server; the analysis layers render regardless. MapLibre's tags are kept exactly as
in index.html, with their Subresource Integrity hashes. The About dialog's links to the method pages point at the
hosted copies (https://span.tfwelch.com/parking/uoa/docs/), since the file may be opened far from web/docs.

--offline makes a file that needs no network at all. It also inlines MapLibre GL JS and its stylesheet from
MAPLIBRE_DIST (make vendor puts the pinned version in build/vendor; the files must match index.html's Subresource
Integrity hashes) and the Inter font from STAND_INTER when that file exists (else the system sans-serif is used),
drops the font links, and sets window.STAND_OFFLINE: the map then offers only its own Plain and Aerial basemaps and
keeps the view on their window. Links to other sites still point there.

The finished file is checked by the privacy guard (pipeline/build_docs.py) before it is written; on a hit nothing
is written.

Usage: python3 pipeline/build_standalone.py [--no-imagery] [--offline] [--out web/stand_standalone.html]
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_docs
from paths import HERE, WEB_DATA

WEB = HERE / "web"
DOCS = "https://span.tfwelch.com/parking/uoa/docs/"
ML_JS = re.compile(
    r'<script src="https://unpkg\.com/maplibre-gl@([^"/]+)/dist/maplibre-gl\.js"[^>]*></script>'
)
ML_CSS = re.compile(
    r'<link href="https://unpkg\.com/maplibre-gl@([^"/]+)/dist/maplibre-gl\.css"[^>]*>'
)
FONT_LINKS = re.compile(r"<link [^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\n?")


def b64(path):
    return base64.b64encode(pathlib.Path(path).read_bytes()).decode()


def script(js):
    return "<script>\n" + js.replace("</script", "<\\/script") + "\n</script>"


def inline_maplibre(html):
    """index.html with MapLibre's two CDN tags replaced by the same files from MAPLIBRE_DIST, checked against the
    tags' Subresource Integrity hashes so the inlined copy is exactly the pinned one."""
    version = ML_JS.search(html).group(1)
    dist = pathlib.Path(
        os.environ.get("MAPLIBRE_DIST")
        or HERE / "build" / "vendor" / f"maplibre-gl-{version}" / "dist"
    )
    for rx, name in ((ML_JS, "maplibre-gl.js"), (ML_CSS, "maplibre-gl.css")):
        f = dist / name
        if not f.is_file():
            sys.exit(
                f"build_standalone: --offline needs {name} (MapLibre {version}) in MAPLIBRE_DIST={dist}; run make vendor"
            )
        tag = rx.search(html).group(0)
        want = re.search(r'integrity="sha384-([^"]+)"', tag).group(1)
        if base64.b64encode(hashlib.sha384(f.read_bytes()).digest()).decode() != want:
            sys.exit(
                f"build_standalone: {f} is not the MapLibre {version} that index.html pins (its SRI hash differs)"
            )
        body = f.read_text()
        html = html.replace(
            tag, script(body) if name.endswith(".js") else f"<style>\n{body}\n</style>", 1
        )
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-imagery", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=str(WEB / "stand_standalone.html"))
    a = ap.parse_args()
    html = (WEB / "index.html").read_text()
    assert ML_JS.search(html), "index.html has no MapLibre script tag"
    assert ML_CSS.search(html), "index.html has no MapLibre stylesheet tag"
    css = (WEB / "ld.css").read_text()
    js = (WEB / "js" / "app.js").read_text()
    marks = {
        p.name: "data:image/svg+xml;base64," + b64(p)
        for p in sorted((WEB / "assets").glob("*.svg"))
    }
    data = {}
    for p in sorted(WEB_DATA.glob("*.geojson")):
        data[p.stem] = json.loads(p.read_text())
    results = json.loads((WEB_DATA / "results.json").read_text())
    if a.no_imagery:
        results.pop("imagery", None)
    elif results.get("imagery"):
        for v in results["imagery"].values():
            f = WEB_DATA / v["file"]
            if f.exists():
                v["file"] = "data:image/jpeg;base64," + b64(f)
    # own-data basemaps: inline Plain (overview + detail), the labels and the wide aerial mosaic (about 4.5 MB)
    bm = results.get("basemap")
    if bm:
        if bm.get("aerial"):
            for v in bm["aerial"].get("images", []):
                f = WEB_DATA / v["file"]
                if f.exists():
                    v["file"] = "data:image/jpeg;base64," + b64(f)
                else:
                    bm.pop("aerial", None)
                    break
        if bm.get("plain"):
            for v in [bm["plain"]["overview"], *bm["plain"].get("detail", [])]:
                f = WEB_DATA / v["file"]
                if f.exists():
                    v["file"] = "data:image/png;base64," + b64(f)
                else:
                    bm.pop("plain", None)
                    break
    for name in ["labels_suburbs", "labels_roads"]:
        f = WEB_DATA / "basemap" / f"{name}.geojson"
        if f.exists():
            data[name] = json.loads(f.read_text())
    data["results"] = results
    # glyphs for map labels, keyed "<fontstack>/<range>.pbf"
    data["glyphs"] = {
        f"{f.parent.name}/{f.name}": b64(f)
        for f in sorted((WEB / "assets" / "font").glob("*/*.pbf"))
    }
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    if a.offline:
        html = FONT_LINKS.sub("", inline_maplibre(html))
        inter = pathlib.Path(
            os.environ.get("STAND_INTER")
            or HERE / "build" / "vendor" / "inter-ui-3.19.3" / "Inter-roman.var.woff2"
        )
        if inter.is_file():
            css = (
                '@font-face { font-family: "Inter"; font-style: normal; font-weight: 100 900; font-display: swap; '
                f'src: url(data:font/woff2;base64,{b64(inter)}) format("woff2"); }}\n'
            ) + css
    html = html.replace('<link rel="stylesheet" href="ld.css">', f"<style>\n{css}\n</style>")
    offline = "<script>window.STAND_OFFLINE = true;</script>\n" if a.offline else ""
    html = html.replace(
        '<script src="js/app.js"></script>',
        f"{offline}<script>window.STAND_DATA = {blob};</script>\n{script(js)}",
    )
    # any other local script (the embed shim) is inlined too, so the file stands alone
    html = re.sub(
        r'<script src="(js/[^"]+)"></script>',
        lambda m: script((WEB / m.group(1)).read_text()),
        html,
    )
    for n, uri in marks.items():
        html = html.replace(f"assets/{n}", uri)
    html = html.replace('href="docs/', f'href="{DOCS}')
    out = pathlib.Path(a.out)
    hits = build_docs.private_hits(html, html_text=True)
    if hits:
        out.unlink(missing_ok=True)  # no stale copy either
        sys.exit(
            f"build_standalone: private or internal text would be in {out.name}; nothing written:\n"
            + "\n".join(f'  {t!r} in "...{c}..."' for t, c in hits)
        )
    out.write_text(html)
    print(
        f"{out} written, {out.stat().st_size / 1e6:.1f} MB{' (no imagery)' if a.no_imagery else ''}{' (offline)' if a.offline else ''}"
    )


if __name__ == "__main__":
    main()
