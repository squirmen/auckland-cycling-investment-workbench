from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cycling_investment_workbench.config import ConfigError, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "auckland.yml"


def _write_config(tmp_path: Path, value: object) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    path = config_dir / "test.yml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _raw_config() -> dict[str, object]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_auckland_config_is_strict_and_declares_full_pipeline() -> None:
    config = load_config(CONFIG_PATH)

    assert config.project.crs == "EPSG:2193"
    assert [stage.name for stage in config.pipeline.stages] == [
        "source-inventory",
        "prepare-demand",
        "build-topology",
        "assign-routes",
        "generate-candidates",
        "evaluate-portfolios",
        "appraisal-uncertainty-validation",
        "export-outputs",
        "export-web",
    ]
    assert config.parameters["routing"]["od_selection"] == "stratified_probability_sample"
    assert config.parameters["routing"]["sampling"] == {
        "design": "stratified_simple_random_without_replacement",
        "stratum": "source_cell_id",
        "records_per_stratum_by_purpose": {
            "commute": 1,
            "school": 3,
            "everyday": 3,
            "transit": 3,
        },
        "seed": 20260301,
        "estimator": "Horvitz-Thompson",
    }
    assert config.parameters["routing"]["plausible_paths"] == 5
    assert config.parameters["routing"]["maximum_cost_ratio"] == 1.5
    assert config.parameters["routing"]["maximum_alternative_attempts"] == 4
    assert "maximum_od_pairs" not in config.parameters["routing"]
    assert "maximum_origin_distance_m" not in config.parameters["candidates"]
    assert config.parameters["uncertainty"]["sample_count"] == 1000
    appraisal = config.parameters["appraisal"]
    assert appraisal["appraisal_years"] == 40
    assert [step["rate"] for step in appraisal["non_commercial_discount_schedule"]] == [
        0.02,
        0.015,
        0.01,
    ]
    assert appraisal["sensitivity_discount_rate"] == 0.08


def test_unknown_root_key_is_rejected(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["unexpected"] = True

    with pytest.raises(ConfigError, match="unknown keys: unexpected"):
        load_config(_write_config(tmp_path, raw))


def test_traversal_path_is_rejected(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["paths"]["runs"] = "../runs"

    with pytest.raises(ConfigError, match="normalised relative path"):
        load_config(_write_config(tmp_path, raw))


def test_pipeline_cycle_is_rejected(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["pipeline"]["stages"][0]["depends_on"] = ["prepare-demand"]

    with pytest.raises(ConfigError, match="dependency cycle"):
        load_config(_write_config(tmp_path, raw))


def test_external_data_root_does_not_change_serialised_config(tmp_path: Path) -> None:
    external = tmp_path / "external-data"
    config = load_config(CONFIG_PATH, data_root=external)

    assert config.data_dir == external.resolve()
    assert config.to_dict()["paths"]["data"] == "data"


def test_json_configuration_snapshot_preserves_scientific_notation(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["parameters"]["demand_response"]["minimum_probability"] = 1e-5
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    snapshot = config_dir / "snapshot.json"
    snapshot.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_config(snapshot)

    assert loaded.parameters["demand_response"]["minimum_probability"] == pytest.approx(1e-5)
    assert isinstance(loaded.parameters["demand_response"]["minimum_probability"], float)


def test_all_public_schemas_are_valid_json() -> None:
    schema_paths = sorted((PROJECT_ROOT / "schemas").glob("*.json"))

    assert {path.name for path in schema_paths} == {
        "config.schema.json",
        "run-manifest.schema.json",
        "source-registry.schema.json",
        "web-export.schema.json",
    }
    for path in schema_paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
