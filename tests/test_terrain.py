from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from cycling_investment_workbench.models import Edge
from cycling_investment_workbench.provenance import sha256_file
from cycling_investment_workbench.terrain import (
    TerrainError,
    apply_raster_gradients,
    verify_raster_manifest,
)


def _raster(path: Path) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:2193",
        transform=from_origin(0, 2, 1, 1),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.array([[1, 3], [2, -9999]], dtype="float32"), 1)


def _manifest(path: Path, raster: Path, *, digest: str | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "path": raster.name,
                        "size": raster.stat().st_size,
                        "sha256": digest or sha256_file(raster),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_raster_manifest_verifies_every_file_and_gradient_coverage(
    tmp_path: Path,
) -> None:
    raster = tmp_path / "tile.tif"
    manifest = tmp_path / "manifest.json"
    _raster(raster)
    _manifest(manifest, raster)

    verified = verify_raster_manifest(raster, manifest)
    edges, coverage = apply_raster_gradients(
        (
            Edge("valid", "a", "b", 1, geometry=((0.5, 1.5), (1.5, 1.5))),
            Edge("nodata", "c", "d", 1, geometry=((0.5, 0.5), (1.5, 0.5))),
            Edge("no-geometry", "e", "f", 1),
        ),
        raster,
    )

    assert verified.file_count == 1
    assert verified.total_size == raster.stat().st_size
    assert edges[0].gradient == pytest.approx(2)
    assert edges[0].attributes["terrain_status"] == "sampled"
    assert edges[1].attributes["terrain_status"] == "missing_or_nodata"
    assert coverage.valid_gradient_edges == 1
    assert coverage.missing_or_nodata_edges == 2
    assert coverage.coverage == pytest.approx(1 / 3)


def test_raster_manifest_fails_on_hash_or_reference_mismatch(tmp_path: Path) -> None:
    raster = tmp_path / "tile.tif"
    manifest = tmp_path / "manifest.json"
    _raster(raster)
    _manifest(manifest, raster, digest="0" * 64)
    with pytest.raises(TerrainError, match="hash mismatch"):
        verify_raster_manifest(raster, manifest)

    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [{"path": "other.tif", "size": 1, "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TerrainError, match="does not exactly match"):
        verify_raster_manifest(raster, manifest)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 2, "files": []}, "schema_version"),
        ({"schema_version": 1, "files": []}, "non-empty array"),
        (
            {"schema_version": 1, "files": [{"path": "tile.tif"}]},
            "invalid fields",
        ),
        (
            {
                "schema_version": 1,
                "files": [{"path": "../tile.tif", "size": 1, "sha256": "0" * 64}],
            },
            "normal relative path",
        ),
        (
            {
                "schema_version": 1,
                "files": [{"path": "tile.tif", "size": 0, "sha256": "0" * 64}],
            },
            "positive integer",
        ),
        (
            {
                "schema_version": 1,
                "files": [{"path": "tile.tif", "size": 1, "sha256": "INVALID"}],
            },
            "lowercase SHA-256",
        ),
        (
            {
                "schema_version": 1,
                "files": [
                    {"path": "tile.tif", "size": 1, "sha256": "0" * 64},
                    {"path": "tile.tif", "size": 1, "sha256": "0" * 64},
                ],
            },
            "duplicate",
        ),
    ],
)
def test_raster_manifest_rejects_malformed_contracts(
    tmp_path: Path, payload: dict[str, object], message: str
) -> None:
    raster = tmp_path / "tile.tif"
    manifest = tmp_path / "manifest.json"
    raster.write_bytes(b"x")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TerrainError, match=message):
        verify_raster_manifest(raster, manifest)


def test_vrt_requires_relative_nonblank_sources_and_pinned_sizes(tmp_path: Path) -> None:
    tile = tmp_path / "tile.tif"
    tile.write_bytes(b"tile")
    vrt = tmp_path / "terrain.vrt"
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, tile)

    vrt.write_text("<broken", encoding="utf-8")
    with pytest.raises(TerrainError, match="could not parse VRT"):
        verify_raster_manifest(vrt, manifest)
    vrt.write_text(
        '<VRTDataset><SourceFilename relativeToVRT="1"> </SourceFilename></VRTDataset>',
        encoding="utf-8",
    )
    with pytest.raises(TerrainError, match="blank SourceFilename"):
        verify_raster_manifest(vrt, manifest)
    vrt.write_text(
        "<VRTDataset><SourceFilename>tile.tif</SourceFilename></VRTDataset>",
        encoding="utf-8",
    )
    with pytest.raises(TerrainError, match="must be relative"):
        verify_raster_manifest(vrt, manifest)
    vrt.write_text("<VRTDataset/>", encoding="utf-8")
    with pytest.raises(TerrainError, match="no source rasters"):
        verify_raster_manifest(vrt, manifest)
    vrt.write_text(
        '<VRTDataset><SourceFilename relativeToVRT="1">tile.tif</SourceFilename></VRTDataset>',
        encoding="utf-8",
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"][0]["size"] = tile.stat().st_size + 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TerrainError, match="size mismatch"):
        verify_raster_manifest(vrt, manifest)
