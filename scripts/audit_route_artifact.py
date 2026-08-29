#!/usr/bin/env python3
"""Independently audit a completed production routing artifact.

The audit works from the published Parquet ledgers and the resumable chunk
manifests. It verifies file integrity, sampling/failure accounting, route-choice
probabilities, detour limits, ordered exact-edge membership, and the final
edge-flow aggregation without loading the full path-edge ledger into memory.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


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


def parquet_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def verify_declared_files(route_dir: Path, manifest: dict[str, Any]) -> None:
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "route manifest has no file inventory")
    for name, record in sorted(files.items()):
        path = route_dir / name
        require(path.is_file(), f"declared route file is missing: {name}")
        require(path.stat().st_size == record["size"], f"size mismatch: {name}")
        require(sha256_file(path) == record["sha256"], f"SHA-256 mismatch: {name}")


def audit_od_ledger(route_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = route_dir / "od_ledger.parquet"
    file = pq.ParquetFile(path)
    od_ids: set[str] = set()
    assigned_paths: dict[str, tuple[str, ...]] = {}
    assigned_probabilities: dict[str, tuple[float, ...]] = {}
    selected_by_stratum: Counter[str] = Counter()
    stratum_sample_size: dict[str, int] = {}
    statuses: Counter[str] = Counter()
    failure_ids: set[str] = set()
    selected_ids: set[str] = set()
    purpose_by_od: dict[str, str] = {}
    probability_max_error = 0.0
    weighted_attempted_eligible = 0.0
    estimated_assigned_eligible = 0.0
    attempted_by_purpose: defaultdict[str, float] = defaultdict(float)
    assigned_by_purpose: defaultdict[str, float] = defaultdict(float)
    schema_version = int(manifest["schema_version"])

    columns = [
        "schema_version",
        "od_id",
        "source_cell_id",
        "purpose",
        "route_sample_selected",
        "route_stratum_sample_size",
        "route_inclusion_probability",
        "analysis_weight",
        "weighted_eligible",
        "status",
        "failure_reason",
        "path_ids",
        "path_probabilities",
    ]
    if schema_version >= 3:
        columns.extend(
            [
                "shortest_distance_m",
                "shortest_average_absolute_gradient_percent",
                "shortest_total_ascent_m",
            ]
        )
    for batch in file.iter_batches(columns=columns, batch_size=20_000):
        for row in batch.to_pylist():
            od_id = row["od_id"]
            require(od_id not in od_ids, f"duplicate OD id: {od_id}")
            od_ids.add(od_id)
            require(
                row["schema_version"] == schema_version,
                f"unexpected OD schema version: {od_id}",
            )
            purpose = str(row["purpose"])
            purpose_by_od[od_id] = purpose
            selected = row["route_sample_selected"]
            status = row["status"]
            statuses[status] += 1
            paths = tuple(row["path_ids"])
            probabilities = tuple(row["path_probabilities"])
            require(len(paths) == len(probabilities), f"OD path/probability mismatch: {od_id}")
            if selected:
                selected_ids.add(od_id)
                source_cell_id = row["source_cell_id"]
                selected_by_stratum[source_cell_id] += 1
                stratum_sample_size[source_cell_id] = row["route_stratum_sample_size"]
                require(row["route_inclusion_probability"] > 0, f"invalid inclusion: {od_id}")
                require(row["analysis_weight"] > 0, f"invalid analysis weight: {od_id}")
                weighted_attempted_eligible += row["weighted_eligible"]
                attempted_by_purpose[purpose] += row["weighted_eligible"]
                require(status in {"assigned", "unassigned"}, f"invalid selected status: {od_id}")
            else:
                require(
                    status == "not_selected_probability_sample",
                    f"invalid unsampled status: {od_id}",
                )
                require(not paths and not probabilities, f"unsampled OD has paths: {od_id}")
                require(row["analysis_weight"] == 0, f"unsampled OD has analysis weight: {od_id}")
            if status == "assigned":
                require(paths, f"assigned OD has no paths: {od_id}")
                require(not row["failure_reason"], f"assigned OD has failure reason: {od_id}")
                error = abs(sum(probabilities) - 1.0)
                probability_max_error = max(probability_max_error, error)
                require(error <= 1e-12, f"path probabilities do not sum to one: {od_id}")
                assigned_paths[od_id] = paths
                assigned_probabilities[od_id] = probabilities
                estimated_assigned_eligible += row["weighted_eligible"]
                assigned_by_purpose[purpose] += row["weighted_eligible"]
                if schema_version >= 3:
                    require(row["shortest_distance_m"] > 0, f"invalid shortest path: {od_id}")
                    require(
                        row["shortest_average_absolute_gradient_percent"] >= 0,
                        f"invalid shortest gradient: {od_id}",
                    )
                    require(
                        row["shortest_total_ascent_m"] >= 0,
                        f"invalid shortest ascent: {od_id}",
                    )
            elif status == "unassigned":
                require(bool(row["failure_reason"]), f"failed OD has no reason: {od_id}")
                require(not paths and not probabilities, f"failed OD has paths: {od_id}")
                failure_ids.add(od_id)

    for stratum, selected_count in selected_by_stratum.items():
        require(
            selected_count == stratum_sample_size[stratum],
            f"selected count does not match declared stratum sample size: {stratum}",
        )

    counts = manifest["row_counts"]
    require(len(od_ids) == counts["disaggregated_od"], "OD row count differs from manifest")
    require(
        sum(selected_by_stratum.values()) == counts["selected_for_routing"],
        "selected OD count differs from manifest",
    )
    require(
        len(assigned_paths) == counts["assigned_selected_od"],
        "assigned OD count differs from manifest",
    )
    require(len(failure_ids) == counts["routing_failures"], "failed OD count differs from manifest")

    coverage = manifest["coverage"]
    if schema_version == 1:
        require(
            close(weighted_attempted_eligible, coverage["weighted_attempted_eligible"]),
            "attempted eligible total differs from manifest",
        )
        require(
            close(estimated_assigned_eligible, coverage["estimated_assigned_eligible"]),
            "assigned eligible total differs from manifest",
        )
        failure_share = (
            weighted_attempted_eligible - estimated_assigned_eligible
        ) / weighted_attempted_eligible
        require(
            close(
                failure_share,
                coverage["routing_failure_share_of_weighted_attempted_eligible"],
            ),
            "failure share differs from manifest",
        )
    else:
        require(coverage.get("cross_purpose_units_are_not_summed") is True, "purpose units summed")
        declared = coverage.get("by_purpose")
        require(isinstance(declared, dict), "purpose coverage ledger is missing")
        for purpose in sorted(set(purpose_by_od.values())):
            item = declared.get(purpose)
            require(isinstance(item, dict), f"coverage is missing purpose: {purpose}")
            require(
                close(attempted_by_purpose[purpose], item["weighted_attempted"]),
                f"attempted eligible differs for purpose: {purpose}",
            )
            require(
                close(assigned_by_purpose[purpose], item["estimated_assigned"]),
                f"assigned eligible differs for purpose: {purpose}",
            )

    failure_ledger_ids = {
        row["od_id"]
        for batch in pq.ParquetFile(route_dir / "failure_ledger.parquet").iter_batches(
            columns=["od_id"]
        )
        for row in batch.to_pylist()
    }
    require(failure_ledger_ids == failure_ids, "failure ledger does not match failed OD records")
    return {
        "od_ids": od_ids,
        "assigned_paths": assigned_paths,
        "assigned_probabilities": assigned_probabilities,
        "failure_ids": failure_ids,
        "selected_ids": selected_ids,
        "purpose_by_od": purpose_by_od,
        "statuses": dict(sorted(statuses.items())),
        "probability_max_error": probability_max_error,
        "weighted_attempted_eligible": weighted_attempted_eligible,
        "estimated_assigned_eligible": estimated_assigned_eligible,
    }


def audit_path_ledger(
    route_dir: Path,
    manifest: dict[str, Any],
    od_audit: dict[str, Any],
) -> dict[str, Any]:
    assigned_paths = od_audit["assigned_paths"]
    assigned_probabilities = od_audit["assigned_probabilities"]
    purpose_by_od = od_audit["purpose_by_od"]
    schema_version = int(manifest["schema_version"])
    expected_path_ids = {path_id for paths in assigned_paths.values() for path_id in paths}
    seen: set[str] = set()
    probability_by_od: defaultdict[str, float] = defaultdict(float)
    paths_by_od: Counter[str] = Counter()
    maximum_detour = 0.0
    maximum_paths = 0
    empty_path_ids: set[str] = set()
    configured_detour = float(manifest["parameters"]["maximum_detour_ratio"])
    configured_paths = int(manifest["parameters"]["plausible_paths"])

    columns = [
        "schema_version",
        "path_id",
        "od_id",
        "path_index",
        "probability",
        "generalized_cost",
        "length_m",
        "shortest_distance_m",
        "detour_ratio",
        "r5_edge_ids",
        "r5_osm_way_ids",
        "project_edge_ids",
        "project_edge_reversed",
    ]
    if schema_version >= 2:
        columns.append("purpose")
    for batch in pq.ParquetFile(route_dir / "path_ledger.parquet").iter_batches(
        columns=columns, batch_size=2_000
    ):
        for row in batch.to_pylist():
            path_id = row["path_id"]
            od_id = row["od_id"]
            require(
                row["schema_version"] == schema_version,
                f"unexpected path schema version: {path_id}",
            )
            require(path_id not in seen, f"duplicate path id: {path_id}")
            require(path_id in expected_path_ids, f"path not referenced by assigned OD: {path_id}")
            require(path_id in assigned_paths[od_id], f"path has inconsistent OD id: {path_id}")
            if schema_version >= 2:
                require(
                    row["purpose"] == purpose_by_od[od_id],
                    f"path purpose differs from OD: {path_id}",
                )
            expected_index = assigned_paths[od_id].index(path_id)
            require(row["path_index"] == expected_index + 1, f"path index mismatch: {path_id}")
            require(
                close(row["probability"], assigned_probabilities[od_id][expected_index]),
                f"path probability differs from OD ledger: {path_id}",
            )
            require(row["probability"] > 0, f"path probability is not positive: {path_id}")
            if not row["project_edge_ids"]:
                require(
                    row["generalized_cost"] == row["length_m"] == 0,
                    f"empty path has non-zero cost or length: {path_id}",
                )
                require(
                    row["shortest_distance_m"] == 0,
                    f"empty path has non-zero shortest distance: {path_id}",
                )
                empty_path_ids.add(path_id)
            else:
                require(
                    row["generalized_cost"] > 0 and row["length_m"] > 0,
                    f"path has non-positive cost or length: {path_id}",
                )
                require(
                    row["shortest_distance_m"] > 0,
                    f"path has non-positive shortest distance: {path_id}",
                )
            require(
                row["detour_ratio"] <= configured_detour + 1e-9,
                f"path exceeds detour cap: {path_id}",
            )
            require(
                len(row["r5_edge_ids"]) == len(row["r5_osm_way_ids"]),
                f"R5 edge/way list mismatch: {path_id}",
            )
            require(
                len(row["project_edge_ids"]) == len(row["project_edge_reversed"]),
                f"project edge/direction list mismatch: {path_id}",
            )
            seen.add(path_id)
            probability_by_od[od_id] += row["probability"]
            paths_by_od[od_id] += 1
            maximum_detour = max(maximum_detour, row["detour_ratio"])

    require(seen == expected_path_ids, "path ledger and assigned OD path IDs differ")
    for od_id, probability in probability_by_od.items():
        require(
            close(probability, 1.0, absolute=1e-12),
            f"path-ledger probabilities do not sum to one: {od_id}",
        )
    if paths_by_od:
        maximum_paths = max(paths_by_od.values())
    require(maximum_paths <= configured_paths, "OD has more paths than configured")
    require(len(seen) == manifest["row_counts"]["paths"], "path row count differs from manifest")
    return {
        "path_ids": seen,
        "path_count": len(seen),
        "maximum_paths_per_od": maximum_paths,
        "maximum_detour_ratio": maximum_detour,
        "empty_path_ids": empty_path_ids,
    }


def audit_scenario_ledger(
    route_dir: Path,
    manifest: dict[str, Any],
    od_audit: dict[str, Any],
) -> dict[str, Any]:
    if int(manifest["schema_version"]) < 3:
        return {"scenario_rows": 0, "scenario_ids": []}
    expected_scenarios = {
        "baseline",
        "government_target",
        "go_dutch",
        "ebike",
        "commute_8pct",
    }
    selected_commute = {
        od_id for od_id in od_audit["selected_ids"] if od_audit["purpose_by_od"][od_id] == "commute"
    }
    seen: set[tuple[str, str]] = set()
    scenarios_by_od: Counter[str] = Counter()
    total_8pct = 0.0
    for batch in pq.ParquetFile(route_dir / "scenario_od_ledger.parquet").iter_batches(
        batch_size=20_000
    ):
        for row in batch.to_pylist():
            require(row["schema_version"] == 3, "scenario row schema mismatch")
            key = (row["scenario_id"], row["od_id"])
            require(key not in seen, f"duplicate scenario OD row: {key}")
            seen.add(key)
            require(row["scenario_id"] in expected_scenarios, f"unknown scenario: {key}")
            require(row["od_id"] in selected_commute, f"scenario row has unknown OD: {key}")
            scenarios_by_od[row["od_id"]] += 1
            if row["route_status"] == "assigned":
                require(
                    row["weighted_observed_cycle"]
                    <= row["scenario_cycle"]
                    <= row["weighted_eligible"],
                    f"scenario count is outside capacity: {key}",
                )
                require(row["route_distance_km"] > 0, f"scenario route distance invalid: {key}")
                require(
                    row["average_absolute_gradient_percent"] >= 0,
                    f"scenario gradient invalid: {key}",
                )
                if row["scenario_id"] == "commute_8pct":
                    total_8pct += row["scenario_cycle"]
            else:
                require(row["scenario_cycle"] is None, f"failed route has scenario count: {key}")
    require(set(scenarios_by_od) == selected_commute, "scenario ledger omits selected commute OD")
    require(all(count == 5 for count in scenarios_by_od.values()), "OD scenario set is incomplete")
    require(len(seen) == manifest["row_counts"]["scenario_od"], "scenario count mismatch")
    summary = manifest["scenario_summaries"]["commute_8pct"]
    require(
        close(total_8pct, summary["assigned_route_sample_total"]),
        "8% scenario total differs from manifest",
    )
    require(
        close(
            summary["achieved_additional"] + summary["unallocated"],
            summary["target_additional"],
        ),
        "8% target accounting is incomplete",
    )
    require(
        summary["denominator_not_shrunk_to_routable_sample"] is True,
        "8% target denominator was shrunk",
    )
    return {
        "scenario_rows": len(seen),
        "scenario_ids": sorted(expected_scenarios),
        "selected_commute_od": len(selected_commute),
    }


def audit_chunks_and_edge_flows(
    route_dir: Path,
    work_dir: Path,
    manifest: dict[str, Any],
    path_audit: dict[str, Any],
) -> dict[str, Any]:
    schema_version = int(manifest["schema_version"])
    edge_flow_table = pq.read_table(route_dir / "edge_flows.parquet").to_pandas()
    edge_index_columns = (
        ["purpose", "project_edge_id"] if schema_version >= 2 else ["project_edge_id"]
    )
    edge_flow_table = edge_flow_table.set_index(edge_index_columns, verify_integrity=True)
    edge_index = edge_flow_table.index
    observed = np.zeros(len(edge_index), dtype=np.float64)
    eligible = np.zeros(len(edge_index), dtype=np.float64)
    records = np.zeros(len(edge_index), dtype=np.int64)
    seen_paths: set[str] = set()
    total_od = 0
    total_paths = 0
    total_path_edges = 0
    chunk_manifests = sorted(work_dir.glob("chunk-*.json"))
    require(bool(chunk_manifests), "no routing chunk manifests found")

    for chunk_number, chunk_manifest_path in enumerate(chunk_manifests, start=1):
        chunk_manifest = read_json(chunk_manifest_path)
        files = chunk_manifest.get("files")
        counts = chunk_manifest.get("row_counts")
        require(
            isinstance(files, dict) and isinstance(counts, dict),
            f"invalid chunk manifest: {chunk_manifest_path.name}",
        )
        for filename, digest in files.items():
            path = work_dir / filename
            require(path.is_file(), f"chunk file missing: {filename}")
            require(sha256_file(path) == digest, f"chunk SHA-256 mismatch: {filename}")

        prefix = chunk_manifest_path.stem
        od_path = work_dir / f"{prefix}-od.parquet"
        path_path = work_dir / f"{prefix}-paths.parquet"
        path_edge_path = work_dir / f"{prefix}-path-edges.parquet"
        require(parquet_rows(od_path) == counts["od"], f"chunk OD count mismatch: {prefix}")
        require(parquet_rows(path_path) == counts["paths"], f"chunk path count mismatch: {prefix}")
        require(
            parquet_rows(path_edge_path) == counts["path_edges"],
            f"chunk path-edge count mismatch: {prefix}",
        )
        total_od += counts["od"]
        total_paths += counts["paths"]
        total_path_edges += counts["path_edges"]

        all_expected = {
            row["path_id"]: (
                row["od_id"],
                row.get("purpose"),
                row["path_index"],
                tuple(row["project_edge_ids"]),
                tuple(row["project_edge_reversed"]),
                row["length_m"],
                row["generalized_cost"],
                row["probability"],
                row.get("average_absolute_gradient_percent"),
                row.get("total_ascent_m"),
                row.get("total_descent_m"),
            )
            for row in pq.read_table(path_path).to_pylist()
        }
        require(not seen_paths.intersection(all_expected), f"path repeated across chunks: {prefix}")
        seen_paths.update(all_expected)
        expected = {
            path_id: value
            for path_id, value in all_expected.items()
            if path_id not in path_audit["empty_path_ids"]
        }
        sequence: defaultdict[str, list[tuple[str, bool]]] = defaultdict(list)
        length_by_path: defaultdict[str, float] = defaultdict(float)
        cost_by_path: defaultdict[str, float] = defaultdict(float)
        absolute_rise_by_path: defaultdict[str, float] = defaultdict(float)
        ascent_by_path: defaultdict[str, float] = defaultdict(float)
        descent_by_path: defaultdict[str, float] = defaultdict(float)
        edge_file = pq.ParquetFile(path_edge_path)
        for batch in edge_file.iter_batches(batch_size=100_000):
            frame = batch.to_pandas()
            require(
                (frame["schema_version"] == schema_version).all(),
                f"path-edge schema mismatch: {prefix}",
            )
            group_fields = (
                ["purpose", "project_edge_id"] if schema_version >= 2 else ["project_edge_id"]
            )
            grouped = frame.groupby(group_fields, sort=False).agg(
                estimated_observed_cycle=("estimated_observed_cycle", "sum"),
                estimated_eligible=("estimated_eligible", "sum"),
                path_edge_records=("project_edge_id", "size"),
            )
            positions = edge_index.get_indexer(grouped.index)
            require(
                (positions >= 0).all(),
                f"chunk references edge absent from edge-flow table: {prefix}",
            )
            np.add.at(observed, positions, grouped["estimated_observed_cycle"].to_numpy())
            np.add.at(eligible, positions, grouped["estimated_eligible"].to_numpy())
            np.add.at(records, positions, grouped["path_edge_records"].to_numpy())
            for row in frame.itertuples(index=False):
                path_id = row.path_id
                require(path_id in expected, f"path-edge record has unknown path: {path_id}")
                od_id, purpose, path_index, _, _, _, _, probability, _, _, _ = expected[path_id]
                require(
                    row.od_id == od_id and row.path_index == path_index,
                    f"path-edge identity mismatch: {path_id}",
                )
                if schema_version >= 2:
                    require(row.purpose == purpose, f"path-edge purpose mismatch: {path_id}")
                require(
                    row.edge_sequence == len(sequence[path_id]) + 1,
                    f"non-contiguous edge sequence: {path_id}",
                )
                require(
                    close(row.path_probability, probability),
                    f"path-edge probability mismatch: {path_id}",
                )
                sequence[path_id].append((row.project_edge_id, row.reversed))
                length_by_path[path_id] += row.length_m
                cost_by_path[path_id] += row.generalized_cost
                if schema_version >= 3:
                    rise = row.directed_gradient_ratio * row.length_m
                    absolute_rise_by_path[path_id] += abs(rise)
                    ascent_by_path[path_id] += max(0.0, rise)
                    descent_by_path[path_id] += max(0.0, -rise)

        require(set(sequence) == set(expected), f"chunk path-edge/path ledgers differ: {prefix}")
        for path_id, values in expected.items():
            (
                _,
                _,
                _,
                edge_ids,
                reversed_flags,
                expected_length,
                expected_cost,
                _,
                expected_gradient,
                expected_ascent,
                expected_descent,
            ) = values
            actual = sequence[path_id]
            require(
                tuple(edge for edge, _ in actual) == edge_ids,
                f"exact edge sequence differs: {path_id}",
            )
            require(
                tuple(flag for _, flag in actual) == reversed_flags,
                f"edge directions differ: {path_id}",
            )
            require(
                close(length_by_path[path_id], expected_length, absolute=1e-5),
                f"path length differs from exact edges: {path_id}",
            )
            require(
                close(cost_by_path[path_id], expected_cost, absolute=1e-5),
                f"path cost differs from exact edges: {path_id}",
            )
            if schema_version >= 3:
                actual_gradient = 100.0 * absolute_rise_by_path[path_id] / expected_length
                require(
                    close(actual_gradient, expected_gradient, absolute=1e-8),
                    f"path gradient differs from exact edges: {path_id}",
                )
                require(
                    close(ascent_by_path[path_id], expected_ascent, absolute=1e-6),
                    f"path ascent differs from exact edges: {path_id}",
                )
                require(
                    close(descent_by_path[path_id], expected_descent, absolute=1e-6),
                    f"path descent differs from exact edges: {path_id}",
                )

        if chunk_number % 10 == 0 or chunk_number == len(chunk_manifests):
            print(f"audited chunks: {chunk_number}/{len(chunk_manifests)}", flush=True)

    require(seen_paths == path_audit["path_ids"], "chunk and consolidated path sets differ")
    require(
        total_od == manifest["row_counts"]["selected_for_routing"],
        "chunk OD total differs from manifest",
    )
    require(
        total_paths == manifest["row_counts"]["paths"], "chunk path total differs from manifest"
    )
    require(
        total_path_edges == manifest["row_counts"]["path_edges"],
        "chunk path-edge total differs from manifest",
    )
    require(
        np.allclose(
            observed, edge_flow_table["estimated_observed_cycle"].to_numpy(), rtol=1e-9, atol=1e-7
        ),
        "observed-cycle edge aggregation differs",
    )
    require(
        np.allclose(
            eligible, edge_flow_table["estimated_eligible"].to_numpy(), rtol=1e-9, atol=1e-7
        ),
        "eligible edge aggregation differs",
    )
    require(
        np.array_equal(records, edge_flow_table["path_edge_records"].to_numpy()),
        "edge record aggregation differs",
    )
    require(
        int(records.sum()) == total_path_edges, "edge-flow counts do not cover all path-edge rows"
    )
    return {
        "chunks": len(chunk_manifests),
        "selected_od_rows": total_od,
        "path_rows": total_paths,
        "path_edge_rows": total_path_edges,
        "edge_flow_rows": len(edge_flow_table),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route_dir", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    route_dir = args.route_dir.resolve()
    work_dir = args.work_dir.resolve()
    manifest = read_json(route_dir / "manifest.json")
    verify_declared_files(route_dir, manifest)
    od_audit = audit_od_ledger(route_dir, manifest)
    path_audit = audit_path_ledger(route_dir, manifest, od_audit)
    scenario_audit = audit_scenario_ledger(route_dir, manifest, od_audit)
    chunk_audit = audit_chunks_and_edge_flows(route_dir, work_dir, manifest, path_audit)
    empty_paths = sorted(path_audit["empty_path_ids"])
    passed = not empty_paths
    report = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "run_id": manifest["run_id"],
        "routing_identity": manifest["routing_identity"],
        "checks": {
            "declared_file_hashes": "passed",
            "sampling_and_failure_accounting": "passed",
            "path_probabilities": "passed",
            "scenario_capacity_and_target_accounting": "passed",
            "detour_cap": "passed",
            "ordered_exact_edge_membership": "passed" if passed else "failed",
            "edge_flow_aggregation": "passed",
        },
        "metrics": {
            "statuses": od_audit["statuses"],
            "path_probability_max_error": od_audit["probability_max_error"],
            "maximum_paths_per_od": path_audit["maximum_paths_per_od"],
            "maximum_detour_ratio": path_audit["maximum_detour_ratio"],
            "empty_assigned_paths": len(empty_paths),
            **scenario_audit,
            **chunk_audit,
        },
        "findings": [
            {
                "code": "empty_assigned_path",
                "count": len(empty_paths),
                "path_ids": empty_paths,
            }
        ]
        if empty_paths
        else [],
    }
    rendered = json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
