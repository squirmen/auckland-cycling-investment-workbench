import pytest

from cycling_investment_workbench.appraisal import (
    AppraisalInputs,
    AppraisalParameters,
    PriceBaseReconciliation,
    lifecycle_appraisal,
    rebase_appraisal_inputs,
)


def test_health_values_are_mode_specific_and_capped_per_user() -> None:
    parameters = AppraisalParameters(
        discount_rate=0,
        appraisal_years=1,
        ramp_up_years=0,
    )
    result = lifecycle_appraisal(
        AppraisalInputs(
            capital_cost=1_000,
            price_base_year=2021,
            annual_conventional_cycle_km=10_000,
            annual_ebike_cycle_km=10_000,
            new_conventional_users=1,
            new_ebike_users=1,
            annual_maintenance_cost=100,
            renewal_costs={1: 500},
            residual_value=200,
        ),
        parameters,
    )
    assert result.full_annual_health_benefit == pytest.approx(6_200 + 4_600)
    assert result.present_value_costs == pytest.approx(1_400)
    assert result.benefit_cost_ratio == pytest.approx(10_800 / 1_400)


def test_ramp_and_discount_are_applied_year_by_year() -> None:
    result = lifecycle_appraisal(
        AppraisalInputs(capital_cost=100, price_base_year=2021, other_annual_benefits=120),
        AppraisalParameters(discount_rate=0.10, appraisal_years=2, ramp_up_years=2),
    )
    expected = 60 / 1.1 + 120 / (1.1**2)
    assert result.present_value_benefits == pytest.approx(expected)
    assert [flow.ramp_factor for flow in result.cash_flows] == [0.5, 1.0]


def test_price_base_mismatch_fails_loudly() -> None:
    with pytest.raises(ValueError, match="price bases differ"):
        lifecycle_appraisal(
            AppraisalInputs(capital_cost=1, price_base_year=2024),
            AppraisalParameters(price_base_year=2021),
        )


def test_health_kilometres_without_new_users_are_not_monetised() -> None:
    result = lifecycle_appraisal(
        AppraisalInputs(
            capital_cost=1,
            price_base_year=2021,
            annual_conventional_cycle_km=1_000,
            new_conventional_users=0,
        ),
        AppraisalParameters(appraisal_years=1, ramp_up_years=0, discount_rate=0),
    )
    assert result.full_annual_health_benefit == 0


def test_current_default_discount_schedule_declines_after_year_30() -> None:
    parameters = AppraisalParameters(appraisal_years=40)
    assert parameters.rate_for_year(1) == pytest.approx(0.02)
    assert parameters.rate_for_year(30) == pytest.approx(0.02)
    assert parameters.rate_for_year(31) == pytest.approx(0.015)
    assert parameters.rate_for_year(101) == pytest.approx(0.01)
    result = lifecycle_appraisal(AppraisalInputs(capital_cost=1, price_base_year=2021), parameters)
    assert result.cash_flows[29].discount_rate == pytest.approx(0.02)
    assert result.cash_flows[30].discount_rate == pytest.approx(0.015)


def test_eight_percent_discount_sensitivity_is_explicit() -> None:
    parameters = AppraisalParameters(discount_rate=0.08, appraisal_years=40)
    assert all(parameters.rate_for_year(year) == 0.08 for year in (1, 30, 31, 40))


def test_price_base_reconciliation_converts_all_and_only_monetary_inputs() -> None:
    original = AppraisalInputs(
        capital_cost=100,
        price_base_year=2021,
        annual_conventional_cycle_km=1_000,
        new_conventional_users=20,
        annual_avoided_vehicle_km=500,
        other_annual_benefits=10,
        annual_maintenance_cost=5,
        renewal_costs={20: 25},
        residual_value=15,
    )
    conversion = PriceBaseReconciliation(2021, 2025, 1.1, "published index table A")

    rebased = rebase_appraisal_inputs(original, conversion)

    assert rebased.inputs.capital_cost == pytest.approx(110)
    assert rebased.inputs.other_annual_benefits == pytest.approx(11)
    assert rebased.inputs.annual_maintenance_cost == pytest.approx(5.5)
    assert rebased.inputs.renewal_costs == pytest.approx({20: 27.5})
    assert rebased.inputs.residual_value == pytest.approx(16.5)
    assert rebased.inputs.annual_conventional_cycle_km == 1_000
    assert rebased.inputs.new_conventional_users == 20
    assert rebased.inputs.annual_avoided_vehicle_km == 500
    assert rebased.reconciliation.to_dict()["source"] == "published index table A"


def test_price_base_reconciliation_prevents_double_or_mixed_conversion() -> None:
    conversion = PriceBaseReconciliation(2021, 2025, 1.1, "published index")
    first = rebase_appraisal_inputs(
        AppraisalInputs(capital_cost=100, price_base_year=2021), conversion
    )

    with pytest.raises(ValueError, match="already have been converted"):
        rebase_appraisal_inputs(first.inputs, conversion)
    with pytest.raises(ValueError, match="price bases differ"):
        lifecycle_appraisal(first.inputs, AppraisalParameters(price_base_year=2021))
