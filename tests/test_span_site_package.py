"""The site identity gate is separate from the existing web export integrity tests."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from cycling_investment_workbench.provenance import sha256_file

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_span_site.py"
spec = importlib.util.spec_from_file_location("package_span_site", SCRIPT)
assert spec and spec.loader
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def fixture(tmp_path, monkeypatch):
    site = tmp_path / "site"
    data = site / "data"
    data.mkdir(parents=True)
    (site / "documentation").mkdir()
    for name in (
        "research.html",
        ".htaccess",
        "span-mark.svg",
        "bpl-mark.svg",
        "documentation/effective-network.md",
    ):
        (site / name).write_text("fixture")
    (site / "index.html").write_text("<title>SPAN</title>")
    (site / "CNAME").write_text("span.tfwelch.com\n")
    (data / "intersections.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    manifest = {
        "dataStatus": "research_snapshot",
        "runId": "native",
        "effectiveNetwork": {"runId": "native", "topologySha256": "topology"},
    }
    research = {
        "runId": "native",
        "sourceHashes": {"topology": "topology"},
        "graph": {"nodes": 3},
        "intersectionContext": {"scenario": "default"},
    }
    (data / "manifest.json").write_text(json.dumps(manifest))
    (data / "access-experiment.json").write_text(json.dumps(research))
    manifest["journeyReport"] = {
        "url": "./data/access-experiment.json",
        "sha256": sha256_file(data / "access-experiment.json"),
        "runId": "native",
        "topologySha256": "topology",
    }
    (data / "manifest.json").write_text(json.dumps(manifest))
    comparison = {
        "scope": {"sourceHashes": research["sourceHashes"]},
        "scenarios": {"default": {"sha256": sha256_file(data / "access-experiment.json")}},
    }
    (data / "delay-comparison.json").write_text(json.dumps(comparison))
    monkeypatch.setattr(package, "verify_web_export", lambda *a, **kw: [])
    monkeypatch.setattr(package, "load_config", lambda *a: SimpleNamespace(export=None))
    output = tmp_path / "span.zip"
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--site", str(site), "--output", str(output)])
    return site, output


def test_complete_site_contains_hidden_settings_and_sha256_record(tmp_path, monkeypatch):
    site, output = fixture(tmp_path, monkeypatch)
    package.main()
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert ".htaccess" in archive.namelist()
        release = json.loads(archive.read("span-release.json"))
        assert release["product"].startswith("SPAN")
        assert release["intendedHost"] == "span.tfwelch.com"
        assert release["files"]["index.html"] == sha256_file(site / "index.html")
        assert archive.getinfo("span-release.json").external_attr >> 16 & 0o777 == 0o644
    assert json.loads(output.with_suffix(".json").read_text())["archive"]["sha256"] == sha256_file(
        output
    )


@pytest.mark.parametrize(
    "condition",
    [
        "wrong_product",
        "wrong_host",
        "stale",
        "private",
        "missing_descriptor",
        "descriptor_run",
        "descriptor_url",
        "descriptor_topology",
    ],
)
def test_site_gate_rejects_wrong_or_unsafe_packages(tmp_path, monkeypatch, condition):
    site, output = fixture(tmp_path, monkeypatch)
    if condition == "wrong_product":
        (site / "index.html").write_text("<title>Legacy PCT</title>")
    elif condition == "wrong_host":
        (site / "CNAME").write_text("ciw.tfwelch.com")
    elif condition == "stale":
        with (site / "data/access-experiment.json").open("a") as stream:
            stream.write("\n")
    elif condition.startswith("descriptor_") or condition == "missing_descriptor":
        path = site / "data/manifest.json"
        manifest = json.loads(path.read_text())
        if condition == "missing_descriptor":
            del manifest["journeyReport"]
        else:
            key = {
                "descriptor_run": "runId",
                "descriptor_url": "url",
                "descriptor_topology": "topologySha256",
            }[condition]
            manifest["journeyReport"][key] = "wrong"
        path.write_text(json.dumps(manifest))
    else:
        (site / "data/private.parquet").write_bytes(b"private")
    with pytest.raises(ValueError):
        package.main()
    assert not output.exists()
