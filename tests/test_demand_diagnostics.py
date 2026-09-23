from math import isclose

import pytest

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.portfolio_analysis import ChoicePath, ODChoiceSet
from cycling_investment_workbench.research.demand_diagnostics import diagnose_candidate


def test_concentration_reports_weighted_record_influence_not_rider_counts():
    choices = [
        ODChoiceSet(str(n), "commute", n, n / 10, (ChoicePath(str(n), 100, 1, {"P": 20}),))
        for n in (100, 900)
    ]
    expected = 1000 * (0.125 / 1.025 - 0.1)
    result = diagnose_candidate(
        "P",
        choices,
        cost_scale=0.002,
        response=DemandResponseParameters(),
        expected_additional=expected,
    )
    assert result["affectedOdRecords"] == 2
    assert result["affectedEligible"] == 1000
    assert isclose(result["largestOdContributionShare"], 0.9)
    assert isclose(result["topThreeOdContributionShare"], 1)
    gains = [r["additionalUsualCommuters"] for r in result["elasticitySensitivity"]]
    assert gains[0] < gains[1] < gains[2]
    assert isclose(gains[1], expected)
    with pytest.raises(ValueError, match="reproduce"):
        diagnose_candidate(
            "P",
            choices,
            cost_scale=0.002,
            response=DemandResponseParameters(),
            expected_additional=999,
        )


def test_no_gain_has_no_concentration():
    choice = ODChoiceSet("zero", "commute", 100, 10, (ChoicePath("p", 100, 1, {}),))
    result = diagnose_candidate(
        "P", [choice], cost_scale=0.002, response=DemandResponseParameters(), expected_additional=0
    )
    assert result["largestOdContributionShare"] == 0
