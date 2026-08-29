"""Core, dependency-free domain models for the investment workbench.

The models deliberately keep identifiers from the source network.  In particular,
an :class:`Edge` is not inferred from geometric proximity: it represents a known
connection between two known network nodes, on a declared vertical layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from itertools import pairwise
from math import hypot, isfinite


class Direction(str, Enum):
    """Permitted travel relative to an edge's ``u`` to ``v`` orientation."""

    BOTH = "both"
    FORWARD = "forward"
    REVERSE = "reverse"


class FacilityType(str, Enum):
    """Cycling treatment relevant to comfort and traffic stress."""

    NONE = "none"
    MIXED_TRAFFIC = "mixed_traffic"
    PAINTED_LANE = "painted_lane"
    PROTECTED_LANE = "protected_lane"
    SHARED_PATH = "shared_path"
    QUIET_STREET = "quiet_street"


class RoadClass(str, Enum):
    """Small, portable road hierarchy used by the stress model."""

    MOTORWAY = "motorway"
    ARTERIAL = "arterial"
    COLLECTOR = "collector"
    LOCAL = "local"
    SERVICE = "service"
    PATH = "path"


Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Node:
    """A source-identified network node.

    Importers must prefer source node identifiers (for example OSM node IDs)
    over rounded coordinates. ``layer`` is optional node metadata; physical-edge
    layer, bridge, and tunnel attributes should govern structure auditing without
    splitting an explicitly shared source node.
    """

    id: str
    x: float
    y: float
    layer: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("node id must be non-empty")
        if not (isfinite(self.x) and isfinite(self.y)):
            raise ValueError("node coordinates must be finite")


@dataclass(frozen=True, slots=True)
class Edge:
    """A physical network edge in its source orientation."""

    id: str
    u: str
    v: str
    length_m: float
    direction: Direction = Direction.BOTH
    geometry: tuple[Point, ...] = ()
    road_class: RoadClass = RoadClass.LOCAL
    facility: FacilityType = FacilityType.MIXED_TRAFFIC
    speed_kph: float | None = None
    lanes: int | None = None
    traffic_volume: float | None = None
    gradient: float = 0.0
    intersection_stress: int = 1
    source_way_id: str | None = None
    bridge: bool = False
    tunnel: bool = False
    attributes: Mapping[str, object] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self.id or not self.u or not self.v:
            raise ValueError("edge id and endpoint ids must be non-empty")
        if self.u == self.v:
            raise ValueError("self-loop edges are not supported")
        if not isfinite(self.length_m) or self.length_m <= 0:
            raise ValueError("edge length must be positive and finite")
        if self.speed_kph is not None and self.speed_kph <= 0:
            raise ValueError("speed_kph must be positive when supplied")
        if self.lanes is not None and self.lanes < 1:
            raise ValueError("lanes must be positive when supplied")
        if self.intersection_stress not in (1, 2, 3, 4):
            raise ValueError("intersection_stress must be in 1..4")
        if self.geometry and len(self.geometry) < 2:
            raise ValueError("edge geometry must contain at least two points")


@dataclass(frozen=True, slots=True)
class ODFlow:
    """Demand between two already-resolved network nodes.

    Snap distances are retained on the demand record so routing exports can
    account for every OD relation, including records that fail after snapping.
    ``purpose`` identifies the independently generated demand surface; it is not
    a post-hoc candidate ranking label.
    """

    id: str
    origin: str
    destination: str
    eligible: float
    observed_cycle: float = 0.0
    scenario_cycle: float = 0.0
    weight: float = 1.0
    purpose: str = "commute"
    origin_snap_distance_m: float = 0.0
    destination_snap_distance_m: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.eligible,
            self.observed_cycle,
            self.scenario_cycle,
            self.weight,
            self.origin_snap_distance_m,
            self.destination_snap_distance_m,
        )
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("OD quantities must be finite and non-negative")
        if not self.id or not self.origin or not self.destination or not self.purpose:
            raise ValueError("OD identifiers, endpoints, and purpose must be non-empty")
        if self.observed_cycle > self.eligible + 1e-9:
            raise ValueError("observed cycling cannot exceed eligible demand")
        if self.scenario_cycle > self.eligible + 1e-9:
            raise ValueError("scenario cycling cannot exceed eligible demand")


@dataclass(frozen=True, slots=True)
class RoutePath:
    """One directed route through the topology."""

    nodes: tuple[str, ...]
    edge_ids: tuple[str, ...]
    generalized_cost: float
    length_m: float

    def __post_init__(self) -> None:
        if len(self.nodes) != len(self.edge_ids) + 1:
            raise ValueError("a route must have one more node than edge")
        if self.generalized_cost < 0 or self.length_m < 0:
            raise ValueError("route costs must be non-negative")


@dataclass(frozen=True, slots=True)
class CorridorCandidate:
    """A proposed treatment defined by exact physical edge identifiers."""

    id: str
    edge_ids: frozenset[str]
    capital_cost: float
    treatment: FacilityType = FacilityType.PROTECTED_LANE
    name: str = ""
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("candidate id must be non-empty")
        if not self.edge_ids:
            raise ValueError("candidate must contain at least one exact edge id")
        if not isfinite(self.capital_cost) or self.capital_cost < 0:
            raise ValueError("capital_cost must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CounterSite:
    """Observed cycling count at a geocoded, optionally directional site."""

    id: str
    x: float
    y: float
    observed: float
    bearing_degrees: float | None = None
    bidirectional: bool = True

    def __post_init__(self) -> None:
        if self.observed < 0 or not isfinite(self.observed):
            raise ValueError("observed count must be finite and non-negative")
        if self.bearing_degrees is not None and not 0 <= self.bearing_degrees < 360:
            raise ValueError("bearing_degrees must be in [0, 360)")


@dataclass(frozen=True, slots=True)
class ScenarioAllocation:
    """Target-constrained additional cycling allocation."""

    additional_by_od: Mapping[str, float]
    target_additional: float
    achieved_additional: float
    unallocated: float


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """A candidate's network and demand effects under a stated response model."""

    candidate_id: str
    changed_edge_ids: frozenset[str]
    baseline_cost_by_od: Mapping[str, float]
    treated_cost_by_od: Mapping[str, float]
    additional_cycle_by_od: Mapping[str, float]
    status_by_od: Mapping[str, str] = field(default_factory=dict)

    @property
    def additional_cycle_trips(self) -> float:
        return sum(self.additional_cycle_by_od.values())

    @property
    def evaluated_od_count(self) -> int:
        return sum(status == "evaluated" for status in self.status_by_od.values())

    @property
    def failed_od_count(self) -> int:
        return len(self.status_by_od) - self.evaluated_od_count


@dataclass(frozen=True, slots=True)
class SequenceStep:
    """One step in a cumulatively recomputed investment sequence."""

    rank: int
    candidate_id: str
    cumulative_candidate_ids: tuple[str, ...]
    marginal_score: float
    cumulative_score: float
    cumulative_cost: float


def polyline_length(points: Sequence[Point]) -> float:
    """Return Euclidean polyline length in coordinate units."""

    return sum(hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in pairwise(points))
