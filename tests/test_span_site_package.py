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
        "span-preview.jpg",
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


@pytest.mark.parametrize("fault", [None, "source", "bytes", "size", "count", "url", "format"])
def test_compact_candidate_package_integrity(tmp_path, monkeypatch, fault):
    site, output = fixture(tmp_path, monkeypatch)
    path = site / "data/candidates.compact.json"
    path.write_text(json.dumps({"format": "span-candidates-v1", "metrics": [], "features": []}))
    manifest_path = site / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["layers"] = [{"id": "candidates", "sha256": "source"}]
    manifest["compactCandidates"] = {
        "format": "span-candidates-v1",
        "url": "./data/candidates.compact.json",
        "sourceSha256": "source",
        "sha256": sha256_file(path),
        "featureCount": 0,
        "bytes": path.stat().st_size,
    }
    if fault == "source":
        manifest["compactCandidates"]["sourceSha256"] = "wrong"
    elif fault == "size":
        manifest["compactCandidates"]["bytes"] += 1
    elif fault == "bytes":
        path.write_text("changed")
    elif fault == "count":
        manifest["compactCandidates"]["featureCount"] = 10
    elif fault in {"url", "format"}:
        manifest["compactCandidates"][fault] = "wrong"
    manifest_path.write_text(json.dumps(manifest))
    if fault:
        with pytest.raises(ValueError, match="compact candidate"):
            package.main()
        assert not output.exists()
    else:
        package.main()
        assert output.exists()


@pytest.mark.parametrize(
    "fault", [None, "source", "bytes", "size", "count", "url", "scope", "coverage", "duplicate"]
)
def test_initial_candidate_package_integrity(tmp_path, monkeypatch, fault):
    site, output = fixture(tmp_path, monkeypatch)
    path = site / "data/candidates.initial.json"
    features = [{"properties": {"candidateId": "A"}}]
    if fault == "duplicate":
        features *= 2
    path.write_text(
        json.dumps({"format": "span-candidates-v1", "metrics": [], "features": features})
    )
    manifest_path = site / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["layers"] = [{"id": "candidates", "sha256": "source"}]
    manifest["portfolios"] = {
        "baseline": {"network": [{"candidateId": "missing" if fault == "coverage" else "A"}]}
    }
    manifest["initialCandidates"] = {
        "format": "span-candidates-v1",
        "scope": "portfolios_and_frontiers_v1",
        "url": "./data/candidates.initial.json",
        "sourceSha256": "source",
        "sha256": sha256_file(path),
        "featureCount": len(features),
        "bytes": path.stat().st_size,
    }
    if fault == "source":
        manifest["initialCandidates"]["sourceSha256"] = "wrong"
    elif fault == "size":
        manifest["initialCandidates"]["bytes"] += 1
    elif fault == "bytes":
        path.write_text("changed")
    elif fault == "count":
        manifest["initialCandidates"]["featureCount"] = 10
    elif fault in {"url", "scope"}:
        manifest["initialCandidates"][fault] = "wrong"
    manifest_path.write_text(json.dumps(manifest))
    if fault:
        with pytest.raises(ValueError, match="initial candidate"):
            package.main()
        assert not output.exists()
    else:
        package.main()
        assert output.exists()


def large_text(label):
    """Text that is over the size limit for a brotli copy and differs by label."""
    return json.dumps({"label": label, "rows": [f"{label}-{i}" for i in range(400)]})


@pytest.mark.parametrize("compact", [True, False])
def test_large_text_files_get_checked_brotli_copies(tmp_path, monkeypatch, compact):
    site, output = fixture(tmp_path, monkeypatch)
    (site / "assets").mkdir()
    (site / "assets/app.js").write_text(large_text("script"))
    (site / "assets/app.css").write_text(large_text("style"))
    (site / "assets/pin.png").write_bytes(bytes(range(256)) * 16)
    (site / "data/candidates.geojson").write_text(large_text("canonical"))
    (site / "data/small.json").write_text("{}")
    manifest_path = site / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["padding"] = large_text("manifest")
    if compact:
        path = site / "data/candidates.compact.json"
        path.write_text(
            json.dumps({"format": "span-candidates-v1", "metrics": [], "features": []}) + " " * 2048
        )
        manifest["layers"] = [{"id": "candidates", "sha256": "source"}]
        manifest["compactCandidates"] = {
            "format": "span-candidates-v1",
            "url": "./data/candidates.compact.json",
            "sourceSha256": "source",
            "sha256": sha256_file(path),
            "featureCount": 0,
        }
    manifest_path.write_text(json.dumps(manifest))
    package.main()
    expected = {"assets/app.js.br", "assets/app.css.br", "data/manifest.json.br"}
    expected.add("data/candidates.compact.json.br" if compact else "data/candidates.geojson.br")
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        release = json.loads(archive.read("span-release.json"))
        copies = {name for name in archive.namelist() if name.endswith(".br")}
        assert copies == expected
        for name in copies:
            packed = archive.read(name)
            source = (site / name.removesuffix(".br")).read_bytes()
            decoded = package.pa.Codec("brotli").decompress(
                packed, decompressed_size=len(source), asbytes=True
            )
            assert decoded == source and len(packed) < len(source)
            assert release["files"][name] == package.sha256(packed).hexdigest()
            info = archive.getinfo(name)
            assert info.compress_type == package.ZIP_STORED
            assert info.external_attr >> 16 & 0o777 == 0o644
            assert info.date_time[0] > 1980
    assert release["brotliCopies"]["files"] == len(expected)
    assert release["brotliCopies"]["bytes"] < release["brotliCopies"]["sourceBytes"]
    assert (
        set(release["files"])
        == {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()} | expected
    )


def test_brotli_copies_can_be_left_out_and_stale_ones_are_refused(tmp_path, monkeypatch):
    site, output = fixture(tmp_path, monkeypatch)
    (site / "assets").mkdir()
    (site / "assets/app.js").write_text(large_text("script"))
    monkeypatch.setattr("sys.argv", [*package.sys.argv, "--no-brotli"])
    package.main()
    with ZipFile(output) as archive:
        release = json.loads(archive.read("span-release.json"))
        assert not [name for name in archive.namelist() if name.endswith(".br")]
    assert release["brotliCopies"] == {"files": 0, "sourceBytes": 0, "bytes": 0}
    output.unlink()
    (site / "assets/app.js.br").write_bytes(b"left over from an earlier build")
    with pytest.raises(ValueError, match="brotli copy already in the built site"):
        package.main()
    assert not output.exists()


def test_a_brotli_copy_that_does_not_decode_to_its_source_is_refused(monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def compress(self, data, asbytes):
            return b"packed"

        def decompress(self, packed, decompressed_size, asbytes):
            return b"something else"

    monkeypatch.setattr(package.pa, "Codec", Broken)
    with pytest.raises(ValueError, match="does not decode"):
        package.brotli_copy(b"source")
