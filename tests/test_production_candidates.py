from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.pipeline import StageContext
from cycling_investment_workbench.production_candidates_stage import (
    CandidateEdge,
    _relative_direction,
    enumerate_nonbranching_chains,
    production_candidates_stage,
    split_chain_by_length,
)
from cycling_investment_workbench.provenance import hash_path, read_json, write_json_atomic

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_exported_direction_is_relative_to_candidate_traversal() -> None:
    assert _relative_direction("both", True) == "both"
    assert _relative_direction("forward", False) == "forward"
    assert _relative_direction("forward", True) == "reverse"
    assert _relative_direction("reverse", True) == "forward"


def _edge(
    edge_id: str,
    u: str,
    v: str,
    length_m: float = 100,
    *,
    lts: int = 3,
    facility: str = "mixed_traffic",
) -> CandidateEdge:
    return CandidateEdge(edge_id, u, v, length_m, lts, facility)


def test_candidate_enumeration_uses_exact_nodes_and_stops_at_branches() -> None:
    edges = (
        _edge("a", "n1", "n2"),
        _edge("b", "n2", "n3"),
        _edge("c", "n2", "n4"),
        _edge("low", "n3", "n5", lts=2),
        _edge("protected", "n4", "n6", facility="protected_lane"),
    )

    chains, closed = enumerate_nonbranching_chains(edges)

    assert closed == ()
    assert {chain.edge_ids for chain in chains} == {("a",), ("b",), ("c",)}
    assert {edge_id for chain in chains for edge_id in chain.edge_ids} == {"a", "b", "c"}


def test_parallel_edges_are_not_collapsed_or_captured_together() -> None:
    edges = (
        _edge("parallel-a", "n1", "n2"),
        _edge("parallel-b", "n1", "n2"),
        _edge("tail", "n2", "n3"),
    )

    chains, closed = enumerate_nonbranching_chains(edges)

    assert closed == ()
    assert {chain.edge_ids for chain in chains} == {
        ("parallel-a",),
        ("parallel-b",),
        ("tail",),
    }


def test_coincident_but_differently_identified_nodes_remain_disconnected() -> None:
    edges = (
        _edge("first", "source-node-1", "source-node-2"),
        _edge("second", "coincident-node-2", "source-node-3"),
    )

    chains, _ = enumerate_nonbranching_chains(edges)

    assert {chain.edge_ids for chain in chains} == {("first",), ("second",)}


def test_closed_degree_two_component_is_reported_separately() -> None:
    edges = (
        _edge("a", "n1", "n2"),
        _edge("b", "n2", "n3"),
        _edge("c", "n3", "n1"),
    )

    chains, closed = enumerate_nonbranching_chains(edges)

    assert chains == ()
    assert len(closed) == 1
    assert set(closed[0].edge_ids) == {"a", "b", "c"}


def test_candidate_split_uses_length_and_preserves_exact_order() -> None:
    values = (
        _edge("a", "n1", "n2", 60),
        _edge("b", "n2", "n3", 60),
        _edge("c", "n3", "n4", 40),
    )
    chains, _ = enumerate_nonbranching_chains(values)
    assert len(chains) == 1

    parts = split_chain_by_length(
        chains[0], {edge.id: edge for edge in values}, maximum_length_m=100
    )

    assert tuple(part.edge_ids for part in parts) == (("a",), ("b", "c"))
    assert parts[0].destination == parts[1].origin


def test_production_candidate_stage_writes_exact_edge_ledgers_and_exclusions(
    tmp_path: Path,
) -> None:
    topology_dir = tmp_path / "topology"
    routes_dir = tmp_path / "routes"
    topology_dir.mkdir()
    routes_dir.mkdir()
    nodes = [
        {"id": node_id, "x": x, "y": y}
        for node_id, x, y in (
            ("n1", 0, 0),
            ("n2", 120, 0),
            ("n3", 260, 0),
            ("n4", 360, 0),
            ("c1", 0, 500),
            ("c2", 100, 500),
            ("c3", 50, 580),
        )
    ]

    def edge(
        edge_id: str,
        u: str,
        v: str,
        length_m: float,
        *,
        lts: int = 3,
        direction: str = "both",
        bridge: bool = False,
    ) -> dict[str, object]:
        by_id = {item["id"]: (item["x"], item["y"]) for item in nodes}
        return {
            "id": edge_id,
            "u": u,
            "v": v,
            "source_way_id": edge_id.removeprefix("e"),
            "length_m": length_m,
            "geometry": [list(by_id[u]), list(by_id[v])],
            "direction": direction,
            "gradient": 0.0,
            "lts": lts,
            "facility": "mixed_traffic",
            "road_class": "residential",
            "bridge": bridge,
            "tunnel": False,
            "attributes": {"name": f"Road {edge_id}"},
        }

    topology = {
        "schema_version": 1,
        "crs": "EPSG:2193",
        "nodes": nodes,
        "edges": [
            edge("e1", "n1", "n2", 120),
            edge("e2", "n2", "n3", 140, direction="forward", bridge=True),
            edge("e3", "n3", "n4", 100, lts=2),
            edge("e4", "c1", "c2", 100),
            edge("e5", "c2", "c3", 100),
            edge("e6", "c3", "c1", 100),
        ],
    }
    write_json_atomic(topology_dir / "topology.json", topology)
    flow_rows = [
        {
            "project_edge_id": edge_id,
            "purpose": purpose,
            "estimated_observed_cycle": 2.0 if purpose == "commute" else 0.0,
            "estimated_eligible": eligible,
        }
        for purpose, eligible in (
            ("commute", 20.0),
            ("school", 10.0),
            ("everyday", 8.0),
            ("transit", 6.0),
        )
        for edge_id in ("e1", "e2")
    ]
    pq.write_table(pa.Table.from_pylist(flow_rows), routes_dir / "edge_flows.parquet")
    write_json_atomic(routes_dir / "manifest.json", {"purpose": "commute"})

    config = replace(load_config(PROJECT_ROOT / "configs/auckland.yml"), root_dir=tmp_path)
    run_dir = tmp_path / "runs" / "run-candidates"
    run_dir.mkdir(parents=True)
    context = StageContext(
        config=config,
        run_id="run-candidates",
        run_dir=run_dir,
        stage=PipelineStageConfig("generate-candidates", "test", (), {}),
        sources={},
        dependencies={
            "build-topology": {"topology": hash_path(topology_dir)},
            "assign-routes": {"routes": hash_path(routes_dir)},
        },
    )

    result = production_candidates_stage(context)
    output_dir = result.outputs["candidates"]
    manifest = read_json(output_dir / "manifest.json")
    candidates = pq.read_table(output_dir / "candidate_ledger.parquet").to_pylist()
    candidate_edges = pq.read_table(output_dir / "candidate_edge_ledger.parquet").to_pylist()
    purpose_metrics = pq.read_table(output_dir / "candidate_purpose_metrics.parquet").to_pylist()
    exclusions = pq.read_table(output_dir / "candidate_exclusion_ledger.parquet").to_pylist()

    assert result.metrics["row_counts"] == {
        "candidates": 1,
        "candidate_edges": 2,
        "candidate_purpose_metrics": 4,
        "candidate_exclusions": 1,
    }
    assert candidates[0]["ordered_edge_ids"] == ["e1", "e2"]
    assert candidates[0]["capital_cost_base_nzd"] == 1_560_000
    assert candidates[0]["has_bridge"] is True
    assert [row["project_edge_id"] for row in candidate_edges] == ["e1", "e2"]
    assert candidate_edges[1]["baseline_direction"] == "forward"
    assert {row["purpose"] for row in purpose_metrics} == {
        "commute",
        "school",
        "everyday",
        "transit",
    }
    assert exclusions[0]["reason"] == "closed_component_has_no_unambiguous_terminals"
    assert manifest["row_counts"]["candidate_edges"] == 2
    assert manifest["publication_grade_ready"] is False
    assert manifest["publication_blockers"] == ["capital_unit_cost_evidence_pending"]
