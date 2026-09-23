"""Prepare a disclosure-safe cycling-crash context layer from a local CAS export."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely.ops import transform

from .provenance import sha256_file, write_json_atomic


class SafetySourceError(ValueError):
    """Raised when a CAS extract cannot support the declared safe aggregate."""


@dataclass(frozen=True, slots=True)
class SafetyPreparationResult:
    output_path: Path
    input_cycle_crashes: int
    published_crashes: int
    published_cells: int
    suppressed_cells: int
    source_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": {
                "path": self.output_path.as_posix(),
                "sha256": sha256_file(self.output_path),
            },
            "input_cycle_crashes": self.input_cycle_crashes,
            "published_crashes": self.published_crashes,
            "published_cells": self.published_cells,
            "suppressed_cells": self.suppressed_cells,
            "source_sha256": self.source_sha256,
        }


def _integer(value: str, *, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise SafetySourceError(f"CAS {field} must be an integer") from exc


def _coordinate(value: str, *, field: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise SafetySourceError(f"CAS {field} must be numeric") from exc
    if not math.isfinite(result):
        raise SafetySourceError(f"CAS {field} must be finite")
    return result


def prepare_cycle_crash_grid(
    *,
    cas_csv_path: str | Path,
    output_path: str | Path,
    start_year: int = 2016,
    end_year: int = 2025,
    cell_size_m: int = 500,
    minimum_count: int = 3,
) -> SafetyPreparationResult:
    """Aggregate cycle-involved crashes to suppressed square cells.

    The public output contains no crash identifier, road name, date, time,
    narrative, vehicle movement, or exact crash coordinate.
    """

    if start_year > end_year:
        raise SafetySourceError("start_year cannot be after end_year")
    if cell_size_m < 100 or minimum_count < 2:
        raise SafetySourceError("cell_size_m must be at least 100 and minimum_count at least 2")
    source = Path(cas_csv_path).resolve()
    output = Path(output_path).resolve()
    source_hash = sha256_file(source)
    to_project = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)
    to_browser = Transformer.from_crs("EPSG:2193", "EPSG:4326", always_xy=True)
    required = {
        "Crash year",
        "Crash severity",
        "Longitude",
        "Latitude",
        *(f"Vehicle {index} type" for index in range(1, 5)),
    }
    cells: defaultdict[tuple[int, int], defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    selected = 0
    try:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                missing = sorted(required.difference(reader.fieldnames or ()))
                raise SafetySourceError(f"CAS export is missing required fields: {missing}")
            for row in reader:
                has_cycle = any(
                    row[f"Vehicle {index} type"].strip() == "Cycle" for index in range(1, 5)
                )
                if not has_cycle:
                    continue
                year = _integer(row["Crash year"].strip(), field="Crash year")
                if not start_year <= year <= end_year:
                    continue
                longitude = _coordinate(row["Longitude"].strip(), field="Longitude")
                latitude = _coordinate(row["Latitude"].strip(), field="Latitude")
                if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                    raise SafetySourceError("CAS crash coordinate is outside longitude/latitude")
                x, y = to_project.transform(longitude, latitude)
                cell = (math.floor(x / cell_size_m), math.floor(y / cell_size_m))
                severity = row["Crash severity"].strip()
                cells[cell]["total"] += 1
                if severity in {"Fatal Crash", "Serious Crash"}:
                    cells[cell]["fatal_serious"] += 1
                elif severity == "Minor Crash":
                    cells[cell]["minor"] += 1
                elif severity == "Non-Injury Crash":
                    cells[cell]["non_injury"] += 1
                else:
                    cells[cell]["other"] += 1
                selected += 1
    except OSError as exc:
        raise SafetySourceError(f"could not read CAS export: {exc}") from exc

    features: list[dict[str, Any]] = []
    suppressed = 0
    published_crashes = 0
    for (column, row), counts in sorted(cells.items()):
        total = counts["total"]
        if total < minimum_count:
            suppressed += 1
            continue
        x = column * cell_size_m
        y = row * cell_size_m
        square = Polygon(
            [
                (x, y),
                (x + cell_size_m, y),
                (x + cell_size_m, y + cell_size_m),
                (x, y + cell_size_m),
                (x, y),
            ]
        )
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(transform(to_browser.transform, square)),
                "properties": {
                    "cellId": f"cas-cycle-{start_year}-{end_year}-{column}-{row}",
                    "crashCount": total,
                    "fatalSeriousCount": counts["fatal_serious"],
                    "minorCount": counts["minor"],
                    "nonInjuryCount": counts["non_injury"],
                    "otherSeverityCount": counts["other"],
                    "period": f"{start_year}-{end_year}",
                    "cellSizeM": cell_size_m,
                    "suppressionThreshold": minimum_count,
                    "measure": "police-reported_cycle-involved_crashes_not_exposure-adjusted",
                    "sourceSha256": source_hash,
                },
            }
        )
        published_crashes += total
    write_json_atomic(
        output,
        {
            "type": "FeatureCollection",
            "name": f"Auckland cycle-involved crash grid {start_year}-{end_year}",
            "metadata": {
                "source": "NZ Transport Agency Waka Kotahi Crash Analysis System export",
                "source_sha256": source_hash,
                "period_start": start_year,
                "period_end": end_year,
                "cell_size_m": cell_size_m,
                "minimum_count": minimum_count,
                "input_cycle_crashes": selected,
                "published_crashes": published_crashes,
                "suppressed_cells": suppressed,
                "privacy": (
                    "No identifiers, exact coordinates, names, dates, times, movements, or "
                    "narratives are retained"
                ),
                "interpretation": "context only; counts are not adjusted for cycling exposure",
            },
            "features": features,
        },
    )
    return SafetyPreparationResult(
        output_path=output,
        input_cycle_crashes=selected,
        published_crashes=published_crashes,
        published_cells=len(features),
        suppressed_cells=suppressed,
        source_sha256=source_hash,
    )


__all__ = ["SafetyPreparationResult", "SafetySourceError", "prepare_cycle_crash_grid"]
