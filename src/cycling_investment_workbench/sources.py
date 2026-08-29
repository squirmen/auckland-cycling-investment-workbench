"""Registered input acquisition and integrity checks."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .provenance import sha256_file

_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_ROLE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESOURCE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ACQUISITION = frozenset({"download", "manual", "arcgis_query", "ckan_datastore"})
_REDISTRIBUTION = frozenset({"permitted", "restricted", "unknown"})
_URL_SCHEMES = frozenset({"file", "http", "https"})


class SourceError(ValueError):
    """Base class for source-registry failures."""


class SourceIntegrityError(SourceError):
    """Raised when source content fails its registered integrity check."""


class SourceFetchError(SourceError):
    """Raised when a registered source cannot be acquired."""


def _verify_expected_record_count(spec: SourceSpec, actual: int) -> None:
    expected = spec.expected_record_count
    if expected is not None and actual != expected:
        raise SourceIntegrityError(
            f"record-count mismatch for {spec.id}: expected {expected}, received {actual}"
        )


def _strict_keys(
    value: Mapping[str, Any], *, required: set[str], optional: set[str], context: str
) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise SourceError(f"{context} is missing: {', '.join(sorted(missing))}")
    if unknown:
        raise SourceError(f"{context} has unknown keys: {', '.join(sorted(unknown))}")


def _required_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceError(f"{context} must be a non-empty string")
    return value.strip()


def _optional_url(value: Any, *, context: str) -> str | None:
    if value is None:
        return None
    url = _required_string(value, context=context)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _URL_SCHEMES:
        raise SourceError(f"{context} must use file, http, or https")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise SourceError(f"{context} must include a host")
    return url


def _relative_path(value: Any, *, context: str) -> str:
    path_text = _required_string(value, context=context)
    if "\\" in path_text:
        raise SourceError(f"{context} must use forward slashes")
    path = PurePosixPath(path_text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceError(f"{context} must be a normalised relative path")
    return path.as_posix()


def _request_json(
    url: str, parameters: Mapping[str, object], *, timeout: float
) -> Mapping[str, Any]:
    query = urllib.parse.urlencode(parameters)
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}{query}",
        headers={"User-Agent": "Auckland-Cycling-Investment-Workbench/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SourceFetchError(f"could not query {url}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SourceFetchError(f"provider returned a non-object response from {url}")
    error = payload.get("error")
    if isinstance(error, Mapping):
        message = error.get("message") or "provider returned an unspecified error"
        raise SourceFetchError(f"provider error from {url}: {message}")
    return payload


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    expected_sha256: str | None = None,
    source_id: str | None = None,
) -> None:
    """Serialise, verify, and atomically install a provider response.

    Integrity is checked on the sibling temporary file before ``os.replace``.
    A failed refresh therefore cannot overwrite or delete an existing verified
    snapshot.
    """
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".part",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        actual = sha256_file(temporary_path)
        if expected_sha256 is not None and actual != expected_sha256:
            label = source_id or path.name
            raise SourceIntegrityError(
                f"sha256 mismatch for {label}: expected {expected_sha256}, received {actual}"
            )
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SourceSpec:
    """A single immutable source-registry entry."""

    id: str
    title: str
    acquisition: str
    role: str
    destination: str
    required: bool
    sha256: str | None
    homepage: str | None
    url: str | None
    license: str
    license_url: str | None
    attribution: str
    redistribution: str
    resource_id: str | None = None
    where: str = "1=1"
    out_fields: str = "*"
    page_size: int = 2_000
    include_geometry: bool = True
    expected_record_count: int | None = None
    source_version: str | None = None
    published_at: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, context: str) -> SourceSpec:
        required_keys = {
            "id",
            "title",
            "acquisition",
            "role",
            "destination",
            "required",
            "sha256",
            "homepage",
            "url",
            "license",
            "license_url",
            "attribution",
            "redistribution",
        }
        optional_keys = {
            "resource_id",
            "where",
            "out_fields",
            "page_size",
            "include_geometry",
            "expected_record_count",
            "source_version",
            "published_at",
        }
        _strict_keys(
            value,
            required=required_keys,
            optional=optional_keys,
            context=context,
        )

        source_id = _required_string(value["id"], context=f"{context}.id")
        if not _SOURCE_ID.fullmatch(source_id):
            raise SourceError(f"{context}.id must match {_SOURCE_ID.pattern}")

        acquisition = _required_string(value["acquisition"], context=f"{context}.acquisition")
        if acquisition not in _ACQUISITION:
            choices = ", ".join(sorted(_ACQUISITION))
            raise SourceError(f"{context}.acquisition must be one of: {choices}")

        role = _required_string(value["role"], context=f"{context}.role")
        if not _ROLE.fullmatch(role):
            raise SourceError(f"{context}.role must match {_ROLE.pattern}")

        required = value["required"]
        if not isinstance(required, bool):
            raise SourceError(f"{context}.required must be a boolean")

        digest = value["sha256"]
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            raise SourceError(f"{context}.sha256 must be null or 64 lowercase hex characters")

        url = _optional_url(value["url"], context=f"{context}.url")
        if acquisition in {"download", "arcgis_query", "ckan_datastore"} and url is None:
            raise SourceError(f"{context}.url is required for automated acquisition")

        resource_id = value.get("resource_id")
        if resource_id is not None:
            resource_id = _required_string(resource_id, context=f"{context}.resource_id").lower()
            if not _RESOURCE_ID.fullmatch(resource_id):
                raise SourceError(f"{context}.resource_id must be a lowercase UUID")
        if acquisition == "ckan_datastore" and resource_id is None:
            raise SourceError(f"{context}.resource_id is required for CKAN acquisition")

        where = _required_string(value.get("where", "1=1"), context=f"{context}.where")
        if any(token in where for token in (";", "--", "/*", "*/")):
            raise SourceError(f"{context}.where contains an unsafe SQL token")
        out_fields = _required_string(value.get("out_fields", "*"), context=f"{context}.out_fields")
        page_size = value.get("page_size", 2_000)
        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not 1 <= page_size <= 10_000
        ):
            raise SourceError(f"{context}.page_size must be an integer in 1..10000")
        include_geometry = value.get("include_geometry", True)
        if not isinstance(include_geometry, bool):
            raise SourceError(f"{context}.include_geometry must be a boolean")
        expected_record_count = value.get("expected_record_count")
        if expected_record_count is not None and (
            not isinstance(expected_record_count, int)
            or isinstance(expected_record_count, bool)
            or expected_record_count < 0
        ):
            raise SourceError(
                f"{context}.expected_record_count must be a non-negative integer or null"
            )
        source_version = value.get("source_version")
        if source_version is not None:
            source_version = _required_string(source_version, context=f"{context}.source_version")
        published_at = value.get("published_at")
        if published_at is not None:
            published_at = _required_string(published_at, context=f"{context}.published_at")
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", published_at):
                raise SourceError(f"{context}.published_at must use YYYY-MM-DD")

        redistribution = _required_string(
            value["redistribution"], context=f"{context}.redistribution"
        )
        if redistribution not in _REDISTRIBUTION:
            choices = ", ".join(sorted(_REDISTRIBUTION))
            raise SourceError(f"{context}.redistribution must be one of: {choices}")

        return cls(
            id=source_id,
            title=_required_string(value["title"], context=f"{context}.title"),
            acquisition=acquisition,
            role=role,
            destination=_relative_path(value["destination"], context=f"{context}.destination"),
            required=required,
            sha256=digest,
            homepage=_optional_url(value["homepage"], context=f"{context}.homepage"),
            url=url,
            license=_required_string(value["license"], context=f"{context}.license"),
            license_url=_optional_url(value["license_url"], context=f"{context}.license_url"),
            attribution=_required_string(value["attribution"], context=f"{context}.attribution"),
            redistribution=redistribution,
            resource_id=resource_id,
            where=where,
            out_fields=out_fields,
            page_size=page_size,
            include_geometry=include_geometry,
            expected_record_count=expected_record_count,
            source_version=source_version,
            published_at=published_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "acquisition": self.acquisition,
            "role": self.role,
            "destination": self.destination,
            "required": self.required,
            "sha256": self.sha256,
            "homepage": self.homepage,
            "url": self.url,
            "license": self.license,
            "license_url": self.license_url,
            "attribution": self.attribution,
            "redistribution": self.redistribution,
            "resource_id": self.resource_id,
            "where": self.where,
            "out_fields": self.out_fields,
            "page_size": self.page_size,
            "include_geometry": self.include_geometry,
            "expected_record_count": self.expected_record_count,
            "source_version": self.source_version,
            "published_at": self.published_at,
        }


@dataclass(frozen=True)
class SourceRecord:
    """Observed state for one registered source."""

    id: str
    path: Path
    required: bool
    status: str
    size: int | None
    sha256: str | None
    expected_sha256: str | None

    @property
    def usable(self) -> bool:
        return self.status == "available"

    def to_dict(self, *, root: Path | None = None, data_root: Path | None = None) -> dict[str, Any]:
        path = self.path
        if root is not None:
            try:
                path_text = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                if data_root is None:
                    raise SourceError(f"source path escapes the project root: {path}") from None
                try:
                    relative = path.resolve().relative_to(data_root.resolve()).as_posix()
                except ValueError as exc:
                    raise SourceError(
                        "source path is outside both project and configured data roots"
                    ) from exc
                path_text = f"@data/{relative}"
        else:
            path_text = path.as_posix()
        return {
            "path": path_text,
            "required": self.required,
            "status": self.status,
            "size": self.size,
            "sha256": self.sha256,
        }


class SourceRegistry:
    """Resolve, acquire, and verify a collection of registered sources."""

    def __init__(self, specs: Sequence[SourceSpec], data_root: Path) -> None:
        self._specs = tuple(specs)
        self.data_root = data_root.resolve()
        by_id = {spec.id: spec for spec in self._specs}
        if len(by_id) != len(self._specs):
            raise SourceError("source ids must be unique")
        destinations = {spec.destination for spec in self._specs}
        if len(destinations) != len(self._specs):
            raise SourceError("source destinations must be unique")
        self._by_id = by_id

    @property
    def specs(self) -> tuple[SourceSpec, ...]:
        return self._specs

    def get(self, source_id: str) -> SourceSpec:
        try:
            return self._by_id[source_id]
        except KeyError as exc:
            raise SourceError(f"unknown source id: {source_id}") from exc

    def path_for(self, spec: SourceSpec) -> Path:
        path = (self.data_root / spec.destination).resolve()
        if not path.is_relative_to(self.data_root):
            raise SourceError(f"source destination escapes the data directory: {spec.id}")
        return path

    def select(self, source_ids: Iterable[str] | None = None) -> tuple[SourceSpec, ...]:
        if source_ids is None:
            return self._specs
        requested = tuple(dict.fromkeys(source_ids))
        return tuple(self.get(source_id) for source_id in requested)

    def inspect(self, spec: SourceSpec) -> SourceRecord:
        path = self.path_for(spec)
        if not path.is_file():
            return SourceRecord(spec.id, path, spec.required, "missing", None, None, spec.sha256)
        actual = sha256_file(path)
        status = "available" if spec.sha256 in {None, actual} else "mismatch"
        return SourceRecord(
            spec.id, path, spec.required, status, path.stat().st_size, actual, spec.sha256
        )

    def inventory(self, source_ids: Iterable[str] | None = None) -> dict[str, SourceRecord]:
        return {spec.id: self.inspect(spec) for spec in self.select(source_ids)}

    def fetch(
        self,
        source_ids: Iterable[str] | None = None,
        *,
        offline: bool = False,
        force: bool = False,
        accept_unverified: bool = False,
        timeout: float = 60.0,
    ) -> dict[str, SourceRecord]:
        records: dict[str, SourceRecord] = {}
        for spec in self.select(source_ids):
            existing = self.inspect(spec)
            if existing.usable and not force:
                records[spec.id] = existing
                continue
            if spec.acquisition == "manual" or offline:
                records[spec.id] = existing
                continue
            if spec.acquisition == "download" and spec.sha256 is None and not accept_unverified:
                raise SourceIntegrityError(
                    f"{spec.id} has no registered sha256; pass --accept-unverified only after "
                    "checking the provider and recording the resulting digest"
                )
            if spec.acquisition == "download":
                records[spec.id] = self._download(spec, timeout=timeout)
            elif spec.acquisition == "arcgis_query":
                records[spec.id] = self._arcgis_query(spec, timeout=timeout)
            elif spec.acquisition == "ckan_datastore":
                records[spec.id] = self._ckan_datastore(spec, timeout=timeout)
            else:  # pragma: no cover - SourceSpec rejects unknown acquisition types
                raise SourceFetchError(f"unsupported acquisition type: {spec.acquisition}")
        return records

    def _arcgis_query(self, spec: SourceSpec, *, timeout: float) -> SourceRecord:
        if spec.url is None:
            raise SourceFetchError(f"{spec.id} has no ArcGIS layer URL")
        metadata = _request_json(spec.url, {"f": "json"}, timeout=timeout)
        object_id_field = metadata.get("objectIdField") or metadata.get("objectIdFieldName")
        if not isinstance(object_id_field, str) or not object_id_field:
            fields = metadata.get("fields")
            if isinstance(fields, list):
                object_id_field = next(
                    (
                        field.get("name")
                        for field in fields
                        if isinstance(field, Mapping)
                        and field.get("type") == "esriFieldTypeOID"
                        and isinstance(field.get("name"), str)
                    ),
                    None,
                )
        provider_page_size = metadata.get("maxRecordCount")
        effective_page_size = (
            min(spec.page_size, provider_page_size)
            if isinstance(provider_page_size, int) and provider_page_size > 0
            else spec.page_size
        )
        query_url = spec.url.rstrip("/") + "/query"
        features: list[Mapping[str, Any]] = []
        seen: set[object] = set()
        offset = 0
        while True:
            parameters: dict[str, object] = {
                "f": "geojson" if spec.include_geometry else "json",
                "where": spec.where,
                "outFields": spec.out_fields,
                "returnGeometry": str(spec.include_geometry).lower(),
                "resultOffset": offset,
                "resultRecordCount": effective_page_size,
            }
            if object_id_field:
                parameters["orderByFields"] = f"{object_id_field} ASC"
            if spec.include_geometry:
                parameters["outSR"] = 4326
            page = _request_json(query_url, parameters, timeout=timeout)
            raw_features = page.get("features")
            if not isinstance(raw_features, list):
                raise SourceFetchError(
                    f"ArcGIS page for {spec.id} has no features array at offset {offset}"
                )
            for raw_feature in raw_features:
                if not isinstance(raw_feature, Mapping):
                    raise SourceFetchError(
                        f"ArcGIS page for {spec.id} contains a non-object feature"
                    )
                if spec.include_geometry:
                    identifier = raw_feature.get("id")
                    if identifier is None and isinstance(raw_feature.get("properties"), Mapping):
                        identifier = raw_feature["properties"].get(object_id_field)
                else:
                    attributes = raw_feature.get("attributes")
                    if not isinstance(attributes, Mapping):
                        raise SourceFetchError(
                            f"ArcGIS table page for {spec.id} has invalid attributes"
                        )
                    identifier = attributes.get(object_id_field)
                signature: object = (
                    identifier
                    if identifier is not None
                    else json.dumps(raw_feature, sort_keys=True, separators=(",", ":"))
                )
                if signature in seen:
                    raise SourceFetchError(
                        f"ArcGIS paging repeated a feature for {spec.id} at offset {offset}"
                    )
                seen.add(signature)
                features.append(raw_feature)
            exceeded = bool(page.get("exceededTransferLimit"))
            if not raw_features or (len(raw_features) < effective_page_size and not exceeded):
                break
            offset += len(raw_features)
            if offset > 10_000_000:
                raise SourceFetchError(f"ArcGIS paging limit exceeded for {spec.id}")

        if spec.include_geometry:
            payload: Mapping[str, Any] = {
                "type": "FeatureCollection",
                "name": spec.id,
                "features": features,
            }
        else:
            payload = {
                "dataset_id": spec.id,
                "source_url": spec.url,
                "where": spec.where,
                "out_fields": spec.out_fields,
                "records": [feature["attributes"] for feature in features],
            }
        _verify_expected_record_count(spec, len(features))
        destination = self.path_for(spec)
        _atomic_json(
            destination,
            payload,
            expected_sha256=spec.sha256,
            source_id=spec.id,
        )
        return self.inspect(spec)

    def _ckan_datastore(self, spec: SourceSpec, *, timeout: float) -> SourceRecord:
        if spec.url is None or spec.resource_id is None:
            raise SourceFetchError(f"{spec.id} has incomplete CKAN configuration")
        if spec.out_fields == "*":
            selection = "*"
        else:
            fields = [field.strip() for field in spec.out_fields.split(",")]
            if not fields or any(not re.fullmatch(r"[A-Za-z0-9_]+", field) for field in fields):
                raise SourceFetchError(f"{spec.id} has unsafe CKAN field names")
            selection = ",".join(f'"{field}"' for field in fields)
        records: list[Mapping[str, Any]] = []
        seen: set[object] = set()
        offset = 0
        while True:
            sql = (
                f'SELECT {selection} FROM "{spec.resource_id}" '
                f'WHERE {spec.where} ORDER BY "_id" ASC '
                f"LIMIT {spec.page_size} OFFSET {offset}"
            )
            page = _request_json(spec.url, {"sql": sql}, timeout=timeout)
            if page.get("success") is not True:
                raise SourceFetchError(f"CKAN query was not successful for {spec.id}")
            result = page.get("result")
            raw_records = result.get("records") if isinstance(result, Mapping) else None
            if not isinstance(raw_records, list):
                raise SourceFetchError(
                    f"CKAN page for {spec.id} has no records array at offset {offset}"
                )
            for record in raw_records:
                if not isinstance(record, Mapping):
                    raise SourceFetchError(f"CKAN page for {spec.id} contains a non-object record")
                identifier = record.get("_id")
                signature: object = (
                    identifier
                    if identifier is not None
                    else json.dumps(record, sort_keys=True, separators=(",", ":"))
                )
                if signature in seen:
                    raise SourceFetchError(
                        f"CKAN paging repeated a record for {spec.id} at offset {offset}"
                    )
                seen.add(signature)
                records.append(record)
            if len(raw_records) < spec.page_size:
                break
            offset += len(raw_records)
            if offset > 10_000_000:
                raise SourceFetchError(f"CKAN paging limit exceeded for {spec.id}")
        _verify_expected_record_count(spec, len(records))
        destination = self.path_for(spec)
        _atomic_json(
            destination,
            {
                "dataset_id": spec.id,
                "resource_id": spec.resource_id,
                "where": spec.where,
                "records": records,
            },
            expected_sha256=spec.sha256,
            source_id=spec.id,
        )
        return self.inspect(spec)

    def _download(self, spec: SourceSpec, *, timeout: float) -> SourceRecord:
        if spec.url is None:
            raise SourceFetchError(f"{spec.id} has no download URL")
        destination = self.path_for(spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            request = urllib.request.Request(
                spec.url,
                headers={"User-Agent": "Auckland-Cycling-Investment-Workbench/0.1"},
            )
            with (
                urllib.request.urlopen(request, timeout=timeout) as response,
                tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=destination.parent,
                    prefix=f".{destination.name}.",
                    suffix=".part",
                    delete=False,
                ) as temporary,
            ):
                temporary_path = Path(temporary.name)
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            actual = sha256_file(temporary_path)
            if spec.sha256 is not None and actual != spec.sha256:
                raise SourceIntegrityError(
                    f"sha256 mismatch for {spec.id}: expected {spec.sha256}, received {actual}"
                )
            os.replace(temporary_path, destination)
            temporary_path = None
            return self.inspect(spec)
        except (OSError, urllib.error.URLError) as exc:
            raise SourceFetchError(f"could not fetch {spec.id}: {exc}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
