from __future__ import annotations

import pytest

from cycling_investment_workbench.demand import SpatialSupport
from cycling_investment_workbench.purpose_demand import (
    PurposeDestination,
    generate_everyday_market,
    generate_school_market,
    generate_transit_market,
)


def _origin(origin_id: str, zone_id: str, x: float, y: float, population: float) -> SpatialSupport:
    return SpatialSupport(origin_id, zone_id, x, y, population, "test_population")


def test_school_market_conserves_roll_and_is_seed_reproducible() -> None:
    origins = (
        _origin("o1", "z1", 0, 0, 100),
        _origin("o2", "z1", 1000, 0, 100),
        _origin("outside", "z2", 20_000, 0, 100),
    )
    schools = (PurposeDestination("s1", 200, 0, "school", 300),)

    first, exclusions = generate_school_market(
        origins,
        schools,
        maximum_distance_m=5000,
        distance_decay_m=3000,
        samples_per_school=25,
        seed=7,
    )
    second, _ = generate_school_market(
        origins,
        schools,
        maximum_distance_m=5000,
        distance_decay_m=3000,
        samples_per_school=25,
        seed=7,
    )

    assert exclusions == ()
    assert first == second
    assert sum(item.eligible for item in first) == pytest.approx(300)
    assert {item.origin_support_id for item in first} <= {"o1", "o2"}
    assert all(item.demand_unit == "modelled_enrolment_access" for item in first)


def test_everyday_market_is_category_specific_and_mass_conserving() -> None:
    origins = (_origin("o1", "z1", 0, 0, 120),)
    destinations = (
        PurposeDestination("shop-near", 100, 0, "retail"),
        PurposeDestination("shop-far", 500, 0, "retail"),
        PurposeDestination("park", 0, 200, "recreation"),
    )

    records, exclusions = generate_everyday_market(
        origins,
        destinations,
        category_weights={"retail": 1, "recreation": 2},
        maximum_distance_m=1000,
    )

    assert exclusions == ()
    assert {item.destination_support_id for item in records} == {"shop-near", "park"}
    assert sum(item.eligible for item in records) == pytest.approx(120)
    by_destination = {item.destination_support_id: item.eligible for item in records}
    assert by_destination["shop-near"] == pytest.approx(40)
    assert by_destination["park"] == pytest.approx(80)
    assert {item.source_cell_id for item in records} == {
        "everyday:z1:retail",
        "everyday:z1:recreation",
    }


def test_transit_market_retains_out_of_range_population_as_exclusion() -> None:
    origins = (
        _origin("near", "z1", 0, 0, 80),
        _origin("far", "z2", 10_000, 0, 60),
    )
    destinations = (PurposeDestination("station", 100, 0, "major_transit_node"),)

    records, exclusions = generate_transit_market(origins, destinations, maximum_distance_m=1000)

    assert [item.origin_support_id for item in records] == ["near"]
    assert records[0].eligible == 80
    assert len(exclusions) == 1
    assert exclusions[0].origin_or_destination_id == "far"
    assert exclusions[0].eligible == 60
