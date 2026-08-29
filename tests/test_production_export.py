from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import LineString

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.exports import export_web_payload, verify_web_export
from cycling_investment_workbench.pipeline import StageContext
from cycling_investment_workbench.production_export_stage import build_production_web_payload
from cycling_investment_workbench.provenance import hash_path, write_json_atomic

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_production_export_preserves_edges_units_and_rights_gates(tmp_path: Path) -> None:
    route_dir = tmp_path / "routes"
    candidate_dir = tmp_path / "candidates"
    portfolio_dir = tmp_path / "portfolios"
    evidence_dir = tmp_path / "evidence"
    write_json_atomic(
        route_dir / "manifest.json",
        {
            "coverage": {
                "by_purpose": {
                    purpose: {
                        "unit_specific_denominator": denominator,
                        "estimated_routing_coverage": coverage,
                    }
                    for purpose, denominator, coverage in (
                        ("commute", 100.0, 0.8),
                        ("school", 200.0, 0.9),
                        ("everyday", 300.0, 0.85),
                        ("transit", 400.0, 0.75),
                    )
                }
            },
            "scenario_summaries": {
                scenario: {"assigned_route_sample_total": value}
                for scenario, value in (
                    ("baseline", 10.0),
                    ("government_target", 20.0),
                    ("go_dutch", 30.0),
                    ("ebike", 40.0),
                    ("commute_8pct", 50.0),
                )
            },
        },
    )
    od_rows = [
        {
            "od_id": f"{purpose}-od",
            "origin_support_id": "sa1-7000001",
            "purpose": purpose,
            "weighted_eligible": eligible,
            "origin_x": 1_758_000.0,
            "origin_y": 5_918_000.0,
            "status": "assigned",
        }
        for purpose, eligible in (
            ("commute", 100.0),
            ("school", 200.0),
            ("everyday", 300.0),
            ("transit", 400.0),
        )
    ]
    _write_rows(route_dir / "od_ledger.parquet", od_rows)
    _write_rows(
        route_dir / "scenario_od_ledger.parquet",
        [
            {
                "scenario_id": scenario,
                "od_id": "commute-od",
                "scenario_cycle": value,
            }
            for scenario, value in (
                ("baseline", 10.0),
                ("government_target", 20.0),
                ("go_dutch", 30.0),
                ("ebike", 40.0),
                ("commute_8pct", 50.0),
            )
        ],
    )

    geometry = LineString(
        [(1_758_000.0, 5_918_000.0), (1_758_100.0, 5_918_000.0), (1_758_200.0, 5_918_000.0)]
    )
    _write_rows(
        candidate_dir / "candidate_ledger.parquet",
        [
            {
                "candidate_id": "candidate-a",
                "ordered_edge_ids": ["edge-a", "edge-b"],
                "maximum_baseline_lts": 4,
                "primary_road_names": ["Fixture Road"],
                "capital_cost_base_nzd": 1_200_000.0,
                "geometry_wkb": geometry.wkb,
            }
        ],
    )
    _write_rows(
        candidate_dir / "candidate_edge_ledger.parquet",
        [
            {
                "candidate_id": "candidate-a",
                "edge_sequence": index,
                "project_edge_id": edge_id,
                "from_node_id": f"n{index + 1}",
                "to_node_id": f"n{index + 2}",
                "length_m": 100.0,
                "baseline_lts": 3 + index,
                "baseline_facility": "mixed_traffic",
                "baseline_direction": "forward" if index == 0 else "both",
                "commute_estimated_observed_cycle": 5.0 + index,
            }
            for index, edge_id in enumerate(("edge-a", "edge-b"))
        ],
    )
    counterfactuals = [
        {
            "scenario_id": scenario,
            "purpose": "commute",
            "candidate_id": "candidate-a",
            "objective_value": value,
            "additional_cycle_users": value,
            "annual_cycle_km": value * 1_000,
            "pareto_member": True,
        }
        for scenario, value in (
            ("baseline", 1.0),
            ("government_target", 2.0),
            ("go_dutch", 3.0),
            ("ebike", 4.0),
            ("commute_8pct", 5.0),
        )
    ]
    counterfactuals.extend(
        {
            "scenario_id": "access_baseline",
            "purpose": purpose,
            "candidate_id": "candidate-a",
            "objective_value": value,
            "additional_cycle_users": None,
            "annual_cycle_km": None,
            "pareto_member": True,
        }
        for purpose, value in (("school", 7.0), ("everyday", 8.0), ("transit", 9.0))
    )
    _write_rows(portfolio_dir / "candidate_counterfactuals.parquet", counterfactuals)
    portfolio_steps = [
        {
            "scenario_id": scenario,
            "preset": "network",
            "rank": 1,
            "candidate_id": "candidate-a",
            "marginal_objective": value,
            "cumulative_objective": value,
            "cumulative_cost_nzd": 1_200_000.0,
        }
        for scenario, value in (
            ("baseline", 1.0),
            ("government_target", 2.0),
            ("go_dutch", 3.0),
            ("ebike", 4.0),
            ("commute_8pct", 5.0),
        )
    ]
    portfolio_steps.extend(
        {
            "scenario_id": "access_baseline",
            "preset": purpose,
            "rank": 1,
            "candidate_id": "candidate-a",
            "marginal_objective": value,
            "cumulative_objective": value,
            "cumulative_cost_nzd": 1_200_000.0,
        }
        for purpose, value in (("school", 7.0), ("everyday", 8.0), ("transit", 9.0))
    )
    _write_rows(portfolio_dir / "portfolio_steps.parquet", portfolio_steps)

    write_json_atomic(evidence_dir / "manifest.json", {"scenario_id": "commute_8pct"})
    _write_rows(
        evidence_dir / "candidate_evidence_profiles.parquet",
        [
            {
                "candidate_id": "candidate-a",
                "uncertainty_bcr_p05": 0.8,
                "uncertainty_bcr_p50": 1.2,
                "uncertainty_bcr_p95": 1.8,
                "mean_rank": 1.0,
                "top_k_probability": 0.9,
                "frontier_probability": 0.8,
                "warnings": ["fixture_warning"],
            }
        ],
    )
    _write_rows(
        evidence_dir / "candidate_appraisal.parquet",
        [
            {
                "candidate_id": "candidate-a",
                "discount_case": "principal_declining_rate",
                "present_value_costs_nzd": 1_500_000.0,
            }
        ],
    )

    config = replace(load_config(PROJECT_ROOT / "configs/auckland.yml"), root_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-fixture"
    run_dir.mkdir(parents=True)
    context = StageContext(
        config=config,
        run_id="run-fixture",
        run_dir=run_dir,
        stage=PipelineStageConfig("export-outputs", "test", (), {}),
        sources={},
        dependencies={
            "assign-routes": {"routes": hash_path(route_dir)},
            "generate-candidates": {"candidates": hash_path(candidate_dir)},
            "evaluate-portfolios": {"portfolios": hash_path(portfolio_dir)},
            "appraisal-uncertainty-validation": {"evidence": hash_path(evidence_dir)},
        },
    )

    payload = build_production_web_payload(context)

    manifest = payload["manifest"]
    candidate = payload["layers"]["candidates"]["features"][0]
    network = payload["layers"]["network"]["features"]
    assert manifest["schemaVersion"] == "2.0.0"
    assert manifest["capabilities"]["equity"] == "rights_blocked"
    assert manifest["capabilities"]["appraisal"] == "withheld"
    assert manifest["portfolios"]["baseline"]["appraisal"] == []
    assert "decisionSupport" not in manifest
    assert candidate["properties"]["edgeIds"] == ["edge-a", "edge-b"]
    appraisal = candidate["properties"]["metrics"]["commute_8pct"]["appraisal"]
    assert appraisal["available"] is False
    assert appraisal["objectiveUnit"] == "not available"
    assert appraisal["bcrP50"] is None
    assert "withheld" in appraisal["warnings"][0].lower()
    network_metric = candidate["properties"]["metrics"]["commute_8pct"]["network"]
    assert network_metric["bcrP5"] is None
    assert network_metric["bcrP50"] is None
    assert network_metric["bcrP95"] is None
    assert candidate["properties"]["metrics"]["baseline"]["equity"]["available"] is False
    assert candidate["properties"]["metrics"]["baseline"]["transit"]["available"] is False
    assert [feature["properties"]["edgeId"] for feature in network] == ["edge-a", "edge-b"]
    assert network[0]["properties"]["direction"] == "forward"

    output_dir = tmp_path / "public-data"
    export_web_payload(
        payload,
        export_config=config.export,
        output_dir=output_dir,
        source_specs=config.sources,
    )
    assert verify_web_export(output_dir, export_config=config.export) == ()
