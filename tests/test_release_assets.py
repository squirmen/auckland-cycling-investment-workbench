from __future__ import annotations

import json
import tarfile
from pathlib import Path

from cycling_investment_workbench.provenance import hash_path, read_json
from cycling_investment_workbench.release_assets import package_web_release


def _fixture_run(tmp_path: Path) -> Path:
    run = tmp_path / "run-0123456789abcdef"
    data = run / "artifacts" / "export-web" / "data"
    data.mkdir(parents=True)
    layer_names = ("cells", "network", "candidates", "programmes", "counters")
    for name in layer_names:
        features = []
        if name == "candidates":
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    "properties": {
                        "metrics": {
                            "baseline": {
                                "network": {"bcrP5": 1.0, "bcrP50": 2.0, "bcrP95": 3.0},
                                "appraisal": {
                                    "available": True,
                                    "objectiveValue": 2.0,
                                    "objectiveUnit": "indicative BCR",
                                    "additionalCycleUsers": 1.0,
                                    "annualBikeKmDelta": 2.0,
                                    "odLowStressShareDelta": None,
                                    "bcrP5": 1.0,
                                    "bcrP50": 2.0,
                                    "bcrP95": 3.0,
                                    "meanRank": 1.0,
                                    "topKProbability": 1.0,
                                    "frontierProbability": 1.0,
                                    "warnings": ["screening only"],
                                },
                            }
                        }
                    },
                }
            ]
        (data / f"{name}.geojson").write_text(
            json.dumps({"features": features, "type": "FeatureCollection"}) + "\n",
            encoding="utf-8",
        )
    (data / "manifest.json").write_text(
        json.dumps(
            {
                "runId": run.name,
                "capabilities": {
                    "equity": "unavailable",
                    "sketchEvaluation": "unavailable",
                },
                "limitations": [],
                "portfolios": {"baseline": {"appraisal": [{"candidateId": "one"}]}},
                "summaries": {"baseline": {"appraisal": {"warnings": []}}},
                "layers": [
                    {
                        "id": "candidates",
                        "sha256": hash_path(data / "candidates.geojson").sha256,
                    }
                ],
                "sourceDecisions": [
                    {
                        "sourceId": "fixture",
                        "decision": "include",
                        "redistribution": "permitted",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    outputs = {
        "web_manifest": hash_path(data / "manifest.json").to_dict(root=run),
        **{name: hash_path(data / f"{name}.geojson").to_dict(root=run) for name in layer_names},
    }
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run.name,
                "stages": {"export-web": {"status": "succeeded", "outputs": outputs}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run


def test_release_asset_is_deterministic_and_contains_only_data_tree(tmp_path: Path) -> None:
    run = _fixture_run(tmp_path)
    first = package_web_release(run_dir=run, output_path=tmp_path / "first.tar.gz")
    second = package_web_release(run_dir=run, output_path=tmp_path / "second.tar.gz")

    assert first.sha256 == second.sha256
    with tarfile.open(first.path, "r:gz") as archive:
        names = sorted(member.name for member in archive.getmembers())
        assert all(name.startswith("data/") for name in names)
        notice_file = archive.extractfile("data/ASSET_NOTICE.json")
        assert notice_file is not None
        notice = json.loads(notice_file.read())
        manifest_file = archive.extractfile("data/manifest.json")
        candidate_file = archive.extractfile("data/candidates.geojson")
        assert manifest_file is not None
        assert candidate_file is not None
        web_manifest = json.loads(manifest_file.read())
        candidates = json.loads(candidate_file.read())
    assert notice["run_id"] == run.name
    assert notice["included_source_ids"] == ["fixture"]
    assert web_manifest["capabilities"]["appraisal"] == "withheld"
    assert web_manifest["portfolios"]["baseline"]["appraisal"] == []
    network = candidates["features"][0]["properties"]["metrics"]["baseline"]["network"]
    appraisal = candidates["features"][0]["properties"]["metrics"]["baseline"]["appraisal"]
    assert network["bcrP50"] is None
    assert appraisal["available"] is False
    assert appraisal["objectiveValue"] is None
    assert appraisal["bcrP50"] is None
    assert notice["files"]["candidates.geojson"]["sha256"] == web_manifest["layers"][0]["sha256"]
    assert read_json(run / "manifest.json")["run_id"] == run.name
