from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from cycling_investment_workbench.production_routing_stage import (
    PATH_EDGE_SCHEMA,
    _write_commute_scenarios,
    _write_edge_flows,
    _write_parquet,
)


def _path_edge(purpose: str, edge_id: str, eligible: float) -> dict[str, object]:
    return {
        "schema_version": 3,
        "path_id": f"{purpose}-path",
        "od_id": f"{purpose}-od",
        "purpose": purpose,
        "path_index": 1,
        "edge_sequence": 1,
        "project_edge_id": edge_id,
        "reversed": False,
        "length_m": 100.0,
        "generalized_cost": 100.0,
        "directed_gradient_ratio": 0.0,
        "path_probability": 1.0,
        "estimated_observed_cycle": 2.0 if purpose == "commute" else 0.0,
        "estimated_eligible": eligible,
    }


def test_edge_flows_remain_separate_by_purpose(tmp_path: Path) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    destination = tmp_path / "flows.parquet"
    _write_parquet(
        first,
        [_path_edge("commute", "edge-a", 10), _path_edge("school", "edge-a", 20)],
        PATH_EDGE_SCHEMA,
    )
    _write_parquet(second, [_path_edge("commute", "edge-a", 5)], PATH_EDGE_SCHEMA)

    edge_count, record_count = _write_edge_flows(destination, (first, second))

    rows = {
        (row["purpose"], row["project_edge_id"]): row
        for row in pq.read_table(destination).to_pylist()
    }
    assert edge_count == 2
    assert record_count == 3
    assert rows[("commute", "edge-a")]["estimated_eligible"] == 15
    assert rows[("commute", "edge-a")]["path_edge_records"] == 2
    assert rows[("school", "edge-a")]["estimated_eligible"] == 20
    assert rows[("school", "edge-a")]["path_edge_records"] == 1


def test_commute_scenario_target_uses_complete_source_denominator(tmp_path: Path) -> None:
    destination = tmp_path / "scenarios.parquet"
    rows = {
        "assigned": {
            "od_id": "assigned",
            "purpose": "commute",
            "status": "assigned",
            "failure_reason": None,
            "analysis_weight": 2.0,
            "weighted_eligible": 10.0,
            "weighted_observed_cycle": 0.0,
            "shortest_distance_m": 1000.0,
            "shortest_average_absolute_gradient_percent": 1.0,
        },
        "failed": {
            "od_id": "failed",
            "purpose": "commute",
            "status": "unassigned",
            "failure_reason": "no_route",
            "analysis_weight": 1.0,
            "weighted_eligible": 5.0,
            "weighted_observed_cycle": 0.0,
            "shortest_distance_m": None,
            "shortest_average_absolute_gradient_percent": None,
        },
    }

    count, summaries = _write_commute_scenarios(
        destination,
        rows,
        complete_market_eligible=100,
        complete_market_observed_cycle=0,
        target_share=0.08,
    )

    assert count == 10
    assert summaries["commute_8pct"]["target_additional"] == 8
    assert summaries["commute_8pct"]["achieved_additional"] == pytest.approx(8)
    assert summaries["commute_8pct"]["denominator_not_shrunk_to_routable_sample"] is True
    table = pq.read_table(destination).to_pylist()
    failed = [row for row in table if row["od_id"] == "failed"]
    assert len(failed) == 5
    assert all(row["scenario_cycle"] is None for row in failed)
