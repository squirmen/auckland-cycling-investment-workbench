#!/usr/bin/env python3
"""Audit mass conservation and accounting in a prepared demand artifact."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def close(first: float, second: float, *, absolute: float = 1e-7) -> bool:
    return math.isclose(first, second, rel_tol=1e-9, abs_tol=absolute)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def audit_commute(payload: dict[str, Any]) -> dict[str, Any]:
    zonal = payload["zonal_od_ledger"]
    records = payload["disaggregated_commute_ledger"]
    expected = {row["id"]: row for row in zonal if row["route_status"] == "internal_spatialized"}
    eligible: defaultdict[str, float] = defaultdict(float)
    cycle: defaultdict[str, float] = defaultdict(float)
    record_ids: set[str] = set()
    for row in records:
        record_id = str(row["id"])
        require(record_id not in record_ids, f"duplicate commute record: {record_id}")
        record_ids.add(record_id)
        source_cell = str(row["source_cell_id"])
        require(source_cell in expected, f"commute record has unknown source cell: {record_id}")
        require(row["purpose"] == "commute", f"invalid commute purpose: {record_id}")
        require(0 <= row["cycle"] <= row["eligible"], f"invalid commute counts: {record_id}")
        require(
            0 < row["selection_probability"] <= 1,
            f"invalid upstream probability: {record_id}",
        )
        require(0 < row["draw_count"] <= row["total_draws"], f"invalid draws: {record_id}")
        eligible[source_cell] += row["eligible"]
        cycle[source_cell] += row["cycle"]
    require(set(eligible) == set(expected), "spatialized zonal and commute source cells differ")
    for source_cell, row in expected.items():
        require(
            close(eligible[source_cell], row["eligible_point"]),
            f"commute eligible mass differs: {source_cell}",
        )
        require(
            close(cycle[source_cell], row["cycle_point"]),
            f"commute cycle mass differs: {source_cell}",
        )
    suppressed = [row for row in zonal if row["cycle_suppressed"]]
    require(bool(suppressed), "audit fixture contains no suppressed commute cells")
    require(
        all(str(row["cycle_treatment"]).startswith("suppressed") for row in suppressed),
        "suppressed commute cells were treated as observed values",
    )
    return {
        "records": len(records),
        "spatialized_zonal_od": len(expected),
        "eligible_point": sum(eligible.values()),
        "cycle_point": sum(cycle.values()),
        "suppressed_cycle_cells": len(suppressed),
    }


def audit_non_commute(payload: dict[str, Any]) -> dict[str, Any]:
    surfaces = payload["purpose_surfaces"]
    origins = {row["id"]: row for row in surfaces["population_origins"]}
    records = payload["non_commute_purpose_od_ledger"]
    exclusions = payload["purpose_generation_exclusion_ledger"]
    record_ids: set[str] = set()
    by_purpose: Counter[str] = Counter()
    units: defaultdict[str, set[str]] = defaultdict(set)
    for row in records:
        record_id = str(row["id"])
        require(record_id not in record_ids, f"duplicate purpose record: {record_id}")
        record_ids.add(record_id)
        purpose = str(row["purpose"])
        require(purpose in {"school", "everyday", "transit"}, f"unknown purpose: {purpose}")
        require(row["origin_support_id"] in origins, f"unknown purpose origin: {record_id}")
        require(row["eligible"] >= 0 and row["cycle"] == 0, f"invalid purpose mass: {record_id}")
        require(row["euclidean_distance_m"] >= 0, f"invalid purpose distance: {record_id}")
        by_purpose[purpose] += 1
        units[purpose].add(str(row["demand_unit"]))
    require(
        all(len(values) == 1 for values in units.values()),
        "a purpose market mixes incompatible units",
    )

    school_mass: defaultdict[str, float] = defaultdict(float)
    for row in records:
        if row["purpose"] == "school":
            school_mass[row["destination_support_id"]] += row["eligible"]
    zero_school_ids = {
        row["origin_or_destination_id"]
        for row in exclusions
        if row["purpose"] == "school" and row["reason"] == "nonpositive_school_roll"
    }
    schools = surfaces["school"]["destinations"]
    for school in schools:
        school_id = school["id"]
        if school["roll"] > 0:
            require(
                close(school_mass[school_id], school["roll"]),
                f"school roll is not conserved: {school_id}",
            )
        else:
            require(school_id in zero_school_ids, f"zero-roll school not accounted: {school_id}")

    everyday_categories = set(surfaces["everyday"]["parameters"]["category_weights"])
    everyday_accounting: Counter[tuple[str, str]] = Counter()
    everyday_mass: defaultdict[str, float] = defaultdict(float)
    for row in records:
        if row["purpose"] != "everyday":
            continue
        category = str(row["source_cell_id"]).rsplit(":", maxsplit=1)[-1]
        everyday_accounting[(row["origin_support_id"], category)] += 1
        everyday_mass[row["origin_support_id"]] += row["eligible"]
    for row in exclusions:
        if row["purpose"] != "everyday":
            continue
        everyday_accounting[(row["origin_or_destination_id"], row["category"])] += 1
        everyday_mass[row["origin_or_destination_id"]] += row["eligible"]
    require(
        set(everyday_accounting)
        == {(origin_id, category) for origin_id in origins for category in everyday_categories},
        "everyday origin-category accounting is incomplete",
    )
    require(
        all(value == 1 for value in everyday_accounting.values()),
        "everyday origin-category is duplicated",
    )

    transit_accounting: Counter[str] = Counter()
    transit_mass: defaultdict[str, float] = defaultdict(float)
    for row in records:
        if row["purpose"] == "transit":
            transit_accounting[row["origin_support_id"]] += 1
            transit_mass[row["origin_support_id"]] += row["eligible"]
    for row in exclusions:
        if row["purpose"] == "transit":
            transit_accounting[row["origin_or_destination_id"]] += 1
            transit_mass[row["origin_or_destination_id"]] += row["eligible"]
    require(set(transit_accounting) == set(origins), "transit origin accounting is incomplete")
    require(all(value == 1 for value in transit_accounting.values()), "transit origin duplicated")

    for origin_id, origin in origins.items():
        require(
            close(everyday_mass[origin_id], origin["weight"]),
            f"everyday population mass differs: {origin_id}",
        )
        require(
            close(transit_mass[origin_id], origin["weight"]),
            f"transit population mass differs: {origin_id}",
        )
    return {
        "population_origins": len(origins),
        "records_by_purpose": dict(sorted(by_purpose.items())),
        "units_by_purpose": {
            purpose: next(iter(values)) for purpose, values in sorted(units.items())
        },
        "generation_exclusions": len(exclusions),
        "school_roll": sum(row["roll"] for row in schools),
        "origin_population": sum(row["weight"] for row in origins.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("demand", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = read_json(args.demand.resolve())
    require(payload.get("schema_version") == 3, "prepared demand schema version 3 required")
    report = {
        "schema_version": 1,
        "status": "passed",
        "run_id": payload["run_id"],
        "checks": {
            "commute_disaggregation_mass_conservation": "passed",
            "suppressed_cells_retained_as_intervals": "passed",
            "school_roll_mass_conservation": "passed",
            "everyday_population_mass_conservation": "passed",
            "transit_population_mass_conservation": "passed",
            "purpose_units_kept_separate": "passed",
            "pre_route_exclusion_accounting": "passed",
        },
        "metrics": {
            "commute": audit_commute(payload),
            "non_commute": audit_non_commute(payload),
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
