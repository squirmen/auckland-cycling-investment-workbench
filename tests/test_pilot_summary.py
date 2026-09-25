"""The public pilot summary must keep scope, provenance and denominators paired."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/summarise_span_pilots.py"


def report():
    return {
        "runId": "example",
        "radiusM": 4000,
        "seed": 7,
        "standard": {},
        "budget": 20e6,
        "parameters": {},
        "implementationHash": "code",
        "experimentScriptHash": "script",
        "intersectionContext": None,
        "sourceHashes": dict.fromkeys(
            [
                "topology",
                "odLedger",
                "candidateLedger",
                "candidateExclusionLedger",
                "scenarioOdLedger",
            ],
            "hash",
        ),
        "area": "Example",
        "anchorCandidateId": "candidate",
        "centre": [174, -36],
        "graph": {},
        "sample": {},
        "cropCoverage": {},
        "candidateCoverage": {},
        "searchSummary": {},
        "elapsedS": 1,
        "baseline": {},
        "searchComplete": True,
        "solutions": [],
        "journeys": [
            {
                "allProjectsDiagnostic": {
                    "conclusiveNoRoute": True,
                    "stopReason": "exhausted",
                    "witnessStressGaps": {
                        "untreatedPhysicalEdges": 3,
                        "physicalEdgesStillHighStressAfterTreatment": 0,
                        "turnMovementsStillHighStress": 0,
                        "untreatedEdgesByReason": {"short": 2, "boundary": 1},
                    },
                    "shortConnectorCheck": {
                        "routeFound": True,
                        "conclusiveNoRoute": False,
                        "stopReason": "first_route",
                    },
                }
            }
        ],
        "shortConnectorDiagnostic": {
            "sourceCandidateManifestSha256": "manifest",
            "screeningCostPerM": 6000,
            "sourceMinimumLengthM": 100,
        },
    }


def run_summary(tmp_path, *reports):
    paths = []
    for index, item in enumerate(reports):
        path = tmp_path / f"input-{index}.json"
        path.write_text(json.dumps(item))
        paths.append(str(path))
    output = tmp_path / "summary.json"
    process = subprocess.run(
        [sys.executable, str(SCRIPT), "--reports", *paths, "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    return process, output


def test_summary_counts_journeys_not_edges_and_keeps_diagnostic_separate(tmp_path):
    process, path = run_summary(tmp_path, report())
    assert process.returncode == 0, process.stderr
    result = json.loads(path.read_text())
    area = result["areas"][0]
    assert area["stressGapReasonWitnessCounts"] == {"short": 1, "boundary": 1}
    assert area["shortConnectorDiagnostic"]["acceptableRouteFound"] == 1
    assert area["shortConnectorDiagnostic"]["foundAfterConclusiveFailure"] == 1
    assert area["shortConnectorDiagnostic"]["foundAfterPreviouslyCappedSearch"] == 0
    assert area["shortConnectorDiagnostic"]["testedJourneys"] == 1
    assert area["solutions"] == []
    assert "journeys" not in area
    assert result["intersectionEvidenceSha256"] is None


@pytest.mark.parametrize("changed", ["budget", "exclusion_hash", "connector_rate", "intersections"])
def test_summary_refuses_unpaired_evidence(tmp_path, changed):
    first = report()
    second = deepcopy(first)
    if changed == "budget":
        second["budget"] = 100e6
    elif changed == "exclusion_hash":
        second["sourceHashes"]["candidateExclusionLedger"] = "different"
    elif changed == "connector_rate":
        second["shortConnectorDiagnostic"]["screeningCostPerM"] = 1
    else:
        second["intersectionContext"] = {"evidenceSha256": "different", "scenario": "default"}
    process, path = run_summary(tmp_path, first, second)
    assert process.returncode != 0
    assert "differs" in process.stderr or "differ" in process.stderr
    assert not path.exists()


def test_summary_accepts_disabled_connector_diagnostic(tmp_path):
    item = report()
    item["shortConnectorDiagnostic"] = None
    item["journeys"] = [{"allProjectsDiagnostic": None}]
    process, path = run_summary(tmp_path, item)
    assert process.returncode == 0, process.stderr
    assert json.loads(path.read_text())["areas"][0]["shortConnectorDiagnostic"] is None


def test_budgeted_summary_does_not_copy_future_raw_journey_fields(tmp_path):
    item = report()
    item["budgetedConnectorComparison"] = {
        "status": "test",
        "sameJourneysAndWeights": True,
        "originalRouteColumnsRetained": 0,
        "routeColumns": 1,
        "journeysWithRouteColumns": 1,
        "searchStopReasons": {},
        "searchComplete": True,
        "labelsExpanded": 1,
        "elapsedS": 0.1,
        "note": "test",
        "solutions": [],
        "privateJourneyCoordinates": [1, 2],
    }
    solution = {
        "selected": ["public-project"],
        "capital_cost": 10,
        "served_weight": 1,
        "served_journeys": 1,
        "method": "route_packages_milp",
        "optimal_within_columns": True,
        "relative_gap": 0,
        "budget": 20,
        "shortConnectorCount": 1,
        "shortConnectorCostNzd": 10,
        "checkedRouteWitnesses": 1,
        "projectOverlapWithReference": 1,
        "privateJourneyCoordinates": [1, 2],
    }
    check = {
        "maxLabelsPerSearch": 100,
        "retainedRouteColumns": 0,
        "routeColumns": 1,
        "journeysWithRouteColumns": 1,
        "searchStopReasons": {"exhausted": 1},
        "searchComplete": True,
        "labelsExpanded": 1,
        "elapsedS": 0.1,
        "solutions": [solution],
        "preferredSolutions": [solution],
        "privateJourneyCoordinates": [1, 2],
    }
    item["budgetedConnectorComparison"].update(
        {
            "maxLabelsPerSearch": 100,
            "retainedRouteColumns": 0,
            "preferredSolutions": [solution],
            "searchLimitChecks": [check],
            "fixedConnectorCostSensitivity": {
                "status": "test",
                "budget": 20,
                "sameRouteColumns": True,
                "reroutedForEachCostCase": False,
                "referenceSelected": ["public-project"],
                "referenceServedWeight": 1,
                "referenceServedJourneys": 1,
                "routeColumns": 1,
                "note": "test",
                "privateJourneyCoordinates": [1, 2],
                "cases": [
                    {
                        "fixedAllowancePerConnectorNzd": 0,
                        "fixedProgrammeCostNzd": 10,
                        "fixedProgrammeAffordable": True,
                        "affordableRouteColumns": 1,
                        "solutions": [solution],
                        "preferredSolutions": [solution],
                        "privateJourneyCoordinates": [1, 2],
                    }
                ],
            },
        }
    )
    process, path = run_summary(tmp_path, item)
    assert process.returncode == 0, process.stderr
    comparison = json.loads(path.read_text())["areas"][0]["budgetedConnectorComparison"]
    assert comparison["routeColumns"] == 1
    assert "privateJourneyCoordinates" not in json.dumps(comparison)
    assert comparison["searchLimitChecks"][0]["maxLabelsPerSearch"] == 100
    case = comparison["fixedConnectorCostSensitivity"]["cases"][0]
    assert case["fixedProgrammeAffordable"]
    assert case["solutions"][0]["projectOverlapWithReference"] == 1
    assert case["preferredSolutions"][0]["method"] == "route_packages_milp"
    assert comparison["preferredSolutions"][0]["selected"] == ["public-project"]
    assert comparison["searchLimitChecks"][0]["preferredSolutions"][0]["capital_cost"] == 10
