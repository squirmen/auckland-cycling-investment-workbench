import json
import subprocess
import sys
from math import isclose
from pathlib import Path

import pytest

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.portfolio_analysis import (
    ChoicePath,
    ODChoiceSet,
    evaluate_choice_set,
)
from cycling_investment_workbench.research.stability import (
    concentration,
    grouped_contributions,
    source_cell_influence,
)


def market():
    return {
        str(i): ODChoiceSet(
            str(i),
            "commute",
            100,
            10,
            (ChoicePath(str(i), 100, 1, {"A": 10, "B": 20}),),
        )
        for i in range(3)
    }


def test_grouped_contributions_cluster_cells_and_deduplicate_joint_gain():
    choices = market()
    groups = {"0": "cell-x", "1": "cell-x", "2": "cell-y"}
    response = DemandResponseParameters()
    standalone, package = grouped_contributions(
        choices,
        groups,
        {"A": ["0", "0", "1", "2"], "B": ["0", "1", "2"], "C": []},
        frozenset({"A", "B"}),
        cost_scale=0.002,
        response=response,
    )
    expected = evaluate_choice_set(
        choices["0"], frozenset({"A", "B"}), cost_scale=0.002, response=response
    ).activity_addition
    assert isclose(package["cell-x"], 2 * expected)
    assert isclose(sum(package.values()), 3 * expected)
    assert not isclose(sum(package.values()), sum(sum(v.values()) for v in standalone.values()))
    assert standalone["C"] == {}
    assert isclose(concentration(standalone["A"])["largestSourceCellShare"], 2 / 3)
    assert isclose(concentration(standalone["A"])["effectiveContributingSourceCells"], 1.8)


def test_each_deletion_is_shared_across_all_candidates_and_reports_no_source_ids():
    report = source_cell_influence(
        {
            "A": {"private-x": 90, "private-y": 10},
            "B": {"private-x": 80, "private-y": 30},
            "C": {"private-z": 50},
            "D": {},
        },
        {"private-x": 120, "private-y": 30},
        ["A", "B"],
        source_cells={
            "od-0": "private-x",
            "od-1": "private-x",
            "od-2": "private-y",
            "od-3": "private-z",
        },
        eligible={"od-0": 100, "od-1": 200, "od-2": 400, "od-3": 500},
        top_k=2,
    )
    assert report["baselineStandaloneTopCandidateIds"] == ["B", "A"]
    assert len(report["cases"]) == 1  # Both leading candidates share their largest cell.
    case = report["cases"][0]
    assert case["standaloneTopCandidateIds"] == ["C", "B"]
    assert case["standaloneTopOverlapShare"] == 0.5
    assert case["excludedSampledRecords"] == 2
    assert case["excludedEligibleWeight"] == 300
    assert case["fixedProgrammeAdditionalUsualCommuters"] == 30
    assert case["fixedProgrammeGainRemovedShare"] == 0.8
    assert {r["candidateId"]: r["additionalUsualCommuters"] for r in case["candidateRanks"]} == {
        "A": 10,
        "B": 30,
    }
    serialised = json.dumps(report)
    assert "private-x" not in serialised and "od-0" not in serialised


def test_zero_gain_and_empty_package_are_well_defined():
    report = source_cell_influence(
        {"A": {}, "B": {}}, {}, ["B"], source_cells={}, eligible={}, top_k=12
    )
    assert report["cases"] == []
    assert report["baselineStandaloneTopCandidateIds"] == []
    assert report["fixedProgramme"]["additionalUsualCommuters"] == 0
    assert report["auditedCandidates"][0]["baselineStandaloneRank"] == 2
    assert report["auditedCandidates"][0]["maximumRankAcrossTestedDeletions"] == 2
    assert concentration({})["effectiveContributingSourceCells"] == 0
    _, package = grouped_contributions(
        market(),
        {"0": "x", "1": "x", "2": "y"},
        {"A": ["0", "1", "2"]},
        frozenset(),
        cost_scale=0,
        response=DemandResponseParameters(),
    )
    assert package == {}


def test_deterministic_ties_and_input_order_independence():
    kwargs = {"source_cells": {"a": "x", "b": "y"}, "eligible": {"a": 100, "b": 100}, "top_k": 2}
    left = source_cell_influence({"B": {"y": 20}, "A": {"x": 20}}, {}, [], **kwargs)
    right = source_cell_influence({"A": {"x": 20}, "B": {"y": 20}}, {}, [], **kwargs)
    assert left == right
    assert left["baselineStandaloneTopCandidateIds"] == ["A", "B"]
    assert len(left["cases"]) == 2
    assert left["cases"][0]["fixedProgrammeGainRemovedShare"] == 0


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_invalid_contributions_are_rejected(bad):
    with pytest.raises(ValueError, match="finite and non-negative"):
        concentration({"x": bad})


@pytest.mark.parametrize(
    "change, message",
    [
        ({"top_k": 0}, "positive integer"),
        ({"top_k": True}, "positive integer"),
        ({"published_ids": ["missing"]}, "unique and known"),
        ({"published_ids": ["A", "A"]}, "unique and known"),
        ({"eligible": {}}, "mappings must agree"),
        ({"eligible": {"a": -1}}, "weights must be finite"),
        ({"standalone": {"A": {"unknown": 1}}}, "unknown source cell"),
        ({"package": {"unknown": 1}}, "unknown source cell"),
    ],
)
def test_invalid_influence_inputs_are_rejected(change, message):
    args = dict(
        standalone={"A": {"x": 1}},
        package={"x": 1},
        published_ids=["A"],
        source_cells={"a": "x"},
        eligible={"a": 100},
    )
    args.update(change)
    with pytest.raises(ValueError, match=message):
        source_cell_influence(**args)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"source_cells": {}}, "exactly one"),
        ({"source_cells": {"0": "", "1": "x", "2": "y"}}, "identifiers must be valid"),
        ({"selected": frozenset({"missing"})}, "unknown candidate"),
        ({"candidate_to_ods": {"": ["0"]}}, "must not be empty"),
        ({"candidate_to_ods": {"A": ["missing"]}}, "unknown OD"),
        ({"cost_scale": -1}, "cost scale"),
    ],
)
def test_invalid_grouping_inputs_are_rejected(change, message):
    args = dict(
        choices=market(),
        source_cells={"0": "x", "1": "x", "2": "y"},
        candidate_to_ods={"A": ["0"]},
        selected=frozenset(),
        cost_scale=0.002,
        response=DemandResponseParameters(),
    )
    args.update(change)
    with pytest.raises(ValueError, match=message):
        grouped_contributions(**args)


@pytest.mark.parametrize("target", ["run", "web", "repository-web"])
def test_audit_cli_refuses_to_write_inside_source_or_browser_trees(tmp_path, target):
    repository = Path(__file__).resolve().parents[1]
    root, web = tmp_path / "source", tmp_path / "browser"
    output_root = {"run": root, "web": web, "repository-web": repository / "web"}[target]
    output = output_root / "must-not-be-written.json"
    result = subprocess.run(
        [
            sys.executable,
            str(repository / "scripts/audit_span_stability.py"),
            "--run",
            str(root),
            "--web",
            str(web),
            "--output",
            str(output),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "outside the source run and browser tree" in result.stderr
    assert not output.exists()


def test_audit_cli_rejects_invalid_budget_before_reading_data(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(repository / "scripts/audit_span_stability.py"),
            "--run",
            str(tmp_path / "missing"),
            "--budget",
            "nan",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "budget must be finite" in result.stderr
