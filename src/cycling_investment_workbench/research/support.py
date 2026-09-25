"""Finite stored-support diagnostics, not a new demand or uptake forecast."""

from collections import Counter
from collections.abc import Mapping, Sequence
from math import fsum, isfinite

from ..r5_routing import select_route_sample


def usage_bounds(records: Sequence[Mapping], outcomes: Mapping, candidate: str) -> dict:
    """Keep routing failures in the denominator and expose their unknown use."""
    if not records or len({r["id"] for r in records}) != len(records):
        raise ValueError("support records must be non-empty and unique")
    if any(not isfinite(r["eligible"]) or r["eligible"] < 0 for r in records):
        raise ValueError("support mass must be finite and non-negative")
    if any(r["id"] not in outcomes for r in records):
        raise ValueError("every support record needs a routing outcome")
    total = fsum(r["eligible"] for r in records)
    if total <= 0:
        raise ValueError("support mass must be positive")
    known, unknown = [], []
    for record in records:
        result = outcomes[record["id"]]
        if result["status"] == "assigned":
            probability = result["candidateProbabilities"][candidate]
            if not isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("route use probability must be in [0, 1]")
            known.append(record["eligible"] * probability)
        elif result["status"] == "unassigned":
            unknown.append(record["eligible"])
        else:
            raise ValueError("unknown routing status")
    used, missing = fsum(known), fsum(unknown)
    return {
        "eligibleMass": total,
        "knownRouteUseMass": used,
        "unassignedMass": missing,
        "routeUseShareLower": used / total,
        "routeUseShareUpper": min(1.0, (used + missing) / total),
    }


def summarise_support(
    records: Sequence[Mapping],
    outcomes: Mapping,
    drivers: Sequence[str],
    *,
    seeds: Sequence[int],
    sample_sizes: Sequence[int] = (1, 5),
) -> dict:
    """Compare seeded SRS estimates with enumeration of the same finite pool.

    HT weighted totals can differ between draws with unequal record masses.
    They are disclosed, never rescaled to make them appear exactly conserved.
    No source IDs or sampled locations are included in the summary.
    """
    if len({r["source_cell_id"] for r in records}) != 1:
        raise ValueError("a support summary must cover exactly one source cell")
    if not drivers or len(set(drivers)) != len(drivers):
        raise ValueError("driver candidates must be non-empty and unique")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("replicate seeds must be non-empty and unique")
    if not sample_sizes or any(
        isinstance(m, bool) or not isinstance(m, int) or m < 1 for m in sample_sizes
    ):
        raise ValueError("sample sizes must be positive integers")
    enumerated = {cid: usage_bounds(records, outcomes, cid) for cid in drivers}
    replicates = []
    for size in sample_sizes:
        for seed in seeds:
            sample = {
                s.record_id: s
                for s in select_route_sample(records, records_per_stratum=size, seed=seed)
                if s.selected
            }
            selected = [
                {**r, "eligible": r["eligible"] * sample[r["id"]].analysis_weight}
                for r in records
                if r["id"] in sample
            ]
            replicates.append(
                {
                    "seed": seed,
                    "recordsRequested": size,
                    "recordsSelected": len(selected),
                    "estimatedEligibleMass": fsum(r["eligible"] for r in selected),
                    "candidateUsage": [
                        {"candidateId": cid, **usage_bounds(selected, outcomes, cid)}
                        for cid in drivers
                    ],
                }
            )
    baseline = [r for r in records if r["route_sample_selected"]]
    return {
        "supportRecords": len(records),
        "sourceEligibleMass": fsum(r["eligible"] for r in records),
        "assignedRecords": sum(outcomes[r["id"]]["status"] == "assigned" for r in records),
        "failureReasons": dict(
            sorted(
                Counter(
                    outcomes[r["id"]]["failureReason"]
                    for r in records
                    if outcomes[r["id"]]["status"] == "unassigned"
                ).items()
            )
        ),
        "publishedSampleRecords": len(baseline),
        "publishedSampleRouteParity": all(
            outcomes[r["id"]].get("publishedRouteParity") is True for r in baseline
        )
        if baseline
        else None,
        "candidateUsage": [
            {
                "candidateId": cid,
                **enumerated[cid],
                "publishedSampleFreshRouteUseShare": (
                    usage_bounds(baseline, outcomes, cid) if baseline else None
                ),
            }
            for cid in drivers
        ],
        "replicates": replicates,
    }
