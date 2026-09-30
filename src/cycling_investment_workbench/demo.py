"""Deterministic miniature-city model used for examples and end-to-end tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .appraisal import (
    AppraisalInputs,
    AppraisalParameters,
    AppraisalResult,
    lifecycle_appraisal,
)
from .candidates import (
    DemandResponseParameters,
    apply_candidates,
    evaluate_candidate,
    evaluate_candidate_set,
)
from .connectivity import (
    PRIORITY_PRESETS,
    pareto_frontier,
    preset_scores,
    weighted_low_stress_connectivity,
)
from .demand import (
    PCT_2020_EBIKE,
    PCT_2020_GO_DUTCH,
    PCT_2020_GOVERNMENT_TARGET,
    PCTFeatures,
    ScenarioUnit,
    allocate_target_scenario,
    interpret_censored_count,
    pct_scenario_counts,
)
from .models import (
    CorridorCandidate,
    CounterSite,
    Direction,
    Edge,
    FacilityType,
    Node,
    ODFlow,
    RoadClass,
)
from .provenance import content_hash
from .routing import assign_demand
from .stress import (
    ComfortParameters,
    StressInputs,
    edge_generalized_cost,
    level_of_traffic_stress,
)
from .topology import DirectedTopology
from .uncertainty import (
    MATERIAL_UNCERTAINTY_DIMENSIONS,
    ParameterSpec,
    frontier_stability,
    latin_hypercube,
    quantile,
    rank_stability,
    validate_material_uncertainty_design,
)
from .validation import match_counters, regression_metrics


@dataclass(frozen=True, slots=True)
class MiniatureCity:
    """Complete deterministic inputs for the six-node demonstration."""

    topology: DirectedTopology
    od_flows_by_scenario: Mapping[str, tuple[ODFlow, ...]]
    candidates: tuple[CorridorCandidate, ...]

    @property
    def od_flows(self) -> tuple[ODFlow, ...]:
        """The explicit 8% commute sensitivity used by the compact demonstration."""

        return self.od_flows_by_scenario["commute_8pct"]


def miniature_city_inputs() -> MiniatureCity:
    """Construct a small network with one low-stress detour and two proposals."""

    nodes = (
        Node("A", 0, 0),
        Node("B", 1_000, 0),
        Node("C", 2_000, 0),
        Node("D", 0, 1_000),
        Node("E", 1_000, 1_000),
        Node("F", 2_000, 1_000),
    )

    def quiet(edge_id: str, u: str, v: str) -> Edge:
        start = next(node for node in nodes if node.id == u)
        end = next(node for node in nodes if node.id == v)
        return Edge(
            edge_id,
            u,
            v,
            1_000,
            Direction.BOTH,
            ((start.x, start.y), (end.x, end.y)),
            RoadClass.LOCAL,
            FacilityType.QUIET_STREET,
            30,
            2,
            500,
        )

    def busy(edge_id: str, u: str, v: str) -> Edge:
        start = next(node for node in nodes if node.id == u)
        end = next(node for node in nodes if node.id == v)
        return Edge(
            edge_id,
            u,
            v,
            1_000,
            Direction.BOTH,
            ((start.x, start.y), (end.x, end.y)),
            RoadClass.ARTERIAL,
            FacilityType.MIXED_TRAFFIC,
            50,
            4,
            15_000,
        )

    topology = DirectedTopology(
        nodes,
        (
            busy("ab", "A", "B"),
            busy("bc", "B", "C"),
            quiet("de", "D", "E"),
            quiet("ef", "E", "F"),
            quiet("ad", "A", "D"),
            busy("be", "B", "E"),
            quiet("cf", "C", "F"),
        ),
    )
    units = (
        ScenarioUnit("west", 1_000, interpret_censored_count(30), PCTFeatures(2.0, 0.3)),
        ScenarioUnit("north", 500, interpret_censored_count(15), PCTFeatures(2.0, 0.2)),
        ScenarioUnit("central", 300, interpret_censored_count(6), PCTFeatures(2.0, 0.4)),
    )
    allocation = allocate_target_scenario(units, 0.08)
    endpoints = {"west": ("A", "C"), "north": ("D", "F"), "central": ("E", "B")}
    scenario_counts: Mapping[str, Mapping[str, float]] = {
        "baseline": {unit.id: unit.observed.point for unit in units},
        "government_target": pct_scenario_counts(units, PCT_2020_GOVERNMENT_TARGET),
        "go_dutch": pct_scenario_counts(units, PCT_2020_GO_DUTCH),
        "ebike": pct_scenario_counts(units, PCT_2020_EBIKE),
        "commute_8pct": {
            unit.id: unit.observed.point + allocation.additional_by_od[unit.id] for unit in units
        },
    }
    od_flows_by_scenario = {
        scenario_id: tuple(
            ODFlow(
                unit.id,
                *endpoints[unit.id],
                eligible=unit.eligible,
                observed_cycle=unit.observed.point,
                scenario_cycle=counts[unit.id],
            )
            for unit in units
        )
        for scenario_id, counts in scenario_counts.items()
    }
    candidates = (
        CorridorCandidate(
            "main_street",
            frozenset({"ab", "bc"}),
            2_000_000,
            FacilityType.PROTECTED_LANE,
            "Main Street protected lanes",
        ),
        CorridorCandidate(
            "central_crossing",
            frozenset({"be"}),
            800_000,
            FacilityType.PROTECTED_LANE,
            "Central protected crossing",
        ),
    )
    return MiniatureCity(topology, od_flows_by_scenario, candidates)


def _rounded(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def run_miniature_city() -> Mapping[str, object]:
    """Run all core methods and return a stable, JSON-serialisable result."""

    city = miniature_city_inputs()
    baseline_connectivity = weighted_low_stress_connectivity(city.topology, city.od_flows)
    treated_topology = apply_candidates(city.topology, city.candidates)
    treated_connectivity = weighted_low_stress_connectivity(treated_topology, city.od_flows)

    main_evaluation = evaluate_candidate(
        city.topology,
        city.candidates[0],
        city.od_flows,
        response=DemandResponseParameters(cost_elasticity=1.0),
    )
    additional_daily = main_evaluation.additional_cycle_trips
    annual_cycle_km = additional_daily * 2.0 * 2.0 * 230.0
    appraisal = lifecycle_appraisal(
        AppraisalInputs(
            capital_cost=city.candidates[0].capital_cost,
            price_base_year=2021,
            annual_conventional_cycle_km=annual_cycle_km * 0.7,
            annual_ebike_cycle_km=annual_cycle_km * 0.3,
            new_conventional_users=additional_daily * 0.7,
            new_ebike_users=additional_daily * 0.3,
            annual_avoided_vehicle_km=annual_cycle_km * 0.65,
            annual_maintenance_cost=25_000,
            renewal_costs={20: 250_000},
            residual_value=100_000,
        ),
        AppraisalParameters(
            emissions_kg_per_vehicle_km=0.12,
            carbon_value_per_kg=0.10,
            other_benefit_per_avoided_vehicle_km=0.15,
        ),
    )

    integrated_uncertainty = _candidate_metrics(city, "commute_8pct", "network")
    portfolio = _portfolio(
        city,
        "commute_8pct",
        "network",
        integrated_uncertainty,
    )
    portfolio_scores = _preset_candidate_scores(integrated_uncertainty, "network")
    uncertainty_order = sorted(
        integrated_uncertainty,
        key=lambda candidate_id: (
            -integrated_uncertainty[candidate_id]["bcrP50"],
            candidate_id,
        ),
    )

    assignment = assign_demand(treated_topology, city.od_flows, k=5, max_cost_ratio=1.5)
    counters = (
        CounterSite("bottom", 500, 10, 95, 90),
        CounterSite("top", 500, 990, 70, 90),
    )
    matches, unmatched = match_counters(counters, treated_topology, max_distance=30)
    predicted = [assignment.edge_flow[matches[counter.id].edge_id] for counter in counters]
    validation = regression_metrics(
        [counter.observed for counter in counters], predicted, total_reference_count=len(counters)
    )

    return {
        "model": "miniature_city_v1",
        "network": {
            "nodes": len(city.topology.nodes),
            "edges": len(city.topology.edges),
            "components": len(city.topology.weak_components()),
        },
        "demand": {
            "eligible": sum(od.eligible for od in city.od_flows),
            "observed_cycle": sum(od.observed_cycle for od in city.od_flows),
            "scenario_cycle": _rounded(sum(od.scenario_cycle for od in city.od_flows)),
        },
        "connectivity": {
            "baseline": _rounded(baseline_connectivity.score),
            "all_projects": _rounded(treated_connectivity.score),
        },
        "sequence": [
            {
                "rank": step["step"],
                "candidate_id": step["candidateId"],
                "marginal_score": _rounded(step["marginalObjective"]),
                "cumulative_score": _rounded(step["cumulativeObjective"]),
                "cumulative_cost": step["cumulativeCostNzd"],
                "preset_score": _rounded(portfolio_scores[str(step["candidateId"])]),
                "pareto_member": step["paretoMember"],
            }
            for step in portfolio
        ],
        "decision_support": {
            "preset": "network",
            "weights": dict(PRIORITY_PRESETS["network"].weights),
            "pareto_frontier": list(_pareto_candidates(integrated_uncertainty, "network")),
        },
        "main_street": {
            "additional_cycle_trips_per_day": _rounded(additional_daily),
            "indicative_bcr": _rounded(appraisal.benefit_cost_ratio),
            "npv": _rounded(appraisal.net_present_value, 2),
        },
        "uncertainty": {
            "draws": 32,
            "parameter_count": len(UNCERTAINTY_PARAMETER_SPECS),
            "parameters": [parameter.name for parameter in UNCERTAINTY_PARAMETER_SPECS],
            "baseline_order": uncertainty_order,
            "candidates": [
                {
                    "id": candidate_id,
                    "rank_stability": _rounded(
                        integrated_uncertainty[candidate_id]["rankStability"]
                    ),
                    "bcr_p5": _rounded(integrated_uncertainty[candidate_id]["bcrP5"]),
                    "bcr_p50": _rounded(integrated_uncertainty[candidate_id]["bcrP50"]),
                    "bcr_p95": _rounded(integrated_uncertainty[candidate_id]["bcrP95"]),
                }
                for candidate_id in sorted(integrated_uncertainty)
            ],
        },
        "validation": {
            "matched": len(matches),
            "unmatched": list(unmatched),
            "coverage": _rounded(validation.coverage),
            "mae": _rounded(validation.mae),
            "rmse": _rounded(validation.rmse),
            "r_squared": _rounded(validation.r_squared),
            "pearson_r": _rounded(validation.pearson_r),
            "calibration_slope": _rounded(validation.calibration_slope),
        },
    }


SCENARIO_IDS = (
    "baseline",
    "government_target",
    "go_dutch",
    "ebike",
    "commute_8pct",
)
PURPOSE_IDS = ("network", "equity", "school", "everyday", "transit", "appraisal")
UNCERTAINTY_PARAMETER_SPECS = (
    ParameterSpec("suppression_factor", 0.80, 1.20, "triangular", 1.0),
    ParameterSpec("pct_uptake_factor", 0.80, 1.20, "triangular", 1.0),
    ParameterSpec("route_choice_factor", 0.85, 1.15, "triangular", 1.0),
    ParameterSpec("stress_penalty_factor", 0.85, 1.25, "triangular", 1.0),
    ParameterSpec("topology_coverage_factor", 0.90, 1.00, "triangular", 0.98),
    ParameterSpec("capital_cost_factor", 0.80, 1.25, "triangular", 1.0),
    ParameterSpec("maintenance_cost_factor", 0.75, 1.50, "triangular", 1.0),
    ParameterSpec("renewal_cost_factor", 0.75, 1.50, "triangular", 1.0),
    ParameterSpec("benefit_value_factor", 0.80, 1.20, "triangular", 1.0),
    ParameterSpec("discount_rate", 0.015, 0.08, "triangular", 0.02),
    ParameterSpec("ebike_share", 0.20, 0.60, "triangular", 0.35),
    ParameterSpec("demand_response_elasticity", 0.50, 2.00, "triangular", 1.0),
)

validate_material_uncertainty_design(UNCERTAINTY_PARAMETER_SPECS)
assert tuple(parameter.name for parameter in UNCERTAINTY_PARAMETER_SPECS) == (
    MATERIAL_UNCERTAINTY_DIMENSIONS
)


def _synthetic_lon_lat(x: float, y: float) -> list[float]:
    """Place metre-based demo coordinates near Auckland for web display only."""

    return [174.75 + x / 90_000.0, -36.86 + y / 111_000.0]


def _candidate_lifecycle_appraisal(
    topology: DirectedTopology,
    candidate: CorridorCandidate,
    daily_trips: float,
    *,
    capital_cost_factor: float = 1.0,
    maintenance_cost_factor: float = 1.0,
    renewal_cost_factor: float = 1.0,
    benefit_value_factor: float = 1.0,
    discount_rate: float | None = None,
    ebike_share: float = 0.30,
) -> AppraisalResult:
    project_length_km = (
        sum(topology.edge(edge_id).length_m for edge_id in candidate.edge_ids) / 1_000.0
    )
    annual_cycle_km = daily_trips * 2.0 * project_length_km * 230.0
    capital = candidate.capital_cost * capital_cost_factor
    if not 0 <= ebike_share <= 1:
        raise ValueError("ebike_share must be in [0, 1]")
    return lifecycle_appraisal(
        AppraisalInputs(
            capital_cost=capital,
            price_base_year=2021,
            annual_conventional_cycle_km=annual_cycle_km * (1 - ebike_share),
            annual_ebike_cycle_km=annual_cycle_km * ebike_share,
            new_conventional_users=daily_trips * (1 - ebike_share),
            new_ebike_users=daily_trips * ebike_share,
            annual_avoided_vehicle_km=annual_cycle_km * 0.65,
            annual_maintenance_cost=capital * 0.0125 * maintenance_cost_factor,
            renewal_costs={20: capital * 0.125 * renewal_cost_factor},
            residual_value=capital * 0.05,
        ),
        AppraisalParameters(
            discount_rate=discount_rate,
            conventional_health_per_km=4.90 * benefit_value_factor,
            ebike_health_per_km=2.50 * benefit_value_factor,
            conventional_health_cap_per_user=6_200 * benefit_value_factor,
            ebike_health_cap_per_user=4_600 * benefit_value_factor,
            emissions_kg_per_vehicle_km=0.12,
            carbon_value_per_kg=0.10 * benefit_value_factor,
            other_benefit_per_avoided_vehicle_km=0.15 * benefit_value_factor,
        ),
    )


def _purpose_od_flows(city: MiniatureCity, scenario_id: str, purpose_id: str) -> tuple[ODFlow, ...]:
    """Create a distinct synthetic OD surface for each planning purpose."""

    if purpose_id == "network":
        return city.od_flows_by_scenario[scenario_id]
    templates: Mapping[str, tuple[tuple[str, str, str, float, float, float], ...]] = {
        "equity": (
            ("equity_central", "E", "B", 420, 8, 1.25),
            ("equity_north", "D", "F", 280, 5, 0.95),
        ),
        "school": (
            ("school_west", "A", "B", 600, 12, 1.15),
            ("school_central", "E", "B", 240, 4, 1.10),
        ),
        "everyday": (
            ("everyday_west", "A", "C", 480, 9, 0.90),
            ("everyday_central", "E", "B", 480, 9, 1.00),
        ),
        "transit": (
            ("transit_west", "A", "C", 350, 6, 0.85),
            ("transit_central", "E", "B", 650, 11, 1.25),
        ),
        "appraisal": (
            ("appraisal_west", "A", "C", 800, 18, 1.00),
            ("appraisal_central", "E", "B", 200, 5, 0.80),
        ),
    }
    if purpose_id not in templates:
        raise KeyError(f"unknown purpose: {purpose_id}")
    scenario_ods = city.od_flows_by_scenario[scenario_id]
    eligible_total = sum(od.eligible for od in scenario_ods)
    scenario_share = (
        sum(od.scenario_cycle for od in scenario_ods) / eligible_total if eligible_total else 0.0
    )
    flows: list[ODFlow] = []
    for od_id, origin, destination, eligible, observed, multiplier in templates[purpose_id]:
        scenario_cycle = (
            observed
            if scenario_id == "baseline"
            else min(eligible, max(observed, eligible * scenario_share * multiplier))
        )
        flows.append(
            ODFlow(
                od_id,
                origin,
                destination,
                eligible,
                observed_cycle=observed,
                scenario_cycle=scenario_cycle,
                weight=1.5 if purpose_id == "equity" else 1.0,
                purpose=purpose_id,
            )
        )
    return tuple(flows)


def _uncertain_od_flows(
    od_flows: tuple[ODFlow, ...], sample: Mapping[str, float]
) -> tuple[ODFlow, ...]:
    """Apply illustrative suppression and propensity factors without exceeding capacity."""

    result: list[ODFlow] = []
    for od in od_flows:
        observed = min(od.eligible, od.observed_cycle * sample["suppression_factor"])
        modelled_additional = max(0.0, od.scenario_cycle - od.observed_cycle)
        scenario = min(
            od.eligible,
            observed + modelled_additional * sample["pct_uptake_factor"],
        )
        result.append(
            ODFlow(
                od.id,
                od.origin,
                od.destination,
                od.eligible,
                observed_cycle=observed,
                scenario_cycle=scenario,
                weight=od.weight,
                purpose=od.purpose,
                origin_snap_distance_m=od.origin_snap_distance_m,
                destination_snap_distance_m=od.destination_snap_distance_m,
            )
        )
    return tuple(result)


_ACCESS_WEIGHTS = {
    "main_street": {
        "equity": 0.45,
        "school": 0.80,
        "everyday": 0.70,
        "transit": 0.35,
    },
    "central_crossing": {
        "equity": 0.85,
        "school": 0.25,
        "everyday": 0.55,
        "transit": 0.90,
    },
}


def _decision_indicators(metric: Mapping[str, float]) -> dict[str, float]:
    """Map published fields to the named, inspectable decision indicators."""

    return {
        "demand": metric["dailyTripsDelta"],
        "connectivity": metric["odLowStressShareDelta"],
        "equity": metric["equityBenefit"],
        "school": metric["schoolAccess"],
        "everyday": metric["everydayAccess"],
        "transit": metric["transitAccess"],
        "value": metric["bcrP50"],
        "cost": metric["lifecycleCostNzd"],
    }


def _pareto_objectives(purpose_id: str) -> tuple[str, ...]:
    primary = {
        "network": "connectivity",
        "equity": "equity",
        "school": "school",
        "everyday": "everyday",
        "transit": "transit",
        "appraisal": "value",
    }[purpose_id]
    return tuple(dict.fromkeys((primary, "demand", "connectivity", "value")))


def _pareto_candidates(
    metrics: Mapping[str, Mapping[str, float]], purpose_id: str
) -> tuple[str, ...]:
    indicators = {
        candidate_id: _decision_indicators(metric) for candidate_id, metric in metrics.items()
    }
    return pareto_frontier(
        indicators,
        maximise=_pareto_objectives(purpose_id),
        minimise=("cost",),
    )


def _preset_candidate_scores(
    metrics: Mapping[str, Mapping[str, float]], purpose_id: str
) -> Mapping[str, float]:
    indicators = {
        candidate_id: _decision_indicators(metric) for candidate_id, metric in metrics.items()
    }
    return preset_scores(indicators, PRIORITY_PRESETS[purpose_id])


def _candidate_metrics(
    city: MiniatureCity, scenario_id: str, purpose_id: str
) -> Mapping[str, Mapping[str, float]]:
    """Calculate deterministic metrics plus integrated uncertainty evidence."""

    ods = _purpose_od_flows(city, scenario_id, purpose_id)
    baseline_nci = weighted_low_stress_connectivity(city.topology, ods).score
    deterministic: dict[str, dict[str, float]] = {}
    for candidate in city.candidates:
        evaluation = evaluate_candidate(city.topology, candidate, ods)
        daily = evaluation.additional_cycle_trips
        treated = apply_candidates(city.topology, (candidate,))
        nci_delta = max(
            0.0,
            weighted_low_stress_connectivity(treated, ods).score - baseline_nci,
        )
        appraisal = _candidate_lifecycle_appraisal(city.topology, candidate, daily)
        length_km = (
            sum(city.topology.edge(edge_id).length_m for edge_id in candidate.edge_ids) / 1_000.0
        )
        weights = _ACCESS_WEIGHTS[candidate.id]
        deterministic[candidate.id] = {
            "capitalCostNzd": candidate.capital_cost,
            "lifecycleCostNzd": appraisal.present_value_costs,
            "dailyTripsDelta": daily,
            "annualBikeKmDelta": daily * 2.0 * length_km * 230.0,
            "odLowStressShareDelta": nci_delta,
            "equityBenefit": daily * weights["equity"],
            "schoolAccess": daily * weights["school"],
            "everydayAccess": daily * weights["everyday"],
            "transitAccess": daily * weights["transit"],
            "bcrP5": appraisal.benefit_cost_ratio,
            "bcrP50": appraisal.benefit_cost_ratio,
            "bcrP95": appraisal.benefit_cost_ratio,
            "routeCoverage": evaluation.evaluated_od_count / len(ods),
            "dataCompleteness": 1.0,
            "rankStability": 0.0,
            "frontierStability": 0.0,
            "dailyTripsP5P95Span": 0.0,
        }

    samples = latin_hypercube(UNCERTAINTY_PARAMETER_SPECS, 32, seed=2026)
    daily_draws: dict[str, list[float]] = {candidate.id: [] for candidate in city.candidates}
    bcr_draws: dict[str, list[float]] = {candidate.id: [] for candidate in city.candidates}
    score_draws: list[Mapping[str, float]] = []
    frontier_draws: list[tuple[str, ...]] = []
    for sample in samples:
        sampled_ods = _uncertain_od_flows(ods, sample)
        stress_factor = sample["stress_penalty_factor"]
        stress_parameters = ComfortParameters(
            stress_multipliers=(
                1.0,
                1.0 + 0.25 * stress_factor,
                1.0 + 0.80 * stress_factor,
                1.0 + 2.00 * stress_factor,
            )
        )
        route_choice_factor = sample["route_choice_factor"]

        def sampled_route_cost(
            edge: Edge,
            reversed: bool,
            stress_parameters: ComfortParameters = stress_parameters,
            route_choice_factor: float = route_choice_factor,
        ) -> float:
            comfort_cost = edge_generalized_cost(
                edge,
                reversed=reversed,
                parameters=stress_parameters,
            )
            comfort_per_metre = comfort_cost / edge.length_m
            return edge.length_m * comfort_per_metre**route_choice_factor

        draw_metrics: dict[str, dict[str, float]] = {}
        for candidate in city.candidates:
            evaluation = evaluate_candidate(
                city.topology,
                candidate,
                sampled_ods,
                response=DemandResponseParameters(sample["demand_response_elasticity"]),
                cost=sampled_route_cost,
            )
            daily = evaluation.additional_cycle_trips * sample["topology_coverage_factor"]
            appraisal = _candidate_lifecycle_appraisal(
                city.topology,
                candidate,
                daily,
                capital_cost_factor=sample["capital_cost_factor"],
                maintenance_cost_factor=sample["maintenance_cost_factor"],
                renewal_cost_factor=sample["renewal_cost_factor"],
                benefit_value_factor=sample["benefit_value_factor"],
                discount_rate=sample["discount_rate"],
                ebike_share=sample["ebike_share"],
            )
            weights = _ACCESS_WEIGHTS[candidate.id]
            daily_draws[candidate.id].append(daily)
            bcr_draws[candidate.id].append(appraisal.benefit_cost_ratio)
            draw_metrics[candidate.id] = {
                "demand": daily,
                "connectivity": deterministic[candidate.id]["odLowStressShareDelta"]
                * sample["topology_coverage_factor"],
                "equity": daily * weights["equity"],
                "school": daily * weights["school"],
                "everyday": daily * weights["everyday"],
                "transit": daily * weights["transit"],
                "value": appraisal.benefit_cost_ratio,
                "cost": appraisal.present_value_costs,
            }
        score_draws.append(preset_scores(draw_metrics, PRIORITY_PRESETS[purpose_id]))
        frontier_draws.append(
            pareto_frontier(
                draw_metrics,
                maximise=_pareto_objectives(purpose_id),
                minimise=("cost",),
            )
        )

    baseline_scores = _preset_candidate_scores(deterministic, purpose_id)
    ranks = rank_stability(score_draws, top_k=1, baseline_scores=baseline_scores)
    rank_by_id = {item.candidate_id: item for item in ranks.candidates}
    baseline_frontier = _pareto_candidates(deterministic, purpose_id)
    frontier = frontier_stability(
        frontier_draws,
        candidate_ids=deterministic,
        baseline_frontier=baseline_frontier,
    )
    for candidate_id, metric in deterministic.items():
        bcr_values = bcr_draws[candidate_id]
        daily_values = daily_draws[candidate_id]
        metric.update(
            {
                "bcrP5": quantile(bcr_values, 0.05),
                "bcrP50": quantile(bcr_values, 0.50),
                "bcrP95": quantile(bcr_values, 0.95),
                "rankStability": rank_by_id[candidate_id].top_k_probability,
                "frontierStability": frontier.membership_probability[candidate_id],
                "dailyTripsP5P95Span": quantile(daily_values, 0.95) - quantile(daily_values, 0.05),
            }
        )
    return deterministic


def _portfolio_order(metrics: Mapping[str, Mapping[str, float]], purpose_id: str) -> list[str]:
    scores = _preset_candidate_scores(metrics, purpose_id)
    return sorted(metrics, key=lambda candidate_id: (-scores[candidate_id], candidate_id))


def _objective_unit(purpose_id: str) -> str:
    return {
        "network": "CIW OD low-stress connectivity share",
        "equity": "synthetic equity-weighted access units",
        "school": "synthetic school access units",
        "everyday": "synthetic everyday access units",
        "transit": "synthetic transit access units",
        "appraisal": "synthetic modelled activity units",
    }[purpose_id]


def _activity_unit(purpose_id: str) -> str:
    return {
        "network": "weighted synthetic daily cycle trips",
        "equity": "weighted synthetic equity-priority trips",
        "school": "weighted synthetic school trips",
        "everyday": "weighted synthetic everyday trips",
        "transit": "weighted synthetic transit-access trips",
        "appraisal": "weighted synthetic daily cycle trips",
    }[purpose_id]


def _browser_candidate_metric(metric: Mapping[str, float], purpose_id: str) -> Mapping[str, object]:
    objective = {
        "network": metric["odLowStressShareDelta"],
        "equity": metric["equityBenefit"],
        "school": metric["schoolAccess"],
        "everyday": metric["everydayAccess"],
        "transit": metric["transitAccess"],
        "appraisal": metric["bcrP50"],
    }[purpose_id]
    return {
        "available": True,
        "capitalCostNzd": metric["capitalCostNzd"],
        "lifecycleCostNzd": metric["lifecycleCostNzd"],
        "objectiveValue": objective,
        "objectiveUnit": _objective_unit(purpose_id),
        "additionalCycleUsers": metric["dailyTripsDelta"],
        "annualBikeKmDelta": metric["annualBikeKmDelta"],
        "odLowStressShareDelta": metric["odLowStressShareDelta"],
        "bcrP5": metric["bcrP5"],
        "bcrP50": metric["bcrP50"],
        "bcrP95": metric["bcrP95"],
        "routeCoverage": metric["routeCoverage"],
        "meanRank": None,
        "topKProbability": metric["rankStability"],
        "frontierProbability": metric["frontierStability"],
        "warnings": ["synthetic demonstration metric; not Auckland evidence"],
    }


def _portfolio(
    city: MiniatureCity,
    scenario_id: str,
    purpose_id: str,
    metrics: Mapping[str, Mapping[str, float]],
) -> list[Mapping[str, object]]:
    ods = _purpose_od_flows(city, scenario_id, purpose_id)
    candidate_by_id = {candidate.id: candidate for candidate in city.candidates}
    current = city.topology
    current_nci = weighted_low_stress_connectivity(current, ods).score
    cumulative_cost = 0.0
    cumulative_daily = 0.0
    cumulative_objective = 0.0
    selected: list[CorridorCandidate] = []
    result: list[Mapping[str, object]] = []
    frontier_ids = set(_pareto_candidates(metrics, purpose_id))
    for index, candidate_id in enumerate(_portfolio_order(metrics, purpose_id), start=1):
        candidate = candidate_by_id[candidate_id]
        selected.append(candidate)
        state_evaluation = evaluate_candidate_set(city.topology, selected, ods)
        current = apply_candidates(current, (candidate,))
        new_nci = weighted_low_stress_connectivity(current, ods).score
        cumulative_cost += candidate.capital_cost
        state_daily = state_evaluation.additional_cycle_trips
        if state_daily + 1e-9 < cumulative_daily:
            raise RuntimeError("cumulative candidate treatment reduced modelled cycling")
        cumulative_daily = state_daily
        if purpose_id == "network":
            objective = new_nci
            marginal_objective = max(0.0, new_nci - current_nci)
        else:
            objective = cumulative_daily
            marginal_objective = max(0.0, objective - cumulative_objective)
        result.append(
            {
                "candidateId": candidate_id,
                "step": index,
                "cumulativeCostNzd": cumulative_cost,
                "marginalObjective": marginal_objective,
                "cumulativeObjective": objective,
                "objectiveUnit": _objective_unit(purpose_id),
                "paretoMember": candidate_id in frontier_ids,
            }
        )
        current_nci = new_nci
        cumulative_objective = objective
    return result


def _candidate_geojson(
    city: MiniatureCity,
    metrics_by_scenario: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]],
) -> Mapping[str, object]:
    purpose_origins = {
        "main_street": ["network", "school", "everyday"],
        "central_crossing": ["equity", "transit", "appraisal"],
    }
    features: list[Mapping[str, object]] = []
    for candidate in city.candidates:
        coordinates = [
            [
                _synthetic_lon_lat(x, y)
                for x, y in (
                    city.topology.edge(edge_id).geometry
                    or (
                        (
                            city.topology.node(city.topology.edge(edge_id).u).x,
                            city.topology.node(city.topology.edge(edge_id).u).y,
                        ),
                        (
                            city.topology.node(city.topology.edge(edge_id).v).x,
                            city.topology.node(city.topology.edge(edge_id).v).y,
                        ),
                    )
                )
            ]
            for edge_id in sorted(candidate.edge_ids)
        ]
        nested_metrics = {
            scenario_id: {
                purpose_id: _browser_candidate_metric(
                    metrics_by_scenario[scenario_id][purpose_id][candidate.id], purpose_id
                )
                for purpose_id in PURPOSE_IDS
            }
            for scenario_id in SCENARIO_IDS
        }
        features.append(
            {
                "type": "Feature",
                "id": candidate.id,
                "geometry": {"type": "MultiLineString", "coordinates": coordinates},
                "properties": {
                    "candidateId": candidate.id,
                    "name": candidate.name,
                    "purposeOrigins": purpose_origins[candidate.id],
                    "edgeIds": sorted(candidate.edge_ids),
                    "facilityType": candidate.treatment.value,
                    "programmeStatus": "unprogrammed",
                    "rationale": (
                        "Synthetic exact-edge proposal used to demonstrate cumulative rerouting "
                        "and scenario-sensitive appraisal."
                    ),
                    "metrics": nested_metrics,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def web_export_payload(
    *, config_sha256: str | None = None, run_id: str = "synthetic-miniature-city-v1"
) -> Mapping[str, object]:
    """Return deterministic manifest metadata and five synthetic GeoJSON layers.

    Layer URLs and SHA-256 values are intentionally left to the atomic exporter,
    which hashes the exact serialized bytes it writes.  Every feature is synthetic
    and the candidate layer carries exact physical edge identifiers.
    """

    if config_sha256 is None:
        config_sha256 = content_hash(
            {
                "model_version": "miniature-city-1.0.0",
                "profile": "synthetic_demo",
                "seed": 2026,
            }
        )
    city = miniature_city_inputs()
    metrics_by_scenario = {
        scenario_id: {
            purpose_id: _candidate_metrics(city, scenario_id, purpose_id)
            for purpose_id in PURPOSE_IDS
        }
        for scenario_id in SCENARIO_IDS
    }
    portfolios = {
        scenario_id: {
            purpose_id: _portfolio(
                city,
                scenario_id,
                purpose_id,
                metrics_by_scenario[scenario_id][purpose_id],
            )
            for purpose_id in PURPOSE_IDS
        }
        for scenario_id in SCENARIO_IDS
    }
    summaries: dict[str, Mapping[str, object]] = {}
    for scenario_id in SCENARIO_IDS:
        purpose_summaries: dict[str, Mapping[str, object]] = {}
        for purpose_id in PURPOSE_IDS:
            ods = _purpose_od_flows(city, scenario_id, purpose_id)
            connectivity = weighted_low_stress_connectivity(city.topology, ods)
            assignment = assign_demand(city.topology, ods, k=5, max_cost_ratio=1.5)
            total_demand = sum(od.scenario_cycle for od in ods)
            assigned_demand = sum(
                od.scenario_cycle for od in ods if od.id not in assignment.unassigned_od_ids
            )
            purpose_summaries[purpose_id] = {
                "activityValue": total_demand,
                "activityUnit": _activity_unit(purpose_id),
                "odLowStressShare": connectivity.score,
                "odLowStressConnectedWeight": connectivity.connected_weight,
                "odLowStressDenominatorWeight": connectivity.total_weight,
                "routingCoverage": assigned_demand / total_demand if total_demand else 0.0,
                "purpose": purpose_id,
                "maximumLts": 2,
                "maximumDetourRatio": 1.5,
                "candidateCount": len(city.candidates),
                "validationCoverage": 1.0,
                "warnings": ["synthetic demonstration summary; not Auckland evidence"],
            }
        summaries[scenario_id] = purpose_summaries

    default_metrics = metrics_by_scenario["commute_8pct"]["network"]
    candidate_by_edge = {
        edge_id: candidate for candidate in city.candidates for edge_id in candidate.edge_ids
    }
    network_features: list[Mapping[str, object]] = []
    for edge_id, edge in sorted(city.topology.edges.items()):
        points = edge.geometry or (
            (city.topology.node(edge.u).x, city.topology.node(edge.u).y),
            (city.topology.node(edge.v).x, city.topology.node(edge.v).y),
        )
        candidate = candidate_by_edge.get(edge_id)
        if candidate is None:
            capital = daily = connectivity_potential = 0.0
        else:
            total_candidate_length = sum(
                city.topology.edge(value).length_m for value in candidate.edge_ids
            )
            share = edge.length_m / total_candidate_length
            capital = candidate.capital_cost * share
            daily = default_metrics[candidate.id]["dailyTripsDelta"] * share
            connectivity_potential = default_metrics[candidate.id]["odLowStressShareDelta"] * share
        network_features.append(
            {
                "type": "Feature",
                "id": edge_id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [_synthetic_lon_lat(x, y) for x, y in points],
                },
                "properties": {
                    "edgeId": edge_id,
                    "u": edge.u,
                    "v": edge.v,
                    "oneway": edge.direction is not Direction.BOTH,
                    "direction": edge.direction.value,
                    "protected": edge.facility
                    in (FacilityType.PROTECTED_LANE, FacilityType.SHARED_PATH),
                    "lts": level_of_traffic_stress(StressInputs.from_edge(edge)).level,
                    "lengthKm": edge.length_m / 1_000.0,
                    "capitalCostNzd": capital,
                    "dailyTripsPotential": daily,
                    "odLowStressSharePotential": connectivity_potential,
                },
            }
        )

    cell_features = []
    for index, node in enumerate(city.topology.nodes.values()):
        lon, lat = _synthetic_lon_lat(node.x, node.y)
        width = 0.0025
        cell_features.append(
            {
                "type": "Feature",
                "id": f"cell-{node.id}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [lon - width, lat - width],
                            [lon + width, lat - width],
                            [lon + width, lat + width],
                            [lon - width, lat + width],
                            [lon - width, lat - width],
                        ]
                    ],
                },
                "properties": {
                    "cellId": f"cell-{node.id}",
                    "population": 250 + index * 50,
                    "equityIndex": round(0.2 + index * 0.12, 2),
                    "dataStatus": "synthetic_demo",
                },
            }
        )

    treated_topology = apply_candidates(city.topology, city.candidates)
    treated_assignment = assign_demand(
        treated_topology,
        city.od_flows_by_scenario["commute_8pct"],
        k=5,
        max_cost_ratio=1.5,
    )
    counter_specs = (
        (CounterSite("bottom", 500, 10, 95, 90), "ab"),
        (CounterSite("top", 500, 990, 70, 90), "de"),
    )
    counter_features = [
        {
            "type": "Feature",
            "id": counter.id,
            "geometry": {
                "type": "Point",
                "coordinates": _synthetic_lon_lat(counter.x, counter.y),
            },
            "properties": {
                "counterId": counter.id,
                "observedDaily": counter.observed,
                "modelledDaily": treated_assignment.edge_flow[edge_id],
                "matchedEdgeId": edge_id,
                "dataStatus": "synthetic_demo",
            },
        }
        for counter, edge_id in counter_specs
    ]
    programme_edge = city.topology.edge("ef")
    programme_points = programme_edge.geometry or (
        (city.topology.node(programme_edge.u).x, city.topology.node(programme_edge.u).y),
        (city.topology.node(programme_edge.v).x, city.topology.node(programme_edge.v).y),
    )
    programme_features = [
        {
            "type": "Feature",
            "id": "synthetic-funded-link",
            "geometry": {
                "type": "LineString",
                "coordinates": [_synthetic_lon_lat(x, y) for x, y in programme_points],
            },
            "properties": {
                "programmeId": "synthetic-funded-link",
                "name": "Synthetic funded northern link",
                "status": "funded",
                "dataStatus": "synthetic_demo",
            },
        }
    ]

    layer_specs = (
        ("cells", "Synthetic analysis cells", True, False),
        ("network", "Synthetic cycling network", True, False),
        ("candidates", "Synthetic candidate corridors", True, False),
        ("programmes", "Synthetic funded programmes", False, True),
        ("counters", "Synthetic validation counters", False, True),
        ("safety", "Synthetic safety context", False, True),
    )
    manifest = {
        "schemaVersion": "2.0.0",
        "modelVersion": "miniature-city-1.0.0",
        "runId": run_id,
        "configSha256": config_sha256,
        "generatedAtUtc": "2026-01-01T00:00:00Z",
        "title": "Auckland Cycling Investment Workbench — synthetic demonstration",
        "dataStatus": "synthetic_demo",
        "dataStatusLabel": "Synthetic demonstration — not Auckland evidence",
        "defaultScenario": "commute_8pct",
        "defaultPurpose": "network",
        "defaultBudgetNzd": 2_000_000,
        "maxBudgetNzd": sum(candidate.capital_cost for candidate in city.candidates),
        "scenarios": [
            {
                "id": "baseline",
                "label": "Present-day baseline",
                "description": "Published descriptive cycling counts; no propensity scenario.",
            },
            {
                "id": "government_target",
                "label": "Government target",
                "description": "Published PCT 2020 government-target propensity scenario.",
            },
            {
                "id": "go_dutch",
                "label": "Go Dutch",
                "description": "Published PCT Go Dutch propensity scenario.",
            },
            {
                "id": "ebike",
                "label": "Go Dutch + e-bike",
                "description": "Published PCT e-bike propensity scenario.",
            },
            {
                "id": "commute_8pct",
                "label": "8% commute sensitivity",
                "description": (
                    "Target-constrained modelling sensitivity, not a stated TERP target."
                ),
            },
        ],
        "purposes": [
            {
                "id": "network",
                "label": "Network",
                "description": "Demand-weighted low-stress OD connectivity.",
                "objectiveLabel": "Marginal connectivity per lifecycle dollar",
            },
            {
                "id": "equity",
                "label": "Equity",
                "description": "Distributional benefit shown separately from base demand.",
                "objectiveLabel": "Equity benefit per lifecycle dollar",
            },
            {
                "id": "school",
                "label": "School",
                "description": "Synthetic school-access opportunity.",
                "objectiveLabel": "School access per lifecycle dollar",
            },
            {
                "id": "everyday",
                "label": "Everyday",
                "description": "Synthetic local essential-access opportunity.",
                "objectiveLabel": "Everyday access per lifecycle dollar",
            },
            {
                "id": "transit",
                "label": "Transit",
                "description": "Synthetic bicycle-to-transit opportunity.",
                "objectiveLabel": "Transit access per lifecycle dollar",
            },
            {
                "id": "appraisal",
                "label": "Appraisal",
                "description": "Indicative lifecycle benefit-cost screening.",
                "objectiveLabel": "Median indicative benefit-cost ratio",
            },
        ],
        "summaries": summaries,
        "portfolios": portfolios,
        "validation": {
            "periodLabel": "Synthetic fixture; no calendar period",
            "counterCount": len(counter_specs),
            "matchedCount": len(counter_features),
            "coverage": 1.0,
            "purposeAlignment": "Synthetic daily cycling counts",
            "status": "synthetic_fixture",
        },
        "capabilities": {
            "equity": "available",
            "appraisal": "research_only",
            "sketchEvaluation": "requires_pipeline_evaluation",
        },
        "limitations": [
            "Synthetic software-verification fixture; not Auckland evidence.",
            "Browser corridor sketches require canonical pipeline evaluation.",
        ],
        "layers": [
            {
                "id": layer_id,
                "label": label,
                "defaultVisible": visible,
                "optional": optional,
                "licence": "Synthetic demonstration data; CC0-1.0",
                "sourceIds": ["synthetic_miniature_city"],
            }
            for layer_id, label, visible, optional in layer_specs
        ],
        "attribution": [
            "Synthetic miniature-city data generated for software verification; "
            "not Auckland evidence."
        ],
        "sourceDecisions": [
            {
                "sourceId": "synthetic_miniature_city",
                "redistribution": "permitted",
                "decision": "include",
                "rationale": "Generated synthetic fixture with no third-party records.",
            }
        ],
        "methodologyUrl": "./documentation/methodology.md",
    }
    return {
        "manifest": manifest,
        "uncertainty": {
            "method": "latin_hypercube",
            "drawsPerScenarioPurpose": 32,
            "seed": 2026,
            "parameters": [
                {
                    "name": parameter.name,
                    "lower": parameter.lower,
                    "upper": parameter.upper,
                    "distribution": parameter.distribution,
                    "mode": parameter.mode,
                }
                for parameter in UNCERTAINTY_PARAMETER_SPECS
            ],
            "note": "Illustrative synthetic ranges; replace with evidenced local priors.",
        },
        "layers": {
            "cells": {"type": "FeatureCollection", "features": cell_features},
            "network": {"type": "FeatureCollection", "features": network_features},
            "candidates": _candidate_geojson(city, metrics_by_scenario),
            "programmes": {"type": "FeatureCollection", "features": programme_features},
            "counters": {"type": "FeatureCollection", "features": counter_features},
            "safety": {"type": "FeatureCollection", "features": []},
        },
    }
