from __future__ import annotations

from cycling_investment_workbench.production_candidates_stage import (
    CandidateEdge,
    _relative_direction,
    enumerate_nonbranching_chains,
    split_chain_by_length,
)


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
