from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

import cycling_investment_workbench.portfolio_analysis as portfolio_analysis
from cycling_investment_workbench.portfolio_analysis import (
    ChoicePath,
    ChoiceSequenceStep,
    ODChoiceSet,
    evaluate_choice_set,
    greedy_choice_set_sequence,
    pareto_frontier_benefit_cost,
)


def _choice() -> ODChoiceSet:
    return ODChoiceSet(
        "od",
        "commute",
        100,
        10,
        (
            ChoicePath("direct", 100, 0.7, {"a": 20}),
            ChoicePath("alternative", 110, 0.3, {"b": 30}),
        ),
    )


def _brute_force_sequence(
    choices: Mapping[str, ODChoiceSet],
    candidate_costs: Mapping[str, float],
    candidate_to_od_ids: Mapping[str, Sequence[str]],
    *,
    purpose: str,
    objective: str,
    cost_scale: float,
    budget_nzd: float,
    score_per_cost: bool,
) -> tuple[ChoiceSequenceStep, ...]:
    """Small reference implementation of the original exhaustive algorithm."""

    relevant = {key: value for key, value in choices.items() if value.purpose == purpose}
    current = {
        key: evaluate_choice_set(value, cost_scale=cost_scale) for key, value in relevant.items()
    }
    selected: list[str] = []
    remaining = set(candidate_to_od_ids)
    spent = 0.0
    cumulative = 0.0
    steps: list[ChoiceSequenceStep] = []

    def value(evaluation: portfolio_analysis.ODChoiceEvaluation) -> float:
        return float(getattr(evaluation, objective))

    while remaining:
        options: list[tuple[float, float, float, str]] = []
        selected_set = frozenset(selected)
        for candidate_id in sorted(remaining):
            cost = float(candidate_costs[candidate_id])
            if spent + cost > budget_nzd + 1e-9:
                continue
            proposed = selected_set | {candidate_id}
            marginal = sum(
                value(evaluate_choice_set(relevant[od_id], proposed, cost_scale=cost_scale))
                - value(current[od_id])
                for od_id in candidate_to_od_ids[candidate_id]
                if od_id in relevant
            )
            denominator = cost if cost > 0 else 1e-12
            efficiency = marginal / denominator if score_per_cost else marginal
            options.append((efficiency, marginal, -cost, candidate_id))
        if not options:
            break
        efficiency, marginal, negative_cost, candidate_id = max(options)
        if marginal <= 1e-12:
            break
        selected.append(candidate_id)
        spent -= negative_cost
        cumulative += marginal
        selected_set = frozenset(selected)
        for od_id in candidate_to_od_ids[candidate_id]:
            if od_id in relevant:
                current[od_id] = evaluate_choice_set(
                    relevant[od_id], selected_set, cost_scale=cost_scale
                )
        steps.append(
            ChoiceSequenceStep(
                len(steps) + 1,
                candidate_id,
                tuple(selected),
                marginal,
                cumulative,
                efficiency,
                spent,
            )
        )
        remaining.remove(candidate_id)
    return tuple(steps)


def test_choice_set_reweights_paths_and_accumulates_joint_treatments() -> None:
    choice = _choice()

    baseline = evaluate_choice_set(choice, cost_scale=0.02)
    first = evaluate_choice_set(choice, frozenset({"a"}), cost_scale=0.02)
    joint = evaluate_choice_set(choice, frozenset({"a", "b"}), cost_scale=0.02)

    assert baseline.expected_generalized_cost == pytest.approx(103)
    assert first.probability_by_path["direct"] > 0.7
    assert joint.expected_generalized_cost < first.expected_generalized_cost
    assert joint.activity_addition > first.activity_addition > 0
    assert joint.impedance_improvement > first.impedance_improvement > 0


def test_choice_set_probability_update_is_stable_for_large_cost_savings() -> None:
    choice = ODChoiceSet(
        "large-od",
        "commute",
        100,
        10,
        (
            ChoicePath("treated", 1_000_000, 0.5, {"a": 900_000}),
            ChoicePath("untreated", 1_000_000, 0.5, {}),
        ),
    )

    result = evaluate_choice_set(choice, frozenset({"a"}), cost_scale=0.02)

    assert result.probability_by_path["treated"] == pytest.approx(1)
    assert 100_000 < result.expected_generalized_cost < 100_100


def test_greedy_sequence_recomputes_each_marginal_on_current_portfolio() -> None:
    choice = _choice()
    sequence = greedy_choice_set_sequence(
        {choice.id: choice},
        {"a": 10, "b": 10},
        {"a": [choice.id], "b": [choice.id]},
        purpose="commute",
        objective="activity_addition",
        cost_scale=0.02,
        budget_nzd=20,
    )

    assert len(sequence) == 2
    assert sequence[0].cumulative_candidate_ids == (sequence[0].candidate_id,)
    assert sequence[1].cumulative_candidate_ids == (
        sequence[0].candidate_id,
        sequence[1].candidate_id,
    )
    joint = evaluate_choice_set(choice, frozenset({"a", "b"}), cost_scale=0.02)
    assert sequence[-1].cumulative_objective == pytest.approx(joint.activity_addition)
    assert sequence[-1].cumulative_cost_nzd == 20


def test_greedy_sequence_honours_budget_and_purpose() -> None:
    commute = _choice()
    school = ODChoiceSet(
        "school-od",
        "school",
        50,
        0,
        (ChoicePath("school-path", 100, 1, {"school-project": 20}),),
    )

    sequence = greedy_choice_set_sequence(
        {commute.id: commute, school.id: school},
        {"a": 10, "b": 10, "school-project": 5},
        {
            "a": [commute.id],
            "b": [commute.id],
            "school-project": [school.id],
        },
        purpose="school",
        objective="impedance_improvement",
        cost_scale=0.02,
        budget_nzd=5,
    )

    assert [step.candidate_id for step in sequence] == ["school-project"]


@pytest.mark.parametrize(
    ("score_per_cost", "budget_nzd"),
    [(True, 30.0), (False, 30.0), (True, 12.0)],
)
def test_sparse_sequence_matches_exhaustive_reference(
    score_per_cost: bool, budget_nzd: float
) -> None:
    choices = {
        "od-1": ODChoiceSet(
            "od-1",
            "commute",
            120,
            12,
            (
                ChoicePath("od-1-direct", 100, 0.65, {"a": 18, "b": 8}),
                ChoicePath("od-1-other", 115, 0.35, {"b": 22}),
            ),
        ),
        "od-2": ODChoiceSet(
            "od-2",
            "commute",
            80,
            9,
            (
                ChoicePath("od-2-direct", 90, 0.8, {"c": 15}),
                ChoicePath("od-2-other", 105, 0.2, {"d": 20}),
            ),
        ),
        "od-3": ODChoiceSet(
            "od-3",
            "commute",
            60,
            5,
            (ChoicePath("od-3-path", 95, 1, {"b": 12, "c": 10}),),
        ),
        "school-od": ODChoiceSet(
            "school-od",
            "school",
            50,
            3,
            (ChoicePath("school-path", 80, 1, {"d": 12}),),
        ),
    }
    costs = {"a": 6.0, "b": 8.0, "c": 5.0, "d": 7.0}
    candidate_to_od_ids = {
        "a": ["od-1"],
        "b": ["od-1", "od-3"],
        "c": ["od-2", "od-3"],
        "d": ["od-2", "school-od"],
    }
    arguments = {
        "purpose": "commute",
        "objective": "activity_addition",
        "cost_scale": 0.02,
        "budget_nzd": budget_nzd,
        "score_per_cost": score_per_cost,
    }

    expected = _brute_force_sequence(choices, costs, candidate_to_od_ids, **arguments)
    actual = greedy_choice_set_sequence(choices, costs, candidate_to_od_ids, **arguments)

    assert [step.candidate_id for step in actual] == [step.candidate_id for step in expected]
    assert [step.cumulative_candidate_ids for step in actual] == [
        step.cumulative_candidate_ids for step in expected
    ]
    assert [step.marginal_objective for step in actual] == pytest.approx(
        [step.marginal_objective for step in expected]
    )
    assert [step.cumulative_objective for step in actual] == pytest.approx(
        [step.cumulative_objective for step in expected]
    )
    assert [step.cumulative_cost_nzd for step in actual] == pytest.approx(
        [step.cumulative_cost_nzd for step in expected]
    )


def test_sparse_sequence_preserves_exhaustive_tie_breaking() -> None:
    choice = ODChoiceSet(
        "tie-od",
        "commute",
        100,
        10,
        (ChoicePath("tie-path", 100, 1, {"a": 10, "b": 10}),),
    )

    sequence = greedy_choice_set_sequence(
        {choice.id: choice},
        {"a": 5, "b": 5},
        {"a": [choice.id], "b": [choice.id]},
        purpose="commute",
        objective="activity_addition",
        cost_scale=0.02,
        budget_nzd=10,
    )

    assert [step.candidate_id for step in sequence] == ["b", "a"]


def test_sparse_sequence_does_not_recompute_disjoint_candidate_marginals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = {
        f"od-{candidate_id}": ODChoiceSet(
            f"od-{candidate_id}",
            "commute",
            100,
            10,
            (ChoicePath(f"path-{candidate_id}", 100, 1, {candidate_id: 10}),),
        )
        for candidate_id in ("a", "b", "c")
    }
    original = portfolio_analysis.evaluate_choice_set
    evaluation_count = 0

    def counted_evaluation(*args: object, **kwargs: object):
        nonlocal evaluation_count
        evaluation_count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(portfolio_analysis, "evaluate_choice_set", counted_evaluation)

    sequence = greedy_choice_set_sequence(
        choices,
        {"a": 1, "b": 1, "c": 1},
        {"a": ["od-a"], "b": ["od-b"], "c": ["od-c"]},
        purpose="commute",
        objective="activity_addition",
        cost_scale=0.02,
        budget_nzd=3,
    )

    assert len(sequence) == 3
    assert evaluation_count == 9


def test_scalable_pareto_frontier_handles_equal_cost_ties() -> None:
    frontier = pareto_frontier_benefit_cost(
        {"a": 5, "b": 4, "c": 5, "d": 8},
        {"a": 10, "b": 10, "c": 10, "d": 20},
    )

    assert frontier == ("a", "c", "d")
