"""Bounded diagnostic witnesses for journeys a proposed programme cannot connect."""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import replace
from math import isfinite

from .active_search import InvestmentGraph, PlanningStandard


def candidate_coverage_reasons(
    crop_edge_ids: set[str],
    source_candidates: Iterable[Mapping],
    source_exclusions: Iterable[Mapping],
) -> dict[str, str]:
    """Account for crop edges without a complete source candidate in the crop.

    Use the original exclusion ledger, not an inferred replacement for its rules.
    Unlisted edges remain explicitly unexplained (e.g. facility eligibility).
    Inputs must describe disjoint physical assets, including across the ledgers.
    """
    classified: dict[str, str | None] = {}
    for rows, excluded in ((source_candidates, False), (source_exclusions, True)):
        for row in rows:
            edges = row["ordered_edge_ids"]
            reason = (
                "source_exclusion:" + row["reason"]
                if excluded
                else (None if set(edges) <= crop_edge_ids else "source_candidate_crosses_crop")
            )
            for edge in edges:
                if edge in classified:
                    raise ValueError("candidate coverage ledgers must have disjoint physical edges")
                classified[edge] = reason
    return {
        edge: reason
        for edge in sorted(crop_edge_ids)
        if (reason := classified.get(edge, "not_in_source_candidate_ledgers")) is not None
    }


def with_short_connector_diagnostic(
    graph: InvestmentGraph,
    source_exclusions: Iterable[Mapping],
    *,
    cost_per_m: float,
) -> InvestmentGraph:
    """Copy the graph with whole, in-crop short exclusions as hypothetical projects.

    Never changes routing geometry, directions, times, turns or treated stress.
    Costs use the declared source screening rate, not an engineering estimate.
    This graph is only for diagnostic searches, not the published portfolio.
    """
    if not isfinite(cost_per_m) or cost_per_m <= 0:
        raise ValueError("connector screening rate must be positive and finite")
    edge_ids = {a.edge_id for a in graph.arcs.values()}
    occupied = {a.edge_id for a in graph.arcs.values() if a.project_id is not None}
    projects = dict(graph.projects)
    by_edge = {}
    for row in source_exclusions:
        if row["reason"] != "below_declared_minimum_physical_length":
            continue
        edges = set(row["ordered_edge_ids"])
        if not edges or not edges <= edge_ids:
            continue
        project = "diagnostic-short:" + row["exclusion_id"]
        if project in projects or edges & (occupied | by_edge.keys()):
            raise ValueError("diagnostic connectors overlap existing physical projects")
        length = float(row["length_m"])
        if not isfinite(length) or length <= 0:
            raise ValueError("connector length must be positive and finite")
        projects[project] = length * cost_per_m
        by_edge.update(dict.fromkeys(edges, project))
    return InvestmentGraph(
        [
            replace(a, project_id=by_edge[a.edge_id]) if a.edge_id in by_edge else a
            for a in graph.arcs.values()
        ],
        projects,
        graph.turns,
    )


def all_projects_check(
    graph: InvestmentGraph,
    origin: str,
    destination: str,
    *,
    standard: PlanningStandard,
    max_labels: int,
) -> dict:
    """Find an acceptable witness with every project funded; no affordability claim."""
    selected = frozenset(graph.projects)
    result = graph.search(
        origin,
        destination,
        standard=standard,
        budget=graph.cost(graph.mask(selected)),
        selected=selected,
        allow_new_projects=False,
        max_labels=max_labels,
        first_only=True,
    )
    return {
        "routeFound": bool(result.routes),
        "stopReason": result.stop_reason,
        "conclusiveNoRoute": result.complete and not result.routes,
        "labelsExpanded": result.labels_expanded,
        "elapsedS": result.elapsed_s,
    }


def diagnose_route_gap(
    graph: InvestmentGraph,
    origin: str,
    destination: str,
    *,
    standard: PlanningStandard,
    max_labels: int,
    untreated_reasons: Mapping[str, str] | None = None,
) -> dict:
    """Distinguish unavailable modelled treatments from budget/search limitations.

    A relaxed-stress route is a diagnostic witness, never a suitable cycling
    recommendation. Counts describe that witness, not a minimum intervention set.
    """
    selected = frozenset(graph.projects)
    options = {
        "budget": graph.cost(graph.mask(selected)),
        "selected": selected,
        "allow_new_projects": False,
        "max_labels": max_labels,
        "first_only": True,
    }
    full = graph.search(origin, destination, standard=standard, **options)
    result = {
        "routeFound": bool(full.routes),
        "stopReason": full.stop_reason,
        "conclusiveNoRoute": full.complete and not full.routes,
        "labelsExpanded": full.labels_expanded,
        "elapsedS": full.elapsed_s,
        "stressRelaxedWitnessFound": None,
        "stressRelaxedStopReason": None,
        "witnessStressGaps": None,
    }
    if full.routes:
        return result
    relaxed = graph.search(
        origin, destination, standard=replace(standard, maximum_stress=4), **options
    )
    result["stressRelaxedWitnessFound"] = bool(relaxed.routes)
    result["stressRelaxedStopReason"] = relaxed.stop_reason
    if relaxed.routes:
        route = relaxed.routes[0]
        arcs = [graph.arcs[key] for key in route.arc_ids]
        untreated = {
            a.edge_id for a in arcs if a.project_id is None and a.stress > standard.maximum_stress
        }
        result["witnessStressGaps"] = {
            "untreatedPhysicalEdges": len(untreated),
            "untreatedEdgesByReason": dict(
                sorted(
                    Counter(
                        (untreated_reasons or {}).get(edge, "untraced") for edge in untreated
                    ).items()
                )
            ),
            "physicalEdgesStillHighStressAfterTreatment": len(
                {
                    a.edge_id
                    for a in arcs
                    if a.project_id is not None and a.treated_stress > standard.maximum_stress
                }
            ),
            "turnMovementsStillHighStress": sum(
                (turn.treated_stress if turn.project_id in selected else turn.stress)
                > standard.maximum_stress
                for pair in zip(route.arc_ids, route.arc_ids[1:], strict=False)
                if (turn := graph.turns.get(pair)) is not None
            ),
        }
    return result
