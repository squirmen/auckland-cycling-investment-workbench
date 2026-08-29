"""Indicative lifecycle appraisal for cycling corridor screening.

Defaults expose, rather than hide, selected parameters from Waka Kotahi's
*Monetised Benefits and Costs Manual*, v1.7.5 (May 2026), including separate
conventional-cycle and e-bike health values and annual per-user caps.  This is a
screening appraisal, not a substitute for a complete business case.  The default
declining discount schedule follows General Circular 25/01, effective 6 January
2025; a constant 8% rate can be supplied as an explicit sensitivity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from math import inf, isfinite


@dataclass(frozen=True, slots=True)
class AppraisalParameters:
    """Economic parameters in a single declared real price base."""

    price_base_year: int = 2021
    discount_rate: float | None = None
    discount_rate_years_1_30: float = 0.02
    discount_rate_years_31_100: float = 0.015
    discount_rate_years_101_plus: float = 0.01
    appraisal_years: int = 40
    ramp_up_years: int = 3
    conventional_health_per_km: float = 4.90
    ebike_health_per_km: float = 2.50
    conventional_health_cap_per_user: float = 6_200.0
    ebike_health_cap_per_user: float = 4_600.0
    emissions_kg_per_vehicle_km: float = 0.0
    carbon_value_per_kg: float = 0.0
    other_benefit_per_avoided_vehicle_km: float = 0.0

    def __post_init__(self) -> None:
        rates = (
            self.discount_rate_years_1_30,
            self.discount_rate_years_31_100,
            self.discount_rate_years_101_plus,
        )
        if self.discount_rate is not None and not 0 <= self.discount_rate < 1:
            raise ValueError("discount_rate must be in [0, 1) when supplied")
        if any(not 0 <= rate < 1 for rate in rates):
            raise ValueError("scheduled discount rates must be in [0, 1)")
        if self.appraisal_years < 1 or self.ramp_up_years < 0:
            raise ValueError("appraisal years must be positive and ramp non-negative")
        monetary = (
            self.conventional_health_per_km,
            self.ebike_health_per_km,
            self.conventional_health_cap_per_user,
            self.ebike_health_cap_per_user,
            self.emissions_kg_per_vehicle_km,
            self.carbon_value_per_kg,
            self.other_benefit_per_avoided_vehicle_km,
        )
        if any(value < 0 or not isfinite(value) for value in monetary):
            raise ValueError("appraisal parameters must be finite and non-negative")

    def rate_for_year(self, year: int) -> float:
        """Return the applicable annual rate for a one-indexed appraisal year."""

        if year < 1:
            raise ValueError("discount year must be positive")
        if self.discount_rate is not None:
            return self.discount_rate
        if year <= 30:
            return self.discount_rate_years_1_30
        if year <= 100:
            return self.discount_rate_years_31_100
        return self.discount_rate_years_101_plus


@dataclass(frozen=True, slots=True)
class AppraisalInputs:
    """Incremental annual outcomes and lifecycle costs for one proposal."""

    capital_cost: float
    price_base_year: int
    annual_conventional_cycle_km: float = 0.0
    annual_ebike_cycle_km: float = 0.0
    new_conventional_users: float = 0.0
    new_ebike_users: float = 0.0
    annual_avoided_vehicle_km: float = 0.0
    other_annual_benefits: float = 0.0
    annual_maintenance_cost: float = 0.0
    renewal_costs: Mapping[int, float] = field(default_factory=dict)
    residual_value: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.capital_cost,
            self.annual_conventional_cycle_km,
            self.annual_ebike_cycle_km,
            self.new_conventional_users,
            self.new_ebike_users,
            self.annual_avoided_vehicle_km,
            self.other_annual_benefits,
            self.annual_maintenance_cost,
            self.residual_value,
        )
        if any(value < 0 or not isfinite(value) for value in values):
            raise ValueError("appraisal inputs must be finite and non-negative")
        if any(year < 1 or cost < 0 for year, cost in self.renewal_costs.items()):
            raise ValueError("renewal years and costs must be positive")


@dataclass(frozen=True, slots=True)
class PriceBaseReconciliation:
    """A documented multiplicative conversion between two real price bases."""

    source_year: int
    target_year: int
    factor: float
    source: str

    def __post_init__(self) -> None:
        if self.source_year == self.target_year:
            raise ValueError("price-base source and target years must differ")
        if not isfinite(self.factor) or self.factor <= 0:
            raise ValueError("price-base factor must be positive and finite")
        if not self.source:
            raise ValueError("price-base factor source must be documented")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_year": self.source_year,
            "target_year": self.target_year,
            "factor": self.factor,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class RebasedAppraisalInputs:
    """Converted appraisal inputs with their auditable reconciliation record."""

    inputs: AppraisalInputs
    reconciliation: PriceBaseReconciliation


def rebase_appraisal_inputs(
    inputs: AppraisalInputs,
    reconciliation: PriceBaseReconciliation,
) -> RebasedAppraisalInputs:
    """Apply one factor consistently to every monetary input field.

    Physical activity, users, and vehicle kilometres are quantities and are not
    multiplied.  Health and vehicle-benefit unit values live in
    :class:`AppraisalParameters`; they remain at their declared price base until
    the caller explicitly supplies reconciled parameters for the target year.
    """

    if not isinstance(inputs, AppraisalInputs):
        raise TypeError("inputs must be unreconciled AppraisalInputs")
    if inputs.price_base_year != reconciliation.source_year:
        raise ValueError(
            "input price base does not match the reconciliation source year; "
            "the case may already have been converted"
        )
    factor = reconciliation.factor
    converted = replace(
        inputs,
        capital_cost=inputs.capital_cost * factor,
        price_base_year=reconciliation.target_year,
        other_annual_benefits=inputs.other_annual_benefits * factor,
        annual_maintenance_cost=inputs.annual_maintenance_cost * factor,
        renewal_costs={year: cost * factor for year, cost in inputs.renewal_costs.items()},
        residual_value=inputs.residual_value * factor,
    )
    return RebasedAppraisalInputs(converted, reconciliation)


@dataclass(frozen=True, slots=True)
class AnnualCashFlow:
    """Undiscounted and discounted flow for one appraisal year."""

    year: int
    ramp_factor: float
    discount_rate: float
    benefits: float
    costs: float
    discounted_benefits: float
    discounted_costs: float


@dataclass(frozen=True, slots=True)
class AppraisalResult:
    """Lifecycle present values and indicative benefit-cost ratio."""

    present_value_benefits: float
    present_value_costs: float
    net_present_value: float
    benefit_cost_ratio: float
    full_annual_health_benefit: float
    full_annual_emissions_benefit: float
    cash_flows: tuple[AnnualCashFlow, ...]
    price_base_year: int


DEFAULT_APPRAISAL_PARAMETERS = AppraisalParameters()


def _capped_health_benefit(km: float, users: float, value: float, cap: float) -> float:
    if users <= 0 or km <= 0:
        return 0.0
    return min(km * value, users * cap)


def lifecycle_appraisal(
    inputs: AppraisalInputs,
    parameters: AppraisalParameters = DEFAULT_APPRAISAL_PARAMETERS,
) -> AppraisalResult:
    """Discount ramped benefits and complete declared lifecycle costs.

    Capital, benefits, maintenance, renewals, and residual value must all be in
    the same real price base.  A mismatch raises instead of being silently mixed.
    """

    if inputs.price_base_year != parameters.price_base_year:
        raise ValueError(
            "input and parameter price bases differ; apply and document a price index first"
        )
    invalid_renewals = [year for year in inputs.renewal_costs if year > parameters.appraisal_years]
    if invalid_renewals:
        raise ValueError(f"renewals outside appraisal horizon: {sorted(invalid_renewals)}")

    conventional_health = _capped_health_benefit(
        inputs.annual_conventional_cycle_km,
        inputs.new_conventional_users,
        parameters.conventional_health_per_km,
        parameters.conventional_health_cap_per_user,
    )
    ebike_health = _capped_health_benefit(
        inputs.annual_ebike_cycle_km,
        inputs.new_ebike_users,
        parameters.ebike_health_per_km,
        parameters.ebike_health_cap_per_user,
    )
    annual_health = conventional_health + ebike_health
    annual_emissions = (
        inputs.annual_avoided_vehicle_km
        * parameters.emissions_kg_per_vehicle_km
        * parameters.carbon_value_per_kg
    )
    annual_vehicle_benefits = (
        inputs.annual_avoided_vehicle_km * parameters.other_benefit_per_avoided_vehicle_km
    )
    full_annual_benefit = (
        annual_health + annual_emissions + annual_vehicle_benefits + inputs.other_annual_benefits
    )

    present_benefits = 0.0
    present_costs = inputs.capital_cost
    flows: list[AnnualCashFlow] = []
    cumulative_discount_factor = 1.0
    for year in range(1, parameters.appraisal_years + 1):
        ramp = 1.0 if parameters.ramp_up_years == 0 else min(1.0, year / parameters.ramp_up_years)
        benefits = full_annual_benefit * ramp
        costs = inputs.annual_maintenance_cost + inputs.renewal_costs.get(year, 0.0)
        if year == parameters.appraisal_years:
            costs -= inputs.residual_value
        annual_discount_rate = parameters.rate_for_year(year)
        cumulative_discount_factor *= 1.0 + annual_discount_rate
        discounted_benefits = benefits / cumulative_discount_factor
        discounted_costs = costs / cumulative_discount_factor
        present_benefits += discounted_benefits
        present_costs += discounted_costs
        flows.append(
            AnnualCashFlow(
                year,
                ramp,
                annual_discount_rate,
                benefits,
                costs,
                discounted_benefits,
                discounted_costs,
            )
        )
    ratio = present_benefits / present_costs if present_costs > 0 else inf
    return AppraisalResult(
        present_value_benefits=present_benefits,
        present_value_costs=present_costs,
        net_present_value=present_benefits - present_costs,
        benefit_cost_ratio=ratio,
        full_annual_health_benefit=annual_health,
        full_annual_emissions_benefit=annual_emissions,
        cash_flows=tuple(flows),
        price_base_year=parameters.price_base_year,
    )
