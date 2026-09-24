from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
    Turn,
)
from cycling_investment_workbench.research.gaps import diagnose_route_gap


def assess(arcs, projects=None, turns=None, max_labels=100, standard=None):
    return diagnose_route_gap(
        InvestmentGraph(arcs, projects or {}, turns),
        "a",
        "c",
        standard=standard or PlanningStandard(),
        max_labels=max_labels,
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
