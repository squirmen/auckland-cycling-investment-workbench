"""Prepare auditable Auckland Transport cycle-counter inputs.

The publisher workbook is an XLSX (a ZIP of XML files).  Reading the small,
fixed table directly keeps this preparation step dependency-free and makes the
accepted worksheet layout explicit.  Counter coordinates are a separate input:
the function never infers a coordinate from a site name.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import yaml

from .provenance import sha256_file, write_json_atomic

_SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REFERENCE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


class CounterSourceError(ValueError):
    """Raised when a counter workbook or coordinate mapping is ambiguous."""


@dataclass(frozen=True, slots=True)
class CounterPreparationResult:
    """Deterministic outputs from one counter preparation."""

    locations_path: Path
    observations_path: Path
    location_count: int
    excluded_count: int
    observation_days: int
    workbook_sha256: str
    coordinate_registry_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "locations": {
                "path": self.locations_path.as_posix(),
                "sha256": sha256_file(self.locations_path),
            },
            "observations": {
                "path": self.observations_path.as_posix(),
                "sha256": sha256_file(self.observations_path),
            },
            "location_count": self.location_count,
            "excluded_count": self.excluded_count,
            "observation_days": self.observation_days,
            "workbook_sha256": self.workbook_sha256,
            "coordinate_registry_sha256": self.coordinate_registry_sha256,
        }


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise CounterSourceError(f"invalid XLSX cell reference: {reference}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _shared_strings(archive: ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except (KeyError, ElementTree.ParseError) as exc:
        raise CounterSourceError("workbook has no readable shared-string table") from exc
    return [
        "".join(node.text or "" for node in item.iter(f"{_SPREADSHEET_NS}t"))
        for item in root.findall(f"{_SPREADSHEET_NS}si")
    ]


def _worksheet_rows(path: Path) -> dict[int, dict[int, str | float | None]]:
    try:
        with ZipFile(path) as archive:
            strings = _shared_strings(archive)
            sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    except (BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise CounterSourceError(f"could not read counter workbook: {exc}") from exc

    rows: dict[int, dict[int, str | float | None]] = {}
    for row in sheet.iter(f"{_SPREADSHEET_NS}row"):
        try:
            row_number = int(row.attrib["r"])
        except (KeyError, ValueError) as exc:
            raise CounterSourceError("worksheet row has no valid number") from exc
        values: dict[int, str | float | None] = {}
        for cell in row.findall(f"{_SPREADSHEET_NS}c"):
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            value_node = cell.find(f"{_SPREADSHEET_NS}v")
            if value_node is None or value_node.text in {None, ""}:
                values[column] = None
                continue
            raw = value_node.text
            if cell.attrib.get("t") == "s":
                try:
                    values[column] = strings[int(raw)]
                except (IndexError, ValueError) as exc:
                    raise CounterSourceError("worksheet uses an invalid shared string") from exc
            else:
                try:
                    values[column] = float(raw)
                except ValueError:
                    values[column] = raw
        rows[row_number] = values
    return rows


def _load_coordinate_registry(path: Path) -> dict[str, Mapping[str, Any]]:
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CounterSourceError(f"could not read coordinate registry: {exc}") from exc
    if not isinstance(payload, list):
        raise CounterSourceError("coordinate registry must be a JSON list")
    by_name: dict[str, Mapping[str, Any]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            raise CounterSourceError("coordinate registry entries must be mappings")
        name = str(row.get("name", "")).strip()
        if not name or name in by_name:
            raise CounterSourceError("coordinate registry names must be non-empty and unique")
        try:
            latitude = float(row["lat"])
            longitude = float(row["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CounterSourceError(f"coordinate registry entry is invalid: {name}") from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise CounterSourceError(f"coordinate registry entry is out of range: {name}")
        by_name[name] = row
    return by_name


def _load_mapping(path: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CounterSourceError(f"could not read counter mapping: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise CounterSourceError("counter mapping must use schema_version 1")
    expected_hash = str(payload.get("coordinate_registry_sha256", "")).strip()
    mappings = payload.get("mappings")
    exclusions = payload.get("exclusions")
    if (
        len(expected_hash) != 64
        or not isinstance(mappings, Mapping)
        or not isinstance(exclusions, Mapping)
    ):
        raise CounterSourceError("counter mapping is missing its registry hash or decisions")
    mapped = {str(key): str(value) for key, value in mappings.items()}
    excluded = {str(key): str(value) for key, value in exclusions.items()}
    if set(mapped).intersection(excluded):
        raise CounterSourceError("a counter header cannot be both mapped and excluded")
    if any(not key or not value for key, value in (*mapped.items(), *excluded.items())):
        raise CounterSourceError("counter mapping decisions must be non-empty")
    return expected_hash, mapped, excluded


def _excel_date(serial: float) -> str:
    if not math.isfinite(serial):
        raise CounterSourceError("counter workbook contains an invalid date serial")
    return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()


def prepare_at_cycle_counters(
    *,
    workbook_path: str | Path,
    coordinate_registry_path: str | Path,
    mapping_path: str | Path,
    locations_output: str | Path,
    observations_output: str | Path,
    source_url: str,
) -> CounterPreparationResult:
    """Prepare exact-period daily means and separately sourced site points.

    Every publisher header must have one explicit mapping or exclusion.  This
    intentionally rejects fuzzy name matching and one-to-many coordinate reuse.
    """

    workbook = Path(workbook_path).resolve()
    registry_path = Path(coordinate_registry_path).resolve()
    mapping = Path(mapping_path).resolve()
    locations_path = Path(locations_output).resolve()
    observations_path = Path(observations_output).resolve()
    workbook_hash = sha256_file(workbook)
    registry_hash = sha256_file(registry_path)
    expected_hash, mappings, exclusions = _load_mapping(mapping)
    if registry_hash != expected_hash:
        raise CounterSourceError(
            "coordinate registry SHA-256 does not match the reviewed counter mapping"
        )
    registry = _load_coordinate_registry(registry_path)
    rows = _worksheet_rows(workbook)
    title = rows.get(1, {}).get(0)
    period_label = rows.get(2, {}).get(1)
    header_row = rows.get(3, {})
    if not isinstance(title, str) or "Daily Cycle Count Data" not in title:
        raise CounterSourceError("unexpected counter workbook title")
    if not isinstance(period_label, str) or not period_label.strip():
        raise CounterSourceError("counter workbook has no period label")

    header_columns = {
        column: str(value).strip()
        for column, value in header_row.items()
        if column > 0 and isinstance(value, str) and value.strip()
    }
    headers = set(header_columns.values())
    decisions = set(mappings).union(exclusions)
    if headers != decisions:
        missing = sorted(headers - decisions)
        stale = sorted(decisions - headers)
        raise CounterSourceError(
            "counter mapping does not exactly cover workbook headers; "
            f"missing={missing}, stale={stale}"
        )
    unknown_registry_names = sorted(set(mappings.values()).difference(registry))
    if unknown_registry_names:
        raise CounterSourceError(
            f"counter mapping references unknown registry names: {unknown_registry_names}"
        )
    registry_names = list(mappings.values())
    if len(registry_names) != len(set(registry_names)):
        raise CounterSourceError("one coordinate registry entry cannot represent multiple counters")

    observation_rows = [rows[number] for number in sorted(rows) if number >= 4]
    date_values = [row.get(0) for row in observation_rows]
    if not date_values or any(not isinstance(value, float) for value in date_values):
        raise CounterSourceError("counter workbook has no complete numeric date column")
    dates = [_excel_date(float(value)) for value in date_values]

    locations: list[dict[str, Any]] = []
    daily_averages: dict[str, float] = {}
    daily_values: dict[str, dict[str, float]] = {}
    exclusion_ledger = dict(exclusions)
    for column, official_name in sorted(header_columns.items()):
        values = [row.get(column) for row in observation_rows]
        numeric = [float(value) for value in values if isinstance(value, float)]
        if official_name in exclusions:
            continue
        if len(numeric) != len(values):
            exclusion_ledger[official_name] = (
                f"incomplete_daily_series_{len(numeric)}_of_{len(values)}"
            )
            continue
        registry_name = mappings[official_name]
        registry_row = registry[registry_name]
        locations.append(
            {
                "counter_id": f"at-july-2026-{len(locations) + 1:03d}",
                "name": official_name,
                "registry_name": registry_name,
                "lat": float(registry_row["lat"]),
                "lng": float(registry_row["lng"]),
                "coordinate_provenance": (
                    "project_maintained_approximate_site_registry_reviewed_by_exact_name"
                ),
                "coordinate_accuracy": "approximate_site_point_not_screenline_or_direction",
                "coordinate_registry_sha256": registry_hash,
            }
        )
        daily_averages[official_name] = sum(numeric) / len(numeric)
        daily_values[official_name] = dict(zip(dates, numeric, strict=True))

    if not locations:
        raise CounterSourceError("counter preparation produced no usable sites")
    common_metadata = {
        "publisher": "Auckland Transport",
        "source_url": source_url,
        "workbook_title": title,
        "workbook_sha256": workbook_hash,
        "period_label": period_label.strip(),
        "period_start": min(dates),
        "period_end": max(dates),
        "observation_days": len(dates),
        "measure": "daily_all_purpose_cycle_movements",
        "licence": "CC BY 4.0",
        "coordinate_registry_sha256": registry_hash,
        "coordinate_provenance_limitation": (
            "project-maintained approximate site points from the Cycleway Dashboard archive do "
            "not define direction, bearing, or a count screenline; use is limited to an explicitly "
            "labelled spatial plausibility check"
        ),
        "exclusions": dict(sorted(exclusion_ledger.items())),
    }
    write_json_atomic(locations_path, locations)
    write_json_atomic(
        observations_path,
        {
            "schema_version": 1,
            "metadata": common_metadata,
            "dailyAverages": dict(sorted(daily_averages.items())),
            "dailyObservations": dict(sorted(daily_values.items())),
        },
    )
    return CounterPreparationResult(
        locations_path=locations_path,
        observations_path=observations_path,
        location_count=len(locations),
        excluded_count=len(exclusion_ledger),
        observation_days=len(dates),
        workbook_sha256=workbook_hash,
        coordinate_registry_sha256=registry_hash,
    )


__all__ = [
    "CounterPreparationResult",
    "CounterSourceError",
    "prepare_at_cycle_counters",
]
