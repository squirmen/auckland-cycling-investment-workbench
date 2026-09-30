"""Deterministic source-cell deletion stress tests on retained route support.

These are leverage diagnostics, not resampled demand, confidence intervals or
new investment recommendations. Every case removes the same source cell from
all candidates. No other weights, probabilities, routes or costs are changed.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from math import fsum, isfinite

from ..candidates import DemandResponseParameters
from ..portfolio_analysis import ODChoiceSet, evaluate_choice_set


def grouped_contributions(
    choices: Mapping[str, ODChoiceSet],
    source_cells: Mapping[str, str],
    candidate_to_ods: Mapping[str, Sequence[str]],
    selected: frozenset[str],
    *,
    cost_scale: float,
    response: DemandResponseParameters,
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Evaluate standalone candidates and the fixed package without double counting."""
    if set(choices) != set(source_cells):
        raise ValueError("every choice must have exactly one source-cell mapping")
    if any(choice.id != key or not source_cells[key] for key, choice in choices.items()):
        raise ValueError("choice keys and source-cell identifiers must be valid")
    if not selected <= candidate_to_ods.keys():
        raise ValueError("selected package references an unknown candidate")
    if not isfinite(cost_scale) or cost_scale < 0:
        raise ValueError("cost scale must be finite and non-negative")
    standalone: dict[str, dict[str, float]] = {}
    package_ods: set[str] = set()
    for candidate, od_ids in sorted(candidate_to_ods.items()):
        if not candidate:
            raise ValueError("candidate identifiers must not be empty")
        unique_ods = sorted(set(od_ids))
        if not set(unique_ods) <= choices.keys():
            raise ValueError("candidate references an unknown OD")
        if candidate in selected:
            package_ods.update(unique_ods)
        grouped: defaultdict[str, list[float]] = defaultdict(list)
        for od in unique_ods:
            gain = evaluate_choice_set(
                choices[od], frozenset({candidate}), cost_scale=cost_scale, response=response
            ).activity_addition
            if gain > 0:
                grouped[source_cells[od]].append(gain)
        standalone[candidate] = {group: fsum(values) for group, values in grouped.items()}
    package: defaultdict[str, list[float]] = defaultdict(list)
    for od in sorted(package_ods):
        gain = evaluate_choice_set(
            choices[od], selected, cost_scale=cost_scale, response=response
        ).activity_addition
        if gain > 0:
            package[source_cells[od]].append(gain)
    return standalone, {group: fsum(values) for group, values in package.items()}


def concentration(values: Mapping[str, float]) -> dict:
    """Effective contributing cells measures concentration, not survey sample precision."""
    if any(not isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("contributions must be finite and non-negative")
    positive = sorted((value for value in values.values() if value > 0), reverse=True)
    total = fsum(positive)
    return {
        "additionalUsualCommuters": total,
        "positiveContributingSourceCells": len(positive),
        "largestSourceCellShare": positive[0] / total if total else 0.0,
        "topThreeSourceCellShare": fsum(positive[:3]) / total if total else 0.0,
        "effectiveContributingSourceCells": (
            1 / fsum((value / total) ** 2 for value in positive) if total else 0.0
        ),
    }


def source_cell_influence(
    standalone: Mapping[str, Mapping[str, float]],
    package: Mapping[str, float],
    published_ids: Sequence[str],
    *,
    source_cells: Mapping[str, str],
    eligible: Mapping[str, float],
    top_k: int = 12,
) -> dict:
    """Delete the largest contributor of each leading/published candidate once.

    Only anonymous case labels and aggregate outputs leave this function.
    Standalone ranking is not the cumulative, budget-constrained build order.
    The published package is held fixed: it is evaluated, not reoptimised.
    """
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if len(set(published_ids)) != len(published_ids) or not set(published_ids) <= standalone.keys():
        raise ValueError("published candidates must be unique and known")
    if set(source_cells) != set(eligible) or any(not group for group in source_cells.values()):
        raise ValueError("source-cell and eligible-population mappings must agree")
    if any(not isfinite(value) or value < 0 for value in eligible.values()):
        raise ValueError("eligible weights must be finite and non-negative")
    known_groups = set(source_cells.values())
    if set(package) - known_groups or any(
        set(values) - known_groups for values in standalone.values()
    ):
        raise ValueError("contribution references an unknown source cell")
    totals = {
        cid: concentration(values)["additionalUsualCommuters"] for cid, values in standalone.items()
    }
    package_summary = concentration(package)
    order = sorted(totals, key=lambda cid: (-totals[cid], cid))
    ranks = {cid: rank for rank, cid in enumerate(order, 1)}
    leading = [cid for cid in order if totals[cid] > 0][:top_k]
    focus = sorted(set(leading) | set(published_ids), key=lambda cid: ranks[cid])
    drivers: defaultdict[str, list[str]] = defaultdict(list)
    for cid in focus:
        positive = {group: gain for group, gain in standalone[cid].items() if gain > 0}
        if positive:
            group = min(positive, key=lambda group: (-positive[group], group))
            drivers[group].append(cid)
    counts = Counter(source_cells.values())
    group_population: defaultdict[str, list[float]] = defaultdict(list)
    for od, group in source_cells.items():
        group_population[group].append(eligible[od])
    tested_ranks: defaultdict[str, list[int]] = defaultdict(list)
    cases = []
    leading_set = set(leading)
    for index, group in enumerate(sorted(drivers), 1):
        scores = {
            cid: max(0.0, total - standalone[cid].get(group, 0.0)) for cid, total in totals.items()
        }
        case_order = sorted(scores, key=lambda cid: (-scores[cid], cid))
        case_ranks = {cid: rank for rank, cid in enumerate(case_order, 1)}
        case_top = [cid for cid in case_order if scores[cid] > 0][:top_k]
        for cid in focus:
            tested_ranks[cid].append(case_ranks[cid])
        loss = package.get(group, 0.0)
        cases.append(
            {
                "case": f"case-{index:02d}",
                "dominantContributorToCandidateIds": drivers[group],
                "excludedSourceCells": 1,
                "excludedSampledRecords": counts[group],
                "excludedEligibleWeight": fsum(group_population[group]),
                "standaloneTopCandidateIds": case_top,
                "standaloneTopOverlapShare": (
                    len(leading_set.intersection(case_top)) / len(leading_set)
                    if leading_set
                    else 1.0
                ),
                "fixedProgrammeAdditionalUsualCommuters": max(
                    0.0, package_summary["additionalUsualCommuters"] - loss
                ),
                "fixedProgrammeGainRemovedShare": (
                    loss / package_summary["additionalUsualCommuters"]
                    if package_summary["additionalUsualCommuters"]
                    else 0.0
                ),
                "candidateRanks": [
                    {
                        "candidateId": cid,
                        "rank": case_ranks[cid],
                        "additionalUsualCommuters": scores[cid],
                    }
                    for cid in focus
                ],
            }
        )
    return {
        "status": "fixed_support_source_cell_deletion_stress_test",
        "candidateCount": len(standalone),
        "topK": top_k,
        "caseSelection": (
            "Largest contributor to each positive top-K standalone or published candidate; "
            "unique source cells only."
        ),
        "rankingTieBreak": (
            "Standalone benefit descending, then candidate ID ascending; "
            "zero-score candidates retain deterministic ranks."
        ),
        "sampledRecords": len(source_cells),
        "sampledSourceCells": len(known_groups),
        "eligibleWeight": fsum(eligible.values()),
        "baselineStandaloneTopCandidateIds": leading,
        "fixedProgramme": {"candidateIds": list(published_ids), **package_summary},
        "auditedCandidates": [
            {
                "candidateId": cid,
                "baselineStandaloneRank": ranks[cid],
                "inPublishedProgramme": cid in published_ids,
                **concentration(standalone[cid]),
                "minimumRankAcrossTestedDeletions": min(tested_ranks[cid], default=ranks[cid]),
                "maximumRankAcrossTestedDeletions": max(tested_ranks[cid], default=ranks[cid]),
            }
            for cid in focus
        ],
        "cases": cases,
        "limitations": [
            "Deletion reduces the evaluated population; other weights are not redistributed.",
            "Cases are targeted influence tests, not random replicates or confidence intervals.",
            "Standalone ranks are not a reoptimised cumulative investment programme.",
            "The published programme is fixed; its benefit is evaluated jointly, not summed.",
            "Retained routes, source locations, costs and response assumptions are unchanged.",
            "Only assigned commutes are represented; omitted and failed demand is not repaired.",
            "Cases do not test new locations within cells, new routing or calibrated uptake.",
            "Rank ranges cover the tested deletions only, not every possible uncertainty.",
            "Effective contributing cells measures concentration, not inferential sample size.",
        ],
    }
