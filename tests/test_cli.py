from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cycling_investment_workbench import cli as cli_module
from cycling_investment_workbench.cli import (
    EXIT_INPUT,
    EXIT_OK,
    EXIT_PIPELINE,
    EXIT_VALIDATION,
    _run_manifest_path,
    _run_output_path,
    main,
)
from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import (
    MissingSourcesError,
    PipelineError,
    _stage_fingerprint,
    demo_project_config,
    demo_stage_registry,
    run_project,
    validate_run_manifest,
)
from cycling_investment_workbench.sources import SourceError, SourceRecord, SourceSpec

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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SourceError("bad source"), EXIT_INPUT),
        (MissingSourcesError("missing source"), EXIT_INPUT),
        (PipelineError("failed stage"), EXIT_PIPELINE),
    ],
)
def test_cli_maps_operational_errors_to_stable_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: int,
) -> None:
    def fail(_args) -> int:
        raise error

    monkeypatch.setattr(cli_module, "_dispatch", fail)

    assert main(["validate", "--config-only"]) == expected
    assert "error:" in capsys.readouterr().err.lower()


def test_cli_debug_mode_preserves_pipeline_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_args) -> int:
        raise PipelineError("failed stage")

    monkeypatch.setattr(cli_module, "_dispatch", fail)

    with pytest.raises(PipelineError, match="failed stage"):
        main(["--debug", "validate", "--config-only"])


def test_cli_reports_counter_preparation_and_pipeline_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    counter_payload = {
        "locations": {"sha256": "a" * 64},
        "observations": {"sha256": "b" * 64},
    }
    counter_result = SimpleNamespace(
        location_count=3,
        observation_days=7,
        excluded_count=1,
        to_dict=lambda: counter_payload,
    )
    monkeypatch.setattr(cli_module, "prepare_at_cycle_counters", lambda **_kwargs: counter_result)
    assert (
        main(
            [
                "data",
                "prepare-at-counters",
                "--config",
                str(PROJECT_ROOT / "configs/auckland.yml"),
                "--workbook",
                "publisher.xlsx",
                "--coordinate-registry",
                "coordinates.csv",
            ]
        )
        == EXIT_OK
    )
    assert "Prepared 3 counter sites across 7 days" in capsys.readouterr().out

    run_result = SimpleNamespace(
        run_id="run-0123456789abcdef",
        status="succeeded",
        executed_stages=("prepare-demand",),
        resumed_stages=("build-topology",),
        to_dict=lambda **_kwargs: {
            "run_id": "run-0123456789abcdef",
            "status": "succeeded",
            "manifest": "runs/run-0123456789abcdef/manifest.json",
        },
    )
    monkeypatch.setattr(cli_module, "run_project", lambda *_args, **_kwargs: run_result)
    assert main(["run", "--config", str(PROJECT_ROOT / "configs/auckland.yml")]) == EXIT_OK
    output = capsys.readouterr().out
    assert "Executed: prepare-demand" in output
    assert "Resumed: build-topology" in output


def test_source_validation_reports_required_integrity_and_licence_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def source(
        source_id: str,
        *,
        acquisition: str,
        required: bool,
        sha256: str | None,
        redistribution: str,
    ) -> SourceSpec:
        return SourceSpec.from_mapping(
            {
                "id": source_id,
                "title": source_id,
                "acquisition": acquisition,
                "role": "test",
                "destination": f"raw/{source_id}.bin",
                "required": required,
                "sha256": sha256,
                "homepage": None,
                "url": "https://example.test/source" if acquisition == "download" else None,
                "license": "Test licence",
                "license_url": None,
                "attribution": "Test custodian",
                "redistribution": redistribution,
            },
            context=source_id,
        )

    specs = (
        source(
            "required_missing",
            acquisition="manual",
            required=True,
            sha256="1" * 64,
            redistribution="restricted",
        ),
        source(
            "download_mismatch",
            acquisition="download",
            required=False,
            sha256=None,
            redistribution="unknown",
        ),
    )
    records = {
        "required_missing": SourceRecord(
            "required_missing", tmp_path / "missing.bin", True, "missing", None, None, "1" * 64
        ),
        "download_mismatch": SourceRecord(
            "download_mismatch", tmp_path / "wrong.bin", False, "mismatch", 1, "2" * 64, None
        ),
    }

    class FixtureRegistry:
        def __init__(self, _sources, _data_dir: Path) -> None:
            pass

        def inventory(self):
            return records

    monkeypatch.setattr(cli_module, "SourceRegistry", FixtureRegistry)
    config = replace(
        load_config(PROJECT_ROOT / "configs/auckland.yml"),
        root_dir=tmp_path,
        sources=specs,
    )

    issues = cli_module._source_validation_issues(config)

    assert {(issue.severity, issue.code) for issue in issues} == {
        ("error", "source-missing"),
        ("error", "source-mismatch"),
        ("warning", "source-unpinned"),
        ("warning", "licence-unconfirmed"),
    }


def test_cli_json_validation_and_offline_fetch_contracts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FetchRegistry:
        def __init__(self, _sources, data_dir: Path) -> None:
            self.data_dir = data_dir

        def fetch(self, *_args, **_kwargs):
            return {
                "required_fixture": SourceRecord(
                    "required_fixture",
                    self.data_dir / "raw/required-fixture.bin",
                    True,
                    "missing",
                    None,
                    None,
                    None,
                )
            }

    monkeypatch.setattr(cli_module, "SourceRegistry", FetchRegistry)
    assert (
        main(
            [
                "data",
                "fetch",
                "--config",
                str(PROJECT_ROOT / "configs/auckland.yml"),
                "--offline",
            ]
        )
        == EXIT_INPUT
    )
    assert "required_fixture: missing" in capsys.readouterr().out

    monkeypatch.setattr(cli_module, "verify_web_export", lambda *_args, **_kwargs: ["corrupt"])
    assert (
        main(
            [
                "validate",
                "--config",
                str(PROJECT_ROOT / "configs/auckland.yml"),
                "--config-only",
                "--web",
                "--json",
            ]
        )
        == EXIT_VALIDATION
    )
    assert '"code": "web-export"' in capsys.readouterr().out
