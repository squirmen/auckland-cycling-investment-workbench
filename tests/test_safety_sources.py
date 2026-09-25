from __future__ import annotations

import csv
from pathlib import Path

from cycling_investment_workbench.provenance import read_json
from cycling_investment_workbench.safety_sources import prepare_cycle_crash_grid


def test_cycle_crash_grid_filters_aggregates_and_suppresses(tmp_path: Path) -> None:
    source = tmp_path / "cas.csv"
    fields = [
        "Crash year",
        "Crash severity",
        "Longitude",
        "Latitude",
        "Vehicle 1 type",
        "Vehicle 2 type",
        "Vehicle 3 type",
        "Vehicle 4 type",
        "What happened",
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for longitude, severity in (
            (174.7600, "Serious Crash"),
            (174.7601, "Minor Crash"),
            (174.7602, "Non-Injury Crash"),
            (174.7900, "Minor Crash"),
        ):
            writer.writerow(
                {
                    "Crash year": "2020",
                    "Crash severity": severity,
                    "Longitude": longitude,
                    "Latitude": -36.85,
                    "Vehicle 1 type": "Cycle",
                    "Vehicle 2 type": "Car/Wagon",
                    "Vehicle 3 type": "",
                    "Vehicle 4 type": "",
                    "What happened": "must not appear",
                }
            )
        writer.writerow(
            {
                "Crash year": "2020",
                "Crash severity": "Minor Crash",
                "Longitude": 174.7600,
                "Latitude": -36.85,
                "Vehicle 1 type": "Motorcycle",
                "Vehicle 2 type": "Car/Wagon",
                "Vehicle 3 type": "",
                "Vehicle 4 type": "",
                "What happened": "must not appear",
            }
        )

    output = tmp_path / "grid.geojson"
    result = prepare_cycle_crash_grid(
        cas_csv_path=source,
        output_path=output,
        start_year=2016,
        end_year=2025,
        cell_size_m=500,
        minimum_count=3,
    )

    payload = read_json(output)
    assert result.input_cycle_crashes == 4
    assert result.published_cells == 1
    assert result.published_crashes == 3
    assert result.suppressed_cells == 1
    assert payload["features"][0]["properties"]["fatalSeriousCount"] == 1
    assert "must not appear" not in output.read_text(encoding="utf-8")
