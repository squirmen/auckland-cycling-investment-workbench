"""Render STAND's method and recommendations as lab-styled HTML pages in web/docs/, published with the map at
https://span.tfwelch.com/parking/uoa/docs/.

docs/methodology.md and docs/recommendations.md are public text and are rendered as they are, once the privacy
guard has read them.

This module also holds that guard, which every public build uses (this script, build_deploy.py and
build_standalone.py): private_hits(text), check_public(text, name) and scan_tree(root). See "privacy guard" below.

Usage: python3 pipeline/build_docs.py   (set STAND_PRIVATE_TERMS to include the private-term scan)
"""

import html
import os
import pathlib
import re

# parking/uoa (as paths.HERE, without creating the data folders)
HERE = pathlib.Path(__file__).resolve().parent.parent
OUT = HERE / "web" / "docs"
SPAN = "https://span.tfwelch.com/"
LAB = "https://www.betterplaces.auckland.ac.nz/"  # the Better Places Lab's site; STAND's page there is LAB + "stand/"

# ---------------------------------------------------------------- privacy guard
# Nothing public may carry private text: people's names, private dates, unpublished reports, internal file and
# folder names, or where a build was made. The guard has two parts.
#
# Built in, needing no private words: absolute paths into a home folder (the macOS or Windows "Users" folder, or
# "home" on Linux), which give away an account name, and file:// URLs that point at a file.
#
# From a file: the private words themselves, which are not kept in this repository. STAND_PRIVATE_TERMS names a
# plain-text file with one term per line; blank lines and lines that start with '#' are skipped. With no file
# named, only the built-in checks run, and the first check says that the private-term scan was skipped. Each term
# is matched by its shape, so a short word does not fire inside another word, base64 or SVG path data:
#   a word or phrase   letters, digits and spaces: whole words, any case, any spacing, an optional plural s. A single
#                      capitalised word (a surname) is not matched when a street word follows it: "<name> Road" is
#                      a place, not the person. A phrase that starts with a capitalised word (a person's name) also
#                      finds a longer form of that word: "Sam Smith" finds "Samuel Smith"
#   an acronym or code capitals and digits only ("NZTA", "B2"): the whole word, in that case only
#   a date             a day and a month ("5 May"): also "5th May", "May 5" and the month shortened ("5 Oct")
#   "re:" + pattern    a Python regular expression, used as written
#   anything else      a file or folder name or a path fragment: a plain substring, any case
# Before matching, data: URIs, long base64 strings, SVG path data and ARIA role values are set aside, and HTML
# entities and \uXXXX escapes are decoded.
_BUILT_IN = [  # (name, pattern, lower-case text that must occur for the pattern to be tried)
    (
        "home folder path",
        re.compile(
            r"(?<![\w.~/-])/(?:Users|home)/[^/\s\"'<>]+/|\b[A-Za-z]:\\+Users\\+[^\\\s\"'<>]+\\"
        ),
        None,
    ),
    (
        "file:// URL",
        re.compile(r"\bfile://(?:/|[\w.:-]+/)", re.I),
        "file://",
    ),  # file:///... or file://host/...
]
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_STREET = r"(?!\s+(?:Road|Rd|Street|St|Avenue|Ave|Place|Pl|Lane|Drive|Dr|Crescent|Cres|Terrace|Tce|Way|Close|Grove)\b)"
_DAY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?", re.I)


def _month(word):
    w = word.lower().rstrip(".")
    return next((m for m in _MONTHS if len(w) >= 3 and m.lower().startswith(w)), None)


def _rule(term):
    """(pattern, lower-case text that must occur for the pattern to be tried, or None) for one private term."""
    if term.startswith("re:"):
        try:
            return re.compile(term[3:]), None
        except re.error as e:
            raise SystemExit(
                f"privacy guard: a pattern in STAND_PRIVATE_TERMS does not compile ({e})"
            ) from e
    words = term.split()
    if len(words) == 2:  # a date: a day and a month, in either order
        d, m = words if _DAY.fullmatch(words[0]) else words[::-1]
        day, month = _DAY.fullmatch(d), _month(m)
        if day and month:
            day_rx = rf"0?{int(day.group(1))}(?:st|nd|rd|th)?"
            mon_rx = rf"(?:{month}|{month[:3]}{'t?' if month == 'September' else ''}\.?)"
            return (
                re.compile(rf"\b{day_rx}\s+{mon_rx}(?!\w)|\b{mon_rx}\s+{day_rx}\b", re.I),
                month[:3].lower(),
            )
    if all(re.fullmatch(r"[A-Za-z0-9]+", w) for w in words):
        # an acronym or code
        if len(words) == 1 and re.fullmatch(r"[A-Z0-9]*[A-Z][A-Z0-9]*", term) and len(term) > 1:
            return re.compile(rf"\b{term}\b"), term.lower()
        street = _STREET if len(words) == 1 and term[0].isupper() else ""
        # "Sam Smith": "Samuel Smith" too
        first = re.escape(words[0]) + (r"\w*" if len(words) > 1 and term[0].isupper() else "")
        return (
            re.compile(
                r"\b" + r"\s+".join([first, *map(re.escape, words[1:])]) + rf"s?\b{street}", re.I
            ),
            words[0].lower(),
        )
    return re.compile(re.escape(term), re.I), term.lower()


_TERMS = None


def private_terms():
    """[(term, pattern, prefilter)] from the file named by STAND_PRIVATE_TERMS, read once; [] when none is named."""
    global _TERMS
    if _TERMS is None:
        src = os.environ.get("STAND_PRIVATE_TERMS", "").strip()
        if not src:
            print(
                "privacy guard: STAND_PRIVATE_TERMS is not set, so the private-term scan was skipped "
                "(the built-in path checks still run)",
                flush=True,
            )
            _TERMS = []
        else:
            f = pathlib.Path(src).expanduser()
            if not f.is_file():
                raise SystemExit(
                    f"privacy guard: STAND_PRIVATE_TERMS names {f}, which is not a file"
                )
            terms = [t.strip() for t in f.read_text(encoding="utf-8").splitlines()]
            _TERMS = [(t, *_rule(t)) for t in terms if t and not t.startswith("#")]
            print(
                f"privacy guard: {len(_TERMS)} private terms from STAND_PRIVATE_TERMS", flush=True
            )
    return _TERMS


# Encoded data is not text: data: URIs, long base64 strings (the inlined map glyphs) and SVG path data.
_ENCODED = re.compile(
    r"data:[\w.+/-]+(?:;[\w=.-]+)*;base64,[A-Za-z0-9+/=]+"
    r"|(?<=[\"'])(?!/)(?=[A-Za-z/]*[0-9+])[A-Za-z0-9+/]{64,}={0,2}(?=[\"'])"  # not a quoted /path
    r"|\sd=(?:\"[^\"]*\"|'[^']*')"
)
# ARIA role values are a fixed vocabulary, not prose: role="..." in markup and ("role", "...") in scripts.
_ROLE = re.compile(r"""\brole\s*=\s*["'][\w\s-]*["']|["']role["']\s*,\s*["'][\w\s-]*["']""", re.I)
_UESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def private_hits(text, html_text=False):
    """[(term, context)] for every built-in check and private term that text fails. html_text: also read it with
    the tags taken out, so a phrase split by inline markup ("<em>annual</em> report") is still found."""
    rules = _BUILT_IN + private_terms()
    text = _UESC.sub(lambda m: chr(int(m.group(1), 16)), html.unescape(text))
    text = _ROLE.sub(" ", _ENCODED.sub(" ", text))
    views = [text, re.sub(r"<[^>]*>", "", text)] if html_text else [text]
    hits = {}
    for view in views:
        low = view.lower()
        for term, rx, needle in rules:
            if term in hits or (needle and needle not in low):
                continue
            m = rx.search(view)
            if m:
                hits[term] = " ".join(view[max(0, m.start() - 60) : m.end() + 60].split())
    order = [r[0] for r in rules]
    return sorted(hits.items(), key=lambda kv: order.index(kv[0]))


TEXT_EXT = {
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".json",
    ".geojson",
    ".css",
    ".txt",
    ".svg",
    ".xml",
    ".md",
}


def scan_tree(root, what="build"):
    """Scan every text file under root (TEXT_EXT, plus dotfiles such as .htaccess); stop naming each file and
    term if any check fails."""
    root = pathlib.Path(root)
    bad, n = [], 0
    for f in sorted(root.rglob("*")):
        if not f.is_file() or not (f.suffix.lower() in TEXT_EXT or f.name.startswith(".")):
            continue
        n += 1
        for term, ctx in private_hits(
            f.read_text(errors="replace"),
            html_text=f.suffix.lower() in {".html", ".htm", ".svg", ".xml"},
        ):
            bad.append(f'  {f.relative_to(root)}: {term!r} in "...{ctx}..."')
    if bad:
        raise SystemExit(
            f"{what}: private or internal text would be published ({len(bad)} hit(s)); nothing shipped:\n"
            + "\n".join(bad)
        )
    print(f"{what}: privacy check passed on {n} text files under {root}")
    return n


def check_public(text, name, html_text=False):
    hits = private_hits(text, html_text)
    if hits:
        raise SystemExit(
            f"{name}: private or internal text would be published:\n"
            + "\n".join(f'  {t!r} in "...{c}..."' for t, c in hits)
        )


# ---------------------------------------------------------------- pages
PAGE = """<!doctype html>
<html lang="en-NZ">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · STAND · SPAN</title>
<meta name="description" content="{description}">
<link rel="icon" href="../assets/stand-mark.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&amp;family=Source+Serif+4:opsz,wght@8..60,600&amp;display=swap" rel="stylesheet">
<style>
:root {{ --navy: #0c0c48; --ink: #15252e; --ink-2: #3b4d56; --muted: #566670; --paper: #f7f3ea; --line: rgba(18, 52, 67, .14); --accent: #a01d5f; --teal: #1f6178;
  --sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; --serif: "Source Serif 4", Georgia, serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.65 var(--sans); -webkit-font-smoothing: antialiased; }}
.wrap {{ width: min(820px, calc(100% - 40px)); margin: 0 auto; padding-block: 28px 72px; }}
.top {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 40px; }}
.crumbs {{ flex: 1 0 100%; display: flex; align-items: center; gap: 6px; margin-bottom: -4px; color: var(--muted); font-size: 13px; font-weight: 600; }}
.crumbs a {{ display: inline-flex; align-items: center; gap: 5px; color: var(--ink-2); text-decoration: none; }}
.crumbs a:hover {{ color: var(--navy); text-decoration: underline; }}
.crumbs img {{ width: 14px; height: 14px; }}
.lockup {{ display: inline-flex; align-items: center; gap: 10px; color: var(--navy); font-weight: 800; letter-spacing: .08em; text-decoration: none; }}
.lockup img {{ width: 30px; height: 30px; }}
.back {{ color: var(--teal); font-weight: 600; font-size: 14px; }}
h1, h2, h3 {{ font-family: var(--serif); font-weight: 600; letter-spacing: -.012em; text-wrap: balance; color: var(--ink); }}
h1 {{ font-size: clamp(30px, 5vw, 42px); line-height: 1.08; margin: 0 0 18px; }}
h2 {{ font-size: 25px; line-height: 1.2; margin: 44px 0 12px; padding-top: 18px; border-top: 1px solid var(--line); }}
h3 {{ font-size: 19px; margin: 28px 0 8px; }}
p, li {{ max-width: 68ch; color: var(--ink-2); }}
a {{ color: var(--teal); text-underline-offset: 3px; }}
strong {{ color: var(--ink); }}
code {{ font-size: 14px; background: rgba(12, 12, 72, .06); padding: 1px 5px; border-radius: 4px; overflow-wrap: anywhere; }}
.table {{ overflow-x: auto; margin: 16px 0; border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ padding: 9px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; }}
tr:last-child td {{ border-bottom: 0; }}
/* Phones: each table row becomes a card, every cell under its column's name (data-label, added in stack_tables()). */
@media (max-width: 700px) {{
  .table {{ overflow: visible; border: 0; border-radius: 0; background: none; }}
  .table table, .table tbody, .table tr, .table td {{ display: block; width: auto; }}
  .table thead {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }}
  .table tr {{ margin: 0 0 12px; padding: 8px 0; border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
  .table td {{ padding: 5px 14px; border-bottom: 0; overflow-wrap: anywhere; }}
  .table td::before {{ content: attr(data-label); display: block; font-size: 12px; font-weight: 600; letter-spacing: .02em; color: var(--muted); }}
}}
.foot {{ margin-top: 56px; padding-top: 18px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
<div class="top"><nav class="crumbs" aria-label="Part of SPAN"><a href="{span}" target="_top"><img src="../assets/span-mark.svg" alt="">SPAN</a><span aria-hidden="true">›</span><a href="{span}parking/" target="_top">Bike parking</a></nav><a class="lockup" href="../"><img src="../assets/stand-mark.svg" alt="">STAND</a><a class="back" href="../">Open the map</a></div>
<main>
{body}
</main>
<p class="foot">STAND is built by the <a href="{lab}" target="_top">Better Places Lab</a>, Te Pare School of Architecture, Planning and Design, Waipapa Taumata Rau | University of Auckland. <a href="{span}" target="_top">Part of SPAN</a> · <a href="{lab}stand/" target="_top">About STAND on the lab’s site</a> · <a href="methodology.html">Method</a> · <a href="recommendations.html">Recommendations</a><br>Data: © OpenStreetMap contributors and Esri Community Maps contributors (ODbL) via Overture Maps; Toitū Te Whenua LINZ LiDAR 2024 and aerial imagery 2024–25 (CC BY 4.0); Auckland Transport cycle counts and facilities (CC BY 4.0).</p>
</div>
</body>
</html>
"""


def stack_tables(body):
    """Give each table cell its column's name (data-label), so on a phone each row reads as a card, and the ARIA
    table roles, which some browsers drop from a table laid out with display: block."""

    def one(m):
        t = m.group(0)
        heads = [
            re.sub(r"<[^>]*>", "", h).strip()
            for h in re.findall(r"<th[^>]*>(.*?)</th>", t, flags=re.S)
        ]
        rows = []
        for row in re.findall(r"<tr>.*?</tr>", t, flags=re.S):
            i = iter(heads)
            rows.append(
                (
                    row,
                    re.sub(
                        r"<td(?=[\s>])",
                        lambda _,
                        i=i: f'<td role="cell" data-label="{html.escape(next(i, ""), quote=True)}"',
                        row,
                    ),
                )
            )
        for a, b in rows:
            t = t.replace(a, b, 1)
        t = (
            t.replace("<table>", '<table role="table">')
            .replace("<thead>", '<thead role="rowgroup">')
            .replace("<tbody>", '<tbody role="rowgroup">')
        )
        t = t.replace("<tr>", '<tr role="row">')
        return re.sub(r"<th(?=[\s>])", '<th role="columnheader"', t)

    return re.sub(r"<table>.*?</table>", one, body, flags=re.S)


def render(md, title, description, path, source):
    import markdown

    check_public(md, f"build_docs: {source}")
    body = stack_tables(markdown.markdown(md, extensions=["tables", "sane_lists"]))
    body = body.replace('<table role="table">', '<div class="table"><table role="table">').replace(
        "</table>", "</table></div>"
    )
    page = PAGE.format(
        title=html.escape(title),
        description=html.escape(description),
        body=body,
        span=SPAN,
        lab=LAB,
    )
    # the finished page too, template and all
    check_public(page, f"build_docs: web/docs/{path.name}", html_text=True)
    return path, page


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pages = [
        render(
            (HERE / "docs" / "recommendations.md").read_text(),
            "Recommended sites",
            "Where secure bike docks should stand on the University of Auckland's City, Grafton and Newmarket campuses, and why.",
            OUT / "recommendations.html",
            "docs/recommendations.md",
        ),
        render(
            (HERE / "docs" / "methodology.md").read_text(),
            "Method",
            "How STAND models cyclist arrivals, scores every walkable spot and chooses the docks.",
            OUT / "methodology.html",
            "docs/methodology.md",
        ),
    ]
    for (
        path,
        page,
    ) in pages:  # written only when both pages pass, and only when they change (build_deploy.py
        # runs this too), so an unchanged page keeps its time
        same = path.is_file() and path.read_text() == page
        if not same:
            path.write_text(page)
        print(path, f"{path.stat().st_size / 1e3:.1f} KB" + (" (unchanged)" if same else ""))


if __name__ == "__main__":
    main()
