from __future__ import annotations

import csv
import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from cycling_investment_workbench.provenance import read_json
from cycling_investment_workbench.transit_sources import (
    TransitSourceError,
    prepare_at_major_transit_nodes,
)


def _csv(rows: list[dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _fixture_feed(path: Path) -> None:
    files = {
        "feed_info.txt": _csv(
            [
                {
                    "feed_publisher_name": "Auckland Transport",
                    "feed_publisher_url": "https://at.govt.nz",
                    "feed_lang": "en",
                    "feed_start_date": "20260822",
                    "feed_end_date": "20261231",
                    "feed_version": "fixture-1",
                }
            ]
        ),
        "calendar.txt": _csv(
            [
                {
                    "service_id": "weekday",
                    "monday": "1",
                    "tuesday": "1",
                    "wednesday": "1",
                    "thursday": "1",
                    "friday": "1",
                    "saturday": "0",
                    "sunday": "0",
                    "start_date": "20260822",
                    "end_date": "20261231",
                }
            ]
        ),
        "calendar_dates.txt": _csv(
            [{"service_id": "weekday", "date": "20260903", "exception_type": "2"}]
        ),
        "routes.txt": _csv(
            [
                {"route_id": "bus", "route_type": "3"},
                {"route_id": "rail", "route_type": "2"},
                {"route_id": "ferry", "route_type": "4"},
            ]
        ),
        "trips.txt": _csv(
            [
                {"route_id": "bus", "service_id": "weekday", "trip_id": "bus-1"},
                {"route_id": "rail", "service_id": "weekday", "trip_id": "rail-1"},
                {"route_id": "ferry", "service_id": "weekday", "trip_id": "ferry-1"},
            ]
        ),
        "stops.txt": _csv(
            [
                {
                    "stop_id": "hub",
                    "stop_name": "Central Station",
                    "stop_lat": "-36.85",
                    "stop_lon": "174.76",
                    "location_type": "1",
                    "parent_station": "",
                },
                {
                    "stop_id": "platform-a",
                    "stop_name": "Central Station platform",
                    "stop_lat": "-36.851",
                    "stop_lon": "174.761",
                    "location_type": "0",
                    "parent_station": "hub",
                },
                {
                    "stop_id": "wharf",
                    "stop_name": "Harbour Wharf",
                    "stop_lat": "-36.84",
                    "stop_lon": "174.77",
                    "location_type": "0",
                    "parent_station": "",
                },
                {
                    "stop_id": "suburb",
                    "stop_name": "Suburb Road",
                    "stop_lat": "-36.86",
                    "stop_lon": "174.75",
                    "location_type": "0",
                    "parent_station": "",
                },
            ]
        ),
        "stop_times.txt": _csv(
            [
                {"trip_id": "rail-1", "stop_id": "platform-a", "stop_sequence": "1"},
                {"trip_id": "bus-1", "stop_id": "platform-a", "stop_sequence": "1"},
                {"trip_id": "bus-1", "stop_id": "suburb", "stop_sequence": "2"},
                {"trip_id": "ferry-1", "stop_id": "wharf", "stop_sequence": "1"},
            ]
        ),
    }
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_prepare_at_major_transit_nodes_is_service_day_specific(tmp_path: Path) -> None:
    gtfs = tmp_path / "gtfs.zip"
    output = tmp_path / "nodes.geojson"
    _fixture_feed(gtfs)

    result = prepare_at_major_transit_nodes(
        gtfs_path=gtfs,
        output_path=output,
        service_date="2026-09-02",
        busiest_bus_fraction=0.5,
    )

    payload = read_json(output)
    by_id = {feature["properties"]["stop_id"]: feature for feature in payload["features"]}
    assert result.feature_count == 2
    assert set(by_id) == {"hub", "wharf"}
    assert by_id["hub"]["properties"]["rail_stop_visits"] == 1
    assert by_id["hub"]["properties"]["platform_count"] == 1
    assert by_id["wharf"]["properties"]["measure"].endswith("not_patronage")


def test_prepare_at_major_transit_nodes_rejects_cancelled_service_day(tmp_path: Path) -> None:
    gtfs = tmp_path / "gtfs.zip"
    _fixture_feed(gtfs)
    with pytest.raises(TransitSourceError, match="no active services"):
        prepare_at_major_transit_nodes(
            gtfs_path=gtfs,
            output_path=tmp_path / "nodes.geojson",
            service_date="2026-09-03",
        )
