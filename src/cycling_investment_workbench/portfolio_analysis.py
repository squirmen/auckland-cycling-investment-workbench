"""Cumulative counterfactual analysis over auditable route choice sets."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import exp, isfinite, log

from .candidates import (
    DEFAULT_DEMAND_RESPONSE,
    DemandResponseParameters,
    continuous_demand_response,
)


@dataclass(frozen=True, slots=True)
class ChoicePath:
    """One retained plausible path and its candidate-specific cost savings."""

    id: str
    baseline_cost: float
    baseline_probability: float
    savings_by_candidate: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.id or self.baseline_cost <= 0 or not isfinite(self.baseline_cost):
            raise ValueError("choice path requires an id and positive finite cost")
        if not 0 < self.baseline_probability <= 1:
            raise ValueError("choice path probability must be in (0, 1]")
        if any(
            not candidate_id or saving < 0 or not isfinite(saving)
            for candidate_id, saving in self.savings_by_candidate.items()
        ):
            raise ValueError("candidate path savings must be identified and non-negative")
        if sum(self.savings_by_candidate.values()) >= self.baseline_cost:
            raise ValueError("candidate savings must leave a positive treated path cost")


@dataclass(frozen=True, slots=True)
class ODChoiceSet:
    """A weighted OD market with a fixed, declared plausible-path set."""

    id: str
    purpose: str
    eligible: float
    baseline_activity: float
    paths: tuple[ChoicePath, ...]
    distance_km: float = 0.0

    def __post_init__(self) -> None:
        if not self.id or not self.purpose or not self.paths:
            raise ValueError("OD choice set identifiers and paths must be non-empty")
        if (
            self.eligible < 0
            or self.baseline_activity < 0
            or self.baseline_activity > self.eligible
            or not isfinite(self.eligible)
            or not isfinite(self.baseline_activity)
            or self.distance_km < 0
            or not isfinite(self.distance_km)
        ):
            raise ValueError("OD activity and distance must be finite and non-negative")
        probability = sum(path.baseline_probability for path in self.paths)
        if abs(probability - 1.0) > 1e-10:
            raise ValueError("choice path probabilities must sum to one")
        if len({path.id for path in self.paths}) != len(self.paths):
            raise ValueError("choice path ids must be unique within an OD")


@dataclass(frozen=True, slots=True)
class ODChoiceEvaluation:
    expected_generalized_cost: float
    activity_addition: float
    impedance_improvement: float
    probability_by_path: Mapping[str, float]


def evaluate_choice_set(
    choice: ODChoiceSet,
    selected_candidate_ids: frozenset[str] = frozenset(),
    *,
    cost_scale: float,
    response: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
) -> ODChoiceEvaluation:
    """Recompute path probabilities and continuous response cumulatively.

    Baseline path probabilities retain the path-size and other alternative
    terms from the routing stage.  A treatment changes only generalized cost,
    so multiplying baseline probability by ``exp(scale * cost_saving)`` gives
    the exact reweighted probability within the declared choice set.
    """

    if cost_scale < 0 or not isfinite(cost_scale):
        raise ValueError("cost_scale must be finite and non-negative")
    treated_costs: list[float] = []
    log_weights: list[float] = []
    for path in choice.paths:
        saving = sum(
            value
            for candidate_id, value in path.savings_by_candidate.items()
            if candidate_id in selected_candidate_ids
        )
        treated_cost = path.baseline_cost - saving
        if treated_cost <= 0:
            raise ValueError(f"candidate treatment makes path cost non-positive: {path.id}")
        treated_costs.append(treated_cost)
        log_weights.append(log(path.baseline_probability) + cost_scale * saving)
    maximum_log_weight = max(log_weights)
    stable_weights = [exp(value - maximum_log_weight) for value in log_weights]
    stable_weight_total = sum(stable_weights)
    probabilities = [value / stable_weight_total for value in stable_weights]
    baseline_expected = sum(path.baseline_probability * path.baseline_cost for path in choice.paths)
    inclusive_saving = (
        (maximum_log_weight + log(stable_weight_total)) / cost_scale
        if cost_scale > 0
        else sum(
            path.baseline_probability * (path.baseline_cost - treated_cost)
            for path, treated_cost in zip(choice.paths, treated_costs, strict=True)
        )
    )
    treated_expected = baseline_expected - inclusive_saving
    if treated_expected <= 0:
        raise ValueError("inclusive candidate saving makes OD cost non-positive")
    activity_addition = continuous_demand_response(
        choice.eligible,
        choice.baseline_activity,
        baseline_expected,
        treated_expected,
        parameters=response,
    )
    impedance_improvement = (
        choice.eligible * (baseline_expected - treated_expected) / baseline_expected
        if baseline_expected > 0
        else 0.0
    )
    return ODChoiceEvaluation(
        treated_expected,
        activity_addition,
        impedance_improvement,
        {
            path.id: probability
            for path, probability in zip(choice.paths, probabilities, strict=True)
        },
    )


@dataclass(frozen=True, slots=True)
class ChoiceSequenceStep:
    rank: int
    candidate_id: str
    cumulative_candidate_ids: tuple[str, ...]
    marginal_objective: float
    cumulative_objective: float
    marginal_objective_per_nzd: float
    cumulative_cost_nzd: float


def greedy_choice_set_sequence(
    choices: Mapping[str, ODChoiceSet],
    candidate_costs: Mapping[str, float],
    candidate_to_od_ids: Mapping[str, Sequence[str]],
    *,
    purpose: str,
    objective: str,
    cost_scale: float,
    budget_nzd: float,
    score_per_cost: bool = True,
    response: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
) -> tuple[ChoiceSequenceStep, ...]:
    """Sequence projects with exact sparse marginal recomputation.

    Selecting a candidate changes only the OD choice sets that use one of its
    treated edges. Marginals for candidates with disjoint affected-OD sets are
    therefore unchanged. A versioned heap retains those exact values and
    recomputes every overlapping candidate after each selection.
    """

    if objective not in {"activity_addition", "impedance_improvement"}:
        raise ValueError("unknown cumulative objective")
    if budget_nzd < 0 or not isfinite(budget_nzd):
        raise ValueError("budget must be finite and non-negative")
    if set(candidate_to_od_ids).difference(candidate_costs):
        raise KeyError("candidate-to-OD mapping contains a candidate without cost")
    relevant_choices = {
        od_id: choice for od_id, choice in choices.items() if choice.purpose == purpose
    }
    baseline = {
        od_id: evaluate_choice_set(choice, cost_scale=cost_scale, response=response)
        for od_id, choice in relevant_choices.items()
    }
    current = dict(baseline)
    selected: list[str] = []
    selected_set: set[str] = set()
    remaining = set(candidate_to_od_ids)
    spent = 0.0
    cumulative = 0.0
    steps: list[ChoiceSequenceStep] = []
    relevant_od_ids = {
        candidate_id: tuple(
            dict.fromkeys(
                od_id for od_id in candidate_to_od_ids[candidate_id] if od_id in relevant_choices
            )
        )
        for candidate_id in remaining
    }
    candidates_by_od: dict[str, set[str]] = {}
    for candidate_id, od_ids in relevant_od_ids.items():
        for od_id in od_ids:
            candidates_by_od.setdefault(od_id, set()).add(candidate_id)
    candidate_tie_rank = {
        candidate_id: rank for rank, candidate_id in enumerate(sorted(remaining, reverse=True))
    }
    versions = {candidate_id: 0 for candidate_id in remaining}
    heap: list[tuple[float, float, float, int, int, str]] = []

    def value(evaluation: ODChoiceEvaluation) -> float:
        return float(getattr(evaluation, objective))

    def candidate_marginal(candidate_id: str) -> tuple[float, float] | None:
        cost = float(candidate_costs[candidate_id])
        if cost < 0 or not isfinite(cost):
            raise ValueError(f"invalid candidate cost: {candidate_id}")
        if spent + cost > budget_nzd + 1e-9:
            return None
        frozen_selected = frozenset(selected_set)
        proposed = frozen_selected | {candidate_id}
        marginal = sum(
            value(
                evaluate_choice_set(
                    relevant_choices[od_id],
                    proposed,
                    cost_scale=cost_scale,
                    response=response,
                )
            )
            - value(current[od_id])
            for od_id in relevant_od_ids[candidate_id]
        )
        denominator = cost if cost > 0 else 1e-12
        selection_value = marginal / denominator if score_per_cost else marginal
        return selection_value, marginal

    def push_candidate(candidate_id: str) -> None:
        result = candidate_marginal(candidate_id)
        if result is None:
            return
        selection_value, marginal = result
        cost = float(candidate_costs[candidate_id])
        heapq.heappush(
            heap,
            (
                -selection_value,
                -marginal,
                cost,
                candidate_tie_rank[candidate_id],
                versions[candidate_id],
                candidate_id,
            ),
        )

    for candidate_id in sorted(remaining):
        push_candidate(candidate_id)

    while remaining:
        selected_option: tuple[float, float, str] | None = None
        while heap:
            (
                negative_efficiency,
                negative_marginal,
                cost,
                _,
                version,
                candidate_id,
            ) = heapq.heappop(heap)
            if candidate_id not in remaining or version != versions[candidate_id]:
                continue
            if spent + cost > budget_nzd + 1e-9:
                remaining.remove(candidate_id)
                continue
            selected_option = (-negative_efficiency, -negative_marginal, candidate_id)
            break
        if selected_option is None:
            break
        efficiency, marginal, candidate_id = selected_option
        if marginal <= 1e-12:
            break
        selected.append(candidate_id)
        selected_set.add(candidate_id)
        spent += float(candidate_costs[candidate_id])
        cumulative += marginal
        frozen_selected = frozenset(selected_set)
        affected_od_ids = relevant_od_ids[candidate_id]
        for od_id in affected_od_ids:
            current[od_id] = evaluate_choice_set(
                relevant_choices[od_id],
                frozen_selected,
                cost_scale=cost_scale,
                response=response,
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
        impacted_candidates = {
            impacted_candidate
            for od_id in affected_od_ids
            for impacted_candidate in candidates_by_od.get(od_id, set())
            if impacted_candidate in remaining
        }
        for impacted_candidate in sorted(impacted_candidates):
            versions[impacted_candidate] += 1
            push_candidate(impacted_candidate)
    return tuple(steps)


def pareto_frontier_benefit_cost(
    benefit_by_candidate: Mapping[str, float], cost_by_candidate: Mapping[str, float]
) -> tuple[str, ...]:
    """Return a scalable exact frontier maximizing benefit and minimizing cost."""

    if set(benefit_by_candidate) != set(cost_by_candidate):
        raise ValueError("benefit and cost candidate sets must match")
    groups: dict[float, list[str]] = {}
    for candidate_id in benefit_by_candidate:
        benefit = benefit_by_candidate[candidate_id]
        cost = cost_by_candidate[candidate_id]
        if not all(isfinite(value) and value >= 0 for value in (benefit, cost)):
            raise ValueError("Pareto benefit and cost must be finite and non-negative")
        groups.setdefault(cost, []).append(candidate_id)
    frontier: list[str] = []
    best_at_lower_cost = -1.0
    for cost in sorted(groups):
        ids = groups[cost]
        group_best = max(benefit_by_candidate[candidate_id] for candidate_id in ids)
        if group_best > best_at_lower_cost:
            frontier.extend(
                candidate_id
                for candidate_id in sorted(ids)
                if benefit_by_candidate[candidate_id] == group_best
            )
        best_at_lower_cost = max(best_at_lower_cost, group_best)
    return tuple(frontier)
