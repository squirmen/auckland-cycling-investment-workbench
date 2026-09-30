"""OD contribution concentration and declared response sensitivities.

Neither metric is a confidence interval. Diagnostics expose leverage in a
weighted sample; they do not decide the correct uptake elasticity.
"""

from collections.abc import Sequence
from math import isclose

from ..candidates import DemandResponseParameters
from ..portfolio_analysis import ODChoiceSet, evaluate_choice_set


def diagnose_candidate(
    candidate_id: str,
    choices: Sequence[ODChoiceSet],
    *,
    cost_scale: float,
    response: DemandResponseParameters,
    expected_additional: float,
) -> dict:
    selected = frozenset({candidate_id})
    additions, savings = [], 0.0
    for choice in choices:
        evaluated = evaluate_choice_set(choice, selected, cost_scale=cost_scale, response=response)
        additions.append(evaluated.activity_addition)
        before = sum(p.baseline_cost * p.baseline_probability for p in choice.paths)
        savings += choice.eligible * (1 - evaluated.expected_generalized_cost / before)
    total = sum(additions)
    if not isclose(total, expected_additional, abs_tol=1e-7):
        raise ValueError("OD recomputation does not reproduce the displayed estimate")
    additions.sort(reverse=True)
    eligible = sum(c.eligible for c in choices)
    return {
        "candidateId": candidate_id,
        "affectedOdRecords": len(choices),
        "affectedEligible": eligible,
        "affectedStartingCycleCommuters": sum(c.baseline_activity for c in choices),
        "additionalUsualCommuters": total,
        "largestOdContributionShare": additions[0] / total if total else 0.0,
        "topThreeOdContributionShare": sum(additions[:3]) / total if total else 0.0,
        "meanRelativeCostSavingWeightedByEligible": savings / eligible if eligible else 0.0,
        "elasticitySensitivity": [
            {
                "elasticity": eta,
                "additionalUsualCommuters": sum(
                    evaluate_choice_set(
                        c,
                        selected,
                        cost_scale=cost_scale,
                        response=DemandResponseParameters(eta, response.minimum_probability),
                    ).activity_addition
                    for c in choices
                ),
            }
            for eta in (0.5, 1.0, 2.0)
        ],
    }
