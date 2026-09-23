"""Aggregate route use and independently evaluated connected packages.

Only aggregate results leave this module. OD records and plausible paths stay
in the run. A person is allocated across alternative paths once, and a path
using multiple selected links is counted once for the whole package.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .candidates import DemandResponseParameters
from .network_context import portfolio_groups
from .portfolio_analysis import ChoicePath, ODChoiceSet, evaluate_choice_set


def treatment_usage(
    choice: ODChoiceSet,
    selected: frozenset[str],
    *,
    cost_scale: float,
    response: DemandResponseParameters,
) -> dict[str, float]:
    """Before/after users of ANY treated link, plus the distinct OD uptake gain."""

    using = [path for path in choice.paths if selected.intersection(path.savings_by_candidate)]
    if not using:
        return {"before": 0.0, "after": 0.0, "additional": 0.0}
    evaluation = evaluate_choice_set(choice, selected, cost_scale=cost_scale, response=response)
    before_share = min(1.0, sum(path.baseline_probability for path in using))
    after_share = min(1.0, sum(evaluation.probability_by_path[path.id] for path in using))
    return {
        "before": choice.baseline_activity * before_share,
        "after": (choice.baseline_activity + evaluation.activity_addition) * after_share,
        "additional": evaluation.activity_addition,
    }


def read_commute_market(
    route_dir: Path, portfolio_dir: Path
) -> tuple[dict[str, ODChoiceSet], dict[str, set[str]], dict[str, dict[str, float]]]:
    """Read compact ledgers, without rescanning the 100m-row path-edge ledger."""

    savings: defaultdict[str, dict[str, float]] = defaultdict(dict)
    saving_table = pq.ParquetFile(portfolio_dir / "path_candidate_savings.parquet")
    for batch in saving_table.iter_batches(
        columns=["path_id", "purpose", "candidate_id", "generalized_cost_saving"]
    ):
        for row in batch.to_pylist():
            if row["purpose"] == "commute":
                savings[str(row["path_id"])][str(row["candidate_id"])] = float(
                    row["generalized_cost_saving"]
                )
    paths: defaultdict[str, list[ChoicePath]] = defaultdict(list)
    candidate_ods: defaultdict[str, set[str]] = defaultdict(set)
    for batch in pq.ParquetFile(route_dir / "path_ledger.parquet").iter_batches(
        columns=["path_id", "od_id", "purpose", "generalized_cost", "probability"]
    ):
        for row in batch.to_pylist():
            if row["purpose"] != "commute":
                continue
            pid, od = str(row["path_id"]), str(row["od_id"])
            path_savings = savings.get(pid, {})
            paths[od].append(
                ChoicePath(
                    pid, float(row["generalized_cost"]), float(row["probability"]), path_savings
                )
            )
            for cid in path_savings:
                candidate_ods[cid].add(od)
    choices: dict[str, ODChoiceSet] = {}
    for batch in pq.ParquetFile(route_dir / "od_ledger.parquet").iter_batches(
        columns=["od_id", "purpose", "status", "weighted_eligible", "weighted_observed_cycle"]
    ):
        for row in batch.to_pylist():
            if row["purpose"] == "commute" and row["status"] == "assigned":
                od = str(row["od_id"])
                choices[od] = ODChoiceSet(
                    od,
                    "commute",
                    float(row["weighted_eligible"]),
                    float(row["weighted_observed_cycle"]),
                    tuple(paths[od]),
                )
    activities: defaultdict[str, dict[str, float]] = defaultdict(dict)
    for batch in pq.ParquetFile(route_dir / "scenario_od_ledger.parquet").iter_batches(
        columns=["scenario_id", "od_id", "scenario_cycle"]
    ):
        for row in batch.to_pylist():
            if row["scenario_cycle"] is not None and str(row["od_id"]) in choices:
                activities[str(row["scenario_id"])][str(row["od_id"])] = float(
                    row["scenario_cycle"]
                )
    return choices, dict(candidate_ods), dict(activities)


def build_route_context(
    choices: Mapping[str, ODChoiceSet],
    candidate_ods: Mapping[str, set[str]],
    activities: Mapping[str, Mapping[str, float]],
    portfolios: Mapping[str, Mapping[str, list[dict[str, Any]]]],
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    cost_scale: float,
    response: DemandResponseParameters,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Re-evaluate whole packages, and add deduplicated use to stored prefixes.

    Existing sequence order and uptake values are retained. Package uptake is
    recomputed independently; it must not be obtained by summing standalones
    or by summing regional marginal values for a subset of links.
    """

    use_by_candidate: defaultdict[str, dict[str, Any]] = defaultdict(dict)
    packages: list[dict[str, Any]] = []
    for scenario, activity in activities.items():
        market = {
            od: replace(choice, baseline_activity=float(activity[od]))
            for od, choice in choices.items()
        }
        evaluated: dict[tuple[str, ...], dict[str, float]] = {}

        def assess(
            ids: Sequence[str],
            evaluated: dict[tuple[str, ...], dict[str, float]] = evaluated,
            market: dict[str, ODChoiceSet] = market,
        ) -> dict[str, float]:
            key = tuple(sorted(ids))
            if key not in evaluated:
                selected = frozenset(key)
                ods = set().union(*(candidate_ods.get(cid, set()) for cid in key))
                total = {"before": 0.0, "after": 0.0, "additional": 0.0}
                for od in sorted(ods):
                    usage = treatment_usage(
                        market[od], selected, cost_scale=cost_scale, response=response
                    )
                    for term in total:
                        total[term] += usage[term]
                evaluated[key] = total
            return evaluated[key]

        for cid in contexts:
            use_by_candidate[cid][scenario] = dict(assess([cid]))

        package_keys: set[tuple[str, ...]] = set()
        for purpose in ("network", "appraisal"):
            selected: list[str] = []
            current_by_od: dict[str, dict[str, float]] = {}
            cumulative_before = cumulative_after = cumulative_additional = 0.0
            for step in portfolios.get(scenario, {}).get(purpose, []):
                cid = str(step["candidateId"])
                selected.append(cid)
                frozen = frozenset(selected)
                for od in sorted(candidate_ods.get(cid, set())):
                    previous = current_by_od.get(
                        od, {"before": 0.0, "after": 0.0, "additional": 0.0}
                    )
                    current = treatment_usage(
                        market[od], frozen, cost_scale=cost_scale, response=response
                    )
                    cumulative_before += current["before"] - previous["before"]
                    cumulative_after += current["after"] - previous["after"]
                    cumulative_additional += current["additional"] - previous["additional"]
                    current_by_od[od] = current
                # Detect incompatible model assumptions instead of attaching mismatched results.
                if abs(cumulative_additional - float(step["cumulativeObjective"])) > max(
                    1e-6, abs(cumulative_additional) * 1e-8
                ):
                    raise ValueError(
                        "route context differs from stored uptake: "
                        f"{scenario}:{purpose}:{step['step']}"
                    )
                step["routeUsersBefore"] = max(0.0, cumulative_before)
                step["routeUsersAfter"] = max(0.0, cumulative_after)
                for group in portfolio_groups(selected, contexts):
                    if cid in group:
                        key = tuple(sorted(group))
                        if key not in package_keys:
                            package_keys.add(key)
                            packages.append(
                                {"scenario": scenario, "candidateIds": list(key), **assess(key)}
                            )
                        break
    return dict(use_by_candidate), packages
