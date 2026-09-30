"""Give the recommended sites their curated names on the map.

The model names every candidate from its street and nearest building ("Grafton Road at Engineering 405").
For the twelve recommended docks, docs/recommendations.md uses names a person would give ("Grafton Road
frontage at Engineering and the Business School"). This copies those names and stages from config/sites.json
into web/data/candidates.geojson as `site_name`, `site_short` (the label beside the pin) and `stage`, so the map
and the recommendations agree. The map falls back to the model's own name for any other site (for example after
re-weighting).

A curated site may list neighbouring candidates in `also`: the same place, which the optimiser can pick
instead after a small change in the inputs. A selected candidate listed there takes that site's name,
stage and short label.

The model's recommended set (`selected` in candidates.geojson) must match sites.json, campus by campus:
every curated site selected (by its cid or one of its `also` cids) and every selected candidate curated.

Candidate ids are positional: they follow the order in which the model generates candidates, so a rerun can
renumber them, and a matching id alone could put a curated name on the wrong spot. sites.json therefore stores
the position of every id it lists (`pos`: {cid: [lon, lat]}), and a selected candidate more than MAX_OFFSET_M
from the position stored for its id counts as a difference too.

If there are differences, the page and the map would describe different docks, so the run stops with a list of
them and changes nothing. Pass --allow-mismatch for exploratory runs (re-weighting, sensitivity tests): the
differences are then printed as warnings and only the sites that match, by id and position, are named.

Safe to run repeatedly. Run after export_web.py (make export does both).
Usage: python3 pipeline/name_sites.py [--allow-mismatch]
"""

import argparse
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import HERE

CAND = HERE / "web" / "data" / "candidates.geojson"
SITES = HERE / "config" / "sites.json"
# how far a selected candidate may sit from the position sites.json stores for its id
MAX_OFFSET_M = 15


def dist_m(a, b):
    """Great-circle distance in metres between two [lon, lat] points."""
    la, lb = math.radians(a[1]), math.radians(b[1])
    h = (
        math.sin((lb - la) / 2) ** 2
        + math.cos(la) * math.cos(lb) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    )
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="name what matches and warn, instead of stopping, when the model's selection and sites.json disagree",
    )
    args = ap.parse_args(argv)
    sites = json.loads(SITES.read_text())
    # cid -> curated site; any listed cid -> the curated site's cid; any listed cid -> [lon, lat]
    named, alias, pos = {}, {}, {}
    for campus, c in sites["campuses"].items():
        for s in c["sites"]:
            for cid in [s["cid"], *s.get("also", [])]:
                if cid in alias:
                    raise SystemExit(
                        f"sites.json lists {cid} under two sites ({alias[cid]} and {s['cid']})"
                    )
                alias[cid] = s["cid"]
                xy = (s.get("pos") or {}).get(cid)
                if not (
                    isinstance(xy, list)
                    and len(xy) == 2
                    and all(isinstance(v, int | float) for v in xy)
                ):
                    raise SystemExit(
                        f'sites.json has no position for {cid} (\'{s["short"]}\'): add "pos": {{"{cid}": [lon, lat]}} '
                        "to that site, from web/data/candidates.geojson"
                    )
                pos[cid] = xy
            named[s["cid"]] = dict(s, campus=campus)
    gj = json.loads(CAND.read_text())
    cids = {f["properties"]["cid"] for f in gj["features"]}
    unknown = sorted(cid for cid in alias if cid not in cids)
    if unknown:
        raise SystemExit(
            f"sites.json names candidates that are not in candidates.geojson: {unknown}"
        )

    # Compare the model's recommended set with the curated one, honouring `also`, then check where each match is.
    selected = {
        f["properties"]["cid"]: f for f in gj["features"] if f["properties"].get("selected")
    }
    problems, hit = [], {}  # hit: curated cid -> the selected cid that stands for it
    for cid, f in sorted(selected.items()):
        p = f["properties"]
        site = alias.get(cid)
        if site is None:
            problems.append(
                f"{p['campus']}: the model selects {cid} (dock {p.get('phase')}, {p.get('street')} near {p.get('nearest_building')}), which sites.json does not name"
            )
        elif site in hit:
            problems.append(
                f"{p['campus']}: the model selects both {hit[site]} and {cid}, which sites.json treats as one site ({site})"
            )
        else:
            hit[site] = cid
            if named[site]["campus"] != p["campus"]:
                problems.append(
                    f"{cid} is selected on the {p['campus']} campus but sites.json lists it under {named[site]['campus']}"
                )
    for site, s in named.items():
        if site not in hit:
            problems.append(
                f"{s['campus']}: sites.json names {site}{' (also ' + ', '.join(s['also']) + ')' if s.get('also') else ''} "
                f"'{s['short']}', which the model does not select"
            )
    moved = set()  # selected cids that match by id but not by position: never named
    for site, cid in sorted(hit.items()):
        xy = selected[cid]["geometry"]["coordinates"]
        d = dist_m(xy, pos[cid])
        if d > MAX_OFFSET_M:
            moved.add(cid)
            p = selected[cid]["properties"]
            problems.append(
                f"{named[site]['campus']}: {cid} is selected, but it is {d:,.0f} m from where sites.json places it "
                f"({pos[cid][0]:.6f}, {pos[cid][1]:.6f}) for '{named[site]['short']}'. Candidate ids can be renumbered "
                f"by a rerun, so check which spot the model picked ({xy[0]:.6f}, {xy[1]:.6f}: "
                f"{p.get('street')} near {p.get('nearest_building')})"
            )
    if problems:
        msg = "the model's recommended sites and config/sites.json disagree:\n  " + "\n  ".join(
            problems
        )
        if not args.allow_mismatch:
            raise SystemExit(
                msg
                + "\nUpdate sites.json (ids and positions) to the new selection, or rerun the model, or pass "
                "--allow-mismatch for an exploratory run. candidates.geojson was not changed."
            )
        print("warning: " + msg, file=sys.stderr)

    # Name the selected candidates that match by id and position (and, for an exploratory run, nothing else).
    n = 0
    for f in gj["features"]:
        p = f["properties"]
        for k in ("site_name", "site_short", "stage"):
            p.pop(k, None)
        site = alias.get(p["cid"])
        if site and p.get("selected") and hit.get(site) == p["cid"] and p["cid"] not in moved:
            s = named[site]
            p["site_name"], p["site_short"], p["stage"] = s["name"], s["short"], s["stage"]
            n += 1
    CAND.write_text(json.dumps(gj))  # same layout as export_web.py (geopandas to_json)
    print(
        f"{CAND.relative_to(HERE)}: named {n} of {len(selected)} recommended sites "
        f"(ids and positions checked against config/sites.json, within {MAX_OFFSET_M} m)"
    )


if __name__ == "__main__":
    main()
