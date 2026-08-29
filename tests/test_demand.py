import pytest

from cycling_investment_workbench.demand import (
    PCT_2020_EBIKE,
    PCT_2020_GO_DUTCH,
    PCT_2020_GOVERNMENT_TARGET,
    PCT_MAXIMUM_DISTANCE_KM,
    ConfidentialODCell,
    CountInterval,
    DemandConstraintError,
    PCTCoefficients,
    PCTFeatures,
    ScenarioUnit,
    SpatialSupport,
    allocate_additional_scenario,
    allocate_suppressed_od_to_origin_margins,
    allocate_target_scenario,
    censored_total_bounds,
    disaggregate_od_to_weighted_supports,
    interpret_censored_count,
    pct_probability,
    pct_scenario_counts,
)


def test_pct_equation_uses_declared_units_and_coefficients() -> None:
    coefficients = PCTCoefficients(0, 1, 0, 0, 2, 1, 0, 0)
    probability = pct_probability(PCTFeatures(2, 3), coefficients)
    assert probability == pytest.approx(0.9975273768)


def test_ebike_propensity_exceeds_go_dutch_for_longer_trip() -> None:
    trip = PCTFeatures(12.0, 1.5)
    assert pct_probability(trip, PCT_2020_EBIKE) > pct_probability(trip, PCT_2020_GO_DUTCH)


@pytest.mark.parametrize(
    ("coefficients", "expected"),
    [
        (PCT_2020_GOVERNMENT_TARGET, 0.061867465393),
        (PCT_2020_GO_DUTCH, 0.361076059315),
        (PCT_2020_EBIKE, 0.443611455569),
    ],
)
def test_pct_2020_manual_reference_vector(coefficients, expected: float) -> None:
    assert pct_probability(PCTFeatures(5.0, 1.2), coefficients) == pytest.approx(
        expected, abs=1e-12
    )


def test_pct_distance_is_explicitly_capped_at_30_km() -> None:
    at_cap = pct_probability(PCTFeatures(PCT_MAXIMUM_DISTANCE_KM, 2.0), PCT_2020_EBIKE)
    beyond_cap = pct_probability(PCTFeatures(60.0, 2.0), PCT_2020_EBIKE)

    assert beyond_cap == pytest.approx(at_cap)
    with pytest.raises(ValueError, match="maximum_distance_km"):
        pct_probability(
            PCTFeatures(5.0, 1.0),
            PCT_2020_EBIKE,
            maximum_distance_km=0,
        )


def test_numeric_zero_and_suppression_marker_are_distinct_intervals() -> None:
    numeric_zero = interpret_censored_count(0)
    suppressed = interpret_censored_count(None, suppressed=True)
    assert numeric_zero == CountInterval(0, 2, 0, "fixed_random_rounded_base_3")
    assert suppressed == CountInterval(0, 5, 2.5, "suppressed_below_6")
    assert interpret_censored_count(6).lower == pytest.approx(4)
    with pytest.raises(ValueError, match="must not also"):
        interpret_censored_count(0, suppressed=True)


def test_target_allocation_conserves_total_and_respects_capacities() -> None:
    units = (
        ScenarioUnit("a", 100, interpret_censored_count(6), PCTFeatures(2, 0)),
        ScenarioUnit("b", 50, interpret_censored_count(3), PCTFeatures(8, 1)),
        ScenarioUnit("c", 10, CountInterval(10, 10, 10), PCTFeatures(1, 0)),
    )
    result = allocate_target_scenario(units, 0.25)
    assert result.target_additional == pytest.approx(21)
    assert result.achieved_additional == pytest.approx(21)
    assert result.unallocated == pytest.approx(0)
    assert result.additional_by_od["c"] == 0
    assert all(
        value <= unit.eligible - unit.observed.point + 1e-9
        for unit, value in zip(units, (result.additional_by_od[u.id] for u in units), strict=True)
    )


def test_external_target_retains_unallocated_complete_market_demand() -> None:
    units = (
        ScenarioUnit("a", 10, CountInterval(0, 0, 0), PCTFeatures(2, 0)),
        ScenarioUnit("b", 5, CountInterval(5, 5, 5), PCTFeatures(3, 1)),
    )

    result = allocate_additional_scenario(units, 20)

    assert result.achieved_additional == pytest.approx(10)
    assert result.unallocated == pytest.approx(10)
    assert result.target_additional == 20


def test_pct_scenario_never_falls_below_observed_and_bounds_sum() -> None:
    units = (
        ScenarioUnit("a", 10, CountInterval(7, 9, 8), PCTFeatures(40, 10)),
        ScenarioUnit("b", 20, CountInterval(0, 5, 2), PCTFeatures(2, 0)),
    )
    counts = pct_scenario_counts(units, PCT_2020_GO_DUTCH)
    assert counts["a"] >= 8
    assert 2 <= counts["b"] <= 20
    assert censored_total_bounds(units) == (7, 10, 14)


def test_suppressed_od_allocation_is_origin_constrained_not_independent_midpoints() -> None:
    cells = (
        ConfidentialODCell("a-x", "a", "x", 20, 3, False),
        ConfidentialODCell("a-y", "a", "y", 20, None, True),
    )
    result = allocate_suppressed_od_to_origin_margins(
        cells,
        {"a": CountInterval(5, 7, 6, "origin_margin")},
        destination_margins={
            "x": CountInterval(1, 5, 3, "destination_margin"),
            "y": CountInterval(0, 2, 1, "destination_margin"),
        },
    )

    assert sum(result.cycle_by_od.values()) == pytest.approx(6)
    assert result.cycle_by_od["a-x"] == pytest.approx(3)
    assert result.cycle_by_od["a-y"] == pytest.approx(3)
    assert result.cycle_by_od["a-y"] != pytest.approx(2.5)
    assert result.feasible
    assert any(item.code == "destination_margin_outside_interval" for item in result.diagnostics)


def test_suppressed_od_allocation_fails_closed_on_incompatible_bounds() -> None:
    cells = (ConfidentialODCell("a-x", "a", "x", 5, None, True),)

    with pytest.raises(DemandConstraintError, match="infeasible_origin_bounds"):
        allocate_suppressed_od_to_origin_margins(
            cells,
            {"a": CountInterval(8, 10, 9, "impossible_margin")},
        )


def test_joint_eligible_and_bicycle_intervals_enforce_bicycle_cap() -> None:
    cell = ConfidentialODCell(
        "a-x",
        "a",
        "x",
        CountInterval(0, 5, 2.5, "suppressed_total_below_6"),
        None,
        True,
    )

    eligible, bicycle = cell.draw_joint_counts(
        eligible_fraction=0.2,
        bicycle_fraction=1.0,
    )

    assert cell.eligible_interval == CountInterval(0, 5, 2.5, "suppressed_total_below_6")
    assert eligible == pytest.approx(1)
    assert bicycle == pytest.approx(eligible)
    with pytest.raises(ValueError, match="draw fractions"):
        cell.draw_joint_counts(eligible_fraction=-0.1, bicycle_fraction=0.5)


def test_weighted_spatial_disaggregation_is_deterministic_conservative_and_intrazonal() -> None:
    cells = (ConfidentialODCell("a-a", "a", "a", 100, None, True),)
    origins = (
        SpatialSupport("o1", "a", 0, 0, 3, "sa1_population"),
        SpatialSupport("o2", "a", 1, 0, 1, "sa1_population"),
    )
    destinations = (
        SpatialSupport("d1", "a", 0, 1, 1, "employment_poi"),
        SpatialSupport("d2", "a", 1, 1, 4, "employment_poi"),
    )
    first = disaggregate_od_to_weighted_supports(
        cells,
        {"a-a": 4},
        origins,
        destinations,
        purpose="commute",
        samples_per_od=3,
        seed=17,
    )
    second = disaggregate_od_to_weighted_supports(
        cells,
        {"a-a": 4},
        origins,
        destinations,
        purpose="commute",
        samples_per_od=3,
        seed=17,
    )

    assert first == second
    assert sum(item.cycle for item in first) == pytest.approx(4)
    assert sum(item.eligible for item in first) == pytest.approx(100)
    assert all(item.purpose == "commute" for item in first)
    assert all(0 < item.selection_probability <= 1 for item in first)


def test_spatial_disaggregation_excludes_zero_weight_support_when_positive_support_exists() -> None:
    cells = (ConfidentialODCell("a-a", "a", "a", 30, 0, False),)
    origins = (
        SpatialSupport("zero", "a", 0, 0, 0, "sa1_population"),
        SpatialSupport("positive", "a", 1, 0, 100, "sa1_population"),
    )
    destinations = (SpatialSupport("job", "a", 1, 1, 10, "employment_poi"),)

    records = disaggregate_od_to_weighted_supports(
        cells,
        {"a-a": 0},
        origins,
        destinations,
        purpose="commute",
        samples_per_od=25,
        seed=17,
    )

    assert [item.origin_support_id for item in records] == ["positive"]
    assert records[0].eligible == 30
    assert records[0].selection_probability == 1
