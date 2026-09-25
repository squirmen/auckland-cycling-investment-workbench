"""Strict project configuration loading."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .sources import SourceError, SourceSpec

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]+$")
_STAGE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_LAYER_IDS = ("cells", "network", "candidates", "programmes", "counters", "safety")


class ConfigError(ValueError):
    """Raised when a configuration is incomplete, ambiguous, or unsafe."""


def _mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{context} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{context} keys must be strings")
    return value


def _sequence(value: Any, *, context: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ConfigError(f"{context} must be a sequence")
    return value


def _strict_keys(
    value: Mapping[str, Any], *, required: set[str], optional: set[str], context: str
) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise ConfigError(f"{context} is missing: {', '.join(sorted(missing))}")
    if unknown:
        raise ConfigError(f"{context} has unknown keys: {', '.join(sorted(unknown))}")


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{context} must be a boolean")
    return value


def _relative_path(value: Any, *, context: str) -> str:
    text = _string(value, context=context)
    if "\\" in text:
        raise ConfigError(f"{context} must use forward slashes")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ConfigError(f"{context} must be a normalised relative path")
    return path.as_posix()


def _json_value(value: Any, *, context: str) -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigError(f"{context} cannot contain NaN or infinity")
        return value
    if isinstance(value, list):
        return [
            _json_value(item, context=f"{context}[{index}]") for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfigError(f"{context} keys must be strings")
            converted[key] = _json_value(item, context=f"{context}.{key}")
        return converted
    raise ConfigError(f"{context} contains unsupported value type {type(value).__name__}")


@dataclass(frozen=True)
class ProjectMetadata:
    id: str
    title: str
    region: str
    crs: str
    timezone: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "region": self.region,
            "crs": self.crs,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class PathsConfig:
    data: str
    cache: str
    runs: str
    exports: str
    web_source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "data": self.data,
            "cache": self.cache,
            "runs": self.runs,
            "exports": self.exports,
            "web_source": self.web_source,
        }


@dataclass(frozen=True)
class PipelineStageConfig:
    name: str
    version: str
    depends_on: tuple[str, ...]
    options: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "depends_on": list(self.depends_on),
            "options": json.loads(json.dumps(self.options)),
        }


@dataclass(frozen=True)
class PipelineConfig:
    resume: bool
    stages: tuple[PipelineStageConfig, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"resume": self.resume, "stages": [stage.to_dict() for stage in self.stages]}


@dataclass(frozen=True)
class ExportConfig:
    public_data_dir: str
    manifest_filename: str
    layer_filenames: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "public_data_dir": self.public_data_dir,
            "manifest_filename": self.manifest_filename,
            "layer_filenames": dict(self.layer_filenames),
        }


@dataclass(frozen=True)
class ProjectConfig:
    schema_version: int
    project: ProjectMetadata
    paths: PathsConfig
    sources: tuple[SourceSpec, ...]
    pipeline: PipelineConfig
    export: ExportConfig
    parameters: dict[str, Any]
    source_path: Path
    root_dir: Path
    data_root_override: Path | None = None

    def resolve(self, relative_path: str) -> Path:
        path = (self.root_dir / relative_path).resolve()
        if not path.is_relative_to(self.root_dir):
            raise ConfigError(f"configured path escapes the project root: {relative_path}")
        return path

    @property
    def data_dir(self) -> Path:
        if self.data_root_override is not None:
            return self.data_root_override.resolve()
        return self.resolve(self.paths.data)

    @property
    def cache_dir(self) -> Path:
        return self.resolve(self.paths.cache)

    @property
    def runs_dir(self) -> Path:
        return self.resolve(self.paths.runs)

    @property
    def exports_dir(self) -> Path:
        return self.resolve(self.paths.exports)

    @property
    def web_source_dir(self) -> Path:
        return self.resolve(self.paths.web_source)

    @property
    def public_data_dir(self) -> Path:
        return self.resolve(self.export.public_data_dir)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project.to_dict(),
            "paths": self.paths.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
            "pipeline": self.pipeline.to_dict(),
            "export": self.export.to_dict(),
            "parameters": json.loads(json.dumps(self.parameters)),
        }


def _parse_project(value: Any) -> ProjectMetadata:
    item = _mapping(value, context="project")
    keys = {"id", "title", "region", "crs", "timezone"}
    _strict_keys(item, required=keys, optional=set(), context="project")
    project_id = _string(item["id"], context="project.id")
    if not _PROJECT_ID.fullmatch(project_id):
        raise ConfigError(f"project.id must match {_PROJECT_ID.pattern}")
    crs = _string(item["crs"], context="project.crs")
    if not re.fullmatch(r"EPSG:[0-9]+", crs):
        raise ConfigError("project.crs must use the form EPSG:2193")
    return ProjectMetadata(
        id=project_id,
        title=_string(item["title"], context="project.title"),
        region=_string(item["region"], context="project.region"),
        crs=crs,
        timezone=_string(item["timezone"], context="project.timezone"),
    )


def _parse_paths(value: Any) -> PathsConfig:
    item = _mapping(value, context="paths")
    keys = {"data", "cache", "runs", "exports", "web_source"}
    _strict_keys(item, required=keys, optional=set(), context="paths")
    return PathsConfig(
        data=_relative_path(item["data"], context="paths.data"),
        cache=_relative_path(item["cache"], context="paths.cache"),
        runs=_relative_path(item["runs"], context="paths.runs"),
        exports=_relative_path(item["exports"], context="paths.exports"),
        web_source=_relative_path(item["web_source"], context="paths.web_source"),
    )


def _parse_sources(value: Any) -> tuple[SourceSpec, ...]:
    items = _sequence(value, context="sources")
    sources: list[SourceSpec] = []
    for index, raw in enumerate(items):
        try:
            sources.append(
                SourceSpec.from_mapping(
                    _mapping(raw, context=f"sources[{index}]"), context=f"sources[{index}]"
                )
            )
        except SourceError as exc:
            raise ConfigError(str(exc)) from exc
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise ConfigError("sources must have unique ids")
    destinations = [source.destination for source in sources]
    if len(destinations) != len(set(destinations)):
        raise ConfigError("sources must have unique destinations")
    return tuple(sources)


def _parse_pipeline(value: Any) -> PipelineConfig:
    item = _mapping(value, context="pipeline")
    _strict_keys(item, required={"resume", "stages"}, optional=set(), context="pipeline")
    raw_stages = _sequence(item["stages"], context="pipeline.stages")
    if not raw_stages:
        raise ConfigError("pipeline.stages must not be empty")
    stages: list[PipelineStageConfig] = []
    for index, raw_stage in enumerate(raw_stages):
        context = f"pipeline.stages[{index}]"
        stage = _mapping(raw_stage, context=context)
        required = {"name", "version", "depends_on", "options"}
        _strict_keys(stage, required=required, optional=set(), context=context)
        name = _string(stage["name"], context=f"{context}.name")
        if not _STAGE_NAME.fullmatch(name):
            raise ConfigError(f"{context}.name must match {_STAGE_NAME.pattern}")
        dependencies = tuple(
            _string(dependency, context=f"{context}.depends_on")
            for dependency in _sequence(stage["depends_on"], context=f"{context}.depends_on")
        )
        if len(dependencies) != len(set(dependencies)):
            raise ConfigError(f"{context}.depends_on contains duplicates")
        options = _json_value(
            _mapping(stage["options"], context=f"{context}.options"), context=f"{context}.options"
        )
        stages.append(
            PipelineStageConfig(
                name=name,
                version=_string(stage["version"], context=f"{context}.version"),
                depends_on=dependencies,
                options=options,
            )
        )
    _validate_stage_graph(stages)
    return PipelineConfig(
        resume=_boolean(item["resume"], context="pipeline.resume"), stages=tuple(stages)
    )


def _validate_stage_graph(stages: Sequence[PipelineStageConfig]) -> None:
    by_name = {stage.name: stage for stage in stages}
    if len(by_name) != len(stages):
        raise ConfigError("pipeline stage names must be unique")
    for stage in stages:
        missing = set(stage.depends_on) - set(by_name)
        if missing:
            names = ", ".join(sorted(missing))
            raise ConfigError(f"pipeline stage {stage.name} has unknown dependencies: {names}")
        if stage.name in stage.depends_on:
            raise ConfigError(f"pipeline stage {stage.name} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ConfigError(f"pipeline contains a dependency cycle at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in by_name[name].depends_on:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for stage_name in by_name:
        visit(stage_name)


def _parse_export(value: Any) -> ExportConfig:
    item = _mapping(value, context="export")
    keys = {"public_data_dir", "manifest_filename", "layer_filenames"}
    _strict_keys(item, required=keys, optional=set(), context="export")
    public_data_dir = _relative_path(item["public_data_dir"], context="export.public_data_dir")
    manifest_filename = _relative_path(
        item["manifest_filename"], context="export.manifest_filename"
    )
    if "/" in manifest_filename or not manifest_filename.endswith(".json"):
        raise ConfigError("export.manifest_filename must be a .json basename")
    raw_layers = _mapping(item["layer_filenames"], context="export.layer_filenames")
    _strict_keys(
        raw_layers,
        required=set(_LAYER_IDS),
        optional=set(),
        context="export.layer_filenames",
    )
    layer_filenames: dict[str, str] = {}
    for layer_id in _LAYER_IDS:
        filename = _relative_path(
            raw_layers[layer_id], context=f"export.layer_filenames.{layer_id}"
        )
        if "/" in filename or not filename.endswith(".geojson"):
            raise ConfigError(f"export.layer_filenames.{layer_id} must be a .geojson basename")
        layer_filenames[layer_id] = filename
    if len(set(layer_filenames.values())) != len(layer_filenames):
        raise ConfigError("export.layer_filenames must be unique")
    return ExportConfig(
        public_data_dir=public_data_dir,
        manifest_filename=manifest_filename,
        layer_filenames=layer_filenames,
    )


def load_config(
    path: str | Path,
    *,
    project_root: str | Path | None = None,
    data_root: str | Path | None = None,
) -> ProjectConfig:
    """Load and fully validate a project YAML or JSON file."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise ConfigError(f"configuration file does not exist: {source_path}")
    try:
        text = source_path.read_text(encoding="utf-8")
        raw = json.loads(text) if source_path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"could not read configuration: {exc}") from exc
    root = _mapping(raw, context="configuration")
    required = {"schema_version", "project", "paths", "sources", "pipeline", "export", "parameters"}
    _strict_keys(root, required=required, optional=set(), context="configuration")
    if root["schema_version"] != 1:
        raise ConfigError("schema_version must be 1")

    if project_root is None:
        inferred_root = (
            source_path.parent.parent
            if source_path.parent.name == "configs"
            else source_path.parent
        )
    else:
        inferred_root = Path(project_root).expanduser()
    resolved_root = inferred_root.resolve()

    parameters = _json_value(
        _mapping(root["parameters"], context="parameters"), context="parameters"
    )
    config = ProjectConfig(
        schema_version=1,
        project=_parse_project(root["project"]),
        paths=_parse_paths(root["paths"]),
        sources=_parse_sources(root["sources"]),
        pipeline=_parse_pipeline(root["pipeline"]),
        export=_parse_export(root["export"]),
        parameters=parameters,
        source_path=source_path,
        root_dir=resolved_root,
        data_root_override=(Path(data_root).expanduser().resolve() if data_root else None),
    )
    for configured_path in config.paths.to_dict().values():
        config.resolve(configured_path)
    return config
