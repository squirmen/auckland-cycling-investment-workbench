import hashlib
import json
from pathlib import Path

import pytest

from cycling_investment_workbench.demo import (
    PURPOSE_IDS,
    SCENARIO_IDS,
    UNCERTAINTY_PARAMETER_SPECS,
    run_miniature_city,
    web_export_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "miniature_city_expected.json"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def test_end_to_end_result_matches_publication_fixture() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert run_miniature_city() == expected


def test_demo_is_deterministic_and_explicitly_eight_percent() -> None:
    first = run_miniature_city()
    second = run_miniature_city()
    assert (
        hashlib.sha256(canonical_bytes(first)).hexdigest()
        == hashlib.sha256(canonical_bytes(second)).hexdigest()
    )
    assert first["demand"]["scenario_cycle"] / first["demand"]["eligible"] == pytest.approx(0.08)


def test_web_adapter_has_all_exact_scenarios_purposes_and_layers() -> None:
    payload = web_export_payload()
    manifest = payload["manifest"]
    assert manifest["dataStatus"] == "synthetic_demo"
    assert len(manifest["configSha256"]) == 64
    assert tuple(item["id"] for item in manifest["scenarios"]) == SCENARIO_IDS
    assert tuple(item["id"] for item in manifest["purposes"]) == PURPOSE_IDS
    assert set(payload["layers"]) == {
        "cells",
        "network",
        "candidates",
        "programmes",
        "counters",
        "safety",
    }
    assert payload["manifest"]["validation"] == {
        "periodLabel": "Synthetic fixture; no calendar period",
        "counterCount": 2,
        "matchedCount": 2,
        "coverage": 1.0,
        "purposeAlignment": "Synthetic daily cycling counts",
        "status": "synthetic_fixture",
    }
    assert len(payload["layers"]["programmes"]["features"]) == 1
    assert set(manifest["summaries"]) == set(SCENARIO_IDS)
    assert all(
        set(manifest["portfolios"][scenario]) == set(PURPOSE_IDS) for scenario in SCENARIO_IDS
    )


def test_candidate_contract_contains_exact_edges_and_complete_metrics() -> None:
    payload = web_export_payload()
    candidates = payload["layers"]["candidates"]["features"]
    metric_keys = {
        "available",
        "capitalCostNzd",
        "lifecycleCostNzd",
        "objectiveValue",
        "objectiveUnit",
        "additionalCycleUsers",
        "annualBikeKmDelta",
        "odLowStressShareDelta",
        "bcrP5",
        "bcrP50",
        "bcrP95",
        "routeCoverage",
        "meanRank",
        "topKProbability",
        "frontierProbability",
        "warnings",
    }
    graph_edge_ids = {
        feature["properties"]["edgeId"] for feature in payload["layers"]["network"]["features"]
    }
    for feature in candidates:
        properties = feature["properties"]
        assert set(properties["edgeIds"]).issubset(graph_edge_ids)
        assert set(properties["metrics"]) == set(SCENARIO_IDS)
        for scenario in SCENARIO_IDS:
            assert set(properties["metrics"][scenario]) == set(PURPOSE_IDS)
            for purpose in PURPOSE_IDS:
                assert set(properties["metrics"][scenario][purpose]) == metric_keys


def test_network_layer_exposes_sketching_fields() -> None:
    network = web_export_payload()["layers"]["network"]
    required = {
        "edgeId",
        "u",
        "v",
        "protected",
        "lengthKm",
        "capitalCostNzd",
        "dailyTripsPotential",
        "odLowStressSharePotential",
    }
    assert network["features"]
    assert all(required.issubset(feature["properties"]) for feature in network["features"])
    assert all(len(feature["geometry"]["coordinates"]) >= 2 for feature in network["features"])


def test_purpose_surfaces_use_distinct_demand_and_routing_results() -> None:
    payload = web_export_payload()
    summaries = payload["manifest"]["summaries"]["commute_8pct"]
    purpose_trip_totals = {
        purpose: summary["activityValue"] for purpose, summary in summaries.items()
    }
    assert len(set(purpose_trip_totals.values())) == len(PURPOSE_IDS)
    assert summaries["network"]["activityUnit"] == "weighted synthetic daily cycle trips"
    assert "share" not in summaries["network"]["activityUnit"]
    main_metrics = payload["layers"]["candidates"]["features"][0]["properties"]["metrics"][
        "commute_8pct"
    ]
    purpose_candidate_effects = {
        purpose: metric["objectiveValue"] for purpose, metric in main_metrics.items()
    }
    assert len(set(purpose_candidate_effects.values())) > 3


def test_cumulative_portfolios_are_monotone_without_resetting_demand() -> None:
    portfolios = web_export_payload()["manifest"]["portfolios"]
    for scenario in SCENARIO_IDS:
        for purpose in PURPOSE_IDS:
            steps = portfolios[scenario][purpose]
            objectives = [step["cumulativeObjective"] for step in steps]
            assert objectives == sorted(objectives)


def test_connectivity_summary_exports_units_denominator_and_threshold_context() -> None:
    summaries = web_export_payload()["manifest"]["summaries"]
    for scenario_id in SCENARIO_IDS:
        for purpose_id in PURPOSE_IDS:
            summary = summaries[scenario_id][purpose_id]
            assert 0 <= summary["odLowStressShare"] <= 1
            assert summary["odLowStressDenominatorWeight"] >= 0
            assert summary["odLowStressConnectedWeight"] <= summary["odLowStressDenominatorWeight"]
            assert summary["purpose"] == purpose_id
            assert summary["maximumLts"] == 2
            assert summary["maximumDetourRatio"] == 1.5


def test_integrated_uncertainty_covers_all_material_method_dimensions() -> None:
    expected = {
        "suppression_factor",
        "pct_uptake_factor",
        "route_choice_factor",
        "stress_penalty_factor",
        "topology_coverage_factor",
        "capital_cost_factor",
        "maintenance_cost_factor",
        "renewal_cost_factor",
        "benefit_value_factor",
        "discount_rate",
        "ebike_share",
        "demand_response_elasticity",
    }
    assert {parameter.name for parameter in UNCERTAINTY_PARAMETER_SPECS} == expected
    exported = web_export_payload()["uncertainty"]
    assert {parameter["name"] for parameter in exported["parameters"]} == expected


def test_browser_contract_has_no_composite_master_score() -> None:
    payload = web_export_payload()
    assert "decisionSupport" not in payload["manifest"]
    assert payload["manifest"]["capabilities"]["sketchEvaluation"] == (
        "requires_pipeline_evaluation"
    )
    assert payload["manifest"]["capabilities"]["appraisal"] == "research_only"
    for scenario_id in SCENARIO_IDS:
        for purpose_id in PURPOSE_IDS:
            steps = payload["manifest"]["portfolios"][scenario_id][purpose_id]
            assert all("presetScore" not in step for step in steps)
            assert any(step["paretoMember"] for step in steps)
