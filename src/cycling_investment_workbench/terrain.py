"""Fail-closed raster manifest verification and edge-gradient sampling."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

import numpy as np
import rasterio

from .models import Edge
from .provenance import sha256_file


class TerrainError(ValueError):
    """Raised when the DEM contract or coverage is invalid."""


@dataclass(frozen=True, slots=True)
class TerrainManifestResult:
    file_count: int
    total_size: int
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainCoverage:
    edge_count: int
    valid_gradient_edges: int
    missing_or_nodata_edges: int

    @property
    def coverage(self) -> float:
        return self.valid_gradient_edges / self.edge_count if self.edge_count else 0.0


def _normal_relative_path(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise TerrainError(f"{context} must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TerrainError(f"{context} must be a normal relative path")
    return path.as_posix()


def _vrt_references(vrt_path: Path, manifest_dir: Path) -> set[str]:
    if vrt_path.suffix.lower() != ".vrt":
        try:
            return {vrt_path.resolve().relative_to(manifest_dir.resolve()).as_posix()}
        except ValueError as exc:
            raise TerrainError("the raster must be inside the manifest directory") from exc
    try:
        root = ElementTree.parse(vrt_path).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise TerrainError(f"could not parse VRT: {exc}") from exc
    references: set[str] = set()
    for element in root.iter("SourceFilename"):
        text = (element.text or "").strip()
        if not text:
            raise TerrainError("VRT contains a blank SourceFilename")
        if element.get("relativeToVRT") != "1":
            raise TerrainError("all VRT SourceFilename entries must be relative")
        references.add(_normal_relative_path(text, context="VRT SourceFilename"))
    if not references:
        raise TerrainError("VRT contains no source rasters")
    return references


def verify_raster_manifest(
    raster_path: str | Path, manifest_path: str | Path
) -> TerrainManifestResult:
    """Verify that every and only VRT-referenced raster is hash/size pinned."""

    raster = Path(raster_path)
    manifest = Path(manifest_path)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TerrainError(f"could not read terrain manifest: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TerrainError("terrain manifest schema_version must be 1")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise TerrainError("terrain manifest files must be a non-empty array")
    entries: dict[str, tuple[int, str]] = {}
    for index, raw in enumerate(raw_files):
        if not isinstance(raw, dict) or set(raw) != {"path", "size", "sha256"}:
            raise TerrainError(f"terrain manifest files[{index}] has invalid fields")
        relative = _normal_relative_path(raw["path"], context=f"files[{index}].path")
        size = raw["size"]
        digest = raw["sha256"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise TerrainError(f"files[{index}].size must be a positive integer")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise TerrainError(f"files[{index}].sha256 must be lowercase SHA-256")
        if relative in entries:
            raise TerrainError(f"duplicate terrain manifest path: {relative}")
        entries[relative] = (size, digest)
    expected = _vrt_references(raster, manifest.parent)
    if set(entries) != expected:
        missing = expected.difference(entries)
        extra = set(entries).difference(expected)
        raise TerrainError(
            "terrain manifest does not exactly match raster sources; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    total_size = 0
    for relative, (expected_size, expected_digest) in entries.items():
        path = (manifest.parent / relative).resolve()
        if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
            raise TerrainError(f"terrain raster is missing: {relative}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise TerrainError(f"terrain raster size mismatch: {relative}")
        if sha256_file(path) != expected_digest:
            raise TerrainError(f"terrain raster hash mismatch: {relative}")
        total_size += actual_size
    return TerrainManifestResult(len(entries), total_size, tuple(sorted(entries)))


def apply_raster_gradients(
    edges: tuple[Edge, ...], raster_path: str | Path
) -> tuple[tuple[Edge, ...], TerrainCoverage]:
    """Sample oriented endpoint elevations and report missing/nodata coverage."""

    sample_edges = [edge for edge in edges if len(edge.geometry) >= 2]
    coordinates = [
        coordinate for edge in sample_edges for coordinate in (edge.geometry[0], edge.geometry[-1])
    ]
    try:
        with rasterio.open(raster_path) as dataset:
            values = list(dataset.sample(coordinates, masked=True))
    except (OSError, rasterio.errors.RasterioError) as exc:
        raise TerrainError(f"could not sample terrain raster: {exc}") from exc
    sampled: dict[str, tuple[float, float] | None] = {}
    for index, edge in enumerate(sample_edges):
        start = values[index * 2]
        end = values[index * 2 + 1]
        invalid = (
            np.ma.is_masked(start[0])
            or np.ma.is_masked(end[0])
            or not np.isfinite(float(start[0]))
            or not np.isfinite(float(end[0]))
        )
        sampled[edge.id] = None if invalid else (float(start[0]), float(end[0]))
    result: list[Edge] = []
    valid = 0
    for edge in edges:
        elevations = sampled.get(edge.id)
        if elevations is None:
            result.append(
                replace(
                    edge,
                    attributes={**edge.attributes, "terrain_status": "missing_or_nodata"},
                )
            )
            continue
        valid += 1
        start, end = elevations
        result.append(
            replace(
                edge,
                gradient=(end - start) / edge.length_m,
                attributes={
                    **edge.attributes,
                    "terrain_status": "sampled",
                    "start_elevation_m": start,
                    "end_elevation_m": end,
                },
            )
        )
    coverage = TerrainCoverage(len(edges), valid, len(edges) - valid)
    return tuple(result), coverage
