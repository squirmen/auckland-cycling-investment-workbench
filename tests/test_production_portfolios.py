from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import StageContext
from cycling_investment_workbench.production_portfolios_stage import production_portfolios_stage
from cycling_investment_workbench.provenance import hash_path, read_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_production_portfolio_stage_keeps_metric_rows_unique_and_recomputes_sequences(
    tmp_path: Path,
) -> None:
    route_dir = tmp_path / "routes"
    candidate_dir = tmp_path / "candidates"
    _write_rows(
        candidate_dir / "candidate_ledger.parquet",
        [
            {"candidate_id": "candidate-a", "capital_cost_base_nzd": 100.0},
            {"candidate_id": "candidate-b", "capital_cost_base_nzd": 200.0},
        ],
    )
    _write_rows(
        candidate_dir / "candidate_edge_ledger.parquet",
        [
            {"candidate_id": "candidate-a", "project_edge_id": "edge-a", "baseline_lts": 3},
            {"candidate_id": "candidate-b", "project_edge_id": "edge-b", "baseline_lts": 4},
        ],
    )
    purposes = ("commute", "school", "everyday", "transit")
    _write_rows(
        route_dir / "path_ledger.parquet",
        [
            {
                "path_id": f"{purpose}-path",
                "od_id": f"{purpose}-od",
                "purpose": purpose,
                "probability": 1.0,
                "generalized_cost": 100.0,
            }
            for purpose in purposes
        ],
    )
    _write_rows(
        route_dir / "path_edge_ledger.parquet",
        [
            {
                "path_id": f"{purpose}-path",
                "project_edge_id": "edge-a" if purpose in {"commute", "everyday"} else "edge-b",
                "generalized_cost": 100.0,
            }
            for purpose in purposes
        ],
    )
    _write_rows(
        route_dir / "od_ledger.parquet",
        [
            {
                "od_id": f"{purpose}-od",
                "purpose": purpose,
                "weighted_eligible": 100.0,
                "weighted_observed_cycle": 10.0 if purpose == "commute" else 0.0,
                "shortest_distance_m": 5_000.0,
                "status": "assigned",
            }
            for purpose in purposes
        ],
    )
    _write_rows(
        route_dir / "scenario_od_ledger.parquet",
        [
            {
                "scenario_id": scenario,
                "od_id": "commute-od",
                "scenario_cycle": activity,
            }
            for scenario, activity in (("baseline", 10.0), ("go_dutch", 20.0))
        ],
    )

    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    config = replace(config, root_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-fixture"
    run_dir.mkdir(parents=True)
    context = StageContext(
        config=config,
        run_id="run-fixture",
        run_dir=run_dir,
        stage=PipelineStageConfig("evaluate-portfolios", "test", (), {}),
        sources={},
        dependencies={
            "assign-routes": {"routes": hash_path(route_dir)},
            "generate-candidates": {"candidates": hash_path(candidate_dir)},
        },
    )

    result = production_portfolios_stage(context)

    output_dir = Path(result.outputs["portfolios"])
    metrics = pq.read_table(output_dir / "candidate_counterfactuals.parquet").to_pylist()
    steps = pq.read_table(output_dir / "portfolio_steps.parquet").to_pylist()
    assert len(metrics) == 5
    commute_metrics = [row for row in metrics if row["purpose"] == "commute"]
    assert all(row["annual_cycle_km"] > 0 for row in commute_metrics)
    assert all(row["additional_cycle_users"] > 0 for row in commute_metrics)
    assert all(row["annual_cycle_km"] is None for row in metrics if row["purpose"] != "commute")
    assert len(
        {
            (row["scenario_id"], row["purpose"], row["objective"], row["candidate_id"])
            for row in metrics
        }
    ) == len(metrics)
    assert len(steps) == 7
    assert {row["preset"] for row in steps} == {
        "network",
        "appraisal",
        "school",
        "everyday",
        "transit",
    }
    manifest = read_json(output_dir / "manifest.json")
    assert manifest["counterfactual"]["cumulative_recomputation"] is True
    assert manifest["counterfactual"]["candidate_limit"] is None
