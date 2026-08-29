from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cycling_investment_workbench.config import load_config
from cycling_investment_workbench.demo import web_export_payload
from cycling_investment_workbench.exports import (
    LAYER_IDS,
    ExportError,
    export_web_payload,
    load_web_payload,
    verify_web_export,
)
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic
from cycling_investment_workbench.sources import SourceSpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_export_writes_exact_hashed_browser_contract(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    output = tmp_path / "data"

    result = export_web_payload(
        web_export_payload(), export_config=config.export, output_dir=output
    )
    manifest = json.loads(result.manifest.path.read_text(encoding="utf-8"))

    assert result.manifest.path.name == "manifest.json"
    assert set(result.layers) == set(LAYER_IDS)
    assert set(path.name for path in output.iterdir()) == {
        "manifest.json",
        *(config.export.layer_filenames.values()),
    }
    for descriptor in manifest["layers"]:
        layer_id = descriptor["id"]
        layer_path = result.layers[layer_id].path
        assert descriptor["url"] == f"./data/{layer_path.name}"
        assert descriptor["sha256"] == sha256_file(layer_path)
    assert verify_web_export(output, export_config=config.export) == ()


def test_export_is_byte_deterministic(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    output = tmp_path / "data"

    first = export_web_payload(web_export_payload(), export_config=config.export, output_dir=output)
    first_hashes = {name: item.sha256 for name, item in first.layers.items()}
    second = export_web_payload(
        web_export_payload(), export_config=config.export, output_dir=output
    )

    assert first.manifest.sha256 == second.manifest.sha256
    assert first_hashes == {name: item.sha256 for name, item in second.layers.items()}


def test_verifier_detects_exact_byte_change(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    output = tmp_path / "data"
    result = export_web_payload(
        web_export_payload(), export_config=config.export, output_dir=output
    )
    result.layers["cells"].path.write_bytes(result.layers["cells"].path.read_bytes() + b" ")

    assert verify_web_export(output, export_config=config.export) == (
        "layer integrity check failed: cells",
    )


def test_invalid_layer_is_rejected(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    payload = dict(web_export_payload())
    payload["layers"] = dict(payload["layers"])
    payload["layers"]["cells"] = {"type": "FeatureCollection", "features": "invalid"}

    with pytest.raises(ExportError, match="features must be an array"):
        export_web_payload(payload, export_config=config.export, output_dir=tmp_path)


def test_manifest_requires_authoritative_config_and_declared_capabilities(
    tmp_path: Path,
) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    payload = copy.deepcopy(web_export_payload())
    payload["manifest"]["configSha256"] = "not-a-digest"
    with pytest.raises(ExportError, match="configSha256"):
        export_web_payload(payload, export_config=config.export, output_dir=tmp_path / "digest")

    payload = copy.deepcopy(web_export_payload())
    payload["manifest"]["capabilities"]["sketchEvaluation"] = "browser_approximation"
    with pytest.raises(ExportError, match="sketchEvaluation"):
        export_web_payload(
            payload, export_config=config.export, output_dir=tmp_path / "capabilities"
        )

    payload = copy.deepcopy(web_export_payload())
    payload["manifest"]["validation"]["matchedCount"] = 3
    with pytest.raises(ExportError, match="cannot exceed"):
        export_web_payload(
            payload,
            export_config=config.export,
            output_dir=tmp_path / "validation",
        )


def test_load_web_payload_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    payload = web_export_payload()
    write_json_atomic(path, payload)

    loaded = load_web_payload(path)

    assert loaded["manifest"]["schemaVersion"] == "2.0.0"


def _rights_source(source_id: str, redistribution: str) -> SourceSpec:
    return SourceSpec.from_mapping(
        {
            "id": source_id,
            "title": source_id,
            "acquisition": "manual",
            "role": "upstream",
            "destination": f"raw/{source_id}.json",
            "required": False,
            "sha256": None,
            "homepage": None,
            "url": None,
            "license": "Test terms",
            "license_url": None,
            "attribution": "Test custodian",
            "redistribution": redistribution,
        },
        context="test source",
    )


def _research_rights_payload(source_id: str, redistribution: str) -> dict[str, object]:
    payload = copy.deepcopy(web_export_payload())
    manifest = payload["manifest"]
    manifest["dataStatus"] = "research_snapshot"
    manifest["sourceDecisions"] = [
        {
            "sourceId": source_id,
            "redistribution": redistribution,
            "decision": "include",
        }
    ]
    for layer in manifest["layers"]:
        layer["sourceIds"] = [source_id]
    return payload


def test_public_export_blocks_unknown_or_restricted_source(
    tmp_path: Path,
) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    for redistribution in ("unknown", "restricted"):
        source = _rights_source("uncleared_source", redistribution)
        with pytest.raises(ExportError, match="may include only"):
            export_web_payload(
                _research_rights_payload(source.id, redistribution),
                export_config=config.export,
                output_dir=tmp_path / redistribution,
                source_specs=(source,),
            )


def test_public_export_rejects_reviewed_override_action(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    source = _rights_source("reviewed_source", "unknown")
    payload = _research_rights_payload(source.id, source.redistribution)
    payload["manifest"]["sourceDecisions"][0].update(
        {
            "decision": "include_reviewed_override",
            "reviewedBy": "named data-rights reviewer",
            "reviewedAtUtc": "2026-08-20T00:00:00Z",
            "rationale": "Written provider permission recorded in release dossier.",
        }
    )

    with pytest.raises(ExportError, match="invalid decision"):
        export_web_payload(
            payload,
            export_config=config.export,
            output_dir=tmp_path / "reviewed",
            source_specs=(source,),
        )


def test_excluded_optional_source_requires_recorded_exclusion(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    included = _rights_source("open_source", "permitted")
    excluded = _rights_source("excluded_source", "restricted")
    payload = _research_rights_payload(included.id, included.redistribution)
    payload["manifest"]["sourceDecisions"].append(
        {
            "sourceId": excluded.id,
            "redistribution": excluded.redistribution,
            "decision": "exclude",
            "rationale": "Redistribution permission has not been established.",
        }
    )

    result = export_web_payload(
        payload,
        export_config=config.export,
        output_dir=tmp_path / "excluded",
        source_specs=(included, excluded),
    )

    assert result.manifest.path.is_file()
