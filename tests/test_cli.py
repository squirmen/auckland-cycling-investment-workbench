from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import yaml

from cycling_investment_workbench.cli import (
    EXIT_INPUT,
    EXIT_OK,
    _run_manifest_path,
    _run_output_path,
    main,
)
from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import (
    _stage_fingerprint,
    demo_project_config,
    demo_stage_registry,
    run_project,
    validate_run_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_stage_fingerprint_uses_relevant_parameters_and_explicit_stage_version() -> None:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    stage = PipelineStageConfig("prepare-demand", "2", (), {"profile": "test"})
    first = _stage_fingerprint(
        stage,
        config=config,
        sources={},
        dependencies={},
    )
    irrelevant = copy.deepcopy(config.parameters)
    irrelevant["appraisal"]["ebike_share"] = 0.5
    unchanged = _stage_fingerprint(
        stage,
        config=replace(config, parameters=irrelevant),
        sources={},
        dependencies={},
    )
    relevant = copy.deepcopy(config.parameters)
    relevant["demand"]["disaggregation"]["samples_per_od"] += 1
    changed = _stage_fingerprint(
        stage,
        config=replace(config, parameters=relevant),
        sources={},
        dependencies={},
    )
    versioned = _stage_fingerprint(
        replace(stage, version="3"),
        config=config,
        sources={},
        dependencies={},
    )

    assert first == unchanged
    assert first != changed
    assert first != versioned


def test_stage_cache_reuses_upstream_work_across_run_ids(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "auckland.yml"
    raw = yaml.safe_load((PROJECT_ROOT / "configs/auckland.yml").read_text(encoding="utf-8"))
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    first_config = demo_project_config(load_config(config_path))
    first = run_project(first_config, registry=demo_stage_registry(), resume=False)

    parameters = copy.deepcopy(first_config.parameters)
    parameters["appraisal"] = {"ebike_share": 0.45}
    second_config = replace(first_config, parameters=parameters)
    second = run_project(second_config, registry=demo_stage_registry(), resume=True)

    assert second.run_id != first.run_id
    assert {"source-inventory", "build-topology", "prepare-demand"}.issubset(second.resumed_stages)
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert manifest["stages"]["prepare-demand"]["status"] == "cached"


def test_run_validation_rejects_stale_implementation_checksum(tmp_path: Path) -> None:
    config_path, run_id = _temporary_demo_run(tmp_path)
    manifest_path = tmp_path / "runs" / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model"]["implementation_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_run_manifest(manifest_path, project_root=tmp_path)

    assert any(issue.code == "implementation-mismatch" for issue in report.issues)


def _temporary_demo_run(tmp_path: Path) -> tuple[Path, str]:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "auckland.yml"
    raw = yaml.safe_load((PROJECT_ROOT / "configs/auckland.yml").read_text(encoding="utf-8"))
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    config = demo_project_config(load_config(config_path))
    result = run_project(config, registry=demo_stage_registry(), resume=False)
    return config_path, result.run_id


def test_run_reference_resolves_only_declared_verified_artifacts(tmp_path: Path) -> None:
    config_path, run_id = _temporary_demo_run(tmp_path)
    config = load_config(config_path)

    assert _run_manifest_path(config, run_id).name == "manifest.json"
    payload = _run_output_path(
        config,
        run_id,
        stage_name="export-outputs",
        output_name="web_payload",
    )
    assert payload.name == "web-payload.json"


def test_validate_and_export_web_accept_stable_run_id_interface(
    tmp_path: Path,
) -> None:
    config_path, run_id = _temporary_demo_run(tmp_path)

    assert main(["validate", "--config", str(config_path), "--run", run_id]) == EXIT_OK
    assert main(["export-web", "--config", str(config_path), "--run", run_id]) == EXIT_OK
    assert (tmp_path / "web/public/data/manifest.json").is_file()


def test_public_cli_demo_and_offline_source_interfaces(tmp_path: Path, capsys) -> None:
    config_path, _ = _temporary_demo_run(tmp_path)
    analysis_path = tmp_path / "analysis.json"

    assert (
        main(
            [
                "demo",
                "--config",
                str(config_path),
                "--no-resume",
                "--export-web",
                "--output",
                str(analysis_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert analysis_path.is_file()
    assert (
        main(
            [
                "data",
                "fetch",
                "--config",
                str(config_path),
                "--source",
                "nzdep2023_sa1",
                "--offline",
                "--json",
            ]
        )
        == EXIT_OK
    )
    assert '"ok": true' in capsys.readouterr().out


def test_cli_reports_invalid_run_reference_without_traceback(tmp_path: Path, capsys) -> None:
    config_path, _ = _temporary_demo_run(tmp_path)

    assert main(["validate", "--config", str(config_path), "--run", "not-a-run-id"]) == EXIT_INPUT
    assert "run id must use the form" in capsys.readouterr().err
