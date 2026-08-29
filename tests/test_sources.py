from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cycling_investment_workbench import sources as source_module
from cycling_investment_workbench.provenance import sha256_file
from cycling_investment_workbench.sources import (
    SourceFetchError,
    SourceIntegrityError,
    SourceRegistry,
    SourceSpec,
)


def _source(
    *,
    acquisition: str = "manual",
    destination: str = "raw/input.bin",
    url: str | None = None,
    sha256: str | None = None,
    required: bool = True,
    **options: object,
) -> SourceSpec:
    value = {
        "id": "example_source",
        "title": "Example source",
        "acquisition": acquisition,
        "role": "upstream",
        "destination": destination,
        "required": required,
        "sha256": sha256,
        "homepage": None,
        "url": url,
        "license": "Test licence",
        "license_url": None,
        "attribution": "Test custodian",
        "redistribution": "restricted",
    }
    value.update(options)
    return SourceSpec.from_mapping(value, context="source")


def test_download_is_atomic_and_hash_verified(tmp_path: Path) -> None:
    provider_file = tmp_path / "provider.bin"
    provider_file.write_bytes(b"registered content")
    digest = sha256_file(provider_file)
    data_root = tmp_path / "data"
    registry = SourceRegistry(
        (_source(acquisition="download", url=provider_file.as_uri(), sha256=digest),),
        data_root,
    )

    records = registry.fetch()

    assert records["example_source"].usable
    assert (data_root / "raw/input.bin").read_bytes() == b"registered content"
    assert not list((data_root / "raw").glob("*.part"))


def test_hash_mismatch_never_replaces_destination(tmp_path: Path) -> None:
    provider_file = tmp_path / "provider.bin"
    provider_file.write_bytes(b"wrong content")
    data_root = tmp_path / "data"
    registry = SourceRegistry(
        (
            _source(
                acquisition="download",
                url=provider_file.as_uri(),
                sha256="0" * 64,
            ),
        ),
        data_root,
    )

    with pytest.raises(SourceIntegrityError, match="sha256 mismatch"):
        registry.fetch()

    assert not (data_root / "raw/input.bin").exists()


def test_unpinned_download_requires_explicit_opt_in(tmp_path: Path) -> None:
    provider_file = tmp_path / "provider.bin"
    provider_file.write_bytes(b"content")
    registry = SourceRegistry(
        (_source(acquisition="download", url=provider_file.as_uri()),),
        tmp_path / "data",
    )

    with pytest.raises(SourceIntegrityError, match="no registered sha256"):
        registry.fetch()

    assert registry.fetch(accept_unverified=True)["example_source"].usable


def test_manual_missing_source_is_reported_without_mutation(tmp_path: Path) -> None:
    registry = SourceRegistry((_source(),), tmp_path / "data")

    record = registry.fetch()["example_source"]

    assert record.status == "missing"
    assert record.required
    assert not record.path.exists()


def test_external_source_path_is_serialised_logically(tmp_path: Path) -> None:
    data_root = tmp_path / "external"
    path = data_root / "raw/input.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"content")
    record = SourceRegistry((_source(),), data_root).inspect(_source())

    serialised = record.to_dict(root=tmp_path / "project", data_root=data_root)

    assert serialised["path"] == "@data/raw/input.bin"


def test_source_destination_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError, match="normalised relative path"):
        _source(destination="../outside.bin")


def test_arcgis_query_fetches_every_transfer_limited_page_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del timeout
        if not url.endswith("/query"):
            return {"objectIdField": "OBJECTID"}
        offset = int(parameters["resultOffset"])
        pages = {
            0: [
                {"type": "Feature", "id": 1, "geometry": None, "properties": {}},
                {"type": "Feature", "id": 2, "geometry": None, "properties": {}},
            ],
            2: [{"type": "Feature", "id": 3, "geometry": None, "properties": {}}],
        }
        return {
            "type": "FeatureCollection",
            "features": pages[offset],
            "exceededTransferLimit": offset == 0,
        }

    monkeypatch.setattr(source_module, "_request_json", fake_request)
    spec = _source(
        acquisition="arcgis_query",
        destination="raw/layer.geojson",
        url="https://example.test/FeatureServer/0",
        page_size=2,
    )
    registry = SourceRegistry((spec,), tmp_path / "data")

    record = registry.fetch()[spec.id]

    assert record.usable
    payload = json.loads(record.path.read_text(encoding="utf-8"))
    assert [feature["id"] for feature in payload["features"]] == [1, 2, 3]
    assert not list(record.path.parent.glob("*.part"))


def test_arcgis_query_fails_closed_when_provider_repeats_a_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def repeated_page(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del parameters, timeout
        if not url.endswith("/query"):
            return {"objectIdField": "OBJECTID"}
        return {
            "features": [
                {"type": "Feature", "id": 1, "geometry": None, "properties": {}},
                {"type": "Feature", "id": 2, "geometry": None, "properties": {}},
            ],
            "exceededTransferLimit": True,
        }

    monkeypatch.setattr(source_module, "_request_json", repeated_page)
    spec = _source(
        acquisition="arcgis_query",
        destination="raw/layer.geojson",
        url="https://example.test/FeatureServer/0",
        page_size=2,
    )

    with pytest.raises(SourceFetchError, match="repeated a feature"):
        SourceRegistry((spec,), tmp_path / "data").fetch()


def test_arcgis_hash_mismatch_preserves_existing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del parameters, timeout
        if not url.endswith("/query"):
            return {"objectIdField": "OBJECTID"}
        return {
            "features": [
                {
                    "type": "Feature",
                    "id": 2,
                    "geometry": None,
                    "properties": {},
                }
            ],
            "exceededTransferLimit": False,
        }

    monkeypatch.setattr(source_module, "_request_json", fake_request)
    spec = _source(
        acquisition="arcgis_query",
        destination="raw/layer.geojson",
        url="https://example.test/FeatureServer/0",
        sha256="0" * 64,
    )
    registry = SourceRegistry((spec,), tmp_path / "data")
    destination = registry.path_for(spec)
    destination.parent.mkdir(parents=True)
    original = b'{"verified":"snapshot"}\n'
    destination.write_bytes(original)

    with pytest.raises(SourceIntegrityError, match="sha256 mismatch"):
        registry.fetch(force=True)

    assert destination.read_bytes() == original
    assert not list(destination.parent.glob("*.part"))


def test_arcgis_record_count_mismatch_preserves_existing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del parameters, timeout
        if not url.endswith("/query"):
            return {"objectIdField": "OBJECTID"}
        return {
            "features": [{"type": "Feature", "id": 1, "geometry": None, "properties": {}}],
            "exceededTransferLimit": False,
        }

    monkeypatch.setattr(source_module, "_request_json", fake_request)
    spec = _source(
        acquisition="arcgis_query",
        destination="raw/layer.geojson",
        url="https://example.test/FeatureServer/0",
        expected_record_count=2,
    )
    registry = SourceRegistry((spec,), tmp_path / "data")
    destination = registry.path_for(spec)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'{"verified":"snapshot"}\n')

    with pytest.raises(SourceIntegrityError, match="record-count mismatch"):
        registry.fetch(force=True)

    assert destination.read_bytes() == b'{"verified":"snapshot"}\n'
    assert not list(destination.parent.glob("*.part"))


def test_ckan_datastore_fetches_all_pages_with_stable_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queries: list[str] = []

    def fake_request(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del url, timeout
        sql = str(parameters["sql"])
        queries.append(sql)
        offset = int(re.search(r"OFFSET ([0-9]+)$", sql).group(1))
        pages = {
            0: [{"_id": 1, "name": "A"}, {"_id": 2, "name": "B"}],
            2: [{"_id": 3, "name": "C"}],
        }
        return {"success": True, "result": {"records": pages[offset]}}

    monkeypatch.setattr(source_module, "_request_json", fake_request)
    spec = _source(
        acquisition="ckan_datastore",
        destination="raw/schools.json",
        url="https://example.test/api/3/action/datastore_search_sql",
        resource_id="4b292323-9fcc-41f8-814b-3c7b19cf14b3",
        where="\"Regional_Council\" = 'Auckland Region'",
        page_size=2,
        include_geometry=False,
    )

    record = SourceRegistry((spec,), tmp_path / "data").fetch()[spec.id]

    payload = json.loads(record.path.read_text(encoding="utf-8"))
    assert [item["_id"] for item in payload["records"]] == [1, 2, 3]
    assert len(queries) == 2
    assert all('ORDER BY "_id" ASC' in query for query in queries)


def test_ckan_record_count_is_verified_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request(
        url: str, parameters: dict[str, object], *, timeout: float
    ) -> dict[str, object]:
        del url, parameters, timeout
        return {"success": True, "result": {"records": [{"_id": 1}]}}

    monkeypatch.setattr(source_module, "_request_json", fake_request)
    spec = _source(
        acquisition="ckan_datastore",
        destination="raw/records.json",
        url="https://example.test/api/3/action/datastore_search_sql",
        resource_id="4b292323-9fcc-41f8-814b-3c7b19cf14b3",
        expected_record_count=2,
    )

    with pytest.raises(SourceIntegrityError, match="expected 2, received 1"):
        SourceRegistry((spec,), tmp_path / "data").fetch()

    assert not (tmp_path / "data/raw/records.json").exists()
