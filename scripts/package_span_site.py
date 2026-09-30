#!/usr/bin/env python3
"""Package the built SPAN site, refusing stale or mismatched research data.

When the site has a parking folder (STAND, the University of Auckland bike parking map), that
folder is checked and packaged too. This creates a local archive only. It never uploads files or
changes a server.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from cycling_investment_workbench.config import load_config
from cycling_investment_workbench.exports import verify_web_export
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic

STAND_URL = "https://span.tfwelch.com/parking/uoa/"


def on_stand_host(url: str) -> bool:
    """Is url a page of STAND as deployed, under https://span.tfwelch.com/parking/uoa/?"""
    parts = urlsplit(url)
    on_host = (parts.scheme, parts.netloc) == ("https", "span.tfwelch.com")
    return on_host and (posixpath.normpath(parts.path) + "/").startswith("/parking/uoa/")


def check_parking(site: Path) -> dict[str, str | None] | None:
    """Check the site's parking folder and describe STAND for the release record.

    Returns None when the site has no parking folder, so SPAN alone packages as before.
    """
    parking = site / "parking"
    if not parking.exists() and not parking.is_symlink():
        return None
    if parking.is_symlink() or not parking.is_dir():
        raise ValueError("parking must be a folder in the built site")
    required = [
        "index.html",
        "uoa/index.html",
        "uoa/.htaccess",
        "uoa/oembed.json",
        "uoa/data/results.json",
    ]
    missing = [f"parking/{name}" for name in required if not (parking / name).is_file()]
    if missing:
        raise ValueError("build STAND's complete parking site first; missing " + ", ".join(missing))
    title = re.search(r"<title>([^<]*)</title>", (parking / "uoa/index.html").read_text(), re.I)
    if not title or not title.group(1).strip().startswith("STAND"):
        raise ValueError("parking/uoa/index.html is not the STAND map")
    oembed = json.loads((parking / "uoa/oembed.json").read_text())
    if not isinstance(oembed, dict):
        raise ValueError("parking/uoa/oembed.json is not an oEmbed response")
    # The embed's own addresses must be STAND's; provider_url names the lab, not the embed.
    urls = re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']*)["']""", str(oembed.get("html", "")))
    urls += [oembed[key] for key in ("url", "thumbnail_url") if key in oembed]
    if not urls or not all(isinstance(url, str) and on_stand_host(url) for url in urls):
        raise ValueError(f"parking/uoa/oembed.json must embed pages under {STAND_URL}")
    results = json.loads((parking / "uoa/data/results.json").read_text())
    if not isinstance(results, dict):
        raise ValueError("parking/uoa/data/results.json is not STAND's results")
    built = results.get("built")
    return {
        "product": "STAND",
        "url": STAND_URL,
        "dataBuilt": built if isinstance(built, str) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("web/dist"))
    parser.add_argument(
        "--output", type=Path, default=Path("release-assets/span-effective-network-beta.zip")
    )
    args = parser.parse_args()
    site = args.site.resolve()
    output = args.output.resolve()
    if output.is_relative_to(site):
        raise ValueError("the release archive must be outside the built site")
    required = [
        "index.html",
        "research.html",
        ".htaccess",
        "span-mark.svg",
        "bpl-mark.svg",
        "CNAME",
        "data/manifest.json",
        "data/intersections.geojson",
        "data/access-experiment.json",
        "data/delay-comparison.json",
        "documentation/effective-network.md",
    ]
    if any(not (site / name).is_file() for name in required):
        raise ValueError("build the complete SPAN effective-network site first")
    if "<title>SPAN" not in (site / "index.html").read_text():
        raise ValueError("this is not the SPAN browser application")
    if (site / "CNAME").read_text().strip() != "span.tfwelch.com":
        raise ValueError("the built site names the wrong deployment host")
    errors = verify_web_export(
        site / "data", export_config=load_config("configs/auckland.yml").export
    )
    if errors:
        raise ValueError("invalid site export: " + "; ".join(errors))
    manifest = json.loads((site / "data/manifest.json").read_text())
    compact = manifest.get("compactCandidates")
    if compact is not None:
        source = next(layer for layer in manifest["layers"] if layer["id"] == "candidates")
        compact_path = site / "data/candidates.compact.json"
        if (
            compact.get("format") != "span-candidates-v1"
            or compact.get("url") != "./data/candidates.compact.json"
            or compact.get("sourceSha256") != source["sha256"]
            or not compact_path.is_file()
            or compact.get("sha256") != sha256_file(compact_path)
        ):
            raise ValueError("compact candidate descriptor is stale or mismatched")
        packed = json.loads(compact_path.read_text())
        if packed.get("format") != compact["format"] or len(
            packed.get("features", [])
        ) != compact.get("featureCount"):
            raise ValueError("compact candidate format or count mismatch")
    research = json.loads((site / "data/access-experiment.json").read_text())
    comparison = json.loads((site / "data/delay-comparison.json").read_text())
    evidence = manifest["effectiveNetwork"]
    descriptor = manifest.get("journeyReport", {})
    if (
        descriptor.get("url") != "./data/access-experiment.json"
        or descriptor.get("sha256") != sha256_file(site / "data/access-experiment.json")
        or descriptor.get("runId") != manifest["runId"]
        or descriptor.get("topologySha256") != research["sourceHashes"]["topology"]
    ):
        raise ValueError("journey report descriptor is missing, stale or mismatched")
    if manifest["dataStatus"] != "research_snapshot":
        raise ValueError("this package must be labelled as a research snapshot")
    if evidence["runId"] != manifest["runId"] or research["runId"] != manifest["runId"]:
        raise ValueError("intersection and research data do not belong to this SPAN run")
    if evidence["topologySha256"] != research["sourceHashes"]["topology"]:
        raise ValueError("intersection and research data do not use the same native topology")
    if research["intersectionContext"]["scenario"] != "default":
        raise ValueError("the published pilot must explicitly use the default sensitivity")
    if comparison["scenarios"]["default"]["sha256"] != sha256_file(
        site / "data/access-experiment.json"
    ):
        raise ValueError("the sensitivity comparison is stale")
    if comparison["scope"]["sourceHashes"] != research["sourceHashes"]:
        raise ValueError("the comparison uses different journeys or weights")
    stand = check_parking(site)
    # Include only built, public site files. Never package source runs or raw OD ledgers.
    files = sorted(p for p in site.rglob("*") if p.is_file())
    allowed_roots = {
        "index.html",
        "research.html",
        ".htaccess",
        "span-mark.svg",
        "bpl-mark.svg",
        "CNAME",
        "assets",
        "data",
        "documentation",
        "parking",
    }
    for path in files:
        relative = path.relative_to(site)
        if path.is_symlink() or relative.parts[0] not in allowed_roots:
            raise ValueError(f"unexpected public release file: {relative}")
        if path.suffix in {".parquet", ".env", ".py", ".zip"} or path.name.startswith(".env"):
            raise ValueError(f"source/private artifact in site: {relative}")
        # STAND's only hidden file is its Apache settings; a .DS_Store or .git folder would leak.
        if relative.parts[0] == "parking" and (
            any(part.startswith(".") for part in relative.parts[:-1])
            or (relative.name.startswith(".") and relative.name != ".htaccess")
        ):
            raise ValueError(f"hidden file in the parking site: {relative}")
    release = {
        "product": "SPAN — Spending Priorities for Active Networks",
        "status": "research_beta_not_deployed",
        "builtAtUtc": datetime.now(UTC).isoformat(),
        "runId": manifest["runId"],
        "intendedHost": "span.tfwelch.com",
        "effectiveNetwork": evidence,
        "researchGraph": research["graph"],
        **({"components": {"parking/uoa": stand}} if stand else {}),
        "files": {p.relative_to(site).as_posix(): sha256_file(p) for p in files},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip") as temp:
        with ZipFile(temp.name, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, path.relative_to(site).as_posix())
            info = ZipInfo("span-release.json")
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, json.dumps(release, indent=2) + "\n")
        with ZipFile(temp.name) as archive:
            if archive.testzip() is not None:
                raise ValueError("archive integrity test failed")
        # Copy after a complete archive has passed verification.
        shutil.copyfile(temp.name, output)
    release["archive"] = {
        "file": output.name,
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
    }
    write_json_atomic(output.with_suffix(".json"), release)
    print(json.dumps({"archive": str(output), **release["archive"]}, indent=2))


if __name__ == "__main__":
    main()
