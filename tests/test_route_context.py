from __future__ import annotations

import pytest

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.portfolio_analysis import ChoicePath, ODChoiceSet
from cycling_investment_workbench.route_context import build_route_context, treatment_usage

PARAMS = {"cost_scale": 0.02, "response": DemandResponseParameters()}


def choice():
    return ODChoiceSet(
        "od",
        "commute",
        100,
        10,
        (
            ChoicePath("direct", 100, 0.6, {"a": 20, "b": 10}),
            ChoicePath("other", 110, 0.4, {"b": 15}),
        ),
    )


def test_route_users_are_weighted_and_deduplicated_across_links():
    a = treatment_usage(choice(), frozenset({"a"}), **PARAMS)
    b = treatment_usage(choice(), frozenset({"b"}), **PARAMS)
    together = treatment_usage(choice(), frozenset({"a", "b"}), **PARAMS)
    assert a["before"] == 6
    assert b["before"] == together["before"] == 10
    assert together["after"] == pytest.approx(10 + together["additional"])
    assert a["after"] - a["before"] != pytest.approx(a["additional"])  # Rerouting too.
    assert together["after"] < a["after"] + b["after"]
    assert treatment_usage(choice(), frozenset({"unrelated"}), **PARAMS) == {
        "before": 0,
        "after": 0,
        "additional": 0,
    }


def test_prefix_and_independent_package_evaluation_and_fail_closed():
    a = treatment_usage(choice(), frozenset({"a"}), **PARAMS)
    joint = treatment_usage(choice(), frozenset({"a", "b"}), **PARAMS)
    steps = [
        {"candidateId": "a", "step": 1, "cumulativeObjective": a["additional"]},
        {"candidateId": "b", "step": 2, "cumulativeObjective": joint["additional"]},
    ]
    contexts = {cid: {"componentIds": ["area"], "touchingCandidateIds": []} for cid in "ab"}
    args = (
        {"od": choice()},
        {"a": {"od"}, "b": {"od"}},
        {"baseline": {"od": 10}},
        {"baseline": {"network": steps}},
        contexts,
    )
    usage, packages = build_route_context(*args, **PARAMS)
    assert steps[1]["routeUsersBefore"] == 10
    assert steps[1]["routeUsersAfter"] == pytest.approx(joint["after"])
    assert packages[-1] == {"scenario": "baseline", "candidateIds": ["a", "b"], **joint}
    assert packages[-1]["additional"] != pytest.approx(
        usage["a"]["baseline"]["additional"] + usage["b"]["baseline"]["additional"]
    )
    steps[1]["cumulativeObjective"] += 1
    with pytest.raises(ValueError, match="differs from stored uptake"):
        build_route_context(*args, **PARAMS)
