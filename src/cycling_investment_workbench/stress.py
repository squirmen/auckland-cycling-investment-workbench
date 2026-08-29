"""Transparent Level of Traffic Stress and continuous comfort impedance.

The categorical rules are an auditable screening implementation informed by
Mekuria, Furth & Nixon (2012), *Low-Stress Bicycling and Network Connectivity*.
They are not a substitute for locally calibrated engineering assessment.  Missing
road attributes are imputed conservatively and reported in the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from .models import Edge, FacilityType, RoadClass


@dataclass(frozen=True, slots=True)
class StressInputs:
    """Road and treatment attributes used by the LTS classifier."""

    road_class: RoadClass
    facility: FacilityType
    speed_kph: float | None
    lanes: int | None
    traffic_volume: float | None
    intersection_stress: int = 1

    @classmethod
    def from_edge(cls, edge: Edge) -> StressInputs:
        return cls(
            edge.road_class,
            edge.facility,
            edge.speed_kph,
            edge.lanes,
            edge.traffic_volume,
            edge.intersection_stress,
        )


@dataclass(frozen=True, slots=True)
class StressResult:
    """LTS classification plus explicit data-imputation provenance."""

    level: int
    segment_level: int
    intersection_level: int
    imputed_fields: tuple[str, ...] = ()


_DEFAULTS: Mapping[RoadClass, tuple[float, int, float]] = {
    RoadClass.MOTORWAY: (100.0, 4, 30_000.0),
    RoadClass.ARTERIAL: (60.0, 4, 15_000.0),
    RoadClass.COLLECTOR: (50.0, 2, 7_000.0),
    RoadClass.LOCAL: (40.0, 2, 3_000.0),
    RoadClass.SERVICE: (30.0, 1, 1_000.0),
    RoadClass.PATH: (20.0, 1, 0.0),
}


def level_of_traffic_stress(inputs: StressInputs) -> StressResult:
    """Classify a link on the conventional four-level LTS scale.

    The final level is the worse of segment and declared intersection stress.
    Protected facilities cannot hide a stressful crossing.
    """

    default_speed, default_lanes, default_volume = _DEFAULTS[inputs.road_class]
    imputed: list[str] = []
    speed = inputs.speed_kph
    if speed is None:
        speed = default_speed
        imputed.append("speed_kph")
    lanes = inputs.lanes
    if lanes is None:
        lanes = default_lanes
        imputed.append("lanes")
    volume = inputs.traffic_volume
    if volume is None:
        volume = default_volume
        imputed.append("traffic_volume")
    if speed <= 0 or lanes < 1 or volume < 0:
        raise ValueError("speed, lanes, and traffic volume must be physically valid")
    if inputs.intersection_stress not in (1, 2, 3, 4):
        raise ValueError("intersection_stress must be in 1..4")

    if inputs.road_class is RoadClass.MOTORWAY:
        segment = 4
    elif inputs.facility in (FacilityType.PROTECTED_LANE, FacilityType.SHARED_PATH):
        segment = 1
    elif inputs.facility is FacilityType.QUIET_STREET:
        segment = 1 if speed <= 30 and volume <= 2_000 else 2 if speed <= 40 else 3
    elif inputs.facility is FacilityType.PAINTED_LANE:
        if speed <= 40 and lanes <= 2 and volume <= 6_000:
            segment = 2
        elif speed <= 50 and lanes <= 3 and volume <= 15_000:
            segment = 3
        else:
            segment = 4
    else:
        if speed <= 30 and lanes <= 2 and volume <= 2_000:
            segment = 1
        elif speed <= 40 and lanes <= 2 and volume <= 4_000:
            segment = 2
        elif speed <= 50 and lanes <= 3 and volume <= 12_000:
            segment = 3
        else:
            segment = 4

    return StressResult(
        level=max(segment, inputs.intersection_stress),
        segment_level=segment,
        intersection_level=inputs.intersection_stress,
        imputed_fields=tuple(imputed),
    )


@dataclass(frozen=True, slots=True)
class ComfortParameters:
    """Continuous generalized-cost parameters, suitable for sensitivity analysis."""

    stress_multipliers: tuple[float, float, float, float] = (1.0, 1.25, 1.8, 3.0)
    uphill_gradient_weight: float = 4.0
    downhill_gradient_weight: float = 0.5
    tunnel_multiplier: float = 1.25
    bridge_multiplier: float = 1.05

    def __post_init__(self) -> None:
        if len(self.stress_multipliers) != 4 or any(
            value < 1 or not isfinite(value) for value in self.stress_multipliers
        ):
            raise ValueError("four finite stress multipliers >= 1 are required")
        if self.uphill_gradient_weight < 0 or self.downhill_gradient_weight < 0:
            raise ValueError("gradient weights must be non-negative")


DEFAULT_COMFORT_PARAMETERS = ComfortParameters()


def comfort_multiplier(
    edge: Edge,
    *,
    reversed: bool = False,
    parameters: ComfortParameters = DEFAULT_COMFORT_PARAMETERS,
) -> float:
    """Return continuous impedance per metre for a directed edge traversal."""

    lts = level_of_traffic_stress(StressInputs.from_edge(edge)).level
    gradient = -edge.gradient if reversed else edge.gradient
    grade_penalty = 1.0 + (
        parameters.uphill_gradient_weight * max(0.0, gradient)
        + parameters.downhill_gradient_weight * max(0.0, -gradient)
    )
    structure_penalty = 1.0
    if edge.tunnel:
        structure_penalty *= parameters.tunnel_multiplier
    if edge.bridge:
        structure_penalty *= parameters.bridge_multiplier
    return parameters.stress_multipliers[lts - 1] * grade_penalty * structure_penalty


def edge_generalized_cost(
    edge: Edge,
    *,
    reversed: bool = False,
    parameters: ComfortParameters = DEFAULT_COMFORT_PARAMETERS,
) -> float:
    """Return length-weighted generalized cycling impedance."""

    return edge.length_m * comfort_multiplier(edge, reversed=reversed, parameters=parameters)
