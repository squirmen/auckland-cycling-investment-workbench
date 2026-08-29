"""Cycling propensity, confidentiality intervals, and constrained scenarios.

The propensity equations follow the published Propensity to Cycle Tool functional
form (Lovelace et al., 2017, *Journal of Transport and Land Use*, 10(1),
doi:10.5198/jtlu.2016.862; and the PCT 2020 manual).  Scenario allocation is kept
separate from propensity so a policy target is never silently presented as a
behavioural prediction.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import exp, isfinite, sqrt
from random import Random
from typing import Literal

from .models import ScenarioAllocation

PCT_MAXIMUM_DISTANCE_KM = 30.0


@dataclass(frozen=True, slots=True)
class PCTFeatures:
    """Route attributes expected by the PCT cycling propensity equation."""

    distance_km: float
    gradient_percent: float

    def __post_init__(self) -> None:
        if not isfinite(self.distance_km) or self.distance_km < 0:
            raise ValueError("distance_km must be finite and non-negative")
        if not isfinite(self.gradient_percent) or self.gradient_percent < 0:
            raise ValueError("gradient_percent must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PCTCoefficients:
    """Coefficients for the documented PCT distance/hilliness logit."""

    intercept: float
    distance: float
    sqrt_distance: float
    distance_squared: float
    gradient: float
    gradient_center: float
    distance_gradient: float
    sqrt_distance_gradient: float
    name: str = "custom"


PCT_2020_GOVERNMENT_TARGET = PCTCoefficients(
    -4.018,
    -0.6369,
    1.988,
    0.008775,
    -0.2555,
    0.78,
    0.02006,
    -0.1234,
    "government_target_2020",
)
PCT_2020_GO_DUTCH = PCTCoefficients(
    -4.018 + 2.550,
    -0.6369 - 0.08036,
    1.988,
    0.008775,
    -0.2555,
    0.78,
    0.02006,
    -0.1234,
    "go_dutch_2020",
)
PCT_2020_EBIKE = PCTCoefficients(
    -4.018 + 2.550,
    -0.6369 - 0.08036 + 0.05509,
    1.988,
    0.008775 - 0.0002950,
    -0.2555 + 0.1812,
    0.78,
    0.02006,
    -0.1234,
    "ebike_2020",
)


def logistic(value: float) -> float:
    """Numerically stable logistic transform."""

    if value >= 0:
        z = exp(-value)
        return 1.0 / (1.0 + z)
    z = exp(value)
    return z / (1.0 + z)


def pct_linear_predictor(
    features: PCTFeatures,
    coefficients: PCTCoefficients,
    *,
    maximum_distance_km: float = PCT_MAXIMUM_DISTANCE_KM,
) -> float:
    """Evaluate the published PCT equation with its explicit 30 km distance cap.

    Every published 2020 term is evaluated explicitly for every scenario,
    including e-bike, using distance capped at the named 30-km maximum.
    """

    if not isfinite(maximum_distance_km) or maximum_distance_km <= 0:
        raise ValueError("maximum_distance_km must be finite and positive")
    distance = min(features.distance_km, maximum_distance_km)
    root_distance = sqrt(distance)
    centred_gradient = features.gradient_percent - coefficients.gradient_center
    return (
        coefficients.intercept
        + coefficients.distance * distance
        + coefficients.sqrt_distance * root_distance
        + coefficients.distance_squared * distance * distance
        + coefficients.gradient * centred_gradient
        + coefficients.distance_gradient * distance * centred_gradient
        + coefficients.sqrt_distance_gradient * root_distance * centred_gradient
    )


def pct_probability(
    features: PCTFeatures,
    coefficients: PCTCoefficients,
    *,
    maximum_distance_km: float = PCT_MAXIMUM_DISTANCE_KM,
) -> float:
    """Return PCT scenario cycling probability for one OD relation."""

    return logistic(
        pct_linear_predictor(
            features,
            coefficients,
            maximum_distance_km=maximum_distance_km,
        )
    )


@dataclass(frozen=True, slots=True)
class CountInterval:
    """An explicit interval for a confidentiality-treated published count.

    ``point`` is an analysis choice, not a recovered confidential value.  Results
    should normally be rerun at ``lower``, ``point``, and ``upper``.
    """

    lower: float
    upper: float
    point: float
    treatment: str = "none"

    def __post_init__(self) -> None:
        if not (0 <= self.lower <= self.point <= self.upper):
            raise ValueError("count interval must satisfy 0 <= lower <= point <= upper")


def interpret_censored_count(
    published: float | None,
    *,
    suppressed: bool = False,
    rounding_base: int = 3,
    suppression_upper: float = 5.0,
    point_strategy: Literal["published", "midpoint", "lower", "upper"] | None = None,
) -> CountInterval:
    """Represent 2023 fixed-random-rounded or explicitly suppressed counts.

    Stats NZ fixed random rounding to base three permits an original count to
    differ from a published numeric value by up to two.  A published numeric zero
    therefore supports ``[0, 2]`` and is not a suppression marker.  Callers must
    pass ``suppressed=True`` (and no numeric value) for a suppressed table cell;
    the 2023 sensitive-table rule then supports ``[0, 5]`` by default.
    """

    if rounding_base < 1:
        raise ValueError("rounding_base must be positive")
    if not isfinite(suppression_upper) or suppression_upper < 0:
        raise ValueError("suppression_upper must be finite and non-negative")
    if suppressed:
        if published is not None:
            raise ValueError("a suppressed cell must not also have a numeric published value")
        lower, upper = 0.0, suppression_upper
        treatment = "suppressed_below_6"
        strategy = point_strategy or "midpoint"
    else:
        if published is None or published < 0 or not isfinite(published):
            raise ValueError("an unsuppressed cell requires a finite non-negative value")
        maximum_error = float(rounding_base - 1)
        lower = max(0.0, published - maximum_error)
        upper = published + maximum_error
        treatment = f"fixed_random_rounded_base_{rounding_base}"
        strategy = point_strategy or "published"
    if strategy == "published" and published is None:
        raise ValueError("point_strategy='published' is invalid for a suppressed cell")
    choices = {
        "published": (
            min(max(published, lower), upper) if published is not None else (lower + upper) / 2.0
        ),
        "midpoint": (lower + upper) / 2.0,
        "lower": lower,
        "upper": upper,
    }
    return CountInterval(lower, upper, choices[strategy], treatment)


@dataclass(frozen=True, slots=True)
class ScenarioUnit:
    """Inputs for a target-constrained cycling scenario."""

    id: str
    eligible: float
    observed: CountInterval
    features: PCTFeatures

    def __post_init__(self) -> None:
        if self.eligible < 0 or not isfinite(self.eligible):
            raise ValueError("eligible must be finite and non-negative")
        if self.observed.point > self.eligible + 1e-9:
            raise ValueError("observed point estimate cannot exceed eligible")


def pct_scenario_counts(
    units: Iterable[ScenarioUnit], coefficients: PCTCoefficients
) -> Mapping[str, float]:
    """Return total scenario counts, capped and never below observed estimates."""

    result: dict[str, float] = {}
    for unit in units:
        predicted = unit.eligible * pct_probability(unit.features, coefficients)
        result[unit.id] = min(unit.eligible, max(unit.observed.point, predicted))
    return result


def _capped_proportional_allocation(
    capacities: Mapping[str, float], weights: Mapping[str, float], target: float
) -> dict[str, float]:
    """Water-fill ``target`` proportionally while respecting individual capacities."""

    allocation = {key: 0.0 for key in capacities}
    active = {key for key, capacity in capacities.items() if capacity > 0}
    remaining = min(target, sum(capacities.values()))
    tolerance = max(1e-10, remaining * 1e-12)
    while active and remaining > tolerance:
        total_weight = sum(max(0.0, weights[key]) for key in active)
        shares = {
            key: (
                remaining * max(0.0, weights[key]) / total_weight
                if total_weight > 0
                else remaining / len(active)
            )
            for key in active
        }
        saturated: set[str] = set()
        distributed = 0.0
        for key in sorted(active):
            room = capacities[key] - allocation[key]
            amount = min(room, shares[key])
            allocation[key] += amount
            distributed += amount
            if room <= shares[key] + tolerance:
                saturated.add(key)
        remaining -= distributed
        active.difference_update(saturated)
        if distributed <= tolerance:
            break
    return allocation


def default_distance_decay(distance_km: float) -> float:
    """Neutral through 12 km, followed by a documented 5 km exponential decay."""

    return 1.0 if distance_km <= 12.0 else exp(-(distance_km - 12.0) / 5.0)


def allocate_target_scenario(
    units: Sequence[ScenarioUnit],
    target_share: float,
    *,
    coefficients: PCTCoefficients = PCT_2020_EBIKE,
    distance_decay: Callable[[float], float] = default_distance_decay,
) -> ScenarioAllocation:
    """Allocate additional cycling to meet an explicit aggregate target.

    Weights are remaining eligible demand times PCT propensity times a declared
    distance-decay function.  Iterative water filling guarantees non-negative
    allocations, individual capacity constraints, and target conservation.
    """

    if not 0 <= target_share <= 1:
        raise ValueError("target_share must be in [0, 1]")
    if len({unit.id for unit in units}) != len(units):
        raise ValueError("scenario unit ids must be unique")

    eligible_total = sum(unit.eligible for unit in units)
    observed_total = sum(unit.observed.point for unit in units)
    requested = max(0.0, target_share * eligible_total - observed_total)
    return allocate_additional_scenario(
        units,
        requested,
        coefficients=coefficients,
        distance_decay=distance_decay,
    )


def allocate_additional_scenario(
    units: Sequence[ScenarioUnit],
    target_additional: float,
    *,
    coefficients: PCTCoefficients = PCT_2020_EBIKE,
    distance_decay: Callable[[float], float] = default_distance_decay,
) -> ScenarioAllocation:
    """Allocate an externally denominated additional-cycling target.

    This form is used when a complete declared source-market denominator is
    broader than the spatialized route sample.  Unallocatable demand is retained
    explicitly instead of shrinking the target to the routable subset.
    """

    if not isfinite(target_additional) or target_additional < 0:
        raise ValueError("target_additional must be finite and non-negative")
    if len({unit.id for unit in units}) != len(units):
        raise ValueError("scenario unit ids must be unique")
    capacities = {unit.id: max(0.0, unit.eligible - unit.observed.point) for unit in units}
    weights = {
        unit.id: capacities[unit.id]
        * pct_probability(unit.features, coefficients)
        * max(0.0, distance_decay(unit.features.distance_km))
        for unit in units
    }
    allocation = _capped_proportional_allocation(capacities, weights, target_additional)
    achieved = sum(allocation.values())
    return ScenarioAllocation(
        additional_by_od=allocation,
        target_additional=target_additional,
        achieved_additional=achieved,
        unallocated=max(0.0, target_additional - achieved),
    )


def censored_total_bounds(units: Iterable[ScenarioUnit]) -> tuple[float, float, float]:
    """Return lower, point, and upper totals for disclosure-controlled counts."""

    intervals = [unit.observed for unit in units]
    return (
        sum(value.lower for value in intervals),
        sum(value.point for value in intervals),
        sum(value.upper for value in intervals),
    )


class DemandConstraintError(ValueError):
    """Raised when confidentiality intervals and published margins are infeasible."""


@dataclass(frozen=True, slots=True)
class ConfidentialODCell:
    """One published OD cell with an explicit FRR3 or suppression state."""

    id: str
    origin_zone: str
    destination_zone: str
    eligible: float | CountInterval
    published_cycle: float | None
    suppressed: bool

    def __post_init__(self) -> None:
        if not self.id or not self.origin_zone or not self.destination_zone:
            raise ValueError("confidential OD identifiers must be non-empty")
        eligible = self.eligible_interval
        if eligible.upper < 0:
            raise ValueError("eligible OD demand must be non-negative")
        if self.suppressed and self.published_cycle is not None:
            raise ValueError("suppressed OD cells must not carry a numeric value")
        if not self.suppressed and self.published_cycle is None:
            raise ValueError("unsuppressed OD cells require a numeric value")

    @property
    def eligible_interval(self) -> CountInterval:
        if isinstance(self.eligible, CountInterval):
            return self.eligible
        if not isfinite(self.eligible) or self.eligible < 0:
            raise ValueError("eligible OD demand must be finite and non-negative")
        return CountInterval(
            self.eligible,
            self.eligible,
            self.eligible,
            "exact_or_prepared_point",
        )

    @property
    def cycle_interval(self) -> CountInterval:
        interval = interpret_censored_count(
            self.published_cycle,
            suppressed=self.suppressed,
            point_strategy="lower" if self.suppressed else "published",
        )
        eligible = self.eligible_interval
        if interval.lower > eligible.upper + 1e-9:
            raise ValueError("bicycle lower bound exceeds eligible upper bound")
        upper = min(interval.upper, eligible.upper)
        lower = min(interval.lower, upper)
        point = min(max(interval.point, lower), upper, eligible.point)
        return CountInterval(lower, upper, point, interval.treatment)

    def draw_joint_counts(
        self, *, eligible_fraction: float, bicycle_fraction: float
    ) -> tuple[float, float]:
        """Draw compatible interval values with bicycle capped by eligible demand."""

        if not 0 <= eligible_fraction <= 1 or not 0 <= bicycle_fraction <= 1:
            raise ValueError("draw fractions must be in [0, 1]")
        eligible = self.eligible_interval
        bicycle = self.cycle_interval
        eligible_draw = eligible.lower + eligible_fraction * (eligible.upper - eligible.lower)
        bicycle_draw = bicycle.lower + bicycle_fraction * (bicycle.upper - bicycle.lower)
        return eligible_draw, min(bicycle_draw, eligible_draw)


@dataclass(frozen=True, slots=True)
class ConstraintDiagnostic:
    """Machine-readable demand constraint or soft-validation diagnostic."""

    severity: Literal["warning", "error"]
    code: str
    relation_id: str
    message: str
    residual: float | None = None


@dataclass(frozen=True, slots=True)
class ConstrainedODAllocation:
    """Origin-constrained cell estimates and destination-margin validation."""

    cycle_by_od: Mapping[str, float]
    origin_target_by_zone: Mapping[str, float]
    destination_total_by_zone: Mapping[str, float]
    destination_residual_by_zone: Mapping[str, float]
    diagnostics: tuple[ConstraintDiagnostic, ...]

    @property
    def feasible(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


def _bounded_adjustment(
    point: Mapping[str, float],
    lower: Mapping[str, float],
    upper: Mapping[str, float],
    weights: Mapping[str, float],
    target: float,
) -> dict[str, float]:
    result = dict(point)
    difference = target - sum(result.values())
    if difference > 1e-12:
        capacities = {key: upper[key] - result[key] for key in result}
        additions = _capped_proportional_allocation(capacities, weights, difference)
        for key, value in additions.items():
            result[key] += value
    elif difference < -1e-12:
        capacities = {key: result[key] - lower[key] for key in result}
        reductions = _capped_proportional_allocation(
            capacities,
            {key: max(result[key], weights[key]) for key in result},
            -difference,
        )
        for key, value in reductions.items():
            result[key] -= value
    return result


def allocate_suppressed_od_to_origin_margins(
    cells: Sequence[ConfidentialODCell],
    origin_margins: Mapping[str, CountInterval],
    *,
    destination_margins: Mapping[str, CountInterval] | None = None,
    fail_on_infeasible: bool = True,
) -> ConstrainedODAllocation:
    """Allocate suppressed OD cells within bounds using origin SA2 margins.

    Origin margins are the hard constraints because Stats NZ's residence and
    workplace universes are not equal.  Destination margins are retained as a
    soft validation comparison and are never silently forced to match.
    Suppressed cells begin at zero and receive residual mass in proportion to
    stated OD demand; the function never assigns an independent 2.5 midpoint to
    each ``-999`` cell.
    """

    if len({cell.id for cell in cells}) != len(cells):
        raise ValueError("confidential OD cell ids must be unique")
    grouped: dict[str, list[ConfidentialODCell]] = defaultdict(list)
    for cell in cells:
        grouped[cell.origin_zone].append(cell)
    diagnostics: list[ConstraintDiagnostic] = []
    allocation: dict[str, float] = {}
    origin_targets: dict[str, float] = {}
    for origin_zone, origin_cells in sorted(grouped.items()):
        margin = origin_margins.get(origin_zone)
        if margin is None:
            diagnostics.append(
                ConstraintDiagnostic(
                    "error",
                    "missing_origin_margin",
                    origin_zone,
                    "no published origin bicycle margin is available",
                )
            )
            continue
        intervals = {cell.id: cell.cycle_interval for cell in origin_cells}
        lower = {key: interval.lower for key, interval in intervals.items()}
        upper = {key: interval.upper for key, interval in intervals.items()}
        point = {key: interval.point for key, interval in intervals.items()}
        weights = {cell.id: max(cell.eligible_interval.point, 1e-9) for cell in origin_cells}
        feasible_lower = max(sum(lower.values()), margin.lower)
        feasible_upper = min(sum(upper.values()), margin.upper)
        if feasible_lower > feasible_upper + 1e-9:
            diagnostics.append(
                ConstraintDiagnostic(
                    "error",
                    "infeasible_origin_bounds",
                    origin_zone,
                    "OD cell bounds do not overlap the published origin margin interval",
                    feasible_lower - feasible_upper,
                )
            )
            continue
        target = min(max(margin.point, feasible_lower), feasible_upper)
        if abs(target - margin.point) > 1e-9:
            diagnostics.append(
                ConstraintDiagnostic(
                    "warning",
                    "origin_point_adjusted_within_interval",
                    origin_zone,
                    "published margin point was adjusted within its FRR3 interval",
                    target - margin.point,
                )
            )
        allocated = dict(point)
        difference = target - sum(allocated.values())
        if difference > 1e-12:
            suppressed_ids = {cell.id for cell in origin_cells if cell.suppressed}
            suppressed_capacity = sum(
                upper[cell_id] - allocated[cell_id] for cell_id in suppressed_ids
            )
            suppressed_target = min(difference, suppressed_capacity)
            if suppressed_target > 0:
                additions = _capped_proportional_allocation(
                    {cell_id: upper[cell_id] - allocated[cell_id] for cell_id in suppressed_ids},
                    {cell_id: weights[cell_id] for cell_id in suppressed_ids},
                    suppressed_target,
                )
                for cell_id, value in additions.items():
                    allocated[cell_id] += value
        allocated = _bounded_adjustment(allocated, lower, upper, weights, target)
        residual = target - sum(allocated.values())
        if abs(residual) > 1e-7:
            diagnostics.append(
                ConstraintDiagnostic(
                    "error",
                    "origin_allocation_residual",
                    origin_zone,
                    "bounded allocation did not conserve the origin target",
                    residual,
                )
            )
        allocation.update(allocated)
        origin_targets[origin_zone] = target

    destination_totals: dict[str, float] = defaultdict(float)
    cell_by_id = {cell.id: cell for cell in cells}
    for cell_id, value in allocation.items():
        destination_totals[cell_by_id[cell_id].destination_zone] += value
    destination_residuals: dict[str, float] = {}
    if destination_margins is not None:
        for destination_zone, margin in sorted(destination_margins.items()):
            actual = destination_totals.get(destination_zone, 0.0)
            residual = actual - margin.point
            destination_residuals[destination_zone] = residual
            if not margin.lower - 1e-9 <= actual <= margin.upper + 1e-9:
                diagnostics.append(
                    ConstraintDiagnostic(
                        "warning",
                        "destination_margin_outside_interval",
                        destination_zone,
                        "origin-constrained OD total is outside the workplace margin interval",
                        residual,
                    )
                )
    result = ConstrainedODAllocation(
        dict(sorted(allocation.items())),
        dict(sorted(origin_targets.items())),
        dict(sorted(destination_totals.items())),
        dict(sorted(destination_residuals.items())),
        tuple(diagnostics),
    )
    if fail_on_infeasible and not result.feasible:
        errors = "; ".join(
            f"{item.code}:{item.relation_id}" for item in diagnostics if item.severity == "error"
        )
        raise DemandConstraintError(f"confidential OD allocation is infeasible: {errors}")
    return result


@dataclass(frozen=True, slots=True)
class SpatialSupport:
    """A weighted within-zone origin or destination support point."""

    id: str
    zone_id: str
    x: float
    y: float
    weight: float
    source: str

    def __post_init__(self) -> None:
        if not self.id or not self.zone_id or not self.source:
            raise ValueError("support identifiers and source must be non-empty")
        if not all(isfinite(value) for value in (self.x, self.y, self.weight)):
            raise ValueError("support coordinates and weights must be finite")
        if self.weight < 0:
            raise ValueError("support weight must be non-negative")


@dataclass(frozen=True, slots=True)
class DisaggregatedODFlow:
    """A spatial OD allocation carrying its declared sampling probability."""

    id: str
    source_cell_id: str
    origin_support_id: str
    destination_support_id: str
    origin_x: float
    origin_y: float
    destination_x: float
    destination_y: float
    eligible: float
    cycle: float
    purpose: str
    selection_probability: float
    draw_count: int
    total_draws: int


def _normalised_supports(
    supports: Sequence[SpatialSupport], *, zone_id: str, role: str
) -> tuple[tuple[SpatialSupport, ...], tuple[float, ...]]:
    available = tuple(
        sorted((item for item in supports if item.zone_id == zone_id), key=lambda x: x.id)
    )
    if not available:
        raise DemandConstraintError(f"{role} zone {zone_id} has no spatial supports")
    positive = tuple(item for item in available if item.weight > 0)
    selected = positive or available
    total = sum(item.weight for item in selected)
    probabilities = (
        tuple(item.weight / total for item in selected)
        if total > 0
        else tuple(1 / len(selected) for _ in selected)
    )
    return selected, probabilities


def disaggregate_od_to_weighted_supports(
    cells: Sequence[ConfidentialODCell],
    allocation: Mapping[str, float],
    origin_supports: Sequence[SpatialSupport],
    destination_supports: Sequence[SpatialSupport],
    *,
    purpose: str,
    samples_per_od: int | None = 25,
    seed: int = 0,
) -> tuple[DisaggregatedODFlow, ...]:
    """Disaggregate all OD cells, retaining intrazonals and declared weights.

    When a support cross-product exceeds ``samples_per_od``, independent
    probability-proportional draws are made with replacement and repeated pairs
    are aggregated.  Allocated demand is divided by the exact draw frequency, so
    each source OD total is conserved and the probability design is auditable.
    """

    if not purpose:
        raise ValueError("purpose must be non-empty")
    if samples_per_od is not None and samples_per_od < 1:
        raise ValueError("samples_per_od must be positive or None")
    rng = Random(seed)
    result: list[DisaggregatedODFlow] = []
    for cell in sorted(cells, key=lambda item: item.id):
        if cell.id not in allocation:
            raise DemandConstraintError(f"allocation is missing OD cell {cell.id}")
        origins, origin_probabilities = _normalised_supports(
            origin_supports, zone_id=cell.origin_zone, role="origin"
        )
        destinations, destination_probabilities = _normalised_supports(
            destination_supports,
            zone_id=cell.destination_zone,
            role="destination",
        )
        pair_count = len(origins) * len(destinations)
        if samples_per_od is None or pair_count <= samples_per_od:
            pairs = [
                (origin_index, destination_index, 1, pair_count)
                for origin_index in range(len(origins))
                for destination_index in range(len(destinations))
            ]
        else:
            origin_draws = rng.choices(
                range(len(origins)), weights=origin_probabilities, k=samples_per_od
            )
            destination_draws = rng.choices(
                range(len(destinations)),
                weights=destination_probabilities,
                k=samples_per_od,
            )
            counts = Counter(zip(origin_draws, destination_draws, strict=True))
            pairs = [
                (origin_index, destination_index, draw_count, samples_per_od)
                for (origin_index, destination_index), draw_count in sorted(counts.items())
            ]
        for origin_index, destination_index, draw_count, total_draws in pairs:
            origin = origins[origin_index]
            destination = destinations[destination_index]
            selection_probability = (
                origin_probabilities[origin_index] * destination_probabilities[destination_index]
            )
            allocation_share = (
                selection_probability
                if samples_per_od is None or pair_count <= samples_per_od
                else draw_count / total_draws
            )
            result.append(
                DisaggregatedODFlow(
                    f"{cell.id}:{origin.id}:{destination.id}",
                    cell.id,
                    origin.id,
                    destination.id,
                    origin.x,
                    origin.y,
                    destination.x,
                    destination.y,
                    cell.eligible_interval.point * allocation_share,
                    allocation[cell.id] * allocation_share,
                    purpose,
                    selection_probability,
                    draw_count,
                    total_draws,
                )
            )
    return tuple(result)
