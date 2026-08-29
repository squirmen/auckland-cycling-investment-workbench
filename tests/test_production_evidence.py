from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import StageContext
from cycling_investment_workbench.production_evidence_stage import (
    _counter_validation,
    production_evidence_stage,
)
from cycling_investment_workbench.provenance import (
    hash_path,
    read_json,
    sha256_file,
    write_json_atomic,
)
from cycling_investment_workbench.sources import SourceRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_production_evidence_stage_emits_appraisal_uncertainty_and_explicit_validation_gap(
    tmp_path: Path,
) -> None:
    portfolio_dir = tmp_path / "portfolios"
    route_dir = tmp_path / "routes"
    topology_dir = tmp_path / "topology"
    topology_dir.mkdir()
    _write_rows(
        portfolio_dir / "candidate_counterfactuals.parquet",
        [
            {
                "scenario_id": "commute_8pct",
                "purpose": "commute",
                "objective": "activity_addition",
                "candidate_id": candidate_id,
                "affected_od_count": 3,
                "additional_cycle_users": users,
                "annual_cycle_km": annual_km,
                "capital_cost_base_nzd": cost,
            }
            for candidate_id, users, annual_km, cost in (
                ("candidate-a", 20.0, 40_000.0, 1_000_000.0),
                ("candidate-b", 10.0, 25_000.0, 500_000.0),
            )
        ],
    )
    route_dir.mkdir()
    write_json_atomic(
        route_dir / "manifest.json",
        {"coverage": {"commute_estimated_routing_coverage_of_complete_source_market": 0.8}},
    )
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    parameters = copy.deepcopy(config.parameters)
    parameters["uncertainty"]["sample_count"] = 10
    parameters["uncertainty"]["rank_top_k"] = 1
    config = replace(config, root_dir=tmp_path, parameters=parameters)
    run_dir = tmp_path / "runs" / "run-fixture"
    run_dir.mkdir(parents=True)
    context = StageContext(
        config=config,
        run_id="run-fixture",
        run_dir=run_dir,
        stage=PipelineStageConfig("appraisal-uncertainty-validation", "test", (), {}),
        sources={},
        dependencies={
            "evaluate-portfolios": {"portfolios": hash_path(portfolio_dir)},
            "assign-routes": {"routes": hash_path(route_dir)},
            "build-topology": {"topology": hash_path(topology_dir)},
        },
    )

    result = production_evidence_stage(context)

    output_dir = Path(result.outputs["evidence"])
    appraisal = pq.read_table(output_dir / "candidate_appraisal.parquet").to_pylist()
    draws = pq.read_table(output_dir / "candidate_uncertainty_draws.parquet").to_pylist()
    summaries = pq.read_table(output_dir / "candidate_evidence_profiles.parquet").to_pylist()
    assert len(appraisal) == 4
    assert len(draws) == 20
    assert len(summaries) == 2
    by_candidate = {(row["candidate_id"], row["discount_case"]): row for row in appraisal}
    assert all(
        by_candidate[(candidate_id, "principal_declining_rate")]["indicative_bcr"]
        > by_candidate[(candidate_id, "mandatory_8pct_sensitivity")]["indicative_bcr"]
        for candidate_id in ("candidate-a", "candidate-b")
    )
    assert all(row["routing_coverage"] == 0.8 for row in summaries)
    manifest = read_json(output_dir / "manifest.json")
    assert manifest["uncertainty"]["iid_od_bootstrap"] is False
    assert len(manifest["uncertainty"]["dimensions"]) == 12
    assert manifest["validation"]["status"] == "unavailable"
    assert result.metrics["validation_coverage"] == 0


def test_counter_validation_preserves_incompatible_measure_warning(tmp_path: Path) -> None:
    locations = tmp_path / "counter-locations.json"
    observations = tmp_path / "counter-observations.json"
    write_json_atomic(
        locations,
        [{"name": "Fixture Road", "lng": 174.75, "lat": -36.85}],
    )
    write_json_atomic(observations, {"dailyAverages": {"Fixture Road": 100}})
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)
    x, y = transformer.transform(174.75, -36.85)
    topology_dir = tmp_path / "topology-real"
    topology_dir.mkdir()
    write_json_atomic(
        topology_dir / "topology.json",
        {
            "nodes": [
                {"id": "n1", "x": x - 50, "y": y, "layer": 0},
                {"id": "n2", "x": x + 50, "y": y, "layer": 0},
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "u": "n1",
                    "v": "n2",
                    "length_m": 100,
                    "direction": "both",
                    "geometry": [[x - 50, y], [x + 50, y]],
                    "road_class": "local",
                    "facility": "mixed_traffic",
                    "source_way_id": "way-1",
                }
            ],
        },
    )
    route_dir = tmp_path / "routes-real"
    _write_rows(
        route_dir / "edge_flows.parquet",
        [
            {
                "project_edge_id": "edge-1",
                "purpose": "commute",
                "estimated_observed_cycle": 40.0,
            }
        ],
    )
    config = replace(load_config(PROJECT_ROOT / "configs/auckland.yml"), root_dir=tmp_path)
    run_dir = tmp_path / "runs" / "counter-fixture"
    run_dir.mkdir(parents=True)
    sources = {
        "cycle_counter_locations": SourceRecord(
            "cycle_counter_locations",
            locations,
            False,
            "available",
            locations.stat().st_size,
            sha256_file(locations),
            None,
        ),
        "cycle_counter_observations": SourceRecord(
            "cycle_counter_observations",
            observations,
            False,
            "available",
            observations.stat().st_size,
            sha256_file(observations),
            None,
        ),
    }
    context = StageContext(
        config=config,
        run_id="counter-fixture",
        run_dir=run_dir,
        stage=PipelineStageConfig("appraisal-uncertainty-validation", "test", (), {}),
        sources=sources,
        dependencies={},
    )

    rows, summary = _counter_validation(
        context,
        route_dir,
        topology_dir,
        config.parameters["validation"],
    )

    assert len(rows) == 1
    assert rows[0]["matched_edge_id"] == "edge-1"
    assert rows[0]["status"] == "spatially_matched_incompatible_measure"
    assert rows[0]["exclusion_reason"] == "purpose_and_measure_not_aligned"
    assert summary["spatial_match_coverage"] == 1
    assert summary["calibration"] == "none"
    assert summary["status"] == "plausibility_only_incompatible_measure"
    assert summary["metrics"] is None
    assert summary["null_model_metrics"] is None
