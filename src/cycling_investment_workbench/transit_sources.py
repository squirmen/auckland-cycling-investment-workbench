"""Prepare a deterministic major-node layer from an Auckland Transport GTFS feed."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from .provenance import sha256_file, write_json_atomic

_MAJOR_NAME = re.compile(
    r"\b(station|interchange|transport centre|bus station|ferry terminal|wharf)\b",
    re.IGNORECASE,
)
_WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class TransitSourceError(ValueError):
    """Raised when a GTFS feed cannot support an auditable service-day extract."""


@dataclass(frozen=True, slots=True)
class TransitPreparationResult:
    """Summary of a deterministic GTFS-to-GeoJSON preparation."""

    output_path: Path
    service_date: str
    feature_count: int
    rail_count: int
    ferry_count: int
    named_interchange_count: int
    busiest_bus_count: int
    gtfs_sha256: str
    feed_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": {
                "path": self.output_path.as_posix(),
                "sha256": sha256_file(self.output_path),
            },
            "service_date": self.service_date,
            "feature_count": self.feature_count,
            "selection_counts": {
                "rail": self.rail_count,
                "ferry": self.ferry_count,
                "named_interchange": self.named_interchange_count,
                "busiest_bus": self.busiest_bus_count,
            },
            "gtfs_sha256": self.gtfs_sha256,
            "feed_version": self.feed_version,
        }


def _rows(archive: ZipFile, filename: str) -> list[dict[str, str]]:
    try:
        payload = archive.read(filename)
    except KeyError as exc:
        raise TransitSourceError(f"GTFS feed is missing {filename}") from exc
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        rows = [dict(row) for row in reader]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise TransitSourceError(f"GTFS file is not readable: {filename}") from exc
    if reader.fieldnames is None:
        raise TransitSourceError(f"GTFS file has no header: {filename}")
    return rows


def _parse_gtfs_date(value: str, *, field: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise TransitSourceError(f"GTFS {field} must use YYYYMMDD") from exc


def _active_services(
    calendar: Iterable[Mapping[str, str]],
    exceptions: Iterable[Mapping[str, str]],
    service_date: date,
) -> set[str]:
    active: set[str] = set()
    weekday = _WEEKDAY_FIELDS[service_date.weekday()]
    for row in calendar:
        service_id = str(row.get("service_id", "")).strip()
        if not service_id:
            continue
        start = _parse_gtfs_date(str(row.get("start_date", "")), field="start_date")
        end = _parse_gtfs_date(str(row.get("end_date", "")), field="end_date")
        if start <= service_date <= end and str(row.get(weekday, "0")) == "1":
            active.add(service_id)
    compact_date = service_date.strftime("%Y%m%d")
    for row in exceptions:
        if str(row.get("date", "")) != compact_date:
            continue
        service_id = str(row.get("service_id", "")).strip()
        exception_type = str(row.get("exception_type", "")).strip()
        if exception_type == "1":
            active.add(service_id)
        elif exception_type == "2":
            active.discard(service_id)
        else:
            raise TransitSourceError("GTFS calendar_dates contains an invalid exception_type")
    if not active:
        raise TransitSourceError(f"GTFS feed has no active services on {service_date.isoformat()}")
    return active


def _float(value: str, *, field: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise TransitSourceError(f"GTFS {field} is not numeric") from exc
    if not math.isfinite(result):
        raise TransitSourceError(f"GTFS {field} must be finite")
    return result


def prepare_at_major_transit_nodes(
    *,
    gtfs_path: str | Path,
    output_path: str | Path,
    service_date: str,
    busiest_bus_fraction: float = 0.01,
    source_url: str = "https://gtfs.at.govt.nz/gtfs.zip",
) -> TransitPreparationResult:
    """Select rail, ferry, named interchange, and busiest bus nodes for one service day.

    Platform stops are consolidated to their declared ``parent_station``.  Counts are
    scheduled stop visits made by trips active on the declared service date; they are
    opportunity weights, not observed patronage.
    """

    if not (0 < busiest_bus_fraction <= 1):
        raise TransitSourceError("busiest_bus_fraction must be greater than 0 and at most 1")
    gtfs = Path(gtfs_path).resolve()
    output = Path(output_path).resolve()
    selected_date = date.fromisoformat(service_date)
    try:
        with ZipFile(gtfs) as archive:
            feed_info = _rows(archive, "feed_info.txt")
            calendar = _rows(archive, "calendar.txt")
            exceptions = _rows(archive, "calendar_dates.txt")
            stops = _rows(archive, "stops.txt")
            routes = _rows(archive, "routes.txt")
            trips = _rows(archive, "trips.txt")
            stop_times = _rows(archive, "stop_times.txt")
    except (BadZipFile, OSError) as exc:
        raise TransitSourceError(f"could not read GTFS archive: {exc}") from exc

    active_services = _active_services(calendar, exceptions, selected_date)
    route_types = {
        str(row.get("route_id", "")): int(str(row.get("route_type", "-1")))
        for row in routes
        if str(row.get("route_id", "")).strip()
    }
    active_trips: dict[str, int] = {}
    for row in trips:
        if str(row.get("service_id", "")) not in active_services:
            continue
        trip_id = str(row.get("trip_id", "")).strip()
        route_id = str(row.get("route_id", "")).strip()
        if trip_id and route_id in route_types:
            active_trips[trip_id] = route_types[route_id]
    if not active_trips:
        raise TransitSourceError("GTFS service day contains no usable trips")

    stop_by_id = {
        str(row.get("stop_id", "")): row for row in stops if str(row.get("stop_id", "")).strip()
    }
    member_to_node: dict[str, str] = {}
    for stop_id, row in stop_by_id.items():
        parent = str(row.get("parent_station", "")).strip()
        member_to_node[stop_id] = parent if parent in stop_by_id else stop_id

    visits: defaultdict[str, defaultdict[int, int]] = defaultdict(lambda: defaultdict(int))
    members: defaultdict[str, set[str]] = defaultdict(set)
    for row in stop_times:
        trip_id = str(row.get("trip_id", "")).strip()
        stop_id = str(row.get("stop_id", "")).strip()
        if trip_id not in active_trips or stop_id not in member_to_node:
            continue
        node_id = member_to_node[stop_id]
        visits[node_id][active_trips[trip_id]] += 1
        members[node_id].add(stop_id)
    if not visits:
        raise TransitSourceError("GTFS service day contains no usable stop visits")

    bus_nodes = sorted(
        (node_id for node_id, counts in visits.items() if counts.get(3, 0) > 0),
        key=lambda node_id: (-visits[node_id][3], node_id),
    )
    busiest_count = max(1, math.ceil(len(bus_nodes) * busiest_bus_fraction)) if bus_nodes else 0
    busiest_bus_nodes = set(bus_nodes[:busiest_count])

    feed = feed_info[0] if feed_info else {}
    feed_version = str(feed.get("feed_version", "unspecified")).strip() or "unspecified"
    feed_start = str(feed.get("feed_start_date", "")).strip()
    feed_end = str(feed.get("feed_end_date", "")).strip()
    gtfs_hash = sha256_file(gtfs)
    features: list[dict[str, Any]] = []
    selection_counts: defaultdict[str, int] = defaultdict(int)
    for node_id in sorted(visits):
        row = stop_by_id[node_id]
        name = str(row.get("stop_name", "")).strip() or node_id
        reasons: list[str] = []
        if visits[node_id].get(2, 0) > 0:
            reasons.append("rail")
        if visits[node_id].get(4, 0) > 0:
            reasons.append("ferry")
        if _MAJOR_NAME.search(name):
            reasons.append("named_interchange")
        if node_id in busiest_bus_nodes:
            reasons.append("busiest_bus")
        if not reasons:
            continue
        try:
            latitude = _float(str(row.get("stop_lat", "")), field="stop_lat")
            longitude = _float(str(row.get("stop_lon", "")), field="stop_lon")
        except TransitSourceError:
            coordinates = [
                (
                    _float(str(stop_by_id[member].get("stop_lon", "")), field="stop_lon"),
                    _float(str(stop_by_id[member].get("stop_lat", "")), field="stop_lat"),
                )
                for member in sorted(members[node_id])
            ]
            longitude = sum(value[0] for value in coordinates) / len(coordinates)
            latitude = sum(value[1] for value in coordinates) / len(coordinates)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise TransitSourceError(f"GTFS coordinates are out of range for {node_id}")
        for reason in reasons:
            selection_counts[reason] += 1
        counts = visits[node_id]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "stop_id": node_id,
                    "stop_name": name,
                    "kind": "+".join(reasons),
                    "selection_reasons": reasons,
                    "daily_trips": sum(counts.values()),
                    "service_day_stop_visits": sum(counts.values()),
                    "bus_stop_visits": counts.get(3, 0),
                    "rail_stop_visits": counts.get(2, 0),
                    "ferry_stop_visits": counts.get(4, 0),
                    "platform_count": len(members[node_id]),
                    "service_date": selected_date.isoformat(),
                    "measure": "scheduled_service_day_stop_visits_not_patronage",
                    "feed_sha256": gtfs_hash,
                    "feed_version": feed_version,
                    "feed_start_date": feed_start,
                    "feed_end_date": feed_end,
                    "source_url": source_url,
                    "licence": "CC BY 4.0",
                },
            }
        )
    if not features:
        raise TransitSourceError("major-node selection produced no features")
    write_json_atomic(
        output,
        {
            "type": "FeatureCollection",
            "name": "AT major transit nodes",
            "features": features,
        },
    )
    return TransitPreparationResult(
        output_path=output,
        service_date=selected_date.isoformat(),
        feature_count=len(features),
        rail_count=selection_counts["rail"],
        ferry_count=selection_counts["ferry"],
        named_interchange_count=selection_counts["named_interchange"],
        busiest_bus_count=selection_counts["busiest_bus"],
        gtfs_sha256=gtfs_hash,
        feed_version=feed_version,
    )


__all__ = [
    "TransitPreparationResult",
    "TransitSourceError",
    "prepare_at_major_transit_nodes",
]
