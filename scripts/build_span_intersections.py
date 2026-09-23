#!/usr/bin/env python3
"""Add AT intersection context to an existing SPAN export using its native graph."""

from __future__ import annotations

import argparse
import gc
import json
import os
import tempfile
from pathlib import Path

from build_span_context import require_local

from cycling_investment_workbench.config import load_config
from cycling_investment_workbench.effective_network import (
    SOURCE_ID,
    SOURCE_URL,
    build_intersection_context,
)
from cycling_investment_workbench.exports import export_web_payload, verify_web_export
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic
from cycling_investment_workbench.sources import SourceSpec


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--web-data", type=Path, default=Path("web/public/data"))
    parser.add_argument(
        "--audit", type=Path, default=Path("build/effective-network/intersections.json")
    )
    args = parser.parse_args()
    run = args.run.resolve()
    web = args.web_data.resolve()
    if web.is_relative_to(run) or args.audit.resolve().is_relative_to(run):
        raise ValueError("enriched outputs must be outside the source run")
    config = load_config("configs/auckland.yml")
    errors = verify_web_export(web, export_config=config.export)
    if errors:
        raise ValueError("source web export failed verification: " + "; ".join(errors))
    manifest = json.loads((web / "manifest.json").read_text())
    source_run = json.loads((run / "manifest.json").read_text())
    if manifest["runId"] != source_run["run_id"]:
        raise ValueError("source run and SPAN web export disagree")
    topology = (
        run
        / source_run["stages"]["build-topology"]["outputs"]["topology"]["path"]
        / "topology.json"
    )
    if not topology.resolve().is_relative_to(run):
        raise ValueError("topology path escapes source run")
    require_local(topology)
    require_local(args.inventory)
    topology_hash = sha256_file(topology)
    if topology_hash != manifest.get("networkContext", {}).get("sourceFiles", {}).get(
        "topology.json"
    ):
        raise ValueError("SPAN's existing network context does not match this topology")
    print("Matching AT inventory to SPAN source junctions…", flush=True)
    graph = json.loads(topology.read_text())
    inventory = json.loads(args.inventory.read_text())
    layer, audit, metadata = build_intersection_context(graph, inventory)
    del graph
    gc.collect()
    metadata.update(
        runId=manifest["runId"],
        topologySha256=topology_hash,
        inventorySha256=sha256_file(args.inventory),
        implementationSha256=sha256_file(
            Path(__file__).resolve().parents[1]
            / "src/cycling_investment_workbench/effective_network.py"
        ),
        sourceUrl=SOURCE_URL,
    )
    audit.update(runId=manifest["runId"], topologySha256=topology_hash)
    write_json_atomic(args.audit, audit)
    layers = {
        descriptor["id"]: json.loads((web / Path(descriptor["url"]).name).read_text())
        for descriptor in manifest["layers"]
        if descriptor["id"] != "intersections"
    }
    layers["intersections"] = layer
    manifest["layers"] = [d for d in manifest["layers"] if d["id"] != "intersections"]
    manifest["layers"].append(
        {
            "id": "intersections",
            "label": "Intersections and crossing delays (beta)",
            "defaultVisible": False,
            "optional": False,
            "licence": "Auckland Transport CC BY 4.0; "
            "SPAN topology derived from OpenStreetMap ODbL",
            "sourceIds": [SOURCE_ID, "geofabrik_new_zealand_osm"],
        }
    )
    manifest["effectiveNetwork"] = metadata
    manifest["sourceDecisions"] = [
        d for d in manifest["sourceDecisions"] if d["sourceId"] != SOURCE_ID
    ]
    manifest["sourceDecisions"].append(
        {
            "sourceId": SOURCE_ID,
            "redistribution": "permitted",
            "decision": "include",
            "reason": "AT public Controlled Intersections layer under CC BY 4.0; "
            "inventory only, no operational signal records.",
        }
    )
    attribution = "Auckland Transport: Controlled Intersections, CC BY 4.0"
    if attribution not in manifest["attribution"]:
        manifest["attribution"].append(attribution)
    source = SourceSpec.from_mapping(
        {
            "id": SOURCE_ID,
            "title": "AT Controlled Intersections",
            "acquisition": "manual",
            "role": "upstream",
            "destination": "raw/at_controlled_intersections.geojson",
            "required": False,
            "sha256": metadata["inventorySha256"],
            "homepage": SOURCE_URL,
            "url": None,
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": attribution,
            "redistribution": "permitted",
        },
        context="AT intersection enrichment",
    )
    # Stage through the existing SPAN exporter and its rights/integrity gate.
    # Never stage under public/: an interrupted cleanup or sync restore could
    # otherwise ship duplicate working files in the next browser build.
    staging_parent = Path(__file__).resolve().parents[1] / "build"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".span-intersections-", dir=staging_parent) as folder:
        staged = Path(folder)
        result = export_web_payload(
            {"manifest": manifest, "layers": layers},
            export_config=config.export,
            output_dir=staged,
            source_specs=(*config.sources, source),
        )
        errors = verify_web_export(staged, export_config=config.export)
        if errors:
            raise ValueError("enriched export failed verification: " + "; ".join(errors))
        # Other layers must retain exact hashes: the enrichment cannot rescore candidates.
        for descriptor in manifest["layers"]:
            if (
                descriptor["id"] != "intersections"
                and result.layers[descriptor["id"]].sha256 != descriptor["sha256"]
            ):
                raise ValueError(f"intersection enrichment changed {descriptor['id']}")
        digest = result.layers["intersections"]
        os.replace(digest.path, web / digest.path.name)
        os.replace(result.manifest.path, web / "manifest.json")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
