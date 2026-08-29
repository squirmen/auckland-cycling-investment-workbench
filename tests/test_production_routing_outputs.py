from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import StageContext
from cycling_investment_workbench.production_routing_stage import (
    PATH_EDGE_SCHEMA,
    _write_commute_scenarios,
    _write_edge_flows,
    _write_parquet,
    production_routing_stage,
)
from cycling_investment_workbench.provenance import (
    hash_path,
    read_json,
    sha256_file,
    write_json_atomic,
)
from cycling_investment_workbench.r5_routing import (
    ProjectTraversal,
    R5RouteResult,
    ReconciledPath,
    RouteAlternative,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def test_production_routing_stage_writes_complete_four_purpose_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    topology_dir = tmp_path / "topology"
    topology_dir.mkdir()
    pbf_path = topology_dir / "bounded.osm.pbf"
    pbf_path.write_bytes(b"deterministic bounded fixture")
    topology_payload = {
        "schema_version": 1,
        "crs": "EPSG:2193",
        "osm_extract": {"output_sha256": sha256_file(pbf_path)},
        "nodes": [
            {"id": "a", "x": 0.0, "y": 0.0, "layer": 0},
            {"id": "b", "x": 100.0, "y": 0.0, "layer": 0},
            {"id": "c", "x": 200.0, "y": 0.0, "layer": 0},
        ],
        "edges": [
            {
                "id": "osm-way-10-segment-0",
                "u": "a",
                "v": "b",
                "source_way_id": "10",
                "length_m": 100.0,
                "geometry": [[0.0, 0.0], [100.0, 0.0]],
                "direction": "both",
                "gradient": 0.01,
                "lts": 2,
                "bridge": False,
                "tunnel": False,
            },
            {
                "id": "osm-way-10-segment-1",
                "u": "b",
                "v": "c",
                "source_way_id": "10",
                "length_m": 100.0,
                "geometry": [[100.0, 0.0], [200.0, 0.0]],
                "direction": "both",
                "gradient": 0.02,
                "lts": 3,
                "bridge": False,
                "tunnel": False,
            },
        ],
    }
    write_json_atomic(topology_dir / "topology.json", topology_payload)

    class FixtureEngine:
        def __init__(self, _pbf: Path, topology, **_kwargs: object) -> None:
            self.topology = topology
            self.origin_node_indices = frozenset({0, 1, 2})
            self.destination_node_indices = frozenset({0, 1, 2})
            self.mapping_diagnostics = {"fixture": True}

        def route(self, _origin, _destination, **_kwargs: object) -> R5RouteResult:
            path = ReconciledPath(
                (101, 102),
                (10, 10),
                (ProjectTraversal(0, False), ProjectTraversal(1, False)),
                420.0,
                200.0,
            )
            return R5RouteResult(
                "assigned",
                None,
                0.0,
                0.0,
                200.0,
                (RouteAlternative(path, 1.0, 1.0),),
                1.5,
                3.0,
            )

    monkeypatch.setattr(
        "cycling_investment_workbench.production_routing_stage.R5CyclingEngine",
        FixtureEngine,
    )

    def record(purpose: str, index: int) -> dict[str, object]:
        return {
            "id": f"{purpose}-{index}",
            "source_cell_id": f"source-{purpose}",
            "origin_support_id": f"origin-{purpose}",
            "destination_support_id": f"destination-{purpose}",
            "purpose": purpose,
            "eligible": 10.0 + index,
            "cycle": 1.0 if purpose == "commute" else 0.0,
            "selection_probability": 1.0,
            "draw_count": 1,
            "total_draws": 1,
            "origin_x": 0.0,
            "origin_y": 0.0,
            "destination_x": 200.0,
            "destination_y": 0.0,
        }

    demand_path = tmp_path / "prepared-demand.json"
    write_json_atomic(
        demand_path,
        {
            "publication_blockers": [],
            "disaggregated_commute_ledger": [record("commute", 1)],
            "non_commute_purpose_od_ledger": [
                record("school", 2),
                record("everyday", 3),
                record("transit", 4),
            ],
            "zonal_od_ledger": [{"origin": "z1", "destination": "z2", "eligible": 50.0}],
            "structural_censoring": {
                "unresolved_market_ledger": {
                    "source_market_total_stated_margin_point": 100.0,
                    "source_market_bicycle_margin_point": 2.0,
                }
            },
        },
    )
    config = replace(load_config(PROJECT_ROOT / "configs/auckland.yml"), root_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-routing"
    run_dir.mkdir(parents=True)
    context = StageContext(
        config=config,
        run_id="run-routing",
        run_dir=run_dir,
        stage=PipelineStageConfig("assign-routes", "test", (), {}),
        sources={},
        dependencies={
            "build-topology": {"topology": hash_path(topology_dir)},
            "prepare-demand": {"demand": hash_path(demand_path)},
        },
    )

    result = production_routing_stage(context)
    output_dir = result.outputs["routes"]
    manifest = read_json(output_dir / "manifest.json")
    od_rows = pq.read_table(output_dir / "od_ledger.parquet").to_pylist()
    path_rows = pq.read_table(output_dir / "path_ledger.parquet").to_pylist()
    edge_rows = pq.read_table(output_dir / "path_edge_ledger.parquet").to_pylist()
    flow_rows = pq.read_table(output_dir / "edge_flows.parquet").to_pylist()
    scenario_rows = pq.read_table(output_dir / "scenario_od_ledger.parquet").to_pylist()

    assert result.metrics["row_counts"] == {
        "disaggregated_od": 4,
        "selected_for_routing": 4,
        "assigned_selected_od": 4,
        "paths": 4,
        "path_edges": 8,
        "edges_with_estimated_flow": 8,
        "scenario_od": 5,
    }
    assert result.metrics["routing_failures"] == 0
    assert all(row["status"] == "assigned" for row in od_rows)
    assert len(path_rows) == 4
    assert len(edge_rows) == 8
    assert {(row["purpose"], row["project_edge_id"]) for row in flow_rows} == {
        (purpose, edge_id)
        for purpose in ("commute", "school", "everyday", "transit")
        for edge_id in ("osm-way-10-segment-0", "osm-way-10-segment-1")
    }
    assert {row["scenario_id"] for row in scenario_rows} == {
        "baseline",
        "government_target",
        "go_dutch",
        "ebike",
        "commute_8pct",
    }
    assert manifest["engine"]["mapping_diagnostics"] == {"fixture": True}
    assert manifest["coverage"]["cross_purpose_units_are_not_summed"] is True
    assert manifest["publication_grade_ready"] is False
