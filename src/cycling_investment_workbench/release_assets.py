"""Build deterministic, self-describing web-data release archives."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .provenance import canonical_json, hash_path, read_json, sha256_bytes, sha256_file

_WEB_OUTPUTS = (
    "web_manifest",
    "cells",
    "network",
    "candidates",
    "programmes",
    "counters",
    "safety",
)
_APPRAISAL_WITHHELD_WARNING = (
    "Appraisal is withheld from the public research snapshot until local cost, "
    "maintenance, renewal, benefit, e-bike, and price-base inputs pass expert review."
)
_Payload = Path | bytes


class ReleaseAssetError(ValueError):
    """Raised when a run cannot support a safe web-data release asset."""


@dataclass(frozen=True, slots=True)
class ReleaseAssetResult:
    path: Path
    size: int
    sha256: str
    run_id: str
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path.as_posix(),
            "size": self.size,
            "sha256": self.sha256,
            "run_id": self.run_id,
            "files": list(self.files),
        }


def _safe_run_output(run_dir: Path, record: Mapping[str, Any], name: str) -> Path:
    relative = record.get("path")
    if not isinstance(relative, str):
        raise ReleaseAssetError(f"run output has no path: {name}")
    path = (run_dir / relative).resolve()
    if not path.is_relative_to(run_dir) or not path.is_file():
        raise ReleaseAssetError(f"run output is missing or unsafe: {name}")
    digest = hash_path(path)
    if digest.size != record.get("size") or digest.sha256 != record.get("sha256"):
        raise ReleaseAssetError(f"run output fails integrity verification: {name}")
    return path


def _release_inputs(run_dir: Path) -> tuple[str, Path, dict[str, Path], Mapping[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ReleaseAssetError("run manifest must be a mapping")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or run_dir.name != run_id:
        raise ReleaseAssetError("run manifest identity does not match its directory")
    stages = manifest.get("stages")
    stage = stages.get("export-web") if isinstance(stages, Mapping) else None
    if not isinstance(stage, Mapping) or stage.get("status") not in {
        "succeeded",
        "cached",
        "skipped",
    }:
        raise ReleaseAssetError("run has no completed export-web stage")
    outputs = stage.get("outputs")
    if (
        not isinstance(outputs, Mapping)
        or not set(_WEB_OUTPUTS).issubset(outputs)
        or set(outputs) - set(_WEB_OUTPUTS) - {"existing"}
    ):
        raise ReleaseAssetError("export-web outputs do not match the release contract")
    paths = {name: _safe_run_output(run_dir, outputs[name], name) for name in outputs}
    web_manifest = read_json(paths["web_manifest"])
    if not isinstance(web_manifest, Mapping) or web_manifest.get("runId") != run_id:
        raise ReleaseAssetError("browser manifest identity does not match the run")
    return run_id, manifest_path, paths, web_manifest


def _asset_notice(
    *,
    run_id: str,
    run_manifest_path: Path,
    payloads: Mapping[str, _Payload],
    web_manifest: Mapping[str, Any],
    appraisal_withheld: bool,
) -> bytes:
    source_decisions = web_manifest.get("sourceDecisions")
    if not isinstance(source_decisions, list):
        raise ReleaseAssetError("browser manifest has no source-decision ledger")
    included = [
        str(record.get("sourceId"))
        for record in source_decisions
        if isinstance(record, Mapping) and record.get("decision") == "include"
    ]
    notice = {
        "schema_version": 1,
        "run_id": run_id,
        "source_run_manifest_sha256": sha256_file(run_manifest_path),
        "included_source_ids": sorted(included),
        "files": {
            name: {
                "size": _payload_size(payload),
                "sha256": _payload_sha256(payload),
            }
            for name, payload in sorted(payloads.items())
        },
        "licensing": {
            "software": (
                "The repository software is MIT licensed; that licence does not apply "
                "to these data files."
            ),
            "cells.geojson": "Stats NZ source terms: CC BY 4.0.",
            "network.geojson": (
                "OSM-derived database: ODbL 1.0; AT and LINZ inputs retain CC BY 4.0 attribution."
            ),
            "existing.geojson": (
                "OSM-derived low-stress network: ODbL 1.0; "
                "AT and LINZ inputs retain CC BY 4.0 attribution."
            ),
            "candidates.geojson": (
                "OSM-derived database: ODbL 1.0; Stats NZ, Education Counts, AT, "
                "and LINZ inputs retain CC BY 4.0 attribution."
            ),
            "programmes.geojson": (
                "Auckland Transport Future Connect and RLTP active-modes context; CC BY 4.0."
            ),
            "counters.geojson": (
                "AT observations under CC BY 4.0; approximate site points maintained by CIW."
            ),
            "safety.geojson": (
                "Disclosure-safe aggregate from NZTA CAS open data; record-level data excluded."
            ),
        },
        "required_attribution": [
            "© OpenStreetMap contributors; data available under ODbL 1.0.",
            "This work includes Stats NZ data licensed for reuse under CC BY 4.0.",
            "Contains data sourced from the LINZ Data Service licensed for reuse under CC BY 4.0.",
            "Auckland Transport.",
            "Ministry of Education / Education Counts.",
            "University of Otago NZDep2023; Stats NZ; Eagle Technology public ArcGIS service.",
        ],
        "licence_urls": {
            "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
            "ODbL-1.0": "https://opendatacommons.org/licenses/odbl/1-0/",
        },
        "limitations": [
            "Research snapshot; not an investment recommendation or business case.",
            (
                "Full-network OD low-stress connectivity is intentionally reserved for "
                "separate research integration; no Auckland point estimate is included."
            ),
            *([_APPRAISAL_WITHHELD_WARNING] if appraisal_withheld else []),
            (
                "Counter comparisons are spatial plausibility checks only; daily all-purpose "
                "movements are not calibrated against usual-commute people."
            ),
            "Safety cells are police-reported counts and are not adjusted for cycling exposure.",
        ],
    }
    return (canonical_json(notice) + "\n").encode("utf-8")


def _payload_size(payload: _Payload) -> int:
    return payload.stat().st_size if isinstance(payload, Path) else len(payload)


def _payload_sha256(payload: _Payload) -> str:
    return sha256_file(payload) if isinstance(payload, Path) else sha256_bytes(payload)


def _payload_stream(payload: _Payload) -> io.BufferedReader | io.BytesIO:
    return payload.open("rb") if isinstance(payload, Path) else io.BytesIO(payload)


def _withhold_unreviewed_appraisal(
    *, paths: Mapping[str, Path], web_manifest: Mapping[str, Any]
) -> tuple[dict[str, _Payload], Mapping[str, Any], bool]:
    """Fail closed when a run does not declare reviewed public appraisal inputs."""

    capabilities = web_manifest.get("capabilities")
    appraisal_status = capabilities.get("appraisal") if isinstance(capabilities, Mapping) else None
    payloads: dict[str, _Payload] = {path.name: path for path in paths.values()}
    if appraisal_status in {"reviewed", "research_only"}:
        return payloads, web_manifest, False

    manifest = json.loads(json.dumps(web_manifest))
    manifest.setdefault("capabilities", {})["appraisal"] = "withheld"
    limitations = manifest.setdefault("limitations", [])
    if _APPRAISAL_WITHHELD_WARNING not in limitations:
        limitations.append(_APPRAISAL_WITHHELD_WARNING)
    for portfolio in manifest.get("portfolios", {}).values():
        if isinstance(portfolio, dict):
            portfolio["appraisal"] = []
    for summaries in manifest.get("summaries", {}).values():
        summary = summaries.get("appraisal") if isinstance(summaries, dict) else None
        if isinstance(summary, dict):
            warnings = summary.setdefault("warnings", [])
            if _APPRAISAL_WITHHELD_WARNING not in warnings:
                warnings.append(_APPRAISAL_WITHHELD_WARNING)

    candidates = read_json(paths["candidates"])
    if not isinstance(candidates, dict) or not isinstance(candidates.get("features"), list):
        raise ReleaseAssetError("candidate layer is not a GeoJSON FeatureCollection")
    for feature in candidates["features"]:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        metrics = properties.get("metrics") if isinstance(properties, dict) else None
        if not isinstance(metrics, dict):
            continue
        for by_purpose in metrics.values():
            if not isinstance(by_purpose, dict):
                continue
            for metric in by_purpose.values():
                if isinstance(metric, dict):
                    metric["bcrP5"] = None
                    metric["bcrP50"] = None
                    metric["bcrP95"] = None
            appraisal = by_purpose.get("appraisal")
            if isinstance(appraisal, dict):
                appraisal.update(
                    {
                        "available": False,
                        "objectiveValue": None,
                        "objectiveUnit": "not available",
                        "additionalCycleUsers": None,
                        "annualBikeKmDelta": None,
                        "odLowStressShareDelta": None,
                        "meanRank": None,
                        "topKProbability": None,
                        "frontierProbability": None,
                    }
                )
                appraisal["warnings"] = [_APPRAISAL_WITHHELD_WARNING]

    candidate_bytes = (canonical_json(candidates) + "\n").encode("utf-8")
    for layer in manifest.get("layers", []):
        if isinstance(layer, dict) and layer.get("id") == "candidates":
            layer["sha256"] = sha256_bytes(candidate_bytes)
    manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
    payloads[paths["candidates"].name] = candidate_bytes
    payloads[paths["web_manifest"].name] = manifest_bytes
    return payloads, manifest, True


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    path = PurePosixPath(name)
    if path.is_absolute() or path.parts[0] != "data" or ".." in path.parts:
        raise ReleaseAssetError(f"unsafe release member name: {name}")
    info = tarfile.TarInfo(path.as_posix())
    info.size = size
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def package_web_release(*, run_dir: str | Path, output_path: str | Path) -> ReleaseAssetResult:
    """Create a deterministic ``tar.gz`` containing only a ``data/`` tree."""

    run = Path(run_dir).resolve()
    destination = Path(output_path).resolve()
    if destination.suffixes[-2:] != [".tar", ".gz"]:
        raise ReleaseAssetError("release asset must use a .tar.gz filename")
    run_id, run_manifest_path, paths, web_manifest = _release_inputs(run)
    payloads, release_manifest, appraisal_withheld = _withhold_unreviewed_appraisal(
        paths=paths, web_manifest=web_manifest
    )
    notice = _asset_notice(
        run_id=run_id,
        run_manifest_path=run_manifest_path,
        payloads=payloads,
        web_manifest=release_manifest,
        appraisal_withheld=appraisal_withheld,
    )
    members = [(f"data/{name}", payload) for name, payload in payloads.items()]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name, payload in sorted(members):
            with _payload_stream(payload) as stream:
                archive.addfile(_tar_info(name, _payload_size(payload)), stream)
        archive.addfile(_tar_info("data/ASSET_NOTICE.json", len(notice)), io.BytesIO(notice))
    expected = tuple(sorted([name for name, _ in members] + ["data/ASSET_NOTICE.json"]))
    try:
        with tarfile.open(destination, "r:gz") as archive:
            actual = tuple(sorted(member.name for member in archive.getmembers()))
            if actual != expected or any(not member.isfile() for member in archive.getmembers()):
                raise ReleaseAssetError("release archive member verification failed")
            notice_member = archive.extractfile("data/ASSET_NOTICE.json")
            if notice_member is None or sha256_bytes(notice_member.read()) != sha256_bytes(notice):
                raise ReleaseAssetError("release archive notice verification failed")
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseAssetError(f"could not verify release archive: {exc}") from exc
    return ReleaseAssetResult(
        path=destination,
        size=destination.stat().st_size,
        sha256=sha256_file(destination),
        run_id=run_id,
        files=expected,
    )


__all__ = ["ReleaseAssetError", "ReleaseAssetResult", "package_web_release"]
