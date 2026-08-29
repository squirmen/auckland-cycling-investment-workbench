"""Real Auckland preparation adapters for the publication pipeline.

These adapters never substitute synthetic data.  They produce complete zonal
and disaggregated demand ledgers plus a source-identity OSM graph.  Stages that
are not yet safe for an Auckland release raise a structured production blocker
at the exact boundary where work must stop.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import Point

from .demand import (
    ConfidentialODCell,
    CountInterval,
    DemandConstraintError,
    SpatialSupport,
    disaggregate_od_to_weighted_supports,
    interpret_censored_count,
)
from .osm_adapter import (
    EVERYDAY_POI_MAPPING_VERSION,
    DestinationPOI,
    GeographicBounds,
    apply_facility_matches,
    extract_osm_network,
    match_at_facilities,
)
from .pipeline import ProductionBlocker, StageContext, StageHandler, StageResult
from .provenance import content_hash, read_json, sha256_file, write_json_atomic
from .purpose_demand import (
    PurposeDestination,
    generate_everyday_market,
    generate_school_market,
    generate_transit_market,
)
from .stress import StressInputs, level_of_traffic_stress
from .terrain import apply_raster_gradients, verify_raster_manifest

_ORIGIN = "SA22023_V1_00_usual_residence_address"
_DESTINATION = "SA22023_V1_00_workplace_address"
_BICYCLE = "2023_Bicycle"
_TOTAL = "2023_Total_stated"
_MARGIN_CODE = "SA22023_V1_00"
_COMMUTE_ORIGIN_MARGIN = "VAR_2_780"
_COMMUTE_TOTAL_MARGIN = "VAR_2_786"
_COMMUTE_DESTINATION_MARGIN = "VAR_2_822"
_COMMUTE_DESTINATION_TOTAL = "VAR_2_828"


@dataclass(frozen=True, slots=True)
class MarginEvidence:
    zone_id: str
    metric: str
    universe: str
    row_lower: float
    row_point: float
    row_upper: float
    margin_lower: float | None
    margin_point: float | None
    margin_upper: float | None
    point_residual: float | None
    intervals_overlap: bool | None
    hard_constraint_applied: bool = False


@dataclass(frozen=True, slots=True)
class PreparedZonalDemand:
    cells: tuple[ConfidentialODCell, ...]
    cycle_point_by_od: Mapping[str, float]
    margin_evidence: tuple[MarginEvidence, ...]
    suppressed_cycle_cells: int
    suppressed_eligible_cells: int
    excluded_non_auckland_origin_rows: int
    internal_od_count: int
    outbound_or_special_od_count: int


@dataclass(frozen=True, slots=True)
class GeographyDiagnostics:
    """Auditable counts from the official SA1-to-SA2 spatial assignment."""

    input_sa1_features: int
    input_sa2_features: int
    input_boundary_features: int
    valid_sa1_features: int
    scoped_auckland_sa1_features: int
    outside_auckland_sa1_features: int
    boundary_touching_representative_points: int
    missing_sa2_assignments: int
    ambiguous_sa2_assignments: int
    resolved_ambiguous_sa2_assignments: int
    unresolved_ambiguous_sa2_assignments: int
    minimum_maximum_overlap_share: float | None
    suppressed_population_weights: int


def _count_interval(value: Any, *, suppressed_point: str = "midpoint") -> CountInterval:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DemandConstraintError("published count is blank rather than an explicit marker")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DemandConstraintError(f"published count is not numeric: {value!r}") from exc
    if numeric == -999:
        return interpret_censored_count(
            None,
            suppressed=True,
            point_strategy=suppressed_point,
        )
    if numeric < 0:
        raise DemandConstraintError(f"unexpected negative published count: {numeric}")
    return interpret_censored_count(numeric)


def _margins(
    records: Sequence[Mapping[str, Any]], field: str, zones: set[str]
) -> dict[str, CountInterval]:
    result: dict[str, CountInterval] = {}
    for record in records:
        code = str(record.get(_MARGIN_CODE, "")).strip()
        if code not in zones:
            continue
        if code in result:
            raise DemandConstraintError(f"duplicate SA2 margin record: {code}")
        result[code] = _count_interval(record.get(field))
    return result


def prepare_zonal_commute_demand(
    jtw_rows: Sequence[Mapping[str, Any]],
    margin_records: Sequence[Mapping[str, Any]],
    auckland_sa2_codes: set[str],
) -> PreparedZonalDemand:
    """Prepare all Auckland-origin ODs with margins retained as soft evidence.

    Residence and workplace margins have different universes.  No margin is a
    hard constraint here; outbound and special-destination records remain in the
    ledger so coverage and uncovered-universe residuals are auditable.
    """

    cells: list[ConfidentialODCell] = []
    suppressed_cycle = 0
    suppressed_eligible = 0
    excluded = 0
    for row in jtw_rows:
        origin = str(row.get(_ORIGIN, "")).strip()
        destination = str(row.get(_DESTINATION, "")).strip()
        if origin not in auckland_sa2_codes:
            excluded += 1
            continue
        destination = destination or "__not_stated__"
        eligible_interval = _count_interval(row.get(_TOTAL))
        is_suppressed = float(row[_BICYCLE]) == -999
        suppressed_cycle += is_suppressed
        suppressed_eligible += float(row[_TOTAL]) == -999
        cells.append(
            ConfidentialODCell(
                id=f"commute:{origin}:{destination}",
                origin_zone=origin,
                destination_zone=destination,
                eligible=eligible_interval,
                published_cycle=None if is_suppressed else float(row[_BICYCLE]),
                suppressed=is_suppressed,
            )
        )
    if not cells:
        raise DemandConstraintError("no Auckland-origin journey-to-work rows were found")
    if len({cell.id for cell in cells}) != len(cells):
        raise DemandConstraintError("journey-to-work table has duplicate Auckland-origin ODs")

    margin_sets = {
        "origin_bicycle": _margins(margin_records, _COMMUTE_ORIGIN_MARGIN, auckland_sa2_codes),
        "origin_total_stated": _margins(margin_records, _COMMUTE_TOTAL_MARGIN, auckland_sa2_codes),
        "destination_bicycle": _margins(
            margin_records, _COMMUTE_DESTINATION_MARGIN, auckland_sa2_codes
        ),
        "destination_total_stated": _margins(
            margin_records, _COMMUTE_DESTINATION_TOTAL, auckland_sa2_codes
        ),
    }

    def comparisons(
        *,
        metric: str,
        universe: str,
        grouped: Mapping[str, Sequence[ConfidentialODCell]],
        margins: Mapping[str, CountInterval],
        interval_name: str,
    ) -> list[MarginEvidence]:
        evidence: list[MarginEvidence] = []
        for zone in sorted(auckland_sa2_codes):
            intervals = [
                cell.cycle_interval if interval_name == "cycle" else cell.eligible_interval
                for cell in grouped.get(zone, ())
            ]
            row_lower = sum(item.lower for item in intervals)
            row_point = sum(item.point for item in intervals)
            row_upper = sum(item.upper for item in intervals)
            margin = margins.get(zone)
            evidence.append(
                MarginEvidence(
                    zone_id=zone,
                    metric=metric,
                    universe=universe,
                    row_lower=row_lower,
                    row_point=row_point,
                    row_upper=row_upper,
                    margin_lower=margin.lower if margin else None,
                    margin_point=margin.point if margin else None,
                    margin_upper=margin.upper if margin else None,
                    point_residual=(row_point - margin.point) if margin else None,
                    intervals_overlap=(
                        row_lower <= margin.upper and margin.lower <= row_upper if margin else None
                    ),
                )
            )
        return evidence

    by_origin: dict[str, list[ConfidentialODCell]] = defaultdict(list)
    by_internal_destination: dict[str, list[ConfidentialODCell]] = defaultdict(list)
    for cell in cells:
        by_origin[cell.origin_zone].append(cell)
        if cell.destination_zone in auckland_sa2_codes:
            by_internal_destination[cell.destination_zone].append(cell)
    evidence = [
        *comparisons(
            metric="bicycle",
            universe="all_auckland_origin_jtw_rows_vs_residence_margin",
            grouped=by_origin,
            margins=margin_sets["origin_bicycle"],
            interval_name="cycle",
        ),
        *comparisons(
            metric="total_stated",
            universe="all_auckland_origin_jtw_rows_vs_residence_margin",
            grouped=by_origin,
            margins=margin_sets["origin_total_stated"],
            interval_name="eligible",
        ),
        *comparisons(
            metric="bicycle",
            universe="internal_auckland_origin_rows_vs_all_origin_workplace_margin",
            grouped=by_internal_destination,
            margins=margin_sets["destination_bicycle"],
            interval_name="cycle",
        ),
        *comparisons(
            metric="total_stated",
            universe="internal_auckland_origin_rows_vs_all_origin_workplace_margin",
            grouped=by_internal_destination,
            margins=margin_sets["destination_total_stated"],
            interval_name="eligible",
        ),
    ]
    cycle_points = {cell.id: cell.cycle_interval.point for cell in cells}
    internal = sum(cell.destination_zone in auckland_sa2_codes for cell in cells)
    return PreparedZonalDemand(
        tuple(cells),
        cycle_points,
        tuple(evidence),
        suppressed_cycle,
        suppressed_eligible,
        excluded,
        internal,
        len(cells) - internal,
    )


def _source_path(context: StageContext, source_id: str) -> Path:
    try:
        record = context.sources[source_id]
    except KeyError as exc:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="unregistered_production_source",
            message=f"required production source is not registered: {source_id}",
            evidence={"source_id": source_id},
        ) from exc
    if not record.usable:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="unavailable_production_source",
            message=f"required production source is unavailable: {source_id}",
            evidence={"source_id": source_id, "status": record.status},
        )
    return record.path


def _json_records(path: Path) -> list[Mapping[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON source is not an object: {path.name}")
    raw = payload.get("records")
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise ValueError(f"JSON source has no valid records array: {path.name}")
    return raw


def _feature_collection(path: Path) -> Mapping[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("features"), list):
        raise ValueError(f"source is not a GeoJSON feature collection: {path.name}")
    return payload


def _minimum_records(context: StageContext, source_id: str) -> int | None:
    validation = context.config.parameters.get("validation")
    minima = (
        validation.get("source_regression_minimum_records")
        if isinstance(validation, Mapping)
        else None
    )
    value = minima.get(source_id) if isinstance(minima, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _require_expected_record_count(context: StageContext, source_id: str, actual: int) -> None:
    spec = next((item for item in context.config.sources if item.id == source_id), None)
    expected = spec.expected_record_count if spec is not None else None
    if expected is not None and actual != expected:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="source_record_count_mismatch",
            message=f"{source_id} has {actual} records; exactly {expected} are required",
            evidence={
                "source_id": source_id,
                "actual_records": actual,
                "expected_records": expected,
                "source_version": spec.source_version,
                "published_at": spec.published_at,
            },
        )


def _require_record_count(context: StageContext, source_id: str, actual: int) -> None:
    minimum = _minimum_records(context, source_id)
    if minimum is not None and actual < minimum:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="source_snapshot_truncated",
            message=f"{source_id} has {actual} records; at least {minimum} are required",
            evidence={
                "source_id": source_id,
                "actual_records": actual,
                "minimum_records": minimum,
                "sha256": context.sources[source_id].sha256,
            },
        )


def _require_geography_fields(
    frame: gpd.GeoDataFrame, fields: set[str], *, source_name: str
) -> None:
    missing = fields.difference(frame.columns)
    if missing:
        raise DemandConstraintError(
            f"{source_name} is missing fields: " + ", ".join(sorted(missing))
        )
    if frame.crs is None:
        raise DemandConstraintError(f"{source_name} has no declared coordinate reference system")


def _sa1_supports(
    sa1_path: Path,
    sa2_path: Path,
    boundary_path: Path,
    *,
    target_crs: str,
) -> tuple[
    gpd.GeoDataFrame,
    tuple[SpatialSupport, ...],
    set[str],
    GeographyDiagnostics,
]:
    """Build Auckland supports from independent, publisher-owned geographies.

    The official SA1 census layer contains no higher-geography lookup.  This
    adapter therefore scopes SA1 representative points with the official
    Auckland territorial-authority polygon and assigns them to the official SA2
    polygons.  A point intersecting multiple polygons is assigned only when one
    candidate contains a strictly larger share of the source SA1 polygon.  This
    deterministic maximum-overlap rule resolves coastal slivers without nearest
    neighbour guessing; missing assignments and overlap ties fail closed.
    """

    sa1 = gpd.read_file(sa1_path)
    sa2 = gpd.read_file(sa2_path)
    boundary = gpd.read_file(boundary_path)
    _require_geography_fields(
        sa1,
        {"SA12023_V1_00", "VAR_1_3", "geometry"},
        source_name="Stats NZ SA1 population geography",
    )
    _require_geography_fields(
        sa2,
        {"SA22023_V1_00", "SA22023_V1_00_NAME", "geometry"},
        source_name="Stats NZ SA2 geography",
    )
    _require_geography_fields(
        boundary,
        {"TA2023_V1_00", "TA2023_V1_00_NAME", "geometry"},
        source_name="Stats NZ territorial-authority geography",
    )
    input_counts = (len(sa1), len(sa2), len(boundary))
    auckland = boundary[
        (boundary["TA2023_V1_00"].astype(str).str.zfill(3) == "076")
        & (boundary["TA2023_V1_00_NAME"].astype(str).str.strip() == "Auckland")
    ]
    auckland = auckland[auckland.geometry.notna() & ~auckland.geometry.is_empty].copy()
    if len(auckland) != 1:
        raise DemandConstraintError(
            "territorial-authority source must contain exactly one Auckland (076) feature; "
            f"found {len(auckland)}"
        )

    sa1 = sa1[sa1.geometry.notna() & ~sa1.geometry.is_empty].copy().reset_index(drop=True)
    sa2 = sa2[sa2.geometry.notna() & ~sa2.geometry.is_empty].copy().to_crs(target_crs)
    auckland = auckland.to_crs(target_crs)
    sa1 = sa1.to_crs(target_crs)
    representative = sa1.geometry.representative_point()
    boundary_geometry = auckland.geometry.iloc[0]
    in_auckland = representative.map(boundary_geometry.covers)
    boundary_touches = representative.map(boundary_geometry.boundary.intersects)
    scoped = sa1.loc[in_auckland].copy().reset_index(drop=True)
    scoped_points = scoped.geometry.representative_point()
    point_frame = gpd.GeoDataFrame(
        {"sa1_row": range(len(scoped))}, geometry=scoped_points, crs=target_crs
    )
    zone_frame = sa2[["SA22023_V1_00", "geometry"]].copy().reset_index(drop=True)
    matches = gpd.sjoin(point_frame, zone_frame, how="left", predicate="intersects")
    valid_matches = matches[matches["SA22023_V1_00"].notna()].copy()
    counts = valid_matches.groupby("sa1_row").size()
    missing_count = len(scoped) - int(counts.index.nunique())
    ambiguous_count = int((counts > 1).sum())
    if missing_count:
        raise DemandConstraintError(
            "official SA1-to-SA2 spatial assignment is not one-to-one: "
            f"missing={missing_count}, ambiguous=0"
        )

    assignment: dict[int, str] = {}
    maximum_overlap_shares: list[float] = []
    unresolved_ambiguities = 0
    for sa1_row, candidate_matches in valid_matches.groupby("sa1_row", sort=True):
        candidates = candidate_matches.drop_duplicates(subset=["SA22023_V1_00"])
        if len(candidates) == 1:
            assignment[int(sa1_row)] = str(candidates.iloc[0]["SA22023_V1_00"])
            continue
        source_geometry = make_valid(scoped.geometry.iloc[int(sa1_row)])
        overlaps: list[tuple[float, str]] = []
        for candidate in candidates.itertuples():
            zone_geometry = make_valid(zone_frame.geometry.iloc[int(candidate.index_right)])
            overlaps.append(
                (
                    float(source_geometry.intersection(zone_geometry).area),
                    str(candidate.SA22023_V1_00),
                )
            )
        overlaps.sort(key=lambda item: (-item[0], item[1]))
        winning_area, winning_zone = overlaps[0]
        runner_up_area = overlaps[1][0]
        tie_tolerance = max(1e-6, winning_area * 1e-9)
        if winning_area <= 0 or winning_area - runner_up_area <= tie_tolerance:
            unresolved_ambiguities += 1
            continue
        assignment[int(sa1_row)] = winning_zone
        total_overlap = sum(area for area, _ in overlaps)
        maximum_overlap_shares.append(winning_area / total_overlap if total_overlap > 0 else 0.0)
    if unresolved_ambiguities:
        raise DemandConstraintError(
            "official SA1-to-SA2 spatial assignment is not one-to-one: "
            f"missing=0, ambiguous={unresolved_ambiguities}"
        )
    scoped["SA22023_code"] = [assignment[index] for index in range(len(scoped))]
    scoped["SA12023_code"] = scoped["SA12023_V1_00"].astype(str)

    population_intervals = [_count_interval(value) for value in scoped["VAR_1_3"]]
    scoped["population"] = [interval.point for interval in population_intervals]
    supports = tuple(
        SpatialSupport(
            id=f"sa1-{row.SA12023_code}",
            zone_id=row.SA22023_code,
            x=point.x,
            y=point.y,
            weight=max(float(row.population), 0.0),
            source="stats_nz_sa1_usually_resident_population_2023",
        )
        for row, point in zip(scoped.itertuples(), scoped_points, strict=True)
    )
    zones = set(scoped["SA22023_code"])
    polygons = (
        sa2[sa2["SA22023_V1_00"].astype(str).isin(zones)]
        .assign(SA22023_code=lambda frame: frame["SA22023_V1_00"].astype(str))[
            ["SA22023_code", "geometry"]
        ]
        .dissolve(by="SA22023_code")
    )
    diagnostics = GeographyDiagnostics(
        input_sa1_features=input_counts[0],
        input_sa2_features=input_counts[1],
        input_boundary_features=input_counts[2],
        valid_sa1_features=len(sa1),
        scoped_auckland_sa1_features=len(scoped),
        outside_auckland_sa1_features=int((~in_auckland).sum()),
        boundary_touching_representative_points=int(boundary_touches.sum()),
        missing_sa2_assignments=missing_count,
        ambiguous_sa2_assignments=ambiguous_count,
        resolved_ambiguous_sa2_assignments=ambiguous_count,
        unresolved_ambiguous_sa2_assignments=unresolved_ambiguities,
        minimum_maximum_overlap_share=(
            min(maximum_overlap_shares) if maximum_overlap_shares else None
        ),
        suppressed_population_weights=sum(
            interval.treatment == "suppressed_interval" for interval in population_intervals
        ),
    )
    return polygons, supports, zones, diagnostics


def _assign_pois_to_sa2(
    pois: Sequence[DestinationPOI], polygons: gpd.GeoDataFrame, *, target_crs: str
) -> dict[str, list[DestinationPOI]]:
    if not pois:
        return {}
    points = gpd.GeoDataFrame(
        {"poi_index": range(len(pois))},
        geometry=[Point(item.x, item.y) for item in pois],
        crs=target_crs,
    )
    zones = polygons.reset_index()[["SA22023_code", "geometry"]]
    joined = gpd.sjoin(points, zones, how="left", predicate="within")
    result: dict[str, list[DestinationPOI]] = defaultdict(list)
    for row in joined.itertuples():
        if row.SA22023_code is not None:
            result[str(row.SA22023_code)].append(pois[int(row.poi_index)])
    return result


def _employment_supports(
    pois_by_zone: Mapping[str, Sequence[DestinationPOI]],
    jobs: Sequence[Mapping[str, Any]],
    required_zones: set[str],
) -> tuple[tuple[SpatialSupport, ...], tuple[str, ...]]:
    employee_count = {
        str(row.get(_MARGIN_CODE, "")): max(float(row.get("ec2024") or 0), 0.0) for row in jobs
    }
    supports: list[SpatialSupport] = []
    unresolved_zones: list[str] = []
    for zone in sorted(required_zones):
        pois = [item for item in pois_by_zone.get(zone, ()) if "employment_proxy" in item.roles]
        employment = employee_count.get(zone, 0.0)
        if pois:
            weight = employment / len(pois) if employment > 0 else 1.0
            supports.extend(
                SpatialSupport(
                    item.id,
                    zone,
                    item.x,
                    item.y,
                    weight,
                    f"osm_employment_proxy_{EVERYDAY_POI_MAPPING_VERSION}",
                )
                for item in pois
            )
            continue
        unresolved_zones.append(zone)
    return tuple(supports), tuple(unresolved_zones)


def _read_jtw(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {_ORIGIN, _DESTINATION, _BICYCLE, _TOTAL}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise DemandConstraintError(
                "journey-to-work CSV is missing fields: " + ", ".join(sorted(missing))
            )
        return list(reader)


def _load_osm_destinations_from_dependency(
    context: StageContext,
) -> tuple[DestinationPOI, ...] | None:
    topology = context.dependencies.get("build-topology")
    digest = topology.get("topology") if topology is not None else None
    if digest is None:
        return None
    payload = read_json(_topology_payload_path(digest.path))
    raw = payload.get("destination_pois") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        return None
    return tuple(
        DestinationPOI(
            id=str(item["id"]),
            source_osm_type=str(item["source_osm_type"]),
            source_osm_id=str(item["source_osm_id"]),
            x=float(item["x"]),
            y=float(item["y"]),
            longitude=float(item["longitude"]),
            latitude=float(item["latitude"]),
            category=str(item["category"]),
            roles=tuple(item["roles"]),
            weight=float(item["weight"]),
            mapping_version=str(item["mapping_version"]),
        )
        for item in raw
        if isinstance(item, Mapping)
    )


def _topology_payload_path(path: Path) -> Path:
    """Resolve the versioned topology payload from a file or artifact directory."""

    return path / "topology.json" if path.is_dir() else path


def _major_transit_surface(path: Path, *, target_crs: str) -> list[dict[str, Any]]:
    """Read the registered archived GTFS-derived point surface."""

    payload = read_json(path)
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        raise DemandConstraintError("major transit node source must be a GeoJSON feature array")
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    result: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, Mapping) or not isinstance(properties, Mapping):
            continue
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list):
            continue
        try:
            longitude, latitude = float(coordinates[0]), float(coordinates[1])
            x, y = transformer.transform(longitude, latitude)
            stop_id = str(properties["stop_id"]).strip()
            if not stop_id:
                continue
            daily_trips = max(float(properties.get("daily_trips") or 0), 0.0)
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        result.append(
            {
                "id": f"transit-{stop_id}",
                "source_stop_id": stop_id,
                "x": x,
                "y": y,
                "longitude": longitude,
                "latitude": latitude,
                "kind": str(properties.get("kind", "major_transit_node")),
                "daily_service_trips": daily_trips,
                "service_measure_interpretation": "scheduled_service_trips_not_boardings",
                "source": "archived_at_gtfs",
            }
        )
    if not result:
        raise DemandConstraintError("major transit node source has no usable point features")
    return sorted(result, key=lambda item: str(item["id"]))


def prepare_auckland_demand_stage(context: StageContext) -> StageResult:
    """Run confidentiality-safe Auckland OD preparation and spatial allocation."""

    target_crs = context.config.project.crs
    sa1_path = _source_path(context, "stats_nz_sa1_geography")
    polygons, origins, auckland_zones, geography = _sa1_supports(
        sa1_path,
        _source_path(context, "stats_nz_sa2_geography"),
        _source_path(context, "stats_nz_auckland_boundary"),
        target_crs=target_crs,
    )
    _require_record_count(context, "stats_nz_sa1_geography", geography.input_sa1_features)
    _require_record_count(context, "stats_nz_sa2_geography", geography.input_sa2_features)
    _require_record_count(context, "stats_nz_auckland_boundary", geography.input_boundary_features)
    margin_records = _json_records(_source_path(context, "stats_nz_sa2_transport_margins"))
    _require_record_count(context, "stats_nz_sa2_transport_margins", len(margin_records))
    jobs = _json_records(_source_path(context, "stats_nz_business_demography_sa2_2024"))
    _require_record_count(context, "stats_nz_business_demography_sa2_2024", len(jobs))
    jtw_rows = _read_jtw(_source_path(context, "stats_nz_journey_to_work"))
    _require_expected_record_count(context, "stats_nz_journey_to_work", len(jtw_rows))
    prepared = prepare_zonal_commute_demand(
        jtw_rows,
        margin_records,
        auckland_zones,
    )

    destinations = _load_osm_destinations_from_dependency(context)
    if destinations is None:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="missing_topology_poi_dependency",
            message=(
                "prepare-demand requires the content-addressed build-topology output; "
                "the OSM extract must not be parsed twice"
            ),
            evidence={"required_dependency": "build-topology"},
        )
    pois_by_zone = _assign_pois_to_sa2(destinations, polygons, target_crs=target_crs)
    internal_cells = tuple(
        cell for cell in prepared.cells if cell.destination_zone in auckland_zones
    )
    required_destination_zones = {cell.destination_zone for cell in internal_cells}
    employment_supports, unresolved_destination_zones = _employment_supports(
        pois_by_zone, jobs, required_destination_zones
    )
    unresolved_destination_zone_set = set(unresolved_destination_zones)
    spatializable_cells = tuple(
        cell
        for cell in internal_cells
        if cell.destination_zone not in unresolved_destination_zone_set
    )
    unresolved_destination_cells = tuple(
        cell for cell in internal_cells if cell.destination_zone in unresolved_destination_zone_set
    )
    demand_parameters = context.config.parameters.get("demand")
    disaggregation = (
        demand_parameters.get("disaggregation") if isinstance(demand_parameters, Mapping) else None
    )
    samples_per_od = (
        disaggregation.get("samples_per_od", 25) if isinstance(disaggregation, Mapping) else 25
    )
    seed = disaggregation.get("seed", 20260301) if isinstance(disaggregation, Mapping) else 20260301
    if not isinstance(samples_per_od, int) or samples_per_od < 1:
        raise DemandConstraintError("demand.disaggregation.samples_per_od must be positive")
    if not isinstance(seed, int):
        raise DemandConstraintError("demand.disaggregation.seed must be an integer")
    flows = disaggregate_od_to_weighted_supports(
        spatializable_cells,
        prepared.cycle_point_by_od,
        origins,
        employment_supports,
        purpose="commute",
        samples_per_od=samples_per_od,
        seed=seed,
    )

    schools = _json_records(_source_path(context, "educationcounts_schools_auckland"))
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    school_surface: list[dict[str, Any]] = []
    excluded_non_open_schools = 0
    for school in schools:
        if str(school.get("Status", "")).strip().casefold() != "open":
            excluded_non_open_schools += 1
            continue
        try:
            longitude = float(school["Longitude"])
            latitude = float(school["Latitude"])
            roll = max(float(school.get("Total") or 0), 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        x, y = transformer.transform(longitude, latitude)
        school_surface.append(
            {
                "id": f"school-{school.get('School_Id')}",
                "zone_id": str(school.get("Statistical_Area_2_Code", "")),
                "x": x,
                "y": y,
                "roll": roll,
                "source": "education_counts_school_roll",
                "status": "open",
                "roll_date": school.get("Roll_Date"),
            }
        )
    everyday_surface = [asdict(item) for item in destinations if "everyday" in item.roles]
    transit_surface = _major_transit_surface(
        _source_path(context, "major_transit_nodes"), target_crs=target_crs
    )

    purpose_parameters = (
        demand_parameters.get("purpose_markets") if isinstance(demand_parameters, Mapping) else None
    )
    if not isinstance(purpose_parameters, Mapping):
        raise DemandConstraintError("demand.purpose_markets must be configured")
    school_parameters = purpose_parameters.get("school")
    everyday_parameters = purpose_parameters.get("everyday")
    transit_parameters = purpose_parameters.get("transit")
    if not all(
        isinstance(value, Mapping)
        for value in (school_parameters, everyday_parameters, transit_parameters)
    ):
        raise DemandConstraintError("school, everyday, and transit purpose markets are required")
    assert isinstance(school_parameters, Mapping)
    assert isinstance(everyday_parameters, Mapping)
    assert isinstance(transit_parameters, Mapping)

    try:
        school_records, school_exclusions = generate_school_market(
            origins,
            [
                PurposeDestination(
                    str(item["id"]),
                    float(item["x"]),
                    float(item["y"]),
                    "school",
                    float(item["roll"]),
                    str(item["zone_id"]),
                )
                for item in school_surface
            ],
            maximum_distance_m=float(school_parameters["maximum_distance_m"]),
            distance_decay_m=float(school_parameters["distance_decay_m"]),
            samples_per_school=int(school_parameters["samples_per_school"]),
            seed=int(school_parameters["seed"]),
        )
        everyday_records, everyday_exclusions = generate_everyday_market(
            origins,
            [
                PurposeDestination(
                    str(item["id"]),
                    float(item["x"]),
                    float(item["y"]),
                    str(item["category"]),
                    float(item["weight"]),
                )
                for item in everyday_surface
            ],
            category_weights={
                str(key): float(value)
                for key, value in everyday_parameters["category_weights"].items()
            },
            maximum_distance_m=float(everyday_parameters["maximum_distance_m"]),
        )
        transit_records, transit_exclusions = generate_transit_market(
            origins,
            [
                PurposeDestination(
                    str(item["id"]),
                    float(item["x"]),
                    float(item["y"]),
                    "major_transit_node",
                    max(float(item["daily_service_trips"]), 1.0),
                )
                for item in transit_surface
            ],
            maximum_distance_m=float(transit_parameters["maximum_distance_m"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DemandConstraintError(f"invalid purpose-market configuration: {exc}") from exc
    non_commute_records = (*school_records, *everyday_records, *transit_records)
    purpose_exclusions = (*school_exclusions, *everyday_exclusions, *transit_exclusions)

    zonal_ledger = []
    for cell in prepared.cells:
        cycle_interval = cell.cycle_interval
        eligible_interval = cell.eligible_interval
        internal = cell.destination_zone in auckland_zones
        unresolved_destination = cell.destination_zone in unresolved_destination_zone_set
        zonal_ledger.append(
            {
                "id": cell.id,
                "origin_zone": cell.origin_zone,
                "destination_zone": cell.destination_zone,
                "eligible_lower": eligible_interval.lower,
                "eligible_point": eligible_interval.point,
                "eligible_upper": eligible_interval.upper,
                "eligible_treatment": eligible_interval.treatment,
                "cycle_lower": cycle_interval.lower,
                "cycle_point": prepared.cycle_point_by_od[cell.id],
                "cycle_upper": cycle_interval.upper,
                "cycle_treatment": cycle_interval.treatment,
                "cycle_suppressed": cell.suppressed,
                "route_status": (
                    "unresolved_destination_support"
                    if unresolved_destination
                    else "internal_spatialized"
                    if internal
                    else "outbound_or_special_retained"
                ),
            }
        )
    published_internal_pairs = {
        (cell.origin_zone, cell.destination_zone) for cell in internal_cells
    }
    structurally_omitted_internal_pairs = max(
        0, len(auckland_zones) ** 2 - len(published_internal_pairs)
    )
    origin_total_evidence = [
        item
        for item in prepared.margin_evidence
        if item.metric == "total_stated" and item.universe.startswith("all_auckland_origin")
    ]
    origin_cycle_evidence = [
        item
        for item in prepared.margin_evidence
        if item.metric == "bicycle" and item.universe.startswith("all_auckland_origin")
    ]
    source_market_denominator = sum(item.margin_point or 0.0 for item in origin_total_evidence)
    source_market_observed_cycle = sum(item.margin_point or 0.0 for item in origin_cycle_evidence)
    internal_published_market = sum(cell.eligible_interval.point for cell in internal_cells)
    internal_spatializable_market = sum(
        cell.eligible_interval.point for cell in spatializable_cells
    )
    unresolved_destination_market = sum(
        cell.eligible_interval.point for cell in unresolved_destination_cells
    )
    outbound_published_market = sum(
        cell.eligible_interval.point
        for cell in prepared.cells
        if cell.destination_zone not in auckland_zones
    )
    unresolved_market = max(
        0.0,
        source_market_denominator - internal_published_market - outbound_published_market,
    )
    payload = {
        "schema_version": 3,
        "run_id": context.run_id,
        "crs": target_crs,
        "confidentiality": {
            "method": "joint-fixed-random-rounding-base-3-intervals",
            "numeric_maximum_error": 2,
            "suppression_interval": [0, 5],
            "joint_constraint": "bicycle_count_not_greater_than_eligible_count",
            "origin_margin_role": "soft_bounded_evidence_different_universe",
            "destination_margin_role": "soft_bounded_evidence_different_universe",
            "hard_margin_constraint_applied": False,
            "suppressed_cycle_cells": prepared.suppressed_cycle_cells,
            "suppressed_eligible_cells": prepared.suppressed_eligible_cells,
            "margin_evidence": [asdict(item) for item in prepared.margin_evidence],
        },
        "sampling": {
            "design": "deterministic_probability_proportional_with_replacement",
            "samples_per_od": samples_per_od,
            "seed": seed,
            "weights_retained": True,
        },
        "geography": {
            "assignment": (
                "SA1 representative point intersecting official SA2 polygon; "
                "strict maximum SA1 overlap resolves multiple matches"
            ),
            "scope": "official Auckland territorial authority 2023 code 076",
            "boundary_policy": (
                "Auckland boundary covers representative point; no nearest-zone fallback; "
                "missing assignments and maximum-overlap ties fail closed"
            ),
            "diagnostics": asdict(geography),
            "equity_context": {
                "status": "disabled_unless_separately_licensed_and_joined",
                "source_id": "nzdep2023_sa1",
                "used_in_core_demand": False,
            },
        },
        "structural_censoring": {
            "mechanism": (
                "published table removes rows with total population below 6 and "
                "includes only people with workplace address available at SA2"
            ),
            "absent_pairs_are_observed_zero": False,
            "published_table_rows": len(jtw_rows),
            "published_auckland_origin_rows": len(prepared.cells),
            "published_internal_pairs": len(published_internal_pairs),
            "possible_internal_pairs": len(auckland_zones) ** 2,
            "structurally_omitted_internal_pairs": structurally_omitted_internal_pairs,
            "invented_destination_rows": 0,
            "unresolved_market_ledger": {
                "source_market_total_stated_margin_point": source_market_denominator,
                "source_market_bicycle_margin_point": source_market_observed_cycle,
                "published_internal_eligible_point": internal_published_market,
                "published_internal_spatializable_eligible_point": (internal_spatializable_market),
                "unresolved_destination_support_eligible_point": (unresolved_destination_market),
                "published_outbound_or_special_eligible_point": outbound_published_market,
                "unresolved_or_out_of_scope_eligible_point": unresolved_market,
                "pre_route_coverage_of_source_market": (
                    internal_spatializable_market / source_market_denominator
                    if source_market_denominator > 0
                    else 0.0
                ),
                "destination_allocation": "unknown_not_invented",
            },
        },
        "publication_grade_ready": not unresolved_destination_zones,
        "publication_blockers": [],
        "coverage_exclusions": (
            []
            if not unresolved_destination_zones
            else [
                {
                    "code": "unresolved_destination_support",
                    "message": (
                        "published OD records are retained but not spatialized where no "
                        "defensible employment-point support is available"
                    ),
                    "zone_ids": list(unresolved_destination_zones),
                    "zonal_od_count": len(unresolved_destination_cells),
                    "eligible_point": unresolved_destination_market,
                    "cycle_point": sum(
                        prepared.cycle_point_by_od[cell.id] for cell in unresolved_destination_cells
                    ),
                }
            ]
        ),
        "zonal_od_ledger": zonal_ledger,
        "disaggregated_commute_ledger": [asdict(item) for item in flows],
        "non_commute_purpose_od_ledger": [item.to_dict() for item in non_commute_records],
        "purpose_generation_exclusion_ledger": [item.to_dict() for item in purpose_exclusions],
        "purpose_surfaces": {
            "population_origins": [asdict(item) for item in origins],
            "commute": {
                "source": "Stats NZ journey-to-work with constrained suppression",
                "record_count": len(flows),
                "demand_unit": "census_main_means_of_travel_to_work_persons",
            },
            "school": {
                "destinations": school_surface,
                "record_count": len(school_records),
                "demand_unit": "modelled_enrolment_access",
                "interpretation": (
                    "observed roll allocated to a modelled home catchment; not observed cycling"
                ),
                "parameters": dict(school_parameters),
            },
            "everyday": {
                "destinations": everyday_surface,
                "record_count": len(everyday_records),
                "demand_unit": "person_equivalent_opportunity_access_index",
                "interpretation": "relative accessibility surface; not observed daily trips",
                "parameters": dict(everyday_parameters),
            },
            "transit": {
                "destinations": transit_surface,
                "record_count": len(transit_records),
                "demand_unit": "person_equivalent_major_transit_access_index",
                "interpretation": "nearest-node access surface; scheduled service is not patronage",
                "parameters": dict(transit_parameters),
            },
        },
    }
    destination = context.output_path("demand.json")
    write_json_atomic(destination, payload)
    return StageResult(
        {"demand": destination},
        {
            "row_counts": {
                "zonal_od": len(prepared.cells),
                "published_jtw_table_rows": len(jtw_rows),
                "suppressed_bicycle_cells": prepared.suppressed_cycle_cells,
                "suppressed_eligible_cells": prepared.suppressed_eligible_cells,
                "structurally_omitted_internal_pairs": (structurally_omitted_internal_pairs),
                "disaggregated_commute": len(flows),
                "school_destinations": len(school_surface),
                "school_od": len(school_records),
                "excluded_non_open_schools": excluded_non_open_schools,
                "everyday_destinations": len(everyday_surface),
                "everyday_od": len(everyday_records),
                "transit_destinations": len(transit_surface),
                "transit_od": len(transit_records),
                "purpose_generation_exclusions": len(purpose_exclusions),
                "unresolved_destination_support_zones": len(unresolved_destination_zones),
                "unresolved_destination_support_zonal_od": len(unresolved_destination_cells),
                "input_sa1_geographies": geography.input_sa1_features,
                "scoped_auckland_sa1_geographies": (geography.scoped_auckland_sa1_features),
                "auckland_sa2_geographies": len(auckland_zones),
                "internal_zonal_od": prepared.internal_od_count,
                "outbound_or_special_zonal_od": prepared.outbound_or_special_od_count,
                "excluded_non_auckland_origin_jtw": (prepared.excluded_non_auckland_origin_rows),
            }
        },
    )


def _bounded_osm_extract(
    context: StageContext,
    *,
    bounds: GeographicBounds,
    output_dir: Path,
) -> tuple[Path, Mapping[str, Any]]:
    source = _source_path(context, "geofabrik_new_zealand_osm")
    if source.suffix.lower() != ".pbf":
        destination = output_dir / source.name
        shutil.copy2(source, destination)
        return destination, {
            "strategy": "prebounded_non_pbf_fixture",
            "source_sha256": context.sources["geofabrik_new_zealand_osm"].sha256,
            "output_size": destination.stat().st_size,
            "output_sha256": sha256_file(destination),
        }
    executable = shutil.which("osmium")
    if executable is None:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="osmium_cli_unavailable",
            message="the bounded OSM preprocessing stage requires osmium-tool",
            evidence={"required_command": "osmium extract"},
        )
    specification = {
        "bbox_wgs84": [bounds.west, bounds.south, bounds.east, bounds.north],
        "strategy": "complete_ways",
        "source_sha256": context.sources["geofabrik_new_zealand_osm"].sha256,
        "adapter_version": "1",
    }
    identity = content_hash(specification)[:16]
    destination = output_dir / f"auckland-osm-{identity}.osm.pbf"
    command = [
        executable,
        "extract",
        "--bbox",
        ",".join(str(value) for value in specification["bbox_wgs84"]),
        "--strategy",
        "complete_ways",
        "--output",
        str(destination),
        "--overwrite",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=900,
        )
        version = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="osmium_extract_failed",
            message="could not create the bounded Auckland OSM extract",
            evidence={"error": str(exc), "bbox_wgs84": specification["bbox_wgs84"]},
        ) from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="osmium_extract_empty",
            message="bounded Auckland OSM extraction produced no usable file",
            evidence={"stderr": completed.stderr[-1000:]},
        )
    return destination, {
        **specification,
        "boundary_policy": "retain complete ways intersecting the bbox",
        "osmium_version": version,
        "output_size": destination.stat().st_size,
        "output_sha256": sha256_file(destination),
    }


def _analysis_bounds(context: StageContext) -> GeographicBounds:
    network = context.config.parameters.get("network")
    raw = network.get("analysis_bounds_wgs84") if isinstance(network, Mapping) else None
    if not isinstance(raw, list) or len(raw) != 4:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="missing_analysis_bounds",
            message="network.analysis_bounds_wgs84 must declare west,south,east,north",
            evidence={"configured_value": raw},
        )
    try:
        bounds = GeographicBounds(*(float(value) for value in raw))
    except (TypeError, ValueError) as exc:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_analysis_bounds",
            message="network.analysis_bounds_wgs84 contains a non-numeric value",
            evidence={"configured_value": raw},
        ) from exc
    if bounds.west >= bounds.east or bounds.south >= bounds.north:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_analysis_bounds",
            message="network.analysis_bounds_wgs84 has invalid axis order",
            evidence={"configured_value": raw},
        )
    return bounds


def build_auckland_topology_stage(context: StageContext) -> StageResult:
    """Build the real layer/direction/access-preserving Auckland OSM graph."""

    topology_dir = context.artifact_dir / "topology"
    topology_dir.mkdir(parents=True, exist_ok=True)
    terrain_path = _source_path(context, "linz_auckland_dem")
    terrain_manifest = verify_raster_manifest(
        terrain_path,
        _source_path(context, "linz_auckland_dem_manifest"),
    )
    at_collection = _feature_collection(_source_path(context, "auckland_transport_cycle_network"))
    at_features = at_collection["features"]
    _require_record_count(context, "auckland_transport_cycle_network", len(at_features))
    bounds = _analysis_bounds(context)
    bounded_osm, extract_provenance = _bounded_osm_extract(
        context,
        bounds=bounds,
        output_dir=topology_dir,
    )
    extraction = extract_osm_network(
        bounded_osm,
        bounds=bounds,
        target_crs=context.config.project.crs,
    )
    candidate_parameters = context.config.parameters.get("candidates")
    matching = (
        candidate_parameters.get("facility_matching")
        if isinstance(candidate_parameters, Mapping)
        else {}
    )
    matches = match_at_facilities(
        extraction.edges,
        at_features,
        maximum_offset_m=float(matching.get("maximum_offset_m", 20)),
        minimum_overlap_ratio=float(matching.get("minimum_overlap_ratio", 0.6)),
        maximum_bearing_difference_degrees=float(
            matching.get("maximum_bearing_difference_degrees", 30)
        ),
        require_layer_compatibility=bool(matching.get("require_layer_compatibility", True)),
    )
    facility_edges = apply_facility_matches(extraction.edges, matches)
    edges, terrain_coverage = apply_raster_gradients(facility_edges, terrain_path)
    payload = {
        "schema_version": 2,
        "run_id": context.run_id,
        "crs": context.config.project.crs,
        "source_identity": (
            "OSM node and way identifiers; coincident distinct nodes remain disconnected; "
            "layer, bridge, and tunnel are preserved on physical edges"
        ),
        "osm_extract": extract_provenance,
        "nodes": [asdict(node) for node in extraction.nodes],
        "edges": [
            {
                **asdict(edge),
                "direction": edge.direction.value,
                "road_class": edge.road_class.value,
                "facility": edge.facility.value,
                "lts": level_of_traffic_stress(StressInputs.from_edge(edge)).level,
            }
            for edge in edges
        ],
        "destination_pois": [asdict(item) for item in extraction.destinations],
        "facility_matches": [asdict(item) for item in matches],
        "terrain": {
            "manifest_file_count": terrain_manifest.file_count,
            "manifest_total_size": terrain_manifest.total_size,
            "manifest_files": list(terrain_manifest.files),
            "valid_gradient_edges": terrain_coverage.valid_gradient_edges,
            "missing_or_nodata_edges": terrain_coverage.missing_or_nodata_edges,
            "gradient_coverage": terrain_coverage.coverage,
        },
        "diagnostics": {
            "source_way_count": extraction.way_count,
            "excluded_way_count": extraction.excluded_way_count,
            "invalid_location_count": extraction.invalid_location_count,
            "everyday_poi_mapping_version": EVERYDAY_POI_MAPPING_VERSION,
        },
    }
    destination = topology_dir / "topology.json"
    write_json_atomic(destination, payload)
    return StageResult(
        {"topology": topology_dir},
        {
            "row_counts": {
                "nodes": len(extraction.nodes),
                "directed_physical_edges": len(edges),
                "facility_matches": len(matches),
                "destination_pois": len(extraction.destinations),
                "valid_gradient_edges": terrain_coverage.valid_gradient_edges,
                "missing_or_nodata_edges": terrain_coverage.missing_or_nodata_edges,
            }
        },
    )


def production_stage_handlers() -> Mapping[str, StageHandler]:
    from .production_candidates_stage import production_candidates_stage
    from .production_evidence_stage import production_evidence_stage
    from .production_export_stage import (
        production_export_outputs_stage,
        production_export_web_stage,
    )
    from .production_portfolios_stage import production_portfolios_stage
    from .production_routing_stage import production_routing_stage

    return {
        "prepare-demand": prepare_auckland_demand_stage,
        "build-topology": build_auckland_topology_stage,
        "assign-routes": production_routing_stage,
        "generate-candidates": production_candidates_stage,
        "evaluate-portfolios": production_portfolios_stage,
        "appraisal-uncertainty-validation": production_evidence_stage,
        "export-outputs": production_export_outputs_stage,
        "export-web": production_export_web_stage,
    }
