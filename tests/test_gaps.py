import pytest

from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
    Turn,
)
from cycling_investment_workbench.research.gaps import (
    all_projects_check,
    candidate_coverage_reasons,
    diagnose_route_gap,
    with_short_connector_diagnostic,
)


def assess(arcs, projects=None, turns=None, max_labels=100, standard=None, reasons=None):
    return diagnose_route_gap(
        InvestmentGraph(arcs, projects or {}, turns),
        "a",
        "c",
        standard=standard or PlanningStandard(),
        max_labels=max_labels,
        untreated_reasons=reasons,
    )


def test_all_projects_can_supply_a_route_without_relaxing_stress():
    result = assess([Arc("a", "e", "a", "c", 100, 10, 4, "P")], {"P": 20})
    assert result["routeFound"]
    assert not result["conclusiveNoRoute"]
    assert result["stressRelaxedWitnessFound"] is None


def test_unmodelled_street_gap_is_not_a_suitable_route():
    result = assess([Arc("a", "e", "a", "c", 100, 10, 4)])
    assert result["conclusiveNoRoute"]
    assert result["stressRelaxedWitnessFound"]
    assert result["witnessStressGaps"]["untreatedPhysicalEdges"] == 1
    assert result["witnessStressGaps"]["untreatedEdgesByReason"] == {"untraced": 1}


def test_coverage_distinguishes_source_exclusions_from_boundary_and_unknowns():
    reasons = candidate_coverage_reasons(
        {"complete", "partial", "excluded", "unknown"},
        [{"ordered_edge_ids": ["complete"]}, {"ordered_edge_ids": ["partial", "outside"]}],
        [{"ordered_edge_ids": ["excluded"], "reason": "below_declared_minimum_physical_length"}],
    )
    assert reasons == {
        "partial": "source_candidate_crosses_crop",
        "excluded": "source_exclusion:below_declared_minimum_physical_length",
        "unknown": "not_in_source_candidate_ledgers",
    }
    assert candidate_coverage_reasons(set(), [], []) == {}


@pytest.mark.parametrize("across_ledgers", [True, False])
def test_coverage_rejects_overlapping_physical_assets(across_ledgers):
    candidates = [{"ordered_edge_ids": ["edge"]}]
    duplicate = {"ordered_edge_ids": ["edge"], "reason": "excluded"}
    exclusions = [duplicate] if across_ledgers else []
    if not across_ledgers:
        candidates.append(duplicate)
    with pytest.raises(ValueError, match="disjoint"):
        candidate_coverage_reasons({"edge"}, candidates, exclusions)


def test_witness_reasons_count_physical_edges_not_directional_arcs():
    result = assess(
        [Arc("a", "e", "a", "b", 50, 5, 4), Arc("b", "e", "b", "c", 50, 5, 4)],
        reasons={"e": "source_candidate_crosses_crop"},
    )
    assert result["witnessStressGaps"]["untreatedEdgesByReason"] == {
        "source_candidate_crosses_crop": 1
    }


def test_treatment_retaining_high_stress_is_distinguished():
    result = assess([Arc("a", "e", "a", "c", 100, 10, 4, "P", 3)], {"P": 20})
    assert result["witnessStressGaps"]["physicalEdgesStillHighStressAfterTreatment"] == 1
    assert result["witnessStressGaps"]["untreatedPhysicalEdges"] == 0


def test_turn_stress_and_bans_are_not_silently_treated():
    arcs = [Arc("a", "ea", "a", "b", 50, 5, 1), Arc("b", "eb", "b", "c", 50, 5, 1)]
    result = assess(arcs, turns={("a", "b"): Turn(stress=4)})
    assert result["witnessStressGaps"]["turnMovementsStillHighStress"] == 1
    banned = assess(arcs, turns={("a", "b"): Turn(prohibited=True)})
    assert banned["conclusiveNoRoute"]
    assert not banned["stressRelaxedWitnessFound"]


def test_time_and_search_limits_remain_in_force():
    slow = assess([Arc("a", "e", "a", "c", 100, 1900, 4)])
    assert not slow["stressRelaxedWitnessFound"]
    capped = assess([Arc("a", "e", "a", "c", 100, 10, 4, "P")], {"P": 20}, max_labels=1)
    assert not capped["conclusiveNoRoute"]
    assert capped["stopReason"] == "label_limit"


def short_exclusion(edges, *, reason="below_declared_minimum_physical_length", length=50):
    return {
        "exclusion_id": "short-1",
        "ordered_edge_ids": edges,
        "reason": reason,
        "length_m": length,
    }


def check_graph(graph, *, max_labels=100):
    return all_projects_check(graph, "a", "c", standard=PlanningStandard(), max_labels=max_labels)


def test_short_connector_test_is_separate_and_keeps_whole_project_cost():
    original = InvestmentGraph(
        [Arc("a", "e", "a", "b", 25, 5, 4), Arc("b", "f", "b", "c", 25, 5, 4)], {}
    )
    diagnostic = with_short_connector_diagnostic(
        original, [short_exclusion(["e", "f"])], cost_per_m=6000
    )
    assert original.projects == {}
    assert original.arcs["a"].project_id is None
    assert check_graph(original)["conclusiveNoRoute"]
    assert check_graph(diagnostic)["routeFound"]
    assert diagnostic.projects == {"diagnostic-short:short-1": 300000}
    assert diagnostic.arcs["a"].project_id == diagnostic.arcs["b"].project_id
    assert check_graph(diagnostic, max_labels=1)["stopReason"] == "label_limit"


@pytest.mark.parametrize("barrier", ["stress", "turn", "time"])
def test_short_connectors_do_not_relax_other_requirements(barrier):
    original = InvestmentGraph(
        [
            Arc(
                "a",
                "e",
                "a",
                "b",
                25,
                1900 if barrier == "time" else 5,
                4,
                treated_stress=3 if barrier == "stress" else 1,
            ),
            Arc("b", "f", "b", "c", 25, 5, 1),
        ],
        {},
        {("a", "b"): Turn(prohibited=barrier == "turn", delay_s=20)},
    )
    diagnostic = with_short_connector_diagnostic(
        original, [short_exclusion(["e"])], cost_per_m=6000
    )
    assert diagnostic.turns == original.turns
    assert diagnostic.arcs["a"].treated_stress == original.arcs["a"].treated_stress
    assert check_graph(diagnostic)["conclusiveNoRoute"]


@pytest.mark.parametrize(
    "row",
    [
        short_exclusion(["e", "outside"]),
        short_exclusion([]),
        short_exclusion(["e"], reason="no_exposure_in_routed_purpose_markets"),
    ],
)
def test_diagnostic_does_not_restore_partial_or_other_exclusions(row):
    original = InvestmentGraph([Arc("a", "e", "a", "c", 50, 5, 4)], {})
    diagnostic = with_short_connector_diagnostic(original, [row], cost_per_m=6000)
    assert not diagnostic.projects
    assert check_graph(diagnostic)["conclusiveNoRoute"]


@pytest.mark.parametrize("rate", [0, -1, float("nan"), float("inf")])
def test_short_connector_rate_requires_a_valid_declared_assumption(rate):
    with pytest.raises(ValueError, match="screening rate"):
        with_short_connector_diagnostic(InvestmentGraph([], {}), [], cost_per_m=rate)


def test_short_connector_rejects_overlap_and_invalid_lengths():
    occupied = InvestmentGraph([Arc("a", "e", "a", "c", 50, 5, 4, "P")], {"P": 10})
    with pytest.raises(ValueError, match="overlap"):
        with_short_connector_diagnostic(occupied, [short_exclusion(["e"])], cost_per_m=6000)
    original = InvestmentGraph([Arc("a", "e", "a", "c", 50, 5, 4)], {})
    with pytest.raises(ValueError, match="length"):
        with_short_connector_diagnostic(
            original, [short_exclusion(["e"], length=-1)], cost_per_m=6000
        )
