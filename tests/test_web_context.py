from copy import deepcopy

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cycling_investment_workbench.config import load_config
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic
from cycling_investment_workbench.web_context import add_web_context


def context_fixture(tmp_path):
    routes, portfolios = tmp_path / "routes", tmp_path / "portfolios"
    routes.mkdir()
    portfolios.mkdir()
    topology = {
        "crs": "EPSG:2193",
        "nodes": [{"id": str(i), "x": 1750000 + i * 100, "y": 5920000} for i in range(3)],
        "edges": [
            {
                "id": "existing",
                "u": "0",
                "v": "1",
                "lts": 1,
                "length_m": 100,
                "facility": "shared_path",
            }
        ],
    }
    topology_path = tmp_path / "topology.json"
    write_json_atomic(topology_path, topology)
    write_json_atomic(
        routes / "manifest.json",
        {
            "coverage": {
                "by_purpose": {
                    "commute": {
                        "estimated_assigned": 100,
                        "unit_specific_denominator": 125,
                        "estimated_routing_coverage": 0.8,
                    }
                },
                "commute_complete_source_market_denominator": 200,
                "commute_estimated_routing_coverage_of_complete_source_market": 0.5,
            },
            "scenario_summaries": {
                "baseline": {"assigned_route_sample_total": 10},
                "commute_8pct": {"complete_source_market_observed_cycle": 20},
            },
        },
    )
    rows = {
        routes / "od_ledger.parquet": [
            {
                "od_id": purpose,
                "purpose": purpose,
                "status": "assigned",
                "weighted_eligible": 100,
                "weighted_observed_cycle": 10,
            }
            for purpose in ("commute", "school")
        ],
        routes / "path_ledger.parquet": [
            {
                "od_id": purpose,
                "path_id": purpose,
                "purpose": purpose,
                "generalized_cost": 100,
                "probability": 1.0,
            }
            for purpose in ("commute", "school")
        ],
        routes / "scenario_od_ledger.parquet": [
            {"od_id": purpose, "scenario_id": "baseline", "scenario_cycle": 10.0}
            for purpose in ("commute", "school")
        ],
        portfolios / "path_candidate_savings.parquet": [
            {
                "path_id": purpose,
                "purpose": purpose,
                "candidate_id": "proposal",
                "generalized_cost_saving": 20.0,
            }
            for purpose in ("commute", "school")
        ],
    }
    for path, values in rows.items():
        pq.write_table(pa.Table.from_pylist(values), path)
    edges = [
        {
            "candidate_id": "proposal",
            "from_node_id": "1",
            "to_node_id": "2",
            "edge_sequence": 0,
            "baseline_direction": "both",
            "length_m": 100,
        }
    ]
    payload = {
        "manifest": {
            "portfolios": {"baseline": {"network": []}},
            "limitations": ["The browser network contains exact candidate edges only.", "Keep me"],
            "layers": [
                {"id": key, "defaultVisible": True, "licence": "fixture", "sourceIds": ["fixture"]}
                for key in ("cells", "network", "candidates")
            ],
        },
        "layers": {
            "candidates": {
                "features": [
                    {"properties": {"candidateId": "proposal", "metrics": {"unchanged": 42}}}
                ]
            }
        },
    }
    args = {
        "topology_path": topology_path,
        "candidate_edges": edges,
        "route_dir": routes,
        "portfolio_dir": portfolios,
        "parameters": load_config("configs/auckland.yml").parameters,
    }
    return payload, args


def test_context_enrichment_reads_real_ledgers_preserves_metrics_and_fingerprints(tmp_path):
    payload, args = context_fixture(tmp_path)
    topology_hash = sha256_file(args["topology_path"])
    add_web_context(payload, **args)
    manifest = payload["manifest"]
    properties = payload["layers"]["candidates"]["features"][0]["properties"]
    assert properties["metrics"] == {"unchanged": 42}
    assert properties["networkContext"]["role"] == "extends_area"
    assert properties["commuteRouteUse"]["baseline"]["before"] == 10
    assert properties["commuteRouteUse"]["baseline"]["after"] > 10
    assert manifest["demandContext"]["internalCoverage"] == 0.8
    assert manifest["demandContext"]["sourceCoverage"] == 0.5
    assert manifest["demandContext"]["capitalCostPerKm"] == 6000000
    assert manifest["title"].startswith("SPAN:")
    assert manifest["limitations"][0] == "Keep me"
    assert manifest["networkContext"]["sourceFiles"]["topology.json"] == topology_hash
    assert sha256_file(args["topology_path"]) == topology_hash
    assert all(len(value) == 64 for value in manifest["networkContext"]["sourceFiles"].values())
    assert payload["layers"]["existing"]["features"]
    # A refresh replaces the layer descriptor instead of accumulating duplicates.
    add_web_context(payload, **args)
    assert len([d for d in manifest["layers"] if d["id"] == "existing"]) == 1
    assert all(
        not d["defaultVisible"] for d in manifest["layers"] if d["id"] in {"cells", "candidates"}
    )


def test_context_rejects_broken_source_topology_before_enriching_payload(tmp_path):
    payload, args = context_fixture(tmp_path)
    before = deepcopy(payload)
    write_json_atomic(
        args["topology_path"],
        {
            "crs": "EPSG:2193",
            "nodes": [],
            "edges": [{"id": "broken", "u": "missing", "v": "also-missing", "lts": 1}],
        },
    )
    with pytest.raises(ValueError, match="missing node"):
        add_web_context(payload, **args)
    assert payload == before
