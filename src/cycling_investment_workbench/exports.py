"""Deterministic, integrity-checked browser data exports."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from .config import ExportConfig
from .provenance import ArtifactDigest, canonical_json, portable_path, sha256_bytes
from .sources import SourceSpec

LAYER_IDS = ("cells", "network", "candidates", "programmes", "counters", "safety")
OPTIONAL_LAYER_IDS = ("existing", "intersections")
SCENARIO_IDS = (
    "baseline",
    "government_target",
    "go_dutch",
    "ebike",
    "commute_8pct",
)
PURPOSE_IDS = ("network", "equity", "school", "everyday", "transit", "appraisal")


class ExportError(ValueError):
    """Raised when a browser payload is incomplete or unsafe."""


@dataclass(frozen=True)
class WebExportResult:
    output_dir: Path
    manifest: ArtifactDigest
    layers: Mapping[str, ArtifactDigest]

    def to_dict(self, *, root: Path) -> dict[str, Any]:
        return {
            "output_dir": portable_path(self.output_dir, root=root),
            "manifest": self.manifest.to_dict(root=root),
            "layers": {
                layer_id: digest.to_dict(root=root)
                for layer_id, digest in sorted(self.layers.items())
            },
        }


def _mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExportError(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ExportError(f"{context} keys must be strings")
    return value


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _json_bytes(value: Any, *, pretty: bool) -> bytes:
    if pretty:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
    else:
        text = canonical_json(value)
    return (text + "\n").encode("utf-8")


def _artifact(path: Path, content: bytes) -> ArtifactDigest:
    return ArtifactDigest(path=path.resolve(), size=len(content), sha256=sha256_bytes(content))


def _validate_feature_collection(value: Any, *, layer_id: str) -> Mapping[str, Any]:
    collection = _mapping(value, context=f"layers.{layer_id}")
    if collection.get("type") != "FeatureCollection":
        raise ExportError(f"layers.{layer_id}.type must be FeatureCollection")
    features = collection.get("features")
    if not isinstance(features, list):
        raise ExportError(f"layers.{layer_id}.features must be an array")
    for index, raw_feature in enumerate(features):
        feature = _mapping(raw_feature, context=f"layers.{layer_id}.features[{index}]")
        if feature.get("type") != "Feature":
            raise ExportError(f"layers.{layer_id}.features[{index}].type must be Feature")
        _mapping(feature.get("geometry"), context=f"layers.{layer_id}.features[{index}].geometry")
        _mapping(
            feature.get("properties"),
            context=f"layers.{layer_id}.features[{index}].properties",
        )
    return collection


def _validate_manifest_base(value: Any) -> dict[str, Any]:
    manifest = dict(_mapping(value, context="manifest"))
    required = {
        "schemaVersion",
        "modelVersion",
        "runId",
        "configSha256",
        "generatedAtUtc",
        "title",
        "dataStatus",
        "dataStatusLabel",
        "defaultScenario",
        "defaultPurpose",
        "defaultBudgetNzd",
        "maxBudgetNzd",
        "scenarios",
        "purposes",
        "summaries",
        "portfolios",
        "validation",
        "capabilities",
        "limitations",
        "layers",
        "attribution",
        "methodologyUrl",
        "sourceDecisions",
    }
    missing = required - set(manifest)
    if missing:
        raise ExportError(f"manifest is missing: {', '.join(sorted(missing))}")
    if manifest["schemaVersion"] != "2.0.0":
        raise ExportError("manifest.schemaVersion must be 2.0.0")
    config_sha256 = manifest["configSha256"]
    if not isinstance(config_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None:
        raise ExportError("manifest.configSha256 must be 64 lowercase hexadecimal characters")
    if manifest["defaultScenario"] not in SCENARIO_IDS:
        raise ExportError("manifest.defaultScenario is not supported by the browser client")
    if manifest["defaultPurpose"] not in PURPOSE_IDS:
        raise ExportError("manifest.defaultPurpose is not supported by the browser client")
    if manifest["dataStatus"] not in {
        "synthetic_demo",
        "research_snapshot",
        "validated_release",
    }:
        raise ExportError("manifest.dataStatus is invalid")
    scenario_ids = (
        [item.get("id") for item in manifest["scenarios"] if isinstance(item, Mapping)]
        if isinstance(manifest["scenarios"], list)
        else []
    )
    if tuple(scenario_ids) != SCENARIO_IDS:
        raise ExportError("manifest.scenarios must contain the browser scenarios in stable order")
    purpose_ids = (
        [item.get("id") for item in manifest["purposes"] if isinstance(item, Mapping)]
        if isinstance(manifest["purposes"], list)
        else []
    )
    if tuple(purpose_ids) != PURPOSE_IDS:
        raise ExportError("manifest.purposes must contain the planning purposes in stable order")
    _validate_validation(manifest["validation"])
    capabilities = _mapping(manifest["capabilities"], context="manifest.capabilities")
    if set(capabilities) != {"equity", "appraisal", "sketchEvaluation"}:
        raise ExportError("manifest.capabilities fields are incomplete or unknown")
    if capabilities["equity"] not in {"available", "rights_blocked", "unavailable"}:
        raise ExportError("manifest.capabilities.equity is invalid")
    if capabilities["appraisal"] not in {"reviewed", "research_only", "withheld"}:
        raise ExportError("manifest.capabilities.appraisal is invalid")
    if capabilities["sketchEvaluation"] not in {
        "same_pipeline",
        "requires_pipeline_evaluation",
        "unavailable",
    }:
        raise ExportError("manifest.capabilities.sketchEvaluation is invalid")
    limitations = manifest["limitations"]
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) or not item.strip() for item in limitations
    ):
        raise ExportError("manifest.limitations must be a string array")
    return manifest


def _number(value: Any, *, context: str, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExportError(f"{context} must be a finite number")
    converted = float(value)
    if not isfinite(converted) or converted < 0 or (maximum is not None and converted > maximum):
        suffix = f" in 0..{maximum:g}" if maximum is not None else " greater than or equal to 0"
        raise ExportError(f"{context} must be{suffix}")
    return converted


def _validate_validation(value: Any) -> None:
    validation = _mapping(value, context="manifest.validation")
    required = {
        "periodLabel",
        "counterCount",
        "matchedCount",
        "coverage",
        "purposeAlignment",
        "status",
    }
    if set(validation) != required:
        raise ExportError("manifest.validation fields are incomplete or unknown")
    for field in ("periodLabel", "purposeAlignment", "status"):
        if not isinstance(validation[field], str) or not validation[field].strip():
            raise ExportError(f"manifest.validation.{field} must be a non-empty string")
    for field in ("counterCount", "matchedCount"):
        if (
            isinstance(validation[field], bool)
            or not isinstance(validation[field], int)
            or validation[field] < 0
        ):
            raise ExportError(f"manifest.validation.{field} must be a non-negative integer")
    _number(validation["coverage"], context="manifest.validation.coverage", maximum=1)
    if validation["matchedCount"] > validation["counterCount"]:
        raise ExportError("manifest.validation.matchedCount cannot exceed counterCount")


def _validate_public_rights(
    manifest: Mapping[str, Any],
    descriptors: Mapping[str, Mapping[str, Any]],
    source_specs: Sequence[SourceSpec],
) -> None:
    raw_decisions = manifest.get("sourceDecisions")
    if not isinstance(raw_decisions, list):
        raise ExportError("manifest.sourceDecisions must be an array")
    decisions: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_decisions):
        decision = _mapping(raw, context=f"manifest.sourceDecisions[{index}]")
        source_id = decision.get("sourceId")
        if not isinstance(source_id, str) or not source_id:
            raise ExportError(f"manifest.sourceDecisions[{index}].sourceId is invalid")
        if source_id in decisions:
            raise ExportError(f"manifest contains duplicate source decision: {source_id}")
        if decision.get("redistribution") not in {"permitted", "unknown", "restricted"}:
            raise ExportError(f"source decision has invalid redistribution: {source_id}")
        if decision.get("decision") not in {"include", "exclude"}:
            raise ExportError(f"source decision has invalid decision: {source_id}")
        decisions[source_id] = decision

    configured = {spec.id: spec for spec in source_specs}
    if manifest.get("dataStatus") != "synthetic_demo":
        missing = set(configured).difference(decisions)
        if missing:
            raise ExportError(
                "public export has no rights decision for configured sources: "
                + ", ".join(sorted(missing))
            )
    for source_id, decision in decisions.items():
        spec = configured.get(source_id)
        if spec is not None and decision["redistribution"] != spec.redistribution:
            raise ExportError(
                f"rights decision disagrees with configured redistribution: {source_id}"
            )
        if spec is None and manifest.get("dataStatus") != "synthetic_demo":
            raise ExportError(f"rights decision references an unregistered source: {source_id}")

    included_by_layer: dict[str, set[str]] = {}
    for layer_id, descriptor in descriptors.items():
        source_ids = descriptor.get("sourceIds")
        if not isinstance(source_ids, list) or any(
            not isinstance(source_id, str) or not source_id for source_id in source_ids
        ):
            raise ExportError(f"manifest layer {layer_id}.sourceIds must be a string array")
        included_by_layer[layer_id] = set(source_ids)
        for source_id in source_ids:
            decision = decisions.get(source_id)
            if decision is None:
                raise ExportError(
                    f"layer {layer_id} references source without a rights decision: {source_id}"
                )
            redistribution = decision["redistribution"]
            action = decision["decision"]
            if action == "exclude":
                raise ExportError(f"excluded source appears in layer {layer_id}: {source_id}")
            if redistribution != "permitted" or action != "include":
                raise ExportError(
                    f"public layer {layer_id} may include only a source with "
                    f"redistribution=permitted and decision=include: {source_id}"
                )

    for source_id, decision in decisions.items():
        if (
            decision["redistribution"] in {"unknown", "restricted"}
            and decision["decision"] != "exclude"
        ):
            raise ExportError(
                f"{decision['redistribution']} source must be excluded from public export: "
                f"{source_id}"
            )

    for source_id, decision in decisions.items():
        appears = any(source_id in source_ids for source_ids in included_by_layer.values())
        if decision["decision"] == "exclude" and appears:
            raise ExportError(f"excluded source appears in public layers: {source_id}")
        if decision["decision"] != "exclude" and not appears:
            raise ExportError(f"included source is not attributed to a layer: {source_id}")


def export_web_payload(
    payload: Mapping[str, Any],
    *,
    export_config: ExportConfig,
    output_dir: str | Path,
    source_specs: Sequence[SourceSpec] = (),
) -> WebExportResult:
    """Write a browser manifest and exact-byte verified GeoJSON layers."""

    root_payload = _mapping(payload, context="payload")
    required_payload_keys = {"manifest", "layers"}
    allowed_payload_keys = required_payload_keys | {"uncertainty"}
    if (
        not required_payload_keys <= set(root_payload)
        or not set(root_payload) <= allowed_payload_keys
    ):
        missing = required_payload_keys - set(root_payload)
        unknown = set(root_payload) - allowed_payload_keys
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown {', '.join(sorted(unknown))}")
        raise ExportError(
            "payload must contain manifest and layers, with optional uncertainty metadata: "
            + "; ".join(details)
        )
    if "uncertainty" in root_payload:
        _mapping(root_payload["uncertainty"], context="uncertainty")

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    raw_layers = _mapping(root_payload["layers"], context="layers")
    if not set(LAYER_IDS) <= set(raw_layers) or set(raw_layers) - set(
        LAYER_IDS + OPTIONAL_LAYER_IDS
    ):
        raise ExportError("layers must contain the core layers and only recognised optional layers")
    layer_ids = LAYER_IDS + tuple(layer for layer in OPTIONAL_LAYER_IDS if layer in raw_layers)

    manifest = _validate_manifest_base(root_payload["manifest"])
    descriptors = manifest["layers"]
    if not isinstance(descriptors, list):
        raise ExportError("manifest.layers must be an array")
    descriptor_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_descriptor in enumerate(descriptors):
        descriptor = dict(_mapping(raw_descriptor, context=f"manifest.layers[{index}]"))
        layer_id = descriptor.get("id")
        if layer_id not in layer_ids:
            raise ExportError(f"manifest.layers[{index}].id is invalid")
        if layer_id in descriptor_by_id:
            raise ExportError(f"manifest contains duplicate layer: {layer_id}")
        for field in ("label", "defaultVisible", "optional", "licence", "sourceIds"):
            if field not in descriptor:
                raise ExportError(f"manifest layer {layer_id} is missing {field}")
        descriptor_by_id[layer_id] = descriptor
    if set(descriptor_by_id) != set(layer_ids):
        raise ExportError("manifest.layers must describe every exported layer exactly once")
    _validate_public_rights(manifest, descriptor_by_id, source_specs)

    layer_digests: dict[str, ArtifactDigest] = {}
    final_descriptors: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        collection = _validate_feature_collection(raw_layers[layer_id], layer_id=layer_id)
        content = _json_bytes(collection, pretty=False)
        filename = export_config.layer_filenames.get(layer_id, f"{layer_id}.geojson")
        path = destination / filename
        _write_bytes_atomic(path, content)
        digest = _artifact(path, content)
        layer_digests[layer_id] = digest
        descriptor = descriptor_by_id[layer_id]
        descriptor["url"] = f"./data/{filename}"
        descriptor["sha256"] = digest.sha256
        final_descriptors.append(descriptor)

    manifest["layers"] = final_descriptors
    manifest_content = _json_bytes(manifest, pretty=True)
    manifest_path = destination / export_config.manifest_filename
    _write_bytes_atomic(manifest_path, manifest_content)
    manifest_digest = _artifact(manifest_path, manifest_content)
    return WebExportResult(destination, manifest_digest, layer_digests)


def load_web_payload(path: str | Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"could not load web payload from {path}: {exc}") from exc
    return _mapping(raw, context="payload")


def verify_web_export(output_dir: str | Path, *, export_config: ExportConfig) -> tuple[str, ...]:
    """Return integrity problems found in an existing browser export."""

    destination = Path(output_dir).resolve()
    manifest_path = destination / export_config.manifest_filename
    try:
        manifest = _validate_manifest_base(json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ExportError) as exc:
        return (str(exc),)
    problems: list[str] = []
    descriptors = manifest.get("layers")
    if not isinstance(descriptors, list):
        return ("manifest.layers must be an array",)
    by_id = {
        descriptor.get("id"): descriptor
        for descriptor in descriptors
        if isinstance(descriptor, Mapping)
    }
    if set(by_id) - set(LAYER_IDS + OPTIONAL_LAYER_IDS) or len(by_id) != len(descriptors):
        problems.append("unknown or duplicate layer descriptor")
    for layer_id in LAYER_IDS + tuple(layer for layer in OPTIONAL_LAYER_IDS if layer in by_id):
        descriptor = by_id.get(layer_id)
        if not isinstance(descriptor, Mapping):
            problems.append(f"layer descriptor is missing: {layer_id}")
            continue
        filename = export_config.layer_filenames.get(layer_id, f"{layer_id}.geojson")
        expected_url = f"./data/{filename}"
        if descriptor.get("url") != expected_url:
            problems.append(f"layer URL is incorrect: {layer_id}")
        layer_path = destination / filename
        if not layer_path.is_file():
            problems.append(f"layer file is missing: {layer_id}")
            continue
        actual = sha256_bytes(layer_path.read_bytes())
        if actual != descriptor.get("sha256"):
            problems.append(f"layer integrity check failed: {layer_id}")
    return tuple(problems)
