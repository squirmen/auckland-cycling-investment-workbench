"""Content-addressed and resumable project execution."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import __version__
from .config import PipelineConfig, PipelineStageConfig, ProjectConfig, load_config
from .provenance import (
    ArtifactDigest,
    ProvenanceError,
    canonical_json,
    content_hash,
    deterministic_run_id,
    hash_path,
    portable_path,
    read_json,
    runtime_provenance,
    sha256_file,
    utc_now,
    write_json_atomic,
)
from .sources import SourceRecord, SourceRegistry

_OUTPUT_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
RUN_MANIFEST_SCHEMA_VERSION = 2
STAGE_FINGERPRINT_SCHEMA_VERSION = 2

_STAGE_PARAMETER_SCOPES: Mapping[str, tuple[str, ...]] = {
    "source-inventory": (),
    "prepare-demand": ("demand", "validation.source_regression_minimum_records"),
    "build-topology": ("network", "candidates.facility_matching"),
    "assign-routes": ("network", "routing", "demand_response"),
    "generate-candidates": ("candidates",),
    "evaluate-portfolios": (
        "network",
        "routing",
        "demand_response",
        "portfolios",
        "appraisal",
    ),
    "appraisal-uncertainty-validation": (
        "appraisal",
        "uncertainty",
        "validation",
        "candidates",
    ),
    "export-outputs": ("candidates", "portfolios"),
    "export-web": (),
}

_STAGE_SOURCE_SCOPES: Mapping[str, frozenset[str] | None] = {
    "source-inventory": None,
    "prepare-demand": frozenset(
        {
            "stats_nz_journey_to_work",
            "stats_nz_sa2_transport_margins",
            "stats_nz_sa1_geography",
            "stats_nz_sa2_geography",
            "stats_nz_auckland_boundary",
            "educationcounts_schools_auckland",
            "stats_nz_business_demography_sa2_2024",
            "major_transit_nodes",
        }
    ),
    "build-topology": frozenset(
        {
            "geofabrik_new_zealand_osm",
            "auckland_transport_cycle_network",
            "linz_auckland_dem",
            "linz_auckland_dem_manifest",
        }
    ),
    "assign-routes": frozenset(),
    "generate-candidates": frozenset(),
    "evaluate-portfolios": frozenset(),
    "appraisal-uncertainty-validation": frozenset(
        {"cycle_counter_locations", "cycle_counter_observations"}
    ),
    "export-outputs": None,
    "export-web": None,
}


class PipelineError(RuntimeError):
    """Base class for pipeline execution failures."""


class MissingSourcesError(PipelineError):
    """Raised when required registered inputs are unavailable."""


class StageExecutionError(PipelineError):
    """Raised when one stage cannot produce valid outputs."""


class ProductionBlocker(StageExecutionError):
    """A machine-readable publication blocker at an exact production stage."""

    def __init__(
        self,
        *,
        stage: str,
        code: str,
        message: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self.stage = stage
        self.code = code
        self.message = message
        self.evidence = dict(evidence or {})
        super().__init__(
            canonical_json(
                {
                    "type": "production_blocker",
                    "stage": stage,
                    "code": code,
                    "message": message,
                    "evidence": self.evidence,
                }
            )
        )


RawStageOutput = Mapping[str, str | Path] | Sequence[str | Path] | str | Path | None


@dataclass(frozen=True)
class StageResult:
    """Declared files and audit metrics returned by one stage."""

    outputs: RawStageOutput
    metrics: Mapping[str, Any]


StageOutput = RawStageOutput | StageResult
StageHandler = Callable[["StageContext"], StageOutput]


@dataclass(frozen=True)
class StageContract:
    """Required output and audit fields for a standard pipeline stage."""

    outputs: tuple[str, ...]
    metrics: tuple[str, ...]


STANDARD_STAGE_CONTRACTS: Mapping[str, StageContract] = {
    "source-inventory": StageContract(("source_inventory",), ("row_counts",)),
    "prepare-demand": StageContract(("demand",), ("row_counts",)),
    "build-topology": StageContract(("topology",), ("row_counts",)),
    "assign-routes": StageContract(
        ("routes",), ("row_counts", "routing_failures", "routing_failure_share")
    ),
    "generate-candidates": StageContract(("candidates",), ("row_counts",)),
    "evaluate-portfolios": StageContract(("portfolios",), ("row_counts",)),
    "appraisal-uncertainty-validation": StageContract(
        ("evidence",), ("row_counts", "sample_count", "validation_coverage")
    ),
    "export-outputs": StageContract(("web_payload",), ("row_counts",)),
    "export-web": StageContract(
        ("web_manifest", "cells", "network", "candidates", "programmes", "counters"),
        ("row_counts",),
    ),
}


@dataclass(frozen=True)
class StageContext:
    """Portable inputs supplied to a stage handler."""

    config: ProjectConfig
    run_id: str
    run_dir: Path
    stage: PipelineStageConfig
    sources: Mapping[str, SourceRecord]
    dependencies: Mapping[str, Mapping[str, ArtifactDigest]]

    @property
    def artifact_dir(self) -> Path:
        path = (self.run_dir / "artifacts" / self.stage.name).resolve()
        if not path.is_relative_to(self.run_dir.resolve()):
            raise PipelineError(f"unsafe artifact directory for stage {self.stage.name}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def output_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise PipelineError("stage output filenames must be basenames")
        return self.artifact_dir / filename


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    manifest_path: Path
    status: str
    resumed_stages: tuple[str, ...]
    executed_stages: tuple[str, ...]

    def to_dict(self, *, root: Path) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": portable_path(self.run_dir, root=root),
            "manifest": portable_path(self.manifest_path, root=root),
            "status": self.status,
            "resumed_stages": list(self.resumed_stages),
            "executed_stages": list(self.executed_stages),
        }


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class StageRegistry:
    """Explicit registry for auditable stage implementations."""

    def __init__(self) -> None:
        self._handlers: dict[str, StageHandler] = {}

    def register(self, name: str, handler: StageHandler, *, replace: bool = False) -> None:
        if not _OUTPUT_NAME.fullmatch(name):
            raise PipelineError(f"invalid stage name: {name}")
        if name in self._handlers and not replace:
            raise PipelineError(f"stage is already registered: {name}")
        self._handlers[name] = handler

    def handler_for(self, name: str) -> StageHandler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise PipelineError(f"no implementation is registered for stage: {name}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


def _source_inventory_stage(context: StageContext) -> StageResult:
    destination = context.output_path("source-inventory.json")
    payload = {
        "schema_version": 1,
        "run_id": context.run_id,
        "sources": {
            source_id: record.to_dict(
                root=context.config.root_dir, data_root=context.config.data_dir
            )
            for source_id, record in sorted(context.sources.items())
        },
    }
    write_json_atomic(destination, payload)
    available = sum(record.usable for record in context.sources.values())
    return StageResult(
        {"source_inventory": destination},
        {
            "row_counts": {
                "registered_sources": len(context.sources),
                "available_sources": available,
                "unavailable_sources": len(context.sources) - available,
            }
        },
    )


def _contract_only_stage(context: StageContext) -> StageOutput:
    contract = STANDARD_STAGE_CONTRACTS[context.stage.name]
    profile = context.stage.options.get("profile", "unspecified")
    raise StageExecutionError(
        f"stage {context.stage.name} has no production adapter for profile {profile!r}; "
        f"the adapter must emit {', '.join(contract.outputs)} and audit metrics "
        f"{', '.join(contract.metrics)}"
    )


def default_stage_registry() -> StageRegistry:
    registry = StageRegistry()
    registry.register("source-inventory", _source_inventory_stage)
    for stage_name in STANDARD_STAGE_CONTRACTS:
        if stage_name != "source-inventory":
            registry.register(stage_name, _contract_only_stage)
    from .production import production_stage_handlers

    for stage_name, handler in production_stage_handlers().items():
        registry.register(stage_name, handler, replace=True)
    return registry


def _demo_inputs() -> tuple[Mapping[str, Any], Mapping[str, Any], Any]:
    from .demo import miniature_city_inputs, run_miniature_city, web_export_payload

    return web_export_payload(), run_miniature_city(), miniature_city_inputs()


def _write_stage_json(
    context: StageContext,
    filename: str,
    value: Any,
    *,
    output_name: str,
    metrics: Mapping[str, Any],
) -> StageResult:
    path = context.output_path(filename)
    write_json_atomic(path, value)
    return StageResult({output_name: path}, metrics)


def _demo_prepare_demand(context: StageContext) -> StageResult:
    payload, analysis, city = _demo_inputs()
    manifest = payload["manifest"]
    result = {
        "schema_version": 1,
        "scenarios": manifest["scenarios"],
        "summaries": manifest["summaries"],
        "demand": analysis["demand"],
    }
    od_count = sum(len(flows) for flows in city.od_flows_by_scenario.values())
    return _write_stage_json(
        context,
        "demand.json",
        result,
        output_name="demand",
        metrics={
            "row_counts": {
                "scenarios": len(city.od_flows_by_scenario),
                "origin_destination_flows": od_count,
            }
        },
    )


def _demo_build_topology(context: StageContext) -> StageResult:
    payload, analysis, _ = _demo_inputs()
    topology = payload["layers"]["network"]
    return _write_stage_json(
        context,
        "topology.geojson",
        topology,
        output_name="topology",
        metrics={
            "row_counts": {
                "nodes": analysis["network"]["nodes"],
                "directed_edges": len(topology["features"]),
                "components": analysis["network"]["components"],
            }
        },
    )


def _demo_assign_routes(context: StageContext) -> StageResult:
    from .demo import PURPOSE_IDS, SCENARIO_IDS, _purpose_od_flows
    from .routing import assign_demand

    _, analysis, city = _demo_inputs()
    assignments: dict[str, dict[str, Any]] = {}
    total_od = 0
    total_paths = 0
    total_failures = 0
    failure_reasons: dict[str, int] = {}
    for scenario_id in SCENARIO_IDS:
        by_purpose: dict[str, Any] = {}
        for purpose_id in PURPOSE_IDS:
            ods = _purpose_od_flows(city, scenario_id, purpose_id)
            assignment = assign_demand(
                city.topology,
                ods,
                k=5,
                max_cost_ratio=1.5,
                max_detour_ratio=1.5,
            )
            total_od += len(assignment.od_ledger)
            total_paths += len(assignment.path_ledger)
            total_failures += len(assignment.unassigned_od_ids)
            for record in assignment.od_ledger:
                if record.reason is not None:
                    failure_reasons[record.reason] = failure_reasons.get(record.reason, 0) + 1
            by_purpose[purpose_id] = {
                "od_ledger": [record.to_dict() for record in assignment.od_ledger],
                "path_ledger": [record.to_dict() for record in assignment.path_ledger],
                "edge_flow": dict(sorted(assignment.edge_flow.items())),
            }
        assignments[scenario_id] = by_purpose
    assigned = total_od - total_failures
    failure_share = total_failures / total_od if total_od else 0.0
    result = {
        "schema_version": 1,
        "routing": {
            "scenarios": len(SCENARIO_IDS),
            "purposes": len(PURPOSE_IDS),
            "origin_destination_flows": total_od,
            "assigned_origin_destination_flows": assigned,
            "routing_failures": total_failures,
            "routing_failure_share": failure_share,
            "failure_reasons": dict(sorted(failure_reasons.items())),
            "path_records": total_paths,
            "plausible_paths": 5,
            "maximum_cost_ratio": 1.5,
            "maximum_detour_ratio": 1.5,
        },
        "demand": analysis["demand"],
        "assignments": assignments,
    }
    return _write_stage_json(
        context,
        "routes.json",
        result,
        output_name="routes",
        metrics={
            "row_counts": {
                "origin_destination_flows": total_od,
                "assigned_origin_destination_flows": assigned,
                "path_records": total_paths,
            },
            "routing_failures": total_failures,
            "routing_failure_share": failure_share,
        },
    )


def _demo_generate_candidates(context: StageContext) -> StageResult:
    payload, _, city = _demo_inputs()
    candidates = payload["layers"]["candidates"]
    return _write_stage_json(
        context,
        "candidates.geojson",
        candidates,
        output_name="candidates",
        metrics={
            "row_counts": {
                "candidate_corridors": len(city.candidates),
                "candidate_edges": sum(len(candidate.edge_ids) for candidate in city.candidates),
            }
        },
    )


def _demo_evaluate_portfolios(context: StageContext) -> StageResult:
    payload, _, _ = _demo_inputs()
    manifest = payload["manifest"]
    portfolios = {
        "schema_version": 1,
        "summaries": manifest["summaries"],
        "portfolios": manifest["portfolios"],
    }
    portfolio_steps = sum(
        len(steps)
        for by_purpose in manifest["portfolios"].values()
        for steps in by_purpose.values()
    )
    return _write_stage_json(
        context,
        "portfolios.json",
        portfolios,
        output_name="portfolios",
        metrics={"row_counts": {"portfolio_steps": portfolio_steps}},
    )


def _demo_evidence(context: StageContext) -> StageResult:
    _, analysis, _ = _demo_inputs()
    return _write_stage_json(
        context,
        "evidence.json",
        analysis,
        output_name="evidence",
        metrics={
            "row_counts": {
                "counter_matches": analysis["validation"]["matched"],
                "candidates": len(analysis["sequence"]),
            },
            "sample_count": analysis["uncertainty"]["draws"],
            "validation_coverage": analysis["validation"]["coverage"],
        },
    )


def _demo_export_outputs(context: StageContext) -> StageResult:
    from .demo import web_export_payload

    payload = web_export_payload(
        config_sha256=content_hash(context.config.to_dict()), run_id=context.run_id
    )
    feature_count = sum(len(layer["features"]) for layer in payload["layers"].values())
    return _write_stage_json(
        context,
        "web-payload.json",
        payload,
        output_name="web_payload",
        metrics={"row_counts": {"features": feature_count, "layers": len(payload["layers"])}},
    )


def _demo_export_web(context: StageContext) -> StageResult:
    from .exports import export_web_payload, load_web_payload

    payload_digest = context.dependencies["export-outputs"]["web_payload"]
    payload = load_web_payload(payload_digest.path)
    result = export_web_payload(
        payload,
        export_config=context.config.export,
        output_dir=context.artifact_dir / "data",
        source_specs=context.config.sources,
    )
    outputs: dict[str, Path] = {"web_manifest": result.manifest.path}
    outputs.update({layer_id: digest.path for layer_id, digest in result.layers.items()})
    return StageResult(
        outputs,
        {
            "row_counts": {
                "layers": len(result.layers),
                "bytes": result.manifest.size + sum(item.size for item in result.layers.values()),
            }
        },
    )


def demo_stage_registry() -> StageRegistry:
    """Return the complete stage chain for the deterministic miniature city."""

    registry = default_stage_registry()
    handlers: Mapping[str, StageHandler] = {
        "prepare-demand": _demo_prepare_demand,
        "build-topology": _demo_build_topology,
        "assign-routes": _demo_assign_routes,
        "generate-candidates": _demo_generate_candidates,
        "evaluate-portfolios": _demo_evaluate_portfolios,
        "appraisal-uncertainty-validation": _demo_evidence,
        "export-outputs": _demo_export_outputs,
        "export-web": _demo_export_web,
    }
    for name, handler in handlers.items():
        registry.register(name, handler, replace=True)
    return registry


def demo_project_config(config: ProjectConfig) -> ProjectConfig:
    """Derive an input-free configuration that still executes the production DAG."""

    stages = tuple(
        replace(stage, options={"profile": "miniature-city-v1"}) for stage in config.pipeline.stages
    )
    return replace(
        config,
        sources=(),
        pipeline=PipelineConfig(resume=config.pipeline.resume, stages=stages),
        parameters={"profile": "synthetic_demo", "seed": 2026},
    )


def _topological_stages(
    stages: Sequence[PipelineStageConfig], selected: Iterable[str] | None
) -> tuple[PipelineStageConfig, ...]:
    by_name = {stage.name: stage for stage in stages}
    if selected is None:
        requested = set(by_name)
    else:
        requested = set(selected)
        unknown = requested - set(by_name)
        if unknown:
            raise PipelineError(f"unknown selected stages: {', '.join(sorted(unknown))}")

    included: set[str] = set()

    def include(name: str) -> None:
        if name in included:
            return
        for dependency in by_name[name].depends_on:
            include(dependency)
        included.add(name)

    for name in requested:
        include(name)

    ordered: list[PipelineStageConfig] = []
    emitted: set[str] = set()

    def emit(name: str) -> None:
        if name in emitted:
            return
        for dependency in by_name[name].depends_on:
            emit(dependency)
        emitted.add(name)
        if name in included:
            ordered.append(by_name[name])

    for stage in stages:
        emit(stage.name)
    return tuple(ordered)


def _source_manifest(
    records: Mapping[str, SourceRecord], *, root: Path, data_root: Path
) -> dict[str, dict[str, Any]]:
    return {
        source_id: record.to_dict(root=root, data_root=data_root)
        for source_id, record in sorted(records.items())
    }


def _run_identity_sources(records: Mapping[str, SourceRecord]) -> dict[str, dict[str, Any]]:
    return {
        source_id: {
            "required": record.required,
            "status": record.status,
            "size": record.size,
            "sha256": record.sha256,
            "expected_sha256": record.expected_sha256,
        }
        for source_id, record in sorted(records.items())
    }


def _collect_seeds(value: Any, *, prefix: str = "parameters") -> dict[str, int]:
    seeds: dict[str, int] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            if key == "seed" and isinstance(item, int) and not isinstance(item, bool):
                seeds[path] = item
            else:
                seeds.update(_collect_seeds(item, prefix=path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            seeds.update(_collect_seeds(item, prefix=f"{prefix}[{index}]"))
    return seeds


def _initial_manifest(
    config: ProjectConfig,
    *,
    run_id: str,
    config_digest: str,
    implementation_digest: str,
    config_snapshot: Path,
    source_records: Mapping[str, SourceRecord],
) -> dict[str, Any]:
    timestamp = utc_now()
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": config.project.id,
        "status": "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "config": {
            "source_path": portable_path(config.source_path, root=config.root_dir),
            "snapshot_path": portable_path(config_snapshot, root=config.root_dir),
            "sha256": config_digest,
        },
        "model": {
            "package_version": __version__,
            "methodology_version": __version__,
            "implementation_sha256": implementation_digest,
            "configuration_schema_version": config.schema_version,
            "run_manifest_schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        },
        "seeds": _collect_seeds(config.parameters),
        "sources": _source_manifest(
            source_records, root=config.root_dir, data_root=config.data_dir
        ),
        "runtime": runtime_provenance(
            packages=(
                "auckland-cycling-investment-workbench",
                "PyYAML",
                "geopandas",
                "h3",
                "networkx",
                "numpy",
                "osmnx",
                "pandas",
                "pyarrow",
                "r5py",
                "rasterio",
                "scipy",
                "shapely",
            )
        ),
        "stages": {},
    }


def _load_resumable_manifest(path: Path, *, run_id: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise PipelineError(f"existing manifest does not match run id {run_id}")
    if not isinstance(manifest.get("stages"), dict):
        raise PipelineError("existing manifest has no valid stages mapping")
    return manifest


def _dependency_outputs(
    stage: PipelineStageConfig,
    output_digests: Mapping[str, Mapping[str, ArtifactDigest]],
) -> dict[str, Mapping[str, ArtifactDigest]]:
    missing = [name for name in stage.depends_on if name not in output_digests]
    if missing:
        raise PipelineError(
            f"stage {stage.name} is missing dependency outputs: {', '.join(sorted(missing))}"
        )
    return {name: output_digests[name] for name in stage.depends_on}


def _parameter_scope(config: ProjectConfig, stage_name: str) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for path in _STAGE_PARAMETER_SCOPES.get(stage_name, tuple(sorted(config.parameters))):
        value: Any = config.parameters
        for component in path.split("."):
            if not isinstance(value, Mapping) or component not in value:
                value = None
                break
            value = value[component]
        selected[path] = value
    return selected


def _source_scope(
    records: Mapping[str, SourceRecord], stage_name: str
) -> dict[str, dict[str, Any]]:
    selected_ids = _STAGE_SOURCE_SCOPES.get(stage_name)
    selected = (
        records
        if selected_ids is None
        else {
            source_id: records[source_id]
            for source_id in sorted(selected_ids)
            if source_id in records
        }
    )
    return _run_identity_sources(selected)


def _stage_fingerprint(
    stage: PipelineStageConfig,
    *,
    config: ProjectConfig,
    sources: Mapping[str, SourceRecord],
    dependencies: Mapping[str, Mapping[str, ArtifactDigest]],
) -> str:
    dependency_payload = {
        stage_name: {
            output_name: {"size": digest.size, "sha256": digest.sha256}
            for output_name, digest in sorted(outputs.items())
        }
        for stage_name, outputs in sorted(dependencies.items())
    }
    return content_hash(
        {
            "fingerprint_schema_version": STAGE_FINGERPRINT_SCHEMA_VERSION,
            "name": stage.name,
            "version": stage.version,
            "package_version": __version__,
            "options": stage.options,
            "project": config.project.to_dict(),
            "parameters": _parameter_scope(config, stage.name),
            "export": (
                config.export.to_dict() if stage.name in {"export-outputs", "export-web"} else None
            ),
            "source_specs": {
                source.id: source.to_dict()
                for source in config.sources
                if (
                    _STAGE_SOURCE_SCOPES.get(stage.name) is None
                    or source.id in _STAGE_SOURCE_SCOPES.get(stage.name, frozenset())
                )
            },
            "sources": _source_scope(sources, stage.name),
            "dependencies": dependency_payload,
        }
    )


def _package_implementation_digest() -> str:
    """Hash version-controlled Python implementation sources for cache safety."""

    package_root = Path(__file__).resolve().parent
    entries = [
        {
            "path": path.relative_to(package_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(package_root.rglob("*.py"))
        if path.is_file() and not path.is_symlink()
    ]
    if not entries:
        raise PipelineError("package implementation source tree is empty")
    return content_hash(entries)


def _manifest_output_digests(
    record: Mapping[str, Any], *, run_dir: Path
) -> dict[str, ArtifactDigest] | None:
    if record.get("status") not in {"succeeded", "skipped", "cached"}:
        return None
    outputs = record.get("outputs")
    if not isinstance(outputs, Mapping):
        return None
    verified: dict[str, ArtifactDigest] = {}
    for name, raw in outputs.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            return None
        relative = raw.get("path")
        expected_size = raw.get("size")
        expected_hash = raw.get("sha256")
        if not isinstance(relative, str):
            return None
        path = (run_dir / relative).resolve()
        if not path.is_relative_to(run_dir.resolve()) or not path.exists():
            return None
        actual = hash_path(path)
        if actual.size != expected_size or actual.sha256 != expected_hash:
            return None
        verified[name] = actual
    return verified


def _normalise_outputs(output: RawStageOutput, *, context: StageContext) -> dict[str, Path]:
    if output is None:
        items: list[tuple[str, str | Path]] = []
    elif isinstance(output, Mapping):
        items = list(output.items())
    elif isinstance(output, str | Path):
        items = [(Path(output).stem, output)]
    else:
        items = [(Path(path).stem, path) for path in output]

    normalised: dict[str, Path] = {}
    for name, raw_path in items:
        if not isinstance(name, str) or not _OUTPUT_NAME.fullmatch(name):
            raise StageExecutionError(
                f"stage {context.stage.name} returned invalid output name: {name}"
            )
        path = Path(raw_path).resolve()
        if not path.is_relative_to(context.run_dir.resolve()):
            raise StageExecutionError(
                f"stage {context.stage.name} returned output outside its run directory: {path}"
            )
        if not path.exists():
            raise StageExecutionError(
                f"stage {context.stage.name} declared a missing output: {path}"
            )
        if name in normalised:
            raise StageExecutionError(
                f"stage {context.stage.name} returned duplicate output: {name}"
            )
        normalised[name] = path
    return normalised


def _coerce_stage_result(output: StageOutput) -> StageResult:
    if isinstance(output, StageResult):
        metrics = dict(output.metrics)
        content_hash(metrics)
        return StageResult(output.outputs, metrics)
    return StageResult(output, {})


def _validate_stage_contract(
    stage_name: str, *, outputs: Mapping[str, Path], metrics: Mapping[str, Any]
) -> None:
    contract = STANDARD_STAGE_CONTRACTS.get(stage_name)
    if contract is None:
        return
    missing_outputs = set(contract.outputs) - set(outputs)
    extra_outputs = set(outputs) - set(contract.outputs)
    if missing_outputs or extra_outputs:
        details: list[str] = []
        if missing_outputs:
            details.append("missing outputs " + ", ".join(sorted(missing_outputs)))
        if extra_outputs:
            details.append("unexpected outputs " + ", ".join(sorted(extra_outputs)))
        raise StageExecutionError(f"stage {stage_name} violates its contract: {'; '.join(details)}")
    missing_metrics = set(contract.metrics) - set(metrics)
    if missing_metrics:
        raise StageExecutionError(
            f"stage {stage_name} is missing audit metrics: {', '.join(sorted(missing_metrics))}"
        )


def _output_manifest(
    outputs: Mapping[str, ArtifactDigest], *, run_dir: Path
) -> dict[str, dict[str, Any]]:
    return {name: digest.to_dict(root=run_dir) for name, digest in sorted(outputs.items())}


def _link_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def _copy_cached_artifact(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise PipelineError(f"stage cache does not accept symlink artifacts: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, copy_function=_link_or_copy)
    else:
        _link_or_copy(str(source), str(destination))


def _cache_directory(config: ProjectConfig, stage_name: str, fingerprint: str) -> Path:
    root = (config.cache_dir / f"stage-cache-v{STAGE_FINGERPRINT_SCHEMA_VERSION}").resolve()
    if not root.is_relative_to(config.cache_dir.resolve()):
        raise PipelineError("resolved stage cache escapes the configured cache directory")
    return root / stage_name / fingerprint


def _write_stage_cache(
    context: StageContext,
    *,
    fingerprint: str,
    outputs: Mapping[str, Path],
    digests: Mapping[str, ArtifactDigest],
    metrics: Mapping[str, Any],
) -> None:
    destination = _cache_directory(context.config, context.stage.name, fingerprint)
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{fingerprint[:16]}-", dir=destination.parent))
    try:
        records: dict[str, dict[str, Any]] = {}
        for name, source in sorted(outputs.items()):
            cached = temporary / "outputs" / name / source.name
            _copy_cached_artifact(source, cached)
            records[name] = {
                "path": cached.relative_to(temporary).as_posix(),
                "size": digests[name].size,
                "sha256": digests[name].sha256,
            }
        write_json_atomic(
            temporary / "cache-manifest.json",
            {
                "fingerprint_schema_version": STAGE_FINGERPRINT_SCHEMA_VERSION,
                "stage": context.stage.name,
                "stage_version": context.stage.version,
                "fingerprint": fingerprint,
                "outputs": records,
                "metrics": dict(metrics),
            },
        )
        try:
            os.replace(temporary, destination)
            temporary = Path()
        except OSError:
            if not destination.exists():
                raise
    finally:
        if temporary != Path() and temporary.exists():
            shutil.rmtree(temporary)


def _restore_stage_cache(
    context: StageContext, *, fingerprint: str
) -> tuple[dict[str, Path], dict[str, Any]] | None:
    cache = _cache_directory(context.config, context.stage.name, fingerprint)
    manifest_path = cache / "cache-manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = read_json(manifest_path)
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("fingerprint") != fingerprint
        or manifest.get("stage") != context.stage.name
        or manifest.get("stage_version") != context.stage.version
    ):
        return None
    raw_outputs = manifest.get("outputs")
    raw_metrics = manifest.get("metrics")
    if not isinstance(raw_outputs, Mapping) or not isinstance(raw_metrics, Mapping):
        return None
    cached_paths: dict[str, Path] = {}
    for name, record in raw_outputs.items():
        if not isinstance(name, str) or not isinstance(record, Mapping):
            return None
        relative = record.get("path")
        if not isinstance(relative, str):
            return None
        source = (cache / relative).resolve()
        if not source.is_relative_to(cache) or not source.exists():
            return None
        digest = hash_path(source)
        if digest.size != record.get("size") or digest.sha256 != record.get("sha256"):
            return None
        cached_paths[name] = source
    restore_root = context.artifact_dir / f"cache-{fingerprint[:16]}"
    outputs: dict[str, Path] = {}
    for name, source in cached_paths.items():
        destination = restore_root / name / source.name
        if destination.exists():
            digest = hash_path(destination)
            record = raw_outputs[name]
            if digest.size != record.get("size") or digest.sha256 != record.get("sha256"):
                return None
        else:
            _copy_cached_artifact(source, destination)
        outputs[name] = destination
    metrics = dict(raw_metrics)
    _validate_stage_contract(context.stage.name, outputs=outputs, metrics=metrics)
    return outputs, metrics


def run_project(
    config: ProjectConfig,
    *,
    registry: StageRegistry | None = None,
    resume: bool | None = None,
    selected_stages: Iterable[str] | None = None,
) -> RunResult:
    """Execute configured stages and resume only content-identical completed work."""

    source_registry = SourceRegistry(config.sources, config.data_dir)
    source_records = source_registry.inventory()
    unavailable = [
        source_id
        for source_id, record in source_records.items()
        if record.required and not record.usable
    ]
    if unavailable:
        raise MissingSourcesError(
            "required sources are unavailable or fail integrity checks: "
            + ", ".join(sorted(unavailable))
        )

    config_digest = content_hash(config.to_dict())
    implementation_digest = _package_implementation_digest()
    run_id = deterministic_run_id(config_digest, _run_identity_sources(source_records))
    run_dir = (config.runs_dir / run_id).resolve()
    if not run_dir.is_relative_to(config.runs_dir.resolve()):
        raise PipelineError("resolved run directory escapes configured runs path")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    config_snapshot_path = run_dir / "config.snapshot.json"
    write_json_atomic(config_snapshot_path, config.to_dict())

    should_resume = config.pipeline.resume if resume is None else resume
    existing = _load_resumable_manifest(manifest_path, run_id=run_id) if should_resume else None
    manifest = existing or _initial_manifest(
        config,
        run_id=run_id,
        config_digest=config_digest,
        implementation_digest=implementation_digest,
        config_snapshot=config_snapshot_path,
        source_records=source_records,
    )
    manifest["schema_version"] = RUN_MANIFEST_SCHEMA_VERSION
    manifest["status"] = "running"
    manifest["updated_at"] = utc_now()
    manifest["config"] = {
        "source_path": portable_path(config.source_path, root=config.root_dir),
        "snapshot_path": portable_path(config_snapshot_path, root=config.root_dir),
        "sha256": config_digest,
    }
    manifest["model"] = {
        "package_version": __version__,
        "methodology_version": __version__,
        "implementation_sha256": implementation_digest,
        "configuration_schema_version": config.schema_version,
        "run_manifest_schema_version": RUN_MANIFEST_SCHEMA_VERSION,
    }
    manifest["seeds"] = _collect_seeds(config.parameters)
    manifest["sources"] = _source_manifest(
        source_records, root=config.root_dir, data_root=config.data_dir
    )
    write_json_atomic(manifest_path, manifest)

    handlers = registry or default_stage_registry()
    stages = _topological_stages(config.pipeline.stages, selected_stages)
    stage_records = manifest["stages"]
    output_digests: dict[str, dict[str, ArtifactDigest]] = {}
    resumed: list[str] = []
    executed: list[str] = []
    active_stage_name: str | None = None
    active_stage_timer: float | None = None

    try:
        for stage in stages:
            dependencies = _dependency_outputs(stage, output_digests)
            fingerprint = _stage_fingerprint(
                stage,
                config=config,
                sources=source_records,
                dependencies=dependencies,
            )
            previous = stage_records.get(stage.name)
            if should_resume and isinstance(previous, Mapping):
                previous_outputs = _manifest_output_digests(previous, run_dir=run_dir)
                contract = STANDARD_STAGE_CONTRACTS.get(stage.name)
                previous_metrics = previous.get("metrics")
                metrics_complete = isinstance(previous_metrics, Mapping) and (
                    contract is None or set(contract.metrics) <= set(previous_metrics)
                )
                if (
                    previous.get("fingerprint") == fingerprint
                    and previous_outputs is not None
                    and metrics_complete
                ):
                    stage_records[stage.name] = {
                        **previous,
                        "status": "skipped",
                        "completed_at": utc_now(),
                        "error": None,
                    }
                    output_digests[stage.name] = previous_outputs
                    resumed.append(stage.name)
                    manifest["updated_at"] = utc_now()
                    write_json_atomic(manifest_path, manifest)
                    continue

            context = StageContext(
                config=config,
                run_id=run_id,
                run_dir=run_dir,
                stage=stage,
                sources=source_records,
                dependencies=dependencies,
            )
            if should_resume:
                cached = _restore_stage_cache(context, fingerprint=fingerprint)
                if cached is not None:
                    cached_paths, cached_metrics = cached
                    cached_digests = {name: hash_path(path) for name, path in cached_paths.items()}
                    completed_at = utc_now()
                    stage_records[stage.name] = {
                        "status": "cached",
                        "version": stage.version,
                        "fingerprint": fingerprint,
                        "started_at": completed_at,
                        "completed_at": completed_at,
                        "duration_seconds": 0.0,
                        "outputs": _output_manifest(cached_digests, run_dir=run_dir),
                        "metrics": cached_metrics,
                        "error": None,
                    }
                    output_digests[stage.name] = cached_digests
                    resumed.append(stage.name)
                    manifest["updated_at"] = completed_at
                    write_json_atomic(manifest_path, manifest)
                    continue

            started_at = utc_now()
            stage_records[stage.name] = {
                "status": "running",
                "version": stage.version,
                "fingerprint": fingerprint,
                "started_at": started_at,
                "completed_at": None,
                "duration_seconds": None,
                "outputs": {},
                "metrics": {},
                "error": None,
            }
            manifest["updated_at"] = started_at
            write_json_atomic(manifest_path, manifest)

            active_stage_name = stage.name
            active_stage_timer = time.perf_counter()
            stage_result = _coerce_stage_result(handlers.handler_for(stage.name)(context))
            paths = _normalise_outputs(stage_result.outputs, context=context)
            _validate_stage_contract(stage.name, outputs=paths, metrics=stage_result.metrics)
            digests = {name: hash_path(path) for name, path in paths.items()}
            duration_seconds = round(time.perf_counter() - active_stage_timer, 6)
            output_digests[stage.name] = digests
            executed.append(stage.name)
            _write_stage_cache(
                context,
                fingerprint=fingerprint,
                outputs=paths,
                digests=digests,
                metrics=stage_result.metrics,
            )
            stage_records[stage.name] = {
                "status": "succeeded",
                "version": stage.version,
                "fingerprint": fingerprint,
                "started_at": started_at,
                "completed_at": utc_now(),
                "duration_seconds": duration_seconds,
                "outputs": _output_manifest(digests, run_dir=run_dir),
                "metrics": dict(stage_result.metrics),
                "error": None,
            }
            active_stage_name = None
            active_stage_timer = None
            manifest["updated_at"] = utc_now()
            write_json_atomic(manifest_path, manifest)
    except Exception as exc:
        if stages:
            failed_name = next(
                (
                    stage.name
                    for stage in stages
                    if stage_records.get(stage.name, {}).get("status") == "running"
                ),
                None,
            )
            if failed_name is not None:
                failed = stage_records[failed_name]
                failed["status"] = "failed"
                failed["completed_at"] = utc_now()
                if active_stage_name == failed_name and active_stage_timer is not None:
                    failed["duration_seconds"] = round(time.perf_counter() - active_stage_timer, 6)
                failed["error"] = f"{type(exc).__name__}: {exc}"
        manifest["status"] = "failed"
        manifest["updated_at"] = utc_now()
        write_json_atomic(manifest_path, manifest)
        if isinstance(exc, PipelineError):
            raise
        raise StageExecutionError(str(exc)) from exc

    manifest["status"] = "succeeded"
    manifest["updated_at"] = utc_now()
    write_json_atomic(manifest_path, manifest)
    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        manifest_path=manifest_path,
        status="succeeded",
        resumed_stages=tuple(resumed),
        executed_stages=tuple(executed),
    )


def validate_run_manifest(
    path: str | Path,
    *,
    project_root: str | Path,
    data_root: str | Path | None = None,
) -> ValidationReport:
    """Verify a run manifest, configuration, sources, and declared outputs."""

    manifest_path = Path(path).resolve()
    root = Path(project_root).resolve()
    issues: list[ValidationIssue] = []
    try:
        if not manifest_path.is_relative_to(root):
            raise ProvenanceError("manifest is outside the project root")
        manifest = read_json(manifest_path)
    except (ProvenanceError, OSError) as exc:
        return ValidationReport((ValidationIssue("error", "manifest-read", str(exc)),))
    if not isinstance(manifest, Mapping):
        return ValidationReport(
            (ValidationIssue("error", "manifest-type", "manifest root must be an object"),)
        )

    required_keys = {
        "schema_version",
        "run_id",
        "project_id",
        "status",
        "created_at",
        "updated_at",
        "config",
        "model",
        "seeds",
        "sources",
        "runtime",
        "stages",
    }
    missing = required_keys - set(manifest)
    if missing:
        issues.append(
            ValidationIssue(
                "error", "manifest-fields", f"missing fields: {', '.join(sorted(missing))}"
            )
        )
        return ValidationReport(tuple(issues))

    if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "error",
                "manifest-schema-version",
                f"run manifest schema_version must be {RUN_MANIFEST_SCHEMA_VERSION}",
            )
        )

    model_record = manifest.get("model")
    implementation_sha256 = (
        model_record.get("implementation_sha256") if isinstance(model_record, Mapping) else None
    )
    if (
        not isinstance(model_record, Mapping)
        or model_record.get("run_manifest_schema_version") != RUN_MANIFEST_SCHEMA_VERSION
        or not isinstance(implementation_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", implementation_sha256) is None
    ):
        issues.append(
            ValidationIssue(
                "error",
                "model-record",
                "model record has no valid manifest version and implementation checksum",
            )
        )
    elif implementation_sha256 != _package_implementation_digest():
        issues.append(
            ValidationIssue(
                "error",
                "implementation-mismatch",
                "run implementation source differs from the current package source",
            )
        )

    if manifest.get("status") != "succeeded":
        issues.append(
            ValidationIssue(
                "error", "run-status", f"run status is {manifest.get('status')!r}, not succeeded"
            )
        )

    config_record = manifest.get("config")
    if isinstance(config_record, Mapping) and isinstance(config_record.get("snapshot_path"), str):
        config_path = (root / config_record["snapshot_path"]).resolve()
        if not config_path.is_relative_to(root) or not config_path.is_file():
            issues.append(
                ValidationIssue("error", "config-missing", "run configuration is missing")
            )
        else:
            try:
                config = load_config(config_path, project_root=root, data_root=data_root)
                actual_config_hash = content_hash(config.to_dict())
                if actual_config_hash != config_record.get("sha256"):
                    issues.append(
                        ValidationIssue(
                            "error", "config-mismatch", "run configuration content has changed"
                        )
                    )
            except Exception as exc:
                issues.append(ValidationIssue("error", "config-invalid", str(exc)))
    else:
        issues.append(ValidationIssue("error", "config-record", "invalid configuration record"))

    source_records = manifest.get("sources")
    if isinstance(source_records, Mapping):
        for source_id, record in source_records.items():
            if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
                issues.append(
                    ValidationIssue("error", "source-record", f"invalid source record: {source_id}")
                )
                continue
            source_reference = record["path"]
            if source_reference.startswith("@data/"):
                source_root = Path(data_root).expanduser().resolve() if data_root else root / "data"
                source_path = (source_root / source_reference.removeprefix("@data/")).resolve()
                safe_source_path = source_path.is_relative_to(source_root.resolve())
            else:
                source_path = (root / source_reference).resolve()
                safe_source_path = source_path.is_relative_to(root)
            if not safe_source_path or not source_path.is_file():
                severity = "error" if record.get("required") else "warning"
                issues.append(
                    ValidationIssue(severity, "source-missing", f"source is missing: {source_id}")
                )
                continue
            expected = record.get("sha256")
            if expected is not None and sha256_file(source_path) != expected:
                issues.append(
                    ValidationIssue("error", "source-mismatch", f"source changed: {source_id}")
                )
    else:
        issues.append(ValidationIssue("error", "sources-record", "sources must be an object"))

    stages = manifest.get("stages")
    run_dir = manifest_path.parent
    if isinstance(stages, Mapping):
        for stage_name, record in stages.items():
            if not isinstance(record, Mapping):
                issues.append(
                    ValidationIssue("error", "stage-record", f"invalid stage record: {stage_name}")
                )
                continue
            if record.get("status") not in {"succeeded", "skipped", "cached"}:
                issues.append(
                    ValidationIssue(
                        "error", "stage-status", f"stage {stage_name} is {record.get('status')!r}"
                    )
                )
            contract = STANDARD_STAGE_CONTRACTS.get(str(stage_name))
            metrics = record.get("metrics")
            if not isinstance(metrics, Mapping):
                issues.append(
                    ValidationIssue(
                        "error", "stage-metrics", f"stage metrics are missing: {stage_name}"
                    )
                )
            elif contract is not None and not set(contract.metrics) <= set(metrics):
                issues.append(
                    ValidationIssue(
                        "error",
                        "stage-metrics",
                        f"stage audit metrics are incomplete: {stage_name}",
                    )
                )
            duration = record.get("duration_seconds")
            if not isinstance(duration, int | float) or duration < 0:
                issues.append(
                    ValidationIssue(
                        "error", "stage-timing", f"stage timing is invalid: {stage_name}"
                    )
                )
            if _manifest_output_digests(record, run_dir=run_dir) is None:
                issues.append(
                    ValidationIssue(
                        "error", "output-mismatch", f"stage outputs changed: {stage_name}"
                    )
                )
    else:
        issues.append(ValidationIssue("error", "stages-record", "stages must be an object"))

    return ValidationReport(tuple(issues))
