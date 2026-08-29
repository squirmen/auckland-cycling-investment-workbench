"""Counter-to-network matching and honest predictive validation statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import atan2, degrees, hypot, isfinite, sqrt
from statistics import mean
from typing import Literal

from .models import CounterSite, Direction, Edge, Point
from .topology import DirectedTopology


@dataclass(frozen=True, slots=True)
class CounterMatch:
    """An auditable spatial and directional counter match."""

    counter_id: str
    edge_id: str
    distance: float
    bearing_difference: float | None
    traversal_direction: Literal["forward", "reverse", "both"]


def _edge_points(edge: Edge, topology: DirectedTopology) -> tuple[Point, ...]:
    if edge.geometry:
        return edge.geometry
    u = topology.node(edge.u)
    v = topology.node(edge.v)
    return ((u.x, u.y), (v.x, v.y))


def _point_segment_distance_and_bearing(
    point: Point, start: Point, end: Point
) -> tuple[float, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    squared = dx * dx + dy * dy
    if squared == 0:
        return hypot(point[0] - start[0], point[1] - start[1]), 0.0
    fraction = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / squared),
    )
    projected = (start[0] + fraction * dx, start[1] + fraction * dy)
    distance = hypot(point[0] - projected[0], point[1] - projected[1])
    compass_bearing = (90.0 - degrees(atan2(dy, dx))) % 360.0
    return distance, compass_bearing


def _angle_difference(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _edge_match_measure(
    counter: CounterSite, edge: Edge, topology: DirectedTopology
) -> tuple[float, float | None, Literal["forward", "reverse", "both"]]:
    segments = list(pairwise(_edge_points(edge, topology)))
    closest_distance = float("inf")
    closest_bearing = 0.0
    for start, end in segments:
        distance, bearing = _point_segment_distance_and_bearing((counter.x, counter.y), start, end)
        if distance < closest_distance:
            closest_distance = distance
            closest_bearing = bearing
    if counter.bearing_degrees is None:
        return closest_distance, None, "both" if counter.bidirectional else "forward"
    if counter.bidirectional:
        difference = min(
            _angle_difference(counter.bearing_degrees, closest_bearing),
            _angle_difference(counter.bearing_degrees, (closest_bearing + 180) % 360),
        )
        return closest_distance, difference, "both"
    allowed: list[tuple[float, Literal["forward", "reverse"]]] = []
    if edge.direction in (Direction.BOTH, Direction.FORWARD):
        allowed.append((_angle_difference(counter.bearing_degrees, closest_bearing), "forward"))
    if edge.direction in (Direction.BOTH, Direction.REVERSE):
        allowed.append(
            (_angle_difference(counter.bearing_degrees, (closest_bearing + 180) % 360), "reverse")
        )
    difference, direction = min(allowed)
    return closest_distance, difference, direction


def match_counters(
    counters: Iterable[CounterSite],
    topology: DirectedTopology,
    *,
    max_distance: float = 100.0,
    max_bearing_difference: float = 35.0,
    preferred_edge_ids: Mapping[str, frozenset[str]] | None = None,
) -> tuple[Mapping[str, CounterMatch], tuple[str, ...]]:
    """Match counters to full edge geometry with distance and bearing gates.

    ``preferred_edge_ids`` supports externally audited site-to-link associations;
    when present for a counter, only those exact edges are considered.
    """

    if max_distance < 0 or not 0 <= max_bearing_difference <= 180:
        raise ValueError("invalid counter matching tolerances")
    matches: dict[str, CounterMatch] = {}
    unmatched: list[str] = []
    for counter in sorted(counters, key=lambda value: value.id):
        allowed = (
            preferred_edge_ids[counter.id]
            if preferred_edge_ids is not None and counter.id in preferred_edge_ids
            else frozenset(topology.edges)
        )
        unknown = allowed.difference(topology.edges)
        if unknown:
            raise KeyError(f"preferred match contains unknown edges: {sorted(unknown)}")
        options: list[tuple[float, float, str, Literal["forward", "reverse", "both"]]] = []
        for edge_id in allowed:
            edge = topology.edge(edge_id)
            distance, bearing_difference, direction = _edge_match_measure(counter, edge, topology)
            if distance > max_distance:
                continue
            if bearing_difference is not None and bearing_difference > max_bearing_difference:
                continue
            options.append(
                (
                    distance,
                    bearing_difference if bearing_difference is not None else 0.0,
                    edge_id,
                    direction,
                )
            )
        if not options:
            unmatched.append(counter.id)
            continue
        distance, bearing_difference_value, edge_id, direction = min(options)
        matches[counter.id] = CounterMatch(
            counter.id,
            edge_id,
            distance,
            None if counter.bearing_degrees is None else bearing_difference_value,
            direction,
        )
    return matches, tuple(unmatched)


@dataclass(frozen=True, slots=True)
class ValidationMetrics:
    """Prediction metrics; correlation is never substituted for calibration."""

    n: int
    coverage: float
    mae: float
    rmse: float
    mean_bias: float
    r_squared: float | None
    pearson_r: float | None
    spearman_r: float | None
    calibration_intercept: float | None
    calibration_slope: float | None


def _pearson(first: Sequence[float], second: Sequence[float]) -> float | None:
    first_mean = mean(first)
    second_mean = mean(second)
    numerator = sum(
        (x - first_mean) * (y - second_mean) for x, y in zip(first, second, strict=True)
    )
    first_ss = sum((x - first_mean) ** 2 for x in first)
    second_ss = sum((y - second_mean) ** 2 for y in second)
    if first_ss == 0 or second_ss == 0:
        return None
    return numerator / sqrt(first_ss * second_ss)


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for position in ordered[cursor:end]:
            ranks[position] = rank
        cursor = end
    return ranks


def regression_metrics(
    observed: Sequence[float],
    predicted: Sequence[float],
    *,
    total_reference_count: int | None = None,
) -> ValidationMetrics:
    """Calculate prediction error, association, and calibration statistics.

    ``R²`` is the predictive coefficient ``1 - SSE/SST`` and may legitimately be
    negative.  Calibration fits ``observed = intercept + slope * predicted``.
    """

    if len(observed) != len(predicted) or not observed:
        raise ValueError("observed and predicted must be non-empty and equally sized")
    if any(not isfinite(value) for value in (*observed, *predicted)):
        raise ValueError("validation values must be finite")
    if total_reference_count is None:
        total_reference_count = len(observed)
    if total_reference_count < len(observed):
        raise ValueError("total_reference_count cannot be smaller than matched observations")
    residuals = [
        prediction - observation
        for observation, prediction in zip(observed, predicted, strict=True)
    ]
    mae = mean(abs(value) for value in residuals)
    rmse = sqrt(mean(value * value for value in residuals))
    bias = mean(residuals)
    observed_mean = mean(observed)
    sse = sum(value * value for value in residuals)
    sst = sum((value - observed_mean) ** 2 for value in observed)
    r_squared = None if sst == 0 else 1.0 - sse / sst
    pearson = _pearson(observed, predicted)
    spearman = _pearson(_average_ranks(observed), _average_ranks(predicted))
    predicted_mean = mean(predicted)
    predicted_ss = sum((value - predicted_mean) ** 2 for value in predicted)
    if predicted_ss == 0:
        calibration_slope = None
        calibration_intercept = None
    else:
        calibration_slope = (
            sum(
                (prediction - predicted_mean) * (observation - observed_mean)
                for observation, prediction in zip(observed, predicted, strict=True)
            )
            / predicted_ss
        )
        calibration_intercept = observed_mean - calibration_slope * predicted_mean
    return ValidationMetrics(
        n=len(observed),
        coverage=len(observed) / total_reference_count if total_reference_count else 0.0,
        mae=mae,
        rmse=rmse,
        mean_bias=bias,
        r_squared=r_squared,
        pearson_r=pearson,
        spearman_r=spearman,
        calibration_intercept=calibration_intercept,
        calibration_slope=calibration_slope,
    )


def aggregate_site_counts(
    values_by_counter: Mapping[str, float], groups: Mapping[str, str]
) -> Mapping[str, float]:
    """Aggregate directions/devices to audited count sites before validation."""

    missing = set(values_by_counter).difference(groups)
    if missing:
        raise KeyError(f"counter groups missing for: {sorted(missing)}")
    totals: dict[str, float] = {}
    for counter_id, value in values_by_counter.items():
        if value < 0 or not isfinite(value):
            raise ValueError("counter values must be finite and non-negative")
        site_id = groups[counter_id]
        totals[site_id] = totals.get(site_id, 0.0) + value
    return totals
