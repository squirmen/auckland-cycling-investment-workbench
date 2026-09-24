"""Bounded diagnostic witnesses for journeys a proposed programme cannot connect."""

from dataclasses import replace

from .active_search import InvestmentGraph, PlanningStandard


def diagnose_route_gap(
    graph: InvestmentGraph,
    origin: str,
    destination: str,
    *,
    standard: PlanningStandard,
    max_labels: int,
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
        result["witnessStressGaps"] = {
            "untreatedPhysicalEdges": len(
                {
                    a.edge_id
                    for a in arcs
                    if a.project_id is None and a.stress > standard.maximum_stress
                }
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
