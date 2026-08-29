import pytest

from cycling_investment_workbench.models import Edge, FacilityType, RoadClass
from cycling_investment_workbench.stress import (
    ComfortParameters,
    StressInputs,
    comfort_multiplier,
    edge_generalized_cost,
    level_of_traffic_stress,
)


def test_protection_does_not_hide_intersection_stress() -> None:
    result = level_of_traffic_stress(
        StressInputs(
            RoadClass.ARTERIAL,
            FacilityType.PROTECTED_LANE,
            50,
            4,
            20_000,
            intersection_stress=3,
        )
    )
    assert result.segment_level == 1
    assert result.level == 3


def test_missing_attributes_are_conservatively_imputed_and_reported() -> None:
    result = level_of_traffic_stress(
        StressInputs(RoadClass.ARTERIAL, FacilityType.MIXED_TRAFFIC, None, None, None)
    )
    assert result.level == 4
    assert result.imputed_fields == ("speed_kph", "lanes", "traffic_volume")


def test_lts_boundaries_are_explicit() -> None:
    low = StressInputs(RoadClass.LOCAL, FacilityType.MIXED_TRAFFIC, 30, 2, 2_000)
    higher = StressInputs(RoadClass.LOCAL, FacilityType.MIXED_TRAFFIC, 30, 2, 2_001)
    assert level_of_traffic_stress(low).level == 1
    assert level_of_traffic_stress(higher).level == 2


def test_comfort_cost_is_directional_for_gradient() -> None:
    edge = Edge(
        "hill",
        "a",
        "b",
        100,
        gradient=0.10,
        road_class=RoadClass.PATH,
        facility=FacilityType.SHARED_PATH,
    )
    uphill = comfort_multiplier(edge)
    downhill = comfort_multiplier(edge, reversed=True)
    assert uphill > downhill > 1
    assert edge_generalized_cost(edge) == pytest.approx(100 * uphill)


def test_tunnel_and_bridge_penalties_are_multiplicative() -> None:
    plain = Edge("plain", "a", "b", 1, road_class=RoadClass.PATH, facility=FacilityType.SHARED_PATH)
    structured = Edge(
        "structured",
        "a",
        "b",
        1,
        road_class=RoadClass.PATH,
        facility=FacilityType.SHARED_PATH,
        bridge=True,
        tunnel=True,
    )
    parameters = ComfortParameters(tunnel_multiplier=1.2, bridge_multiplier=1.1)
    assert comfort_multiplier(structured, parameters=parameters) == pytest.approx(
        comfort_multiplier(plain, parameters=parameters) * 1.2 * 1.1
    )
