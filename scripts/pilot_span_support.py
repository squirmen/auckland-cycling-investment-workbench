#!/usr/bin/env python3
"""Reroute all stored locations in influential cells, outside the source run/web."""

from __future__ import annotations

import argparse
import gc
import json
import resource
from collections import defaultdict
from dataclasses import replace
from math import isclose
from pathlib import Path
from time import perf_counter

import pyarrow.parquet as pq
from build_span_context import require_local, verify_ledgers

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.provenance import content_hash, sha256_file, write_json_atomic
from cycling_investment_workbench.r5_routing import ProjectTopologyIndex, R5CyclingEngine
from cycling_investment_workbench.research.stability import grouped_contributions
from cycling_investment_workbench.research.support import summarise_support
from cycling_investment_workbench.route_context import read_commute_market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/stability/support-pilot.json"))
    parser.add_argument("--seeds", nargs="+", type=int, default=[20260924, 20260925, 20260926])
    parser.add_argument("--max-records", type=int, default=350)
    parser.add_argument("--max-memory", default="4G", help="R5 JVM heap limit")
    parser.add_argument("--r5-classpath", type=Path, required=True, help="Existing local R5 jar")
    args = parser.parse_args()
    started = perf_counter()
    repository = Path(__file__).resolve().parents[1]
    root, output = args.run.resolve(), args.output.resolve()
    if output.is_relative_to(root) or output.is_relative_to(repository / "web"):
        raise ValueError("pilot output must be outside the source run and browser tree")
    if args.max_records < 1:
        raise ValueError("max-records must be positive")
    if not args.seeds or len(set(args.seeds)) != len(args.seeds):
        raise ValueError("seeds must be unique")
    jar_hash = sha256_file(args.r5_classpath)
    if jar_hash != "d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7":
        raise ValueError("pilot requires the pinned R5 7.5.1-r5py jar")
    manifest = json.loads((root / "manifest.json").read_text())
    config = json.loads((root / "config.snapshot.json").read_text())
    audit = json.loads(args.audit.read_text())
    if audit["runId"] != manifest["run_id"]:
        raise ValueError("audit and source run differ")

    def artifact(stage, name):
        path = (root / manifest["stages"][stage]["outputs"][name]["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("artifact escapes source run")
        return path

    routes = artifact("assign-routes", "routes")
    portfolios = artifact("evaluate-portfolios", "portfolios")
    candidates = artifact("generate-candidates", "candidates")
    topology_dir = artifact("build-topology", "topology")
    print("Checking source ledgers and identifying private case membership…", flush=True)
    for folder, names in [
        (routes, ("od_ledger.parquet", "path_ledger.parquet", "scenario_od_ledger.parquet")),
        (portfolios, ("path_candidate_savings.parquet",)),
        (candidates, ("candidate_ledger.parquet",)),
    ]:
        verify_ledgers(folder, names)
    choices, affected, activity = read_commute_market(routes, portfolios)
    scenario = audit["scenario"]
    choices = {
        od: replace(c, baseline_activity=activity[scenario][od]) for od, c in choices.items()
    }
    groups = {
        r["od_id"]: r["source_cell_id"]
        for batch in pq.ParquetFile(routes / "od_ledger.parquet").iter_batches(
            columns=["od_id", "source_cell_id"]
        )
        for r in batch.to_pylist()
        if r["od_id"] in choices
    }
    drivers = [r["candidateId"] for r in audit["auditedCandidates"]]
    parameters = config["parameters"]
    response = parameters["demand_response"]
    contributions, _ = grouped_contributions(
        choices,
        groups,
        {cid: sorted(affected.get(cid, ())) for cid in drivers},
        frozenset(),
        cost_scale=parameters["routing"]["path_size_logit_cost_scale"],
        response=DemandResponseParameters(
            response["cost_elasticity"]["mode"], response["minimum_probability"]
        ),
    )
    case_groups = {}
    for case in audit["cases"]:
        found = {
            min(contributions[cid], key=lambda g, values=contributions[cid]: (-values[g], g))
            for cid in case["dominantContributorToCandidateIds"]
        }
        if len(found) != 1:
            raise ValueError("cannot reproduce audit case membership")
        case_groups[case["case"]] = found.pop()
    wanted_groups = set(case_groups.values())
    del contributions, choices, groups, affected, activity
    records = []
    columns = [
        "od_id",
        "source_cell_id",
        "eligible",
        "route_sample_selected",
        "origin_x",
        "origin_y",
        "destination_x",
        "destination_y",
    ]
    for batch in pq.ParquetFile(routes / "od_ledger.parquet").iter_batches(columns=columns):
        records.extend(
            {**r, "id": r["od_id"]}
            for r in batch.to_pylist()
            if r["source_cell_id"] in wanted_groups
        )
    records.sort(key=lambda r: r["id"])
    if not records or len(records) > args.max_records:
        raise ValueError("support enumeration exceeds declared pilot bounds")
    baseline_ids = {r["id"] for r in records if r["route_sample_selected"]}
    published = defaultdict(list)
    for batch in pq.ParquetFile(routes / "path_ledger.parquet").iter_batches(
        columns=[
            "od_id",
            "project_edge_ids",
            "project_edge_reversed",
            "generalized_cost",
            "probability",
        ]
    ):
        for row in batch.to_pylist():
            if row["od_id"] in baseline_ids:
                published[row["od_id"]].append(row)
    project_edges = {
        row["candidate_id"]: set(row["ordered_edge_ids"])
        for batch in pq.ParquetFile(candidates / "candidate_ledger.parquet").iter_batches(
            columns=["candidate_id", "ordered_edge_ids"]
        )
        for row in batch.to_pylist()
        if row["candidate_id"] in drivers
    }
    topology_path = topology_dir / "topology.json"
    pbfs = sorted(topology_dir.glob("*.osm.pbf"))
    if len(pbfs) != 1:
        raise ValueError("source topology needs exactly one PBF")
    require_local(topology_path)
    require_local(pbfs[0])
    source_hashes = {
        "topology": sha256_file(topology_path),
        "pbf": sha256_file(pbfs[0]),
        "odLedger": sha256_file(routes / "od_ledger.parquet"),
        "pathLedger": sha256_file(routes / "path_ledger.parquet"),
        "candidateLedger": sha256_file(candidates / "candidate_ledger.parquet"),
        "config": sha256_file(root / "config.snapshot.json"),
        "audit": sha256_file(args.audit),
        "r5Jar": jar_hash,
    }
    if source_hashes["odLedger"] != audit["sourceHashes"]["od_ledger.parquet"]:
        raise ValueError("audit source ledger differs")
    implementation_hashes = {
        name: sha256_file(repository / "src/cycling_investment_workbench" / name)
        for name in ("r5_routing.py", "research/support.py", "research/stability.py")
    }
    implementation_hashes["pilotScript"] = sha256_file(Path(__file__))
    identity = content_hash({"sources": source_hashes, "implementation": implementation_hashes})
    cache = repository / "build/stability/private-support" / identity
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Enumerating {len(records)} stored pairs in {len(case_groups)} cells…", flush=True)
    outcomes = {}
    engine = None
    startup_s = 0.0
    routing_s = 0.0
    reused = 0
    for index, record in enumerate(records, 1):
        cached = cache / (content_hash(record) + ".json")
        if cached.is_file():
            outcomes[record["id"]] = json.loads(cached.read_text())
            reused += 1
            continue
        if engine is None:
            before = perf_counter()
            print(
                "Building the full source topology and pinned R5 engine (no local crop)…",
                flush=True,
            )
            payload = json.loads(topology_path.read_text())
            topology = ProjectTopologyIndex.from_payload(
                payload, comfort_parameters=parameters["network"]["comfort_impedance"]
            )
            del payload
            gc.collect()
            routing = parameters["routing"]
            engine = R5CyclingEngine(
                pbfs[0],
                topology,
                project_crs=config["project"]["crs"],
                bicycle_speed_kph=routing["bicycle_speed_kph"],
                maximum_bicycle_lts=routing["maximum_bicycle_lts"],
                unmapped_edge_multiplier=routing["unmapped_edge_multiplier"],
            )
            startup_s = perf_counter() - before
        before = perf_counter()
        pair = topology.snap_pair(
            record["origin_x"],
            record["origin_y"],
            record["destination_x"],
            record["destination_y"],
            maximum_distance_m=parameters["network"]["maximum_snap_distance_m"],
            origin_allowed_node_indices=engine.origin_node_indices,
            destination_allowed_node_indices=engine.destination_node_indices,
        )
        result = None
        if pair:
            options = {
                k: parameters["routing"][k]
                for k in (
                    "plausible_paths",
                    "maximum_cost_ratio",
                    "maximum_detour_ratio",
                    "maximum_shared_edge_ratio",
                    "path_size_coefficient",
                    "alternative_penalty_multiplier",
                    "maximum_alternative_attempts",
                    "engine_link_tolerance_m",
                )
            }
            options["cost_scale"] = parameters["routing"]["path_size_logit_cost_scale"]
            result = engine.route(*pair, **options)
        out = {
            "status": result.status if result else "unassigned",
            "failureReason": result.failure_reason if result else "no_compatible_snap_pair",
            "shortestDistanceM": result.shortest_distance_m if result else None,
            "candidateProbabilities": {},
        }
        if result and result.status == "assigned":
            alternative_edges = [
                {topology.segments[i].edge_id for i in a.path.project_edge_indices}
                for a in result.alternatives
            ]
            out["candidateProbabilities"] = {
                cid: min(
                    1.0,
                    sum(
                        a.probability
                        for a, edges in zip(result.alternatives, alternative_edges, strict=True)
                        if edges & project_edges[cid]
                    ),
                )
                for cid in drivers
            }
            if record["id"] in baseline_ids:
                old = published[record["id"]]
                fresh = [
                    {
                        "project_edge_ids": [
                            topology.segments[t.segment_index].edge_id for t in a.path.traversals
                        ],
                        "project_edge_reversed": [t.reversed for t in a.path.traversals],
                        "generalized_cost": a.path.generalized_cost,
                        "probability": a.probability,
                    }
                    for a in result.alternatives
                ]
                out["publishedRouteParity"] = len(old) == len(fresh) and all(
                    a["project_edge_ids"] == b["project_edge_ids"]
                    and a["project_edge_reversed"] == b["project_edge_reversed"]
                    and isclose(a["generalized_cost"], b["generalized_cost"], rel_tol=1e-9)
                    and isclose(a["probability"], b["probability"], abs_tol=1e-9)
                    for a, b in zip(old, fresh, strict=True)
                )
        routing_s += perf_counter() - before
        write_json_atomic(cached, out)
        outcomes[record["id"]] = out
        if index % 10 == 0 or index == len(records):
            print(f"Routed {index}/{len(records)} stored pairs", flush=True)
    report = {
        "status": "targeted_finite_support_routing_pilot",
        "runId": manifest["run_id"],
        "sourceHashes": source_hashes,
        "implementationHashes": implementation_hashes,
        "sampling": {
            "seeds": args.seeds,
            "recordsPerCell": [1, 5],
            "design": "stratified_simple_random_without_replacement",
            "estimator": "Horvitz-Thompson",
            "newSpatialLocations": False,
        },
        "sourceRecords": len(records),
        "freshlyRouted": len(records) - reused,
        "reusedCacheRecords": reused,
        "engineStartupS": startup_s,
        "routingS": routing_s,
        "elapsedS": perf_counter() - started,
        "peakProcessRssRaw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peakRssUnit": "bytes on macOS; KiB on Linux",
        "cases": [
            {
                "case": case["case"],
                **summarise_support(
                    [r for r in records if r["source_cell_id"] == case_groups[case["case"]]],
                    outcomes,
                    case["dominantContributorToCandidateIds"],
                    seeds=args.seeds,
                ),
            }
            for case in audit["cases"]
        ],
        "limitations": [
            "Targeted influential cells, not a representative Auckland sample.",
            "Enumerates existing stored locations; no new within-cell locations are generated.",
            "Route use means any part of a candidate occurs on a retained plausible path.",
            "Failures remain in the denominator with explicit lower and upper usage bounds.",
            "Seeded HT mass estimates vary with unequal record masses; no renormalisation.",
            "Source support masses are unchanged; suppressed demand is not reconstructed.",
            "No demand response, ridership forecast, project ranking or reoptimisation is run.",
            "Full bounded source network, with existing source boundaries and routing assumptions.",
            "Warm/cold runtime and cached runs are distinguished; RSS includes Python and JVM.",
        ],
    }
    write_json_atomic(output, report)
    print(
        json.dumps(
            {
                "output": str(output),
                "records": len(records),
                "baselineRouteParity": all(
                    c["publishedSampleRouteParity"] for c in report["cases"]
                ),
                "elapsedS": report["elapsedS"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
