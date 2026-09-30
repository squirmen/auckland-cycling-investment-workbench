#!/usr/bin/env python3
"""Build an enriched local web export from a completed, unchanged Auckland run.

Usage: uv run python scripts/build_span_context.py --run runs/run-... --output web/public/data
The source run is read-only. The new export is staged and verified before it
replaces the requested browser data files. No routing or ranking is fabricated.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import pyarrow.parquet as pq

from cycling_investment_workbench.config import load_config
from cycling_investment_workbench.exports import export_web_payload, verify_web_export
from cycling_investment_workbench.provenance import sha256_file
from cycling_investment_workbench.web_context import add_web_context


def require_local(path: Path) -> None:
    # Darwin SF_DATALESS: fail promptly when File Provider cannot serve a file.
    if getattr(path.stat(), "st_flags", 0) & 0x40000000:
        raise RuntimeError(f"File is online-only; make it available offline first: {path}")


def verify_ledgers(folder: Path, names: tuple[str, ...]) -> None:
    manifest_path = folder / "manifest.json"
    require_local(manifest_path)
    declared = json.loads(manifest_path.read_text())["files"]
    for name in names:
        path = folder / name
        require_local(path)
        if (
            path.stat().st_size != declared[name]["size"]
            or sha256_file(path) != declared[name]["sha256"]
        ):
            raise ValueError(f"Source ledger failed its checksum: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/auckland.yml"))
    args = parser.parse_args()
    run = args.run.resolve()
    output = args.output.resolve()
    if output.is_relative_to(run):
        raise ValueError("Output must be outside the source run")
    require_local(run / "manifest.json")
    run_manifest = json.loads((run / "manifest.json").read_text())

    def artifact(stage: str, name: str) -> Path:
        path = (run / run_manifest["stages"][stage]["outputs"][name]["path"]).resolve()
        if not path.is_relative_to(run):
            raise ValueError("Run artifact escapes its directory")
        return path

    topology = artifact("build-topology", "topology") / "topology.json"
    routes = artifact("assign-routes", "routes")
    portfolios = artifact("evaluate-portfolios", "portfolios")
    candidates = artifact("generate-candidates", "candidates")
    web_manifest = artifact("export-web", "web_manifest")
    required = [
        topology,
        web_manifest,
        routes / "manifest.json",
        candidates / "candidate_edge_ledger.parquet",
    ]
    required += [
        routes / name
        for name in ("od_ledger.parquet", "path_ledger.parquet", "scenario_od_ledger.parquet")
    ]
    required.append(portfolios / "path_candidate_savings.parquet")
    required += [
        artifact("export-web", name) for name in run_manifest["stages"]["export-web"]["outputs"]
    ]
    for path in required:
        require_local(path)
    verify_ledgers(
        routes, ("od_ledger.parquet", "path_ledger.parquet", "scenario_od_ledger.parquet")
    )
    verify_ledgers(candidates, ("candidate_edge_ledger.parquet",))
    verify_ledgers(portfolios, ("path_candidate_savings.parquet",))
    if (
        sha256_file(web_manifest)
        != run_manifest["stages"]["export-web"]["outputs"]["web_manifest"]["sha256"]
    ):
        raise ValueError("Source browser manifest failed its checksum")
    config = load_config(args.config)
    manifest = json.loads(web_manifest.read_text())
    layers = {}
    for layer in manifest["layers"]:
        path = artifact("export-web", layer["id"])
        if sha256_file(path) != layer["sha256"]:
            raise ValueError(f"Source web layer failed its checksum: {path}")
        layers[layer["id"]] = json.loads(path.read_text())
    payload = {"manifest": manifest, "layers": layers}
    print("Building exact-node network context and deduplicated route use…", flush=True)
    add_web_context(
        payload,
        topology_path=topology,
        candidate_edges=pq.read_table(candidates / "candidate_edge_ledger.parquet").to_pylist(),
        route_dir=routes,
        portfolio_dir=portfolios,
        parameters=config.parameters,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(__file__).resolve().parents[1] / "build"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".span-context-", dir=staging_parent) as staging:
        staged = Path(staging)
        result = export_web_payload(
            payload, export_config=config.export, output_dir=staged, source_specs=config.sources
        )
        errors = verify_web_export(staged, export_config=config.export)
        if errors:
            raise ValueError("Export verification failed: " + "; ".join(errors))
        output.mkdir(parents=True, exist_ok=True)
        # Publish the manifest last, after all assets are present.
        for digest in result.layers.values():
            os.replace(digest.path, output / digest.path.name)
        os.replace(result.manifest.path, output / result.manifest.path.name)
    print(
        json.dumps(
            {
                "output": str(output),
                "existingEdges": manifest["networkContext"]["edgeCount"],
                "packages": len(manifest["networkContext"]["packages"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
