"""Independent school, everyday, and transit cycling-access markets."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import exp, hypot, isfinite
from random import Random
from typing import Any

from scipy.spatial import cKDTree

from .demand import SpatialSupport
from .provenance import content_hash


@dataclass(frozen=True, slots=True)
class PurposeDestination:
    """Destination used by one independently defined purpose market."""

    id: str
    x: float
    y: float
    category: str
    weight: float = 1.0
    zone_id: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.category:
            raise ValueError("purpose destination identifiers must be non-empty")
        if not all(isfinite(value) for value in (self.x, self.y, self.weight)):
            raise ValueError("purpose destination values must be finite")
        if self.weight < 0:
            raise ValueError("purpose destination weight must be non-negative")


@dataclass(frozen=True, slots=True)
class PurposeODRecord:
    """Route-ready synthetic access record with explicit units and design."""

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
    demand_unit: str
    euclidean_distance_m: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PurposeGenerationExclusion:
    purpose: str
    origin_or_destination_id: str
    category: str
    reason: str
    eligible: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _record_id(purpose: str, source_cell_id: str, origin_id: str, destination_id: str) -> str:
    identity = content_hash(
        {
            "purpose": purpose,
            "source_cell_id": source_cell_id,
            "origin_support_id": origin_id,
            "destination_support_id": destination_id,
        }
    )[:20]
    return f"{purpose}:{identity}"


def generate_school_market(
    origins: Sequence[SpatialSupport],
    schools: Sequence[PurposeDestination],
    *,
    maximum_distance_m: float,
    distance_decay_m: float,
    samples_per_school: int,
    seed: int,
) -> tuple[tuple[PurposeODRecord, ...], tuple[PurposeGenerationExclusion, ...]]:
    """Allocate each observed roll over a declared population catchment.

    The unknown home locations of enrolled students are represented by
    population-and-distance weighted draws with replacement.  Repeated draws
    are collapsed, total roll is conserved exactly, and all design quantities
    are retained for uncertainty analysis.  This is an access market, not an
    assertion about observed school cycling trips.
    """

    if maximum_distance_m <= 0 or distance_decay_m <= 0 or samples_per_school < 1:
        raise ValueError("school market distances and sample count must be positive")
    sorted_origins = tuple(sorted(origins, key=lambda item: item.id))
    if not sorted_origins:
        raise ValueError("school market requires origins")
    tree = cKDTree([(item.x, item.y) for item in sorted_origins])
    rng = Random(seed)
    records: list[PurposeODRecord] = []
    exclusions: list[PurposeGenerationExclusion] = []
    for school in sorted(schools, key=lambda item: item.id):
        if school.weight <= 0:
            exclusions.append(
                PurposeGenerationExclusion(
                    "school", school.id, school.category, "nonpositive_school_roll", school.weight
                )
            )
            continue
        indices = sorted(tree.query_ball_point((school.x, school.y), maximum_distance_m))
        if not indices:
            exclusions.append(
                PurposeGenerationExclusion(
                    "school",
                    school.id,
                    school.category,
                    "no_population_support_within_maximum_distance",
                    school.weight,
                )
            )
            continue
        candidate_origins = [sorted_origins[index] for index in indices]
        distances = [
            hypot(origin.x - school.x, origin.y - school.y) for origin in candidate_origins
        ]
        weights = [
            max(origin.weight, 0.0) * exp(-distance / distance_decay_m)
            for origin, distance in zip(candidate_origins, distances, strict=True)
        ]
        if sum(weights) <= 0:
            weights = [exp(-distance / distance_decay_m) for distance in distances]
        probability_total = sum(weights)
        probabilities = [weight / probability_total for weight in weights]
        draws = rng.choices(
            range(len(candidate_origins)), weights=probabilities, k=samples_per_school
        )
        counts = Counter(draws)
        source_cell_id = f"school:{school.id}"
        for origin_index, draw_count in sorted(
            counts.items(), key=lambda item: candidate_origins[item[0]].id
        ):
            origin = candidate_origins[origin_index]
            records.append(
                PurposeODRecord(
                    _record_id("school", source_cell_id, origin.id, school.id),
                    source_cell_id,
                    origin.id,
                    school.id,
                    origin.x,
                    origin.y,
                    school.x,
                    school.y,
                    school.weight * draw_count / samples_per_school,
                    0.0,
                    "school",
                    probabilities[origin_index],
                    draw_count,
                    samples_per_school,
                    "modelled_enrolment_access",
                    distances[origin_index],
                )
            )
    return tuple(records), tuple(exclusions)


def _destinations_by_category(
    destinations: Sequence[PurposeDestination], categories: Sequence[str]
) -> Mapping[str, tuple[PurposeDestination, ...]]:
    grouped: dict[str, list[PurposeDestination]] = defaultdict(list)
    for destination in sorted(destinations, key=lambda item: item.id):
        if destination.category in categories:
            grouped[destination.category].append(destination)
    missing = sorted(set(categories).difference(grouped))
    if missing:
        raise ValueError("purpose destinations missing categories: " + ", ".join(missing))
    return {category: tuple(values) for category, values in grouped.items()}


def generate_everyday_market(
    origins: Sequence[SpatialSupport],
    destinations: Sequence[PurposeDestination],
    *,
    category_weights: Mapping[str, float],
    maximum_distance_m: float,
) -> tuple[tuple[PurposeODRecord, ...], tuple[PurposeGenerationExclusion, ...]]:
    """Connect each population support to its nearest POI in each category.

    Category weights sum to one, so the market total is interpretable as a
    person-equivalent accessibility index rather than an unsupported estimate
    of daily trip frequency.
    """

    if maximum_distance_m <= 0 or not category_weights:
        raise ValueError("everyday market requires positive distance and category weights")
    if any(not isfinite(value) or value < 0 for value in category_weights.values()):
        raise ValueError("everyday category weights must be finite and non-negative")
    weight_total = sum(category_weights.values())
    if weight_total <= 0:
        raise ValueError("everyday category weights must have a positive total")
    categories = tuple(sorted(category_weights))
    grouped = _destinations_by_category(destinations, categories)
    trees = {
        category: cKDTree([(item.x, item.y) for item in grouped[category]])
        for category in categories
    }
    records: list[PurposeODRecord] = []
    exclusions: list[PurposeGenerationExclusion] = []
    for origin in sorted(origins, key=lambda item: item.id):
        for category in categories:
            distance, index = trees[category].query((origin.x, origin.y), k=1)
            allocated = origin.weight * category_weights[category] / weight_total
            if not isfinite(float(distance)) or float(distance) > maximum_distance_m:
                exclusions.append(
                    PurposeGenerationExclusion(
                        "everyday",
                        origin.id,
                        category,
                        "no_destination_within_maximum_distance",
                        allocated,
                    )
                )
                continue
            destination = grouped[category][int(index)]
            source_cell_id = f"everyday:{origin.zone_id}:{category}"
            records.append(
                PurposeODRecord(
                    _record_id("everyday", source_cell_id, origin.id, destination.id),
                    source_cell_id,
                    origin.id,
                    destination.id,
                    origin.x,
                    origin.y,
                    destination.x,
                    destination.y,
                    allocated,
                    0.0,
                    "everyday",
                    1.0,
                    1,
                    1,
                    "person_equivalent_opportunity_access_index",
                    float(distance),
                )
            )
    return tuple(records), tuple(exclusions)


def generate_transit_market(
    origins: Sequence[SpatialSupport],
    destinations: Sequence[PurposeDestination],
    *,
    maximum_distance_m: float,
) -> tuple[tuple[PurposeODRecord, ...], tuple[PurposeGenerationExclusion, ...]]:
    """Connect each population support to its nearest declared major transit node."""

    if maximum_distance_m <= 0 or not destinations:
        raise ValueError("transit market requires destinations and a positive distance")
    sorted_destinations = tuple(sorted(destinations, key=lambda item: item.id))
    tree = cKDTree([(item.x, item.y) for item in sorted_destinations])
    records: list[PurposeODRecord] = []
    exclusions: list[PurposeGenerationExclusion] = []
    for origin in sorted(origins, key=lambda item: item.id):
        distance, index = tree.query((origin.x, origin.y), k=1)
        if not isfinite(float(distance)) or float(distance) > maximum_distance_m:
            exclusions.append(
                PurposeGenerationExclusion(
                    "transit",
                    origin.id,
                    "major_transit_node",
                    "no_destination_within_maximum_distance",
                    origin.weight,
                )
            )
            continue
        destination = sorted_destinations[int(index)]
        source_cell_id = f"transit:{origin.zone_id}"
        records.append(
            PurposeODRecord(
                _record_id("transit", source_cell_id, origin.id, destination.id),
                source_cell_id,
                origin.id,
                destination.id,
                origin.x,
                origin.y,
                destination.x,
                destination.y,
                origin.weight,
                0.0,
                "transit",
                1.0,
                1,
                1,
                "person_equivalent_major_transit_access_index",
                float(distance),
            )
        )
    return tuple(records), tuple(exclusions)
