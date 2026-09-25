import json

import pytest

from cycling_investment_workbench.research.support import summarise_support, usage_bounds


def fixture():
    records = [
        {
            "id": "private-a",
            "source_cell_id": "private-cell",
            "eligible": 10,
            "route_sample_selected": True,
        },
        {
            "id": "private-b",
            "source_cell_id": "private-cell",
            "eligible": 20,
            "route_sample_selected": False,
        },
        {
            "id": "private-c",
            "source_cell_id": "private-cell",
            "eligible": 30,
            "route_sample_selected": False,
        },
    ]
    outcomes = {
        "private-a": {
            "status": "assigned",
            "candidateProbabilities": {"P": 1},
            "publishedRouteParity": True,
        },
        "private-b": {"status": "assigned", "candidateProbabilities": {"P": 0.5}},
        "private-c": {"status": "unassigned", "failureReason": "disconnected"},
    }
    return records, outcomes


def test_failures_are_unknown_not_zero_use_and_source_mass_is_conserved():
    records, outcomes = fixture()
    result = usage_bounds(records, outcomes, "P")
    assert result == {
        "eligibleMass": 60,
        "knownRouteUseMass": 20,
        "unassignedMass": 30,
        "routeUseShareLower": 1 / 3,
        "routeUseShareUpper": 5 / 6,
    }
    report = summarise_support(records, outcomes, ["P"], seeds=[1, 2, 3])
    assert report["sourceEligibleMass"] == 60
    assert report["assignedRecords"] == 2
    assert report["failureReasons"] == {"disconnected": 1}
    assert report["publishedSampleRouteParity"]
    assert "private-" not in json.dumps(report)
    # Census enumeration is identical for every seed when m exceeds support size.
    for replicate in report["replicates"][3:]:
        assert replicate["estimatedEligibleMass"] == 60
        assert replicate["candidateUsage"][0]["knownRouteUseMass"] == 20
    # HT total is not silently normalised to the known source total.
    assert any(r["estimatedEligibleMass"] != 60 for r in report["replicates"][:3])
    assert records[0]["eligible"] == 10


def test_replicates_do_not_depend_on_input_order():
    records, outcomes = fixture()
    left = summarise_support(records, outcomes, ["P"], seeds=[7, 8])
    right = summarise_support(list(reversed(records)), outcomes, ["P"], seeds=[7, 8])
    assert left == right


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_mass_or_probability_fails_closed(bad):
    records, outcomes = fixture()
    records[0]["eligible"] = bad
    with pytest.raises(ValueError, match="mass"):
        usage_bounds(records, outcomes, "P")
    records[0]["eligible"] = 10
    outcomes["private-a"]["candidateProbabilities"]["P"] = bad
    with pytest.raises(ValueError, match="probability"):
        usage_bounds(records, outcomes, "P")


@pytest.mark.parametrize(
    "case",
    ["empty", "duplicate", "missing", "zero", "status", "cells", "drivers", "seeds", "sizes"],
)
def test_invalid_support_inputs_are_rejected(case):
    records, outcomes = fixture()
    options = {"drivers": ["P"], "seeds": [1]}
    if case == "empty":
        records = []
    elif case == "duplicate":
        records.append(records[0])
    elif case == "missing":
        del outcomes["private-a"]
    elif case == "zero":
        for r in records:
            r["eligible"] = 0
    elif case == "status":
        outcomes["private-a"]["status"] = "unknown"
    elif case == "cells":
        records[0]["source_cell_id"] = "another-cell"
    elif case == "drivers":
        options["drivers"] = []
    elif case == "seeds":
        options["seeds"] = [1, 1]
    else:
        options["sample_sizes"] = [True]
    with pytest.raises(ValueError):
        summarise_support(records, outcomes, **options)
