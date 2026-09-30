"""Production Pareto metrics and cumulative purpose portfolio sequences."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .candidates import DemandResponseParameters
from .pipeline import ProductionBlocker, StageContext, StageResult
from .portfolio_analysis import (
    ChoicePath,
    ODChoiceSet,
    evaluate_choice_set,
    greedy_choice_set_sequence,
    pareto_frontier_benefit_cost,
)
from .provenance import content_hash, read_json, sha256_file, write_json_atomic

PORTFOLIO_OUTPUT_SCHEMA_VERSION = 3

PATH_SAVING_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("path_id", pa.string()),
        ("od_id", pa.string()),
        ("purpose", pa.string()),
        ("candidate_id", pa.string()),
        ("generalized_cost_saving", pa.float64()),
    ]
)

CANDIDATE_COUNTERFACTUAL_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("purpose", pa.string()),
        ("objective", pa.string()),
        ("candidate_id", pa.string()),
        ("affected_od_count", pa.int32()),
        ("objective_value", pa.float64()),
        ("additional_cycle_users", pa.float64()),
        ("annual_cycle_km", pa.float64()),
        ("capital_cost_base_nzd", pa.float64()),
        ("objective_per_million_nzd", pa.float64()),
        ("pareto_member", pa.bool_()),
    ]
)

PORTFOLIO_STEP_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("preset", pa.string()),
        ("purpose", pa.string()),
        ("objective", pa.string()),
        ("rank", pa.int32()),
        ("candidate_id", pa.string()),
        ("cumulative_candidate_ids", pa.list_(pa.string())),
        ("marginal_objective", pa.float64()),
        ("cumulative_objective", pa.float64()),
        ("marginal_objective_per_million_nzd", pa.float64()),
        ("cumulative_cost_nzd", pa.float64()),
    ]
)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="invalid_portfolio_configuration",
            message=f"{field} must be a mapping",
            evidence={"field": field},
        )
    return value


def _finite(value: Any, *, field: str, minimum: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="invalid_portfolio_configuration",
            message=f"{field} must be numeric",
        ) from exc
    if not isfinite(result) or result < minimum:
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="invalid_portfolio_configuration",
            message=f"{field} must be finite and at least {minimum}",
        )
    return result


def _artifact_file(path: Path, filename: str) -> Path:
    return path / filename if path.is_dir() else path.parent / filename


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(
        pa.Table.from_pylist([dict(row) for row in rows], schema=schema),
        temporary,
        compression="zstd",
        use_dictionary=True,
    )
    temporary.replace(path)


def _candidate_inputs(
    candidate_dir: Path,
) -> tuple[dict[str, float], dict[str, tuple[str, int]]]:
    candidates = pq.read_table(
        _artifact_file(candidate_dir, "candidate_ledger.parquet"),
        columns=["candidate_id", "capital_cost_base_nzd"],
    ).to_pylist()
    costs = {str(row["candidate_id"]): float(row["capital_cost_base_nzd"]) for row in candidates}
    if len(costs) != len(candidates):
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="duplicate_candidate_id",
            message="candidate ledger ids must be unique",
        )
    edge_rows = pq.read_table(
        _artifact_file(candidate_dir, "candidate_edge_ledger.parquet"),
        columns=["candidate_id", "project_edge_id", "baseline_lts"],
    ).to_pylist()
    edge_mapping: dict[str, tuple[str, int]] = {}
    for row in edge_rows:
        edge_id = str(row["project_edge_id"])
        if edge_id in edge_mapping:
            raise ProductionBlocker(
                stage="evaluate-portfolios",
                code="overlapping_candidate_edges",
                message="screening candidates must partition exact treated edges",
                evidence={"project_edge_id": edge_id},
            )
        edge_mapping[edge_id] = (str(row["candidate_id"]), int(row["baseline_lts"]))
    return costs, edge_mapping


def _path_candidate_savings(
    route_dir: Path,
    edge_mapping: Mapping[str, tuple[str, int]],
    *,
    lts_multipliers: Mapping[int, float],
) -> tuple[dict[tuple[str, str], float], int]:
    """Aggregate exact candidate savings without loading all path edges."""

    edge_to_candidate = {edge_id: value[0] for edge_id, value in edge_mapping.items()}
    edge_to_factor = {
        edge_id: 1.0 - lts_multipliers[1] / lts_multipliers[value[1]]
        for edge_id, value in edge_mapping.items()
    }
    aggregated: defaultdict[tuple[str, str], float] = defaultdict(float)
    matched_rows = 0
    parquet = pq.ParquetFile(_artifact_file(route_dir, "path_edge_ledger.parquet"))
    for batch in parquet.iter_batches(
        batch_size=250_000,
        columns=["path_id", "project_edge_id", "generalized_cost"],
    ):
        frame = batch.to_pandas()
        frame["candidate_id"] = frame["project_edge_id"].map(edge_to_candidate)
        frame = frame[frame["candidate_id"].notna()].copy()
        if frame.empty:
            continue
        frame["saving_factor"] = frame["project_edge_id"].map(edge_to_factor)
        frame["saving"] = frame["generalized_cost"] * frame["saving_factor"]
        grouped = frame.groupby(["path_id", "candidate_id"], sort=False)["saving"].sum()
        for key, value in grouped.items():
            aggregated[(str(key[0]), str(key[1]))] += float(value)
        matched_rows += len(frame)
    return dict(aggregated), matched_rows


def _path_and_od_inputs(
    route_dir: Path,
    savings: Mapping[tuple[str, str], float],
) -> tuple[
    dict[str, tuple[ChoicePath, ...]],
    dict[str, tuple[str, float, float, float, str]],
    dict[str, set[str]],
    list[dict[str, Any]],
]:
    savings_by_path: defaultdict[str, dict[str, float]] = defaultdict(dict)
    for (path_id, candidate_id), value in savings.items():
        savings_by_path[path_id][candidate_id] = value
    path_rows = pq.read_table(
        _artifact_file(route_dir, "path_ledger.parquet"),
        columns=["path_id", "od_id", "purpose", "probability", "generalized_cost"],
    ).to_pylist()
    paths_by_od: defaultdict[str, list[ChoicePath]] = defaultdict(list)
    candidate_to_od: defaultdict[str, set[str]] = defaultdict(set)
    saving_rows: list[dict[str, Any]] = []
    for row in path_rows:
        path_id = str(row["path_id"])
        od_id = str(row["od_id"])
        purpose = str(row["purpose"])
        path_savings = savings_by_path.get(path_id, {})
        paths_by_od[od_id].append(
            ChoicePath(
                path_id,
                float(row["generalized_cost"]),
                float(row["probability"]),
                path_savings,
            )
        )
        for candidate_id, saving in path_savings.items():
            candidate_to_od[candidate_id].add(od_id)
            saving_rows.append(
                {
                    "schema_version": PORTFOLIO_OUTPUT_SCHEMA_VERSION,
                    "path_id": path_id,
                    "od_id": od_id,
                    "purpose": purpose,
                    "candidate_id": candidate_id,
                    "generalized_cost_saving": saving,
                }
            )

    od_rows: dict[str, tuple[str, float, float, float, str]] = {}
    parquet = pq.ParquetFile(_artifact_file(route_dir, "od_ledger.parquet"))
    for batch in parquet.iter_batches(
        batch_size=50_000,
        columns=[
            "od_id",
            "purpose",
            "weighted_eligible",
            "weighted_observed_cycle",
            "shortest_distance_m",
            "origin_support_id",
            "status",
        ],
    ):
        for row in batch.to_pylist():
            if row["status"] == "assigned":
                od_rows[str(row["od_id"])] = (
                    str(row["purpose"]),
                    float(row["weighted_eligible"]),
                    float(row["weighted_observed_cycle"]),
                    float(row["shortest_distance_m"]) / 1_000,
                    str(row["origin_support_id"]),
                )
    if set(paths_by_od) != set(od_rows):
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="choice_set_od_mismatch",
            message="assigned OD and plausible-path sets differ",
            evidence={
                "assigned_od": len(od_rows),
                "path_od": len(paths_by_od),
            },
        )
    return (
        {od_id: tuple(paths) for od_id, paths in paths_by_od.items()},
        od_rows,
        dict(candidate_to_od),
        saving_rows,
    )


def _scenario_activity(route_dir: Path) -> Mapping[str, Mapping[str, float]]:
    result: defaultdict[str, dict[str, float]] = defaultdict(dict)
    table = pq.ParquetFile(_artifact_file(route_dir, "scenario_od_ledger.parquet"))
    for batch in table.iter_batches(
        batch_size=50_000, columns=["scenario_id", "od_id", "scenario_cycle"]
    ):
        for row in batch.to_pylist():
            if row["scenario_cycle"] is not None:
                result[str(row["scenario_id"])][str(row["od_id"])] = float(row["scenario_cycle"])
    return dict(result)


def _choice_sets(
    paths_by_od: Mapping[str, tuple[ChoicePath, ...]],
    od_rows: Mapping[str, tuple[str, float, float, float, str]],
    *,
    purpose: str,
    activity_by_od: Mapping[str, float] | None = None,
    allowed_origin_supports: frozenset[str] | None = None,
    choice_purpose: str | None = None,
) -> dict[str, ODChoiceSet]:
    result: dict[str, ODChoiceSet] = {}
    for od_id, paths in paths_by_od.items():
        od_purpose, eligible, observed, distance_km, origin_support_id = od_rows[od_id]
        if od_purpose != purpose:
            continue
        if allowed_origin_supports is not None and origin_support_id not in allowed_origin_supports:
            continue
        activity = (
            float(activity_by_od[od_id])
            if activity_by_od is not None and od_id in activity_by_od
            else observed
            if purpose == "commute"
            else 0.0
        )
        result[od_id] = ODChoiceSet(
            od_id,
            choice_purpose or purpose,
            eligible,
            activity,
            paths,
            distance_km,
        )
    return result


def _nzdep_deciles(context: StageContext) -> tuple[dict[str, int], dict[str, Any]]:
    """Load an optional, pinned SA1 NZDep source without exposing its raw polygons."""

    source = context.sources.get("nzdep2023_sa1")
    if source is None or not source.usable:
        return {}, {"status": "unavailable", "reason": "registered_source_not_available"}
    payload = read_json(source.path)
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="invalid_nzdep_source",
            message="NZDep source must be a GeoJSON FeatureCollection",
        )
    deciles: dict[str, int] = {}
    missing = 0
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, Mapping) else None
        if not isinstance(properties, Mapping):
            continue
        code = str(properties.get("SA12023_code", "")).strip()
        value = properties.get("NZDep2023")
        if not code or value is None:
            missing += 1
            continue
        try:
            decile = int(value)
        except (TypeError, ValueError) as exc:
            raise ProductionBlocker(
                stage="evaluate-portfolios",
                code="invalid_nzdep_source",
                message="NZDep deciles must be integers",
                evidence={"sa1_code": code, "value": value},
            ) from exc
        if not 1 <= decile <= 10 or code in deciles:
            raise ProductionBlocker(
                stage="evaluate-portfolios",
                code="invalid_nzdep_source",
                message="NZDep records must have unique SA1 codes and deciles in 1..10",
                evidence={"sa1_code": code, "value": decile},
            )
        deciles[f"sa1-{code}"] = decile
    if not deciles:
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="invalid_nzdep_source",
            message="NZDep source contains no usable SA1 deciles",
        )
    return deciles, {
        "status": "available",
        "source_id": "nzdep2023_sa1",
        "sa1_with_decile": len(deciles),
        "records_without_decile_or_code": missing,
        "high_deprivation_definition": "NZDep2023 deciles 8-10",
        "raw_polygons_exposed_in_public_output": False,
    }


def _single_candidate_metrics(
    choices: Mapping[str, ODChoiceSet],
    candidate_to_od: Mapping[str, set[str]],
    costs: Mapping[str, float],
    *,
    objective: str,
    cost_scale: float,
    annualisation_factor: float,
    response: DemandResponseParameters,
) -> tuple[dict[str, float], dict[str, int], dict[str, float], dict[str, float]]:
    values: dict[str, float] = {}
    counts: dict[str, int] = {}
    additional_users: dict[str, float] = {}
    annual_cycle_km: dict[str, float] = {}
    for candidate_id, od_ids in candidate_to_od.items():
        selected = frozenset({candidate_id})
        relevant = [od_id for od_id in od_ids if od_id in choices]
        if not relevant:
            continue
        evaluations = [
            (
                choices[od_id],
                evaluate_choice_set(
                    choices[od_id], selected, cost_scale=cost_scale, response=response
                ),
            )
            for od_id in relevant
        ]
        values[candidate_id] = sum(
            float(getattr(evaluation, objective)) for _, evaluation in evaluations
        )
        counts[candidate_id] = len(relevant)
        if all(choice.purpose in {"commute", "equity"} for choice, _ in evaluations):
            additional_users[candidate_id] = sum(
                evaluation.activity_addition for _, evaluation in evaluations
            )
            annual_cycle_km[candidate_id] = sum(
                evaluation.activity_addition * choice.distance_km * annualisation_factor
                for choice, evaluation in evaluations
            )
    if set(values).difference(costs):
        raise ProductionBlocker(
            stage="evaluate-portfolios",
            code="counterfactual_candidate_missing_cost",
            message="a counterfactual candidate has no declared base cost",
        )
    return values, counts, additional_users, annual_cycle_km


def production_portfolios_stage(context: StageContext) -> StageResult:
    """Evaluate exact-edge candidates and cumulative named presets."""

    route_dir = context.dependencies["assign-routes"]["routes"].path
    candidate_dir = context.dependencies["generate-candidates"]["candidates"].path
    routing = _mapping(context.config.parameters.get("routing"), field="parameters.routing")
    network = _mapping(context.config.parameters.get("network"), field="parameters.network")
    comfort = _mapping(
        network.get("comfort_impedance"), field="parameters.network.comfort_impedance"
    )
    portfolio_parameters = _mapping(
        context.config.parameters.get("portfolios"), field="parameters.portfolios"
    )
    response_parameters = _mapping(
        context.config.parameters.get("demand_response"), field="parameters.demand_response"
    )
    elasticity = _mapping(
        response_parameters.get("cost_elasticity"),
        field="parameters.demand_response.cost_elasticity",
    )
    response = DemandResponseParameters(
        cost_elasticity=_finite(elasticity.get("mode"), field="cost_elasticity.mode"),
        minimum_probability=_finite(
            response_parameters.get("minimum_probability"),
            field="demand_response.minimum_probability",
        ),
    )
    cost_scale = _finite(
        routing.get("path_size_logit_cost_scale"), field="routing.path_size_logit_cost_scale"
    )
    budget_nzd = _finite(
        portfolio_parameters.get("maximum_precomputed_budget_nzd"),
        field="portfolios.maximum_precomputed_budget_nzd",
    )
    appraisal = _mapping(context.config.parameters.get("appraisal"), field="parameters.appraisal")
    annualisation_factor = _finite(
        appraisal.get("commute_operating_days_per_year"),
        field="appraisal.commute_operating_days_per_year",
    ) * _finite(
        appraisal.get("commute_legs_per_day"),
        field="appraisal.commute_legs_per_day",
    )
    lts_multipliers = {
        level: _finite(comfort.get(f"lts_{level}"), field=f"comfort_impedance.lts_{level}")
        for level in range(1, 5)
    }
    costs, edge_mapping = _candidate_inputs(candidate_dir)
    savings, matched_path_edges = _path_candidate_savings(
        route_dir, edge_mapping, lts_multipliers=lts_multipliers
    )
    paths_by_od, od_rows, candidate_to_od, saving_rows = _path_and_od_inputs(route_dir, savings)
    scenario_activity = _scenario_activity(route_dir)
    nzdep_deciles, equity_context = _nzdep_deciles(context)
    high_deprivation_origins = frozenset(
        support_id for support_id, decile in nzdep_deciles.items() if decile >= 8
    )
    commute_od = [row for row in od_rows.values() if row[0] == "commute"]
    assigned_commute_eligible = sum(row[1] for row in commute_od)
    mapped_commute_eligible = sum(row[1] for row in commute_od if row[4] in nzdep_deciles)
    high_deprivation_eligible = sum(
        row[1] for row in commute_od if row[4] in high_deprivation_origins
    )
    equity_context.update(
        {
            "assigned_commute_eligible": assigned_commute_eligible,
            "nzdep_mapped_commute_eligible": mapped_commute_eligible,
            "high_deprivation_commute_eligible": high_deprivation_eligible,
            "nzdep_mapping_coverage": (
                mapped_commute_eligible / assigned_commute_eligible
                if assigned_commute_eligible > 0
                else 0.0
            ),
        }
    )

    output_dir = context.artifact_dir / (
        "portfolios-"
        + content_hash(
            {
                "routes": context.dependencies["assign-routes"]["routes"].sha256,
                "candidates": context.dependencies["generate-candidates"]["candidates"].sha256,
                "parameters": dict(portfolio_parameters),
                "response": dict(response_parameters),
                "annualisation": {
                    "operating_days": appraisal["commute_operating_days_per_year"],
                    "legs_per_day": appraisal["commute_legs_per_day"],
                },
            }
        )[:16]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    saving_path = output_dir / "path_candidate_savings.parquet"
    _write_parquet(saving_path, saving_rows, PATH_SAVING_SCHEMA)

    analyses: list[tuple[str, str, str, str, bool, Mapping[str, ODChoiceSet]]] = []
    for scenario_id, activity in sorted(scenario_activity.items()):
        commute_choices = _choice_sets(
            paths_by_od, od_rows, purpose="commute", activity_by_od=activity
        )
        analyses.append(
            (scenario_id, "network", "commute", "activity_addition", False, commute_choices)
        )
        analyses.append(
            (scenario_id, "appraisal", "commute", "activity_addition", True, commute_choices)
        )
        if high_deprivation_origins:
            analyses.append(
                (
                    scenario_id,
                    "equity",
                    "equity",
                    "activity_addition",
                    True,
                    _choice_sets(
                        paths_by_od,
                        od_rows,
                        purpose="commute",
                        activity_by_od=activity,
                        allowed_origin_supports=high_deprivation_origins,
                        choice_purpose="equity",
                    ),
                )
            )
    analyses.extend(
        (
            "access_baseline",
            purpose,
            purpose,
            "impedance_improvement",
            True,
            _choice_sets(paths_by_od, od_rows, purpose=purpose),
        )
        for purpose in ("school", "everyday", "transit")
    )

    metric_rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    frontier_counts: dict[str, int] = {}
    sequence_counts: dict[str, int] = {}
    metric_cache: dict[
        tuple[str, str, str],
        tuple[
            dict[str, float],
            dict[str, int],
            dict[str, float],
            dict[str, float],
            dict[str, float],
        ],
    ] = {}
    for scenario_id, preset, purpose, objective, score_per_cost, choices in analyses:
        metric_key = (scenario_id, purpose, objective)
        if metric_key not in metric_cache:
            values, affected_counts, additional_users, annual_cycle_km = _single_candidate_metrics(
                choices,
                candidate_to_od,
                costs,
                objective=objective,
                cost_scale=cost_scale,
                annualisation_factor=annualisation_factor,
                response=response,
            )
            relevant_costs = {candidate_id: costs[candidate_id] for candidate_id in values}
            frontier = set(pareto_frontier_benefit_cost(values, relevant_costs))
            metric_id = ":".join(metric_key)
            frontier_counts[metric_id] = len(frontier)
            for candidate_id, value in sorted(values.items()):
                cost = costs[candidate_id]
                metric_rows.append(
                    {
                        "schema_version": PORTFOLIO_OUTPUT_SCHEMA_VERSION,
                        "scenario_id": scenario_id,
                        "purpose": purpose,
                        "objective": objective,
                        "candidate_id": candidate_id,
                        "affected_od_count": affected_counts[candidate_id],
                        "objective_value": value,
                        "additional_cycle_users": additional_users.get(candidate_id),
                        "annual_cycle_km": annual_cycle_km.get(candidate_id),
                        "capital_cost_base_nzd": cost,
                        "objective_per_million_nzd": (
                            value * 1_000_000 / cost if cost > 0 else 0.0
                        ),
                        "pareto_member": candidate_id in frontier,
                    }
                )
            metric_cache[metric_key] = (
                values,
                affected_counts,
                additional_users,
                annual_cycle_km,
                relevant_costs,
            )
        values, _, _, _, relevant_costs = metric_cache[metric_key]
        analysis_id = f"{scenario_id}:{preset}"
        relevant_mapping = {
            candidate_id: sorted(od_ids)
            for candidate_id, od_ids in candidate_to_od.items()
            if candidate_id in values
        }
        sequence = greedy_choice_set_sequence(
            choices,
            relevant_costs,
            relevant_mapping,
            purpose=purpose,
            objective=objective,
            cost_scale=cost_scale,
            budget_nzd=budget_nzd,
            score_per_cost=score_per_cost,
            response=response,
        )
        sequence_counts[analysis_id] = len(sequence)
        step_rows.extend(
            {
                "schema_version": PORTFOLIO_OUTPUT_SCHEMA_VERSION,
                "scenario_id": scenario_id,
                "preset": preset,
                "purpose": purpose,
                "objective": objective,
                "rank": step.rank,
                "candidate_id": step.candidate_id,
                "cumulative_candidate_ids": list(step.cumulative_candidate_ids),
                "marginal_objective": step.marginal_objective,
                "cumulative_objective": step.cumulative_objective,
                "marginal_objective_per_million_nzd": (step.marginal_objective_per_nzd * 1_000_000),
                "cumulative_cost_nzd": step.cumulative_cost_nzd,
            }
            for step in sequence
        )

    metric_rows.sort(
        key=lambda row: (
            str(row["scenario_id"]),
            str(row["purpose"]),
            str(row["candidate_id"]),
        )
    )
    step_rows.sort(key=lambda row: (str(row["scenario_id"]), str(row["preset"]), int(row["rank"])))
    metrics_path = output_dir / "candidate_counterfactuals.parquet"
    steps_path = output_dir / "portfolio_steps.parquet"
    _write_parquet(metrics_path, metric_rows, CANDIDATE_COUNTERFACTUAL_SCHEMA)
    _write_parquet(steps_path, step_rows, PORTFOLIO_STEP_SCHEMA)
    files = {
        path.name: {"size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in (saving_path, metrics_path, steps_path)
    }
    manifest_path = output_dir / "manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "schema_version": PORTFOLIO_OUTPUT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "counterfactual": {
                "choice_set": "up_to_five_routed_plausible_paths_per_selected_od",
                "path_probability_update": (
                    "baseline_path_size_terms_retained_and_probabilities_reweighted_by_cost"
                ),
                "treatment": "exact_candidate_edges_change_lts_impedance_to_lts1",
                "demand_response": ("bounded_continuous_odds_response_for_commute_activity"),
                "non_commute_objective": (
                    "eligible_weighted_proportional_generalized_cost_improvement"
                ),
                "cumulative_recomputation": True,
                "sequence_algorithm": (
                    "exact_sparse_incremental_marginals_over_overlapping_od_sets"
                ),
                "candidate_limit": None,
                "budget_nzd": budget_nzd,
                "commute_annualisation": {
                    "operating_days_per_year": appraisal["commute_operating_days_per_year"],
                    "legs_per_day": appraisal["commute_legs_per_day"],
                    "distance": "shortest_physical_routed_distance_km",
                },
                "cross_purpose_units_are_not_summed": True,
            },
            "presets": {
                "network": "maximise cumulative commute activity subject to budget",
                "school": "maximise school access impedance improvement per NZD",
                "everyday": "maximise everyday access impedance improvement per NZD",
                "transit": "maximise transit access impedance improvement per NZD",
                "appraisal": "screen commute activity improvement per NZD before appraisal",
                "equity": (
                    "maximise additional usual commute cyclists from NZDep2023 decile 8-10 "
                    "origins per NZD"
                    if high_deprivation_origins
                    else "unavailable_without_registered_nzdep_source"
                ),
            },
            "equity": {
                **equity_context,
                "scenario_activity": {
                    scenario_id: sum(
                        float(activity.get(od_id, 0.0))
                        for od_id, row in od_rows.items()
                        if row[0] == "commute" and row[4] in high_deprivation_origins
                    )
                    for scenario_id, activity in sorted(scenario_activity.items())
                },
                "interpretation": (
                    "distributional subgroup objective, not a causal equity effect or welfare "
                    "weight"
                ),
            },
            "row_counts": {
                "path_candidate_savings": len(saving_rows),
                "matched_path_edge_records": matched_path_edges,
                "candidate_counterfactuals": len(metric_rows),
                "portfolio_steps": len(step_rows),
            },
            "frontier_counts": frontier_counts,
            "sequence_counts": sequence_counts,
            "publication_grade_ready": False,
            "publication_blockers": [
                "full_network_low_stress_reserved_for_separate_research",
                "appraisal_inputs_require_local_review_for_decision_use",
                "stratified_manual_audits_required_for_decision_use",
            ],
            "files": files,
        },
    )
    return StageResult(
        {"portfolios": output_dir},
        {
            "row_counts": {
                "path_candidate_savings": len(saving_rows),
                "candidate_counterfactuals": len(metric_rows),
                "portfolio_steps": len(step_rows),
            }
        },
    )
