"""Epistemic parameter sampling and decision-rank stability.

Latin-hypercube sampling follows McKay, Beckman & Conover (1979), *Technometrics*
21(2), 239-245.  It is intended for declared uncertain model parameters; it does
not pretend that a complete OD table is an IID survey sample.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import exp, isfinite, log, sqrt
from random import Random
from statistics import mean
from typing import Literal

Distribution = Literal["uniform", "loguniform", "triangular"]

MATERIAL_UNCERTAINTY_DIMENSIONS = (
    "suppression_factor",
    "pct_uptake_factor",
    "route_choice_factor",
    "stress_penalty_factor",
    "topology_coverage_factor",
    "capital_cost_factor",
    "maintenance_cost_factor",
    "renewal_cost_factor",
    "benefit_value_factor",
    "discount_rate",
    "ebike_share",
    "demand_response_elasticity",
)


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """A bounded uncertain parameter and its explicit sampling distribution."""

    name: str
    lower: float
    upper: float
    distribution: Distribution = "uniform"
    mode: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("parameter name must be non-empty")
        if not (isfinite(self.lower) and isfinite(self.upper) and self.lower < self.upper):
            raise ValueError("parameter bounds must be finite and increasing")
        if self.distribution == "loguniform" and self.lower <= 0:
            raise ValueError("loguniform parameters require a positive lower bound")
        if self.distribution == "triangular":
            if self.mode is None or not self.lower <= self.mode <= self.upper:
                raise ValueError("triangular parameters require a mode within bounds")
        elif self.mode is not None:
            raise ValueError("mode is only valid for a triangular distribution")

    def inverse_cdf(self, quantile: float) -> float:
        """Transform a unit-interval quantile to the declared distribution."""

        if not 0 <= quantile <= 1:
            raise ValueError("quantile must be in [0, 1]")
        if self.distribution == "uniform":
            return self.lower + quantile * (self.upper - self.lower)
        if self.distribution == "loguniform":
            return exp(log(self.lower) + quantile * (log(self.upper) - log(self.lower)))
        assert self.mode is not None
        fraction = (self.mode - self.lower) / (self.upper - self.lower)
        if quantile < fraction:
            return self.lower + sqrt(
                quantile * (self.upper - self.lower) * (self.mode - self.lower)
            )
        return self.upper - sqrt(
            (1 - quantile) * (self.upper - self.lower) * (self.upper - self.mode)
        )


def latin_hypercube(
    parameters: Sequence[ParameterSpec], sample_count: int, *, seed: int = 0
) -> tuple[Mapping[str, float], ...]:
    """Generate deterministic Latin-hypercube parameter draws."""

    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    if len({parameter.name for parameter in parameters}) != len(parameters):
        raise ValueError("parameter names must be unique")
    random = Random(seed)
    columns: dict[str, list[float]] = {}
    for parameter in parameters:
        quantiles = [(stratum + random.random()) / sample_count for stratum in range(sample_count)]
        random.shuffle(quantiles)
        columns[parameter.name] = [parameter.inverse_cdf(value) for value in quantiles]
    return tuple(
        {parameter.name: columns[parameter.name][row] for parameter in parameters}
        for row in range(sample_count)
    )


def validate_material_uncertainty_design(
    parameters: Sequence[ParameterSpec],
) -> tuple[str, ...]:
    """Require one explicit parameter for every material CIW uncertainty source.

    Returning the stable dimension order makes it straightforward for manifests
    and tabular exports to retain a documented column order.
    """

    names = tuple(parameter.name for parameter in parameters)
    if len(set(names)) != len(names):
        raise ValueError("uncertainty parameter names must be unique")
    expected = set(MATERIAL_UNCERTAINTY_DIMENSIONS)
    missing = expected.difference(names)
    unexpected = set(names).difference(expected)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise ValueError("material uncertainty design is incomplete: " + "; ".join(details))
    return MATERIAL_UNCERTAINTY_DIMENSIONS


def evaluate_samples(
    samples: Iterable[Mapping[str, float]],
    evaluator: Callable[[Mapping[str, float]], Mapping[str, float]],
) -> tuple[Mapping[str, float], ...]:
    """Evaluate candidate scores for every parameter draw."""

    return tuple(evaluator(sample) for sample in samples)


def quantile(values: Sequence[float], probability: float) -> float:
    """Linearly interpolated empirical quantile."""

    if not values:
        raise ValueError("cannot calculate a quantile of no values")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(len(ordered) - 1, lower_index + 1)
    fraction = position - lower_index
    return ordered[lower_index] * (1 - fraction) + ordered[upper_index] * fraction


@dataclass(frozen=True, slots=True)
class CandidateRankStability:
    """Score and rank distribution for one candidate."""

    candidate_id: str
    mean_score: float
    score_p05: float
    score_p50: float
    score_p95: float
    mean_rank: float
    top_k_probability: float


@dataclass(frozen=True, slots=True)
class RankStabilityResult:
    """Candidate summaries and stability against a declared baseline ranking."""

    candidates: tuple[CandidateRankStability, ...]
    baseline_order: tuple[str, ...]
    mean_top_k_jaccard: float
    mean_kendall_tau: float


@dataclass(frozen=True, slots=True)
class FrontierStabilityResult:
    """Membership stability for non-dominated sets across parameter draws."""

    baseline_frontier: tuple[str, ...]
    membership_probability: Mapping[str, float]
    mean_jaccard: float


def frontier_stability(
    frontiers_by_draw: Sequence[Iterable[str]],
    *,
    candidate_ids: Iterable[str],
    baseline_frontier: Iterable[str],
) -> FrontierStabilityResult:
    """Summarise how often each candidate remains non-dominated."""

    ids = tuple(sorted(set(candidate_ids)))
    if not ids:
        raise ValueError("candidate_ids must not be empty")
    if not frontiers_by_draw:
        raise ValueError("at least one frontier draw is required")
    id_set = set(ids)
    baseline = tuple(sorted(set(baseline_frontier)))
    if not baseline or not set(baseline) <= id_set:
        raise ValueError("baseline frontier must be a non-empty subset of candidate_ids")
    draws = tuple(set(frontier) for frontier in frontiers_by_draw)
    if any(not frontier or not frontier <= id_set for frontier in draws):
        raise ValueError("every sampled frontier must be a non-empty candidate subset")
    baseline_set = set(baseline)
    probability = {
        candidate_id: sum(candidate_id in frontier for frontier in draws) / len(draws)
        for candidate_id in ids
    }
    jaccards = [len(baseline_set & frontier) / len(baseline_set | frontier) for frontier in draws]
    return FrontierStabilityResult(baseline, probability, mean(jaccards))


def _rank(scores: Mapping[str, float]) -> tuple[str, ...]:
    return tuple(sorted(scores, key=lambda key: (-scores[key], key)))


def _kendall_tau(first: Sequence[str], second: Sequence[str]) -> float:
    if len(first) < 2:
        return 1.0
    second_position = {candidate_id: index for index, candidate_id in enumerate(second)}
    concordant = 0
    discordant = 0
    for i, first_id in enumerate(first):
        for second_id in first[i + 1 :]:
            if second_position[first_id] < second_position[second_id]:
                concordant += 1
            else:
                discordant += 1
    return (concordant - discordant) / (concordant + discordant)


def rank_stability(
    scores_by_draw: Sequence[Mapping[str, float]],
    *,
    top_k: int = 10,
    baseline_scores: Mapping[str, float] | None = None,
) -> RankStabilityResult:
    """Summarise score intervals, top-k inclusion, Jaccard, and Kendall stability."""

    if not scores_by_draw:
        raise ValueError("at least one score draw is required")
    ids = set(scores_by_draw[0])
    if not ids or any(set(draw) != ids for draw in scores_by_draw):
        raise ValueError("all score draws must contain the same candidates")
    if not 1 <= top_k <= len(ids):
        raise ValueError("top_k must be between one and the candidate count")
    if baseline_scores is None:
        baseline_scores = {
            candidate_id: mean(draw[candidate_id] for draw in scores_by_draw)
            for candidate_id in ids
        }
    if set(baseline_scores) != ids:
        raise ValueError("baseline scores must contain exactly the sampled candidates")
    baseline_order = _rank(baseline_scores)
    baseline_top = set(baseline_order[:top_k])
    draw_orders = [_rank(draw) for draw in scores_by_draw]
    rank_maps = [
        {candidate_id: rank + 1 for rank, candidate_id in enumerate(order)} for order in draw_orders
    ]

    summaries: list[CandidateRankStability] = []
    for candidate_id in sorted(ids):
        values = [draw[candidate_id] for draw in scores_by_draw]
        ranks = [ranking[candidate_id] for ranking in rank_maps]
        summaries.append(
            CandidateRankStability(
                candidate_id,
                mean(values),
                quantile(values, 0.05),
                quantile(values, 0.50),
                quantile(values, 0.95),
                mean(ranks),
                sum(rank <= top_k for rank in ranks) / len(ranks),
            )
        )
    jaccards = []
    taus = []
    for order in draw_orders:
        draw_top = set(order[:top_k])
        jaccards.append(len(baseline_top & draw_top) / len(baseline_top | draw_top))
        taus.append(_kendall_tau(baseline_order, order))
    return RankStabilityResult(
        tuple(summaries),
        baseline_order,
        mean(jaccards),
        mean(taus),
    )
