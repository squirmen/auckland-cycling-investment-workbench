from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import yaml

from cycling_investment_workbench.counter_sources import (
    CounterSourceError,
    prepare_at_cycle_counters,
)
from cycling_investment_workbench.provenance import read_json, sha256_file


def _write_workbook(path: Path) -> None:
    strings = [
        "Daily Cycle Count Data July 2026",
        "1st July 2026 → 2nd July 2026",
        "Time",
        "Alpha Cyclist",
        "Missing Cyclist",
    ]
    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    sheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c></row>
<row r="2"><c r="B2" t="s"><v>1</v></c></row>
<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3" t="s"><v>3</v></c>
<c r="C3" t="s"><v>4</v></c></row>
<row r="4"><c r="A4"><v>46204</v></c><c r="B4"><v>10</v></c></row>
<row r="5"><c r="A5"><v>46205</v></c><c r="B5"><v>20</v></c></row>
</sheetData></worksheet>"""
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{shared}</sst>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _fixture_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    workbook = tmp_path / "counts.xlsx"
    registry = tmp_path / "registry.json"
    mapping = tmp_path / "mapping.yml"
    _write_workbook(workbook)
    registry.write_text(
        json.dumps([{"name": "Alpha", "lat": -36.85, "lng": 174.75}]),
        encoding="utf-8",
    )
    mapping.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "coordinate_registry_sha256": sha256_file(registry),
                "mappings": {"Alpha Cyclist": "Alpha"},
                "exclusions": {"Missing Cyclist": "publisher column is empty"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return workbook, registry, mapping


def test_prepare_at_cycle_counters_records_exact_period_and_provenance(tmp_path: Path) -> None:
    workbook, registry, mapping = _fixture_files(tmp_path)
    locations = tmp_path / "locations.json"
    observations = tmp_path / "observations.json"

    result = prepare_at_cycle_counters(
        workbook_path=workbook,
        coordinate_registry_path=registry,
        mapping_path=mapping,
        locations_output=locations,
        observations_output=observations,
        source_url="https://example.test/counts.xlsx",
    )

    assert result.location_count == 1
    assert result.excluded_count == 1
    assert result.observation_days == 2
    assert read_json(locations)[0]["name"] == "Alpha Cyclist"
    payload = read_json(observations)
    assert payload["dailyAverages"] == {"Alpha Cyclist": 15.0}
    assert payload["dailyObservations"]["Alpha Cyclist"] == {
        "2026-07-01": 10.0,
        "2026-07-02": 20.0,
    }
    assert payload["metadata"]["workbook_sha256"] == sha256_file(workbook)


def test_prepare_at_cycle_counters_rejects_unreviewed_workbook_header(tmp_path: Path) -> None:
    workbook, registry, mapping = _fixture_files(tmp_path)
    decisions = yaml.safe_load(mapping.read_text(encoding="utf-8"))
    del decisions["exclusions"]["Missing Cyclist"]
    mapping.write_text(yaml.safe_dump(decisions), encoding="utf-8")

    with pytest.raises(CounterSourceError, match="does not exactly cover"):
        prepare_at_cycle_counters(
            workbook_path=workbook,
            coordinate_registry_path=registry,
            mapping_path=mapping,
            locations_output=tmp_path / "locations.json",
            observations_output=tmp_path / "observations.json",
            source_url="https://example.test/counts.xlsx",
        )


def test_prepare_at_cycle_counters_rejects_coordinate_registry_substitution(
    tmp_path: Path,
) -> None:
    workbook, registry, mapping = _fixture_files(tmp_path)
    registry.write_text("[]", encoding="utf-8")

    with pytest.raises(CounterSourceError, match="SHA-256"):
        prepare_at_cycle_counters(
            workbook_path=workbook,
            coordinate_registry_path=registry,
            mapping_path=mapping,
            locations_output=tmp_path / "locations.json",
            observations_output=tmp_path / "observations.json",
            source_url="https://example.test/counts.xlsx",
        )
