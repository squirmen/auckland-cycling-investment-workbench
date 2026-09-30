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
        assert "components" not in release
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


@pytest.mark.parametrize("fault", [None, "source", "bytes", "count", "url", "format"])
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
    }
    if fault == "source":
        manifest["compactCandidates"]["sourceSha256"] = "wrong"
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


STAND_URL = "https://span.tfwelch.com/parking/uoa/"


def parking_fixture(site):
    """The site's parking folder as STAND's build writes it, with STAND in uoa/."""
    uoa = site / "parking/uoa"
    (uoa / "data").mkdir(parents=True)
    (site / "parking/index.html").write_text("<title>SPAN · Bike parking</title>")
    (uoa / "index.html").write_text("<title>STAND · University of Auckland bike parking</title>")
    (uoa / ".htaccess").write_text("Options -Indexes\n")
    oembed = {
        "version": "1.0",
        "type": "rich",
        "provider_url": "https://betterplaces.blogs.auckland.ac.nz",
        "html": f'<iframe src="{STAND_URL}" title="STAND"></iframe>',
    }
    (uoa / "oembed.json").write_text(json.dumps(oembed))
    (uoa / "data/results.json").write_text(json.dumps({"built": "2026-09-29T23:10:50+13:00"}))
    return uoa


@pytest.mark.parametrize("built", ["2026-09-29T23:10:50+13:00", None])
def test_site_with_stand_packages_and_records_the_parking_folder(tmp_path, monkeypatch, built):
    site, output = fixture(tmp_path, monkeypatch)
    uoa = parking_fixture(site)
    (uoa / "data/results.json").write_text(json.dumps({"built": built} if built else {}))
    package.main()
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        release = json.loads(archive.read("span-release.json"))
    assert {
        "index.html",
        "parking/index.html",
        "parking/uoa/index.html",
        "parking/uoa/.htaccess",
        "parking/uoa/oembed.json",
        "parking/uoa/data/results.json",
    } <= names
    assert release["components"] == {
        "parking/uoa": {"product": "STAND", "url": STAND_URL, "dataBuilt": built}
    }
    assert release["files"]["parking/uoa/.htaccess"] == sha256_file(uoa / ".htaccess")
    record = json.loads(output.with_suffix(".json").read_text())
    assert record["components"] == release["components"]


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("no_htaccess", r"missing parking/uoa/\.htaccess"),
        ("no_parking_page", r"missing parking/index\.html"),
        ("no_results", r"missing parking/uoa/data/results\.json"),
        ("not_stand", "not the STAND map"),
        ("off_host", "oembed.json must embed pages under"),
        ("outside_stand", "oembed.json must embed pages under"),
        ("climbs_out", "oembed.json must embed pages under"),
        ("off_host_url", "oembed.json must embed pages under"),
        ("no_embed", "oembed.json must embed pages under"),
        ("symlink", "parking must be a folder"),
        ("private", "source/private"),
        ("secret", "source/private"),
        ("hidden_file", "hidden file in the parking site"),
        ("hidden_folder", "hidden file in the parking site"),
    ],
)
def test_parking_gate_refuses_an_incomplete_or_misdirected_stand(
    tmp_path, monkeypatch, fault, message
):
    site, output = fixture(tmp_path, monkeypatch)
    uoa = parking_fixture(site)
    oembed = json.loads((uoa / "oembed.json").read_text())
    if fault == "no_htaccess":
        (uoa / ".htaccess").unlink()
    elif fault == "no_parking_page":
        (site / "parking/index.html").unlink()
    elif fault == "no_results":
        (uoa / "data/results.json").unlink()
    elif fault == "not_stand":
        (uoa / "index.html").write_text("<title>Bike parking map</title>")
    elif fault == "off_host":
        oembed["html"] = '<iframe src="https://example.org/"></iframe>'
    elif fault == "outside_stand":
        oembed["html"] = '<iframe src="https://span.tfwelch.com/"></iframe>'
    elif fault == "climbs_out":
        oembed["html"] = f'<iframe src="{STAND_URL}../../"></iframe>'
    elif fault == "off_host_url":
        oembed["url"] = "https://example.org/"
    elif fault == "no_embed":
        del oembed["html"]
    elif fault == "symlink":
        (site / "parking").rename(tmp_path / "parking")
        (site / "parking").symlink_to(tmp_path / "parking", target_is_directory=True)
    elif fault == "private":
        (uoa / "data/sites.parquet").write_bytes(b"private")
    elif fault == "secret":
        (uoa / ".env").write_text("TOKEN=private\n")
    elif fault == "hidden_file":
        (uoa / ".DS_Store").write_bytes(b"\0")
    else:
        (uoa / ".git").mkdir()
        (uoa / ".git/config").write_text("[core]\n")
    (uoa / "oembed.json").write_text(json.dumps(oembed))
    with pytest.raises(ValueError, match=message):
        package.main()
    assert not output.exists()


@pytest.mark.parametrize("with_parking", [True, False])
@pytest.mark.parametrize("stray", ["uoa/index.html", "stand/index.html", "parking.html"])
def test_a_stray_root_is_still_refused(tmp_path, monkeypatch, stray, with_parking):
    site, output = fixture(tmp_path, monkeypatch)
    if with_parking:
        parking_fixture(site)
    (site / stray).parent.mkdir(exist_ok=True)
    (site / stray).write_text("<title>STAND</title>")
    with pytest.raises(ValueError, match="unexpected public release file"):
        package.main()
    assert not output.exists()
