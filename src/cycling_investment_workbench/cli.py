"""Command-line entry point for reproducible CIW workflows."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, ProjectConfig, load_config
from .counter_sources import CounterSourceError, prepare_at_cycle_counters
from .exports import ExportError, export_web_payload, load_web_payload, verify_web_export
from .pipeline import (
    MissingSourcesError,
    PipelineError,
    ValidationIssue,
    ValidationReport,
    demo_project_config,
    demo_stage_registry,
    run_project,
    validate_run_manifest,
)
from .provenance import (
    ProvenanceError,
    content_hash,
    hash_path,
    portable_path,
    read_json,
    write_json_atomic,
)
from .safety_sources import SafetySourceError, prepare_cycle_crash_grid
from .sources import SourceError, SourceRegistry
from .transit_sources import TransitSourceError, prepare_at_major_transit_nodes

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_PIPELINE = 4
EXIT_VALIDATION = 5
_RUN_ID = re.compile(r"^run-[0-9a-f]{16}$")


def _default_config_path() -> str:
    return "configs/auckland.yml"


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        "-c",
        default=_default_config_path(),
        help="Project configuration (default: configs/auckland.yml)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        help="External root for registered source data (kept outside the repository)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ciw",
        description="Run and publish the Auckland Cycling Investment Workbench.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--debug", action="store_true", help="Show an exception traceback when a command fails"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    data_parser = commands.add_parser("data", help="Acquire registered source data")
    data_commands = data_parser.add_subparsers(dest="data_command", required=True)
    fetch_parser = data_commands.add_parser("fetch", help="Fetch and verify registered sources")
    _add_config_argument(fetch_parser)
    fetch_parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="ID",
        help="Fetch only this source; repeat to select several",
    )
    fetch_parser.add_argument(
        "--offline", action="store_true", help="Inspect local sources without network access"
    )
    fetch_parser.add_argument(
        "--force", action="store_true", help="Reacquire selected downloadable sources"
    )
    fetch_parser.add_argument(
        "--accept-unverified",
        action="store_true",
        help="Allow a download with no registered SHA-256 digest",
    )
    fetch_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    counter_parser = data_commands.add_parser(
        "prepare-at-counters",
        help="Prepare exact-period AT counter inputs from a publisher workbook",
    )
    _add_config_argument(counter_parser)
    counter_parser.add_argument("--workbook", type=Path, required=True)
    counter_parser.add_argument("--coordinate-registry", type=Path, required=True)
    counter_parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("configs/at-cycle-counter-mapping.yml"),
    )
    counter_parser.add_argument(
        "--source-url",
        default=("https://at.govt.nz/media/zj0lgcmg/at-daily-cycle-count-data-july-2026.xlsx"),
    )
    counter_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    transit_parser = data_commands.add_parser(
        "prepare-at-transit",
        help="Prepare major transit nodes for one declared AT GTFS service day",
    )
    _add_config_argument(transit_parser)
    transit_parser.add_argument("--gtfs", type=Path, required=True)
    transit_parser.add_argument("--service-date", required=True, help="Service date (YYYY-MM-DD)")
    transit_parser.add_argument(
        "--busiest-bus-fraction",
        type=float,
        default=0.01,
        help="Fraction of busiest bus nodes to retain (default: 0.01)",
    )
    transit_parser.add_argument(
        "--source-url",
        default="https://gtfs.at.govt.nz/gtfs.zip",
    )
    transit_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    safety_parser = data_commands.add_parser(
        "prepare-cas-safety",
        help="Prepare a disclosure-safe cycle-crash grid from a local CAS export",
    )
    _add_config_argument(safety_parser)
    safety_parser.add_argument("--cas-csv", type=Path, required=True)
    safety_parser.add_argument("--start-year", type=int, default=2016)
    safety_parser.add_argument("--end-year", type=int, default=2025)
    safety_parser.add_argument("--cell-size-m", type=int, default=500)
    safety_parser.add_argument("--minimum-count", type=int, default=3)
    safety_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    run_parser = commands.add_parser("run", help="Run configured, content-addressed stages")
    _add_config_argument(run_parser)
    run_parser.add_argument(
        "--stage",
        action="append",
        dest="stages",
        metavar="NAME",
        help="Run this stage and its dependencies; repeat to select several",
    )
    run_parser.add_argument(
        "--no-resume", action="store_true", help="Execute stages even when verified outputs exist"
    )
    run_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    validate_parser = commands.add_parser(
        "validate", help="Validate configuration, source integrity, runs, and browser exports"
    )
    _add_config_argument(validate_parser)
    validate_parser.add_argument(
        "--config-only",
        action="store_true",
        help="Validate structure without requiring source files",
    )
    run_reference = validate_parser.add_mutually_exclusive_group()
    run_reference.add_argument(
        "--manifest", type=Path, help="Also verify a run manifest and every declared artifact"
    )
    run_reference.add_argument(
        "--run",
        metavar="RUN_ID",
        help="Verify runs/<RUN_ID>/manifest.json under the configured project",
    )
    validate_parser.add_argument(
        "--web", action="store_true", help="Also verify the configured browser data export"
    )
    validate_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    export_parser = commands.add_parser(
        "export-web", help="Write the verified browser manifest and GeoJSON layers"
    )
    _add_config_argument(export_parser)
    payload_group = export_parser.add_mutually_exclusive_group(required=True)
    payload_group.add_argument(
        "--input", type=Path, help="JSON file containing manifest and layers"
    )
    payload_group.add_argument(
        "--demo", action="store_true", help="Export the deterministic miniature-city payload"
    )
    payload_group.add_argument(
        "--run",
        metavar="RUN_ID",
        help="Export the verified web payload declared by a completed run",
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        help="Output data directory (default: configured web/public/data)",
    )
    export_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    demo_parser = commands.add_parser("demo", help="Run the deterministic miniature-city analysis")
    demo_parser.add_argument("--output", type=Path, help="Write the analytical result as JSON")
    demo_parser.add_argument(
        "--export-web",
        action="store_true",
        help="Also export the browser-ready miniature-city data",
    )
    demo_parser.add_argument(
        "--no-resume", action="store_true", help="Execute every demo stage again"
    )
    _add_config_argument(demo_parser)
    demo_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")

    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2))


def _portable_user_path(path: Path, *, root: Path) -> str:
    try:
        return portable_path(path, root=root)
    except ProvenanceError:
        return path.name


def _source_payload(config: ProjectConfig, records: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": all(not record.required or record.usable for record in records.values()),
        "sources": {
            source_id: record.to_dict(root=config.root_dir, data_root=config.data_dir)
            for source_id, record in sorted(records.items())
        },
    }


def _run_manifest_path(config: ProjectConfig, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ConfigError("run id must use the form run- followed by 16 lowercase hex digits")
    manifest = (config.runs_dir / run_id / "manifest.json").resolve()
    if not manifest.is_relative_to(config.runs_dir.resolve()):
        raise ConfigError("run path escapes the configured runs directory")
    if not manifest.is_file():
        raise ConfigError(f"run does not exist: {run_id}")
    return manifest


def _run_output_path(
    config: ProjectConfig,
    run_id: str,
    *,
    stage_name: str,
    output_name: str,
) -> Path:
    manifest_path = _run_manifest_path(config, run_id)
    manifest = read_json(manifest_path)
    if not isinstance(manifest, Mapping) or manifest.get("run_id") != run_id:
        raise ConfigError(f"run manifest identity does not match {run_id}")
    stages = manifest.get("stages")
    stage = stages.get(stage_name) if isinstance(stages, Mapping) else None
    if not isinstance(stage, Mapping) or stage.get("status") not in {
        "succeeded",
        "skipped",
        "cached",
    }:
        raise ConfigError(f"run {run_id} has no completed {stage_name} stage")
    outputs = stage.get("outputs")
    output = outputs.get(output_name) if isinstance(outputs, Mapping) else None
    if not isinstance(output, Mapping) or not isinstance(output.get("path"), str):
        raise ConfigError(f"run {run_id} does not declare {stage_name}.{output_name}")
    run_dir = manifest_path.parent
    path = (run_dir / output["path"]).resolve()
    if not path.is_relative_to(run_dir) or not path.is_file():
        raise ConfigError(f"run output is missing or unsafe: {stage_name}.{output_name}")
    digest = hash_path(path)
    if digest.size != output.get("size") or digest.sha256 != output.get("sha256"):
        raise ConfigError(f"run output fails integrity verification: {stage_name}.{output_name}")
    return path


def _command_data_fetch(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    registry = SourceRegistry(config.sources, config.data_dir)
    records = registry.fetch(
        args.sources,
        offline=args.offline,
        force=args.force,
        accept_unverified=args.accept_unverified,
    )
    payload = _source_payload(config, records)
    if args.json:
        _print_json(payload)
    else:
        for source_id, record in sorted(records.items()):
            digest = f" sha256={record.sha256}" if record.sha256 else ""
            print(f"{source_id}: {record.status}{digest}")
    return EXIT_OK if payload["ok"] else EXIT_INPUT


def _source_destination(config: ProjectConfig, source_id: str) -> Path:
    for source in config.sources:
        if source.id == source_id:
            destination = (config.data_dir / source.destination).resolve()
            if not destination.is_relative_to(config.data_dir.resolve()):
                raise ConfigError(f"source destination escapes the data root: {source_id}")
            return destination
    raise ConfigError(f"configuration has no source named {source_id}")


def _command_prepare_at_counters(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    result = prepare_at_cycle_counters(
        workbook_path=args.workbook,
        coordinate_registry_path=args.coordinate_registry,
        mapping_path=args.mapping,
        locations_output=_source_destination(config, "cycle_counter_locations"),
        observations_output=_source_destination(config, "cycle_counter_observations"),
        source_url=args.source_url,
    )
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(
            f"Prepared {result.location_count} counter sites across "
            f"{result.observation_days} days; excluded {result.excluded_count} sites"
        )
        print(f"Locations SHA-256: {payload['locations']['sha256']}")
        print(f"Observations SHA-256: {payload['observations']['sha256']}")
    return EXIT_OK


def _command_prepare_at_transit(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    result = prepare_at_major_transit_nodes(
        gtfs_path=args.gtfs,
        output_path=_source_destination(config, "major_transit_nodes"),
        service_date=args.service_date,
        busiest_bus_fraction=args.busiest_bus_fraction,
        source_url=args.source_url,
    )
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(
            f"Prepared {result.feature_count} major transit nodes for "
            f"{result.service_date}; feed version {result.feed_version}"
        )
        print(f"Output SHA-256: {payload['output']['sha256']}")
    return EXIT_OK


def _command_prepare_cas_safety(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    result = prepare_cycle_crash_grid(
        cas_csv_path=args.cas_csv,
        output_path=_source_destination(config, "crash_safety_aggregate"),
        start_year=args.start_year,
        end_year=args.end_year,
        cell_size_m=args.cell_size_m,
        minimum_count=args.minimum_count,
    )
    payload = result.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(
            f"Prepared {result.published_cells} crash-context cells from "
            f"{result.input_cycle_crashes} cycle-involved crashes"
        )
        print(f"Output SHA-256: {payload['output']['sha256']}")
    return EXIT_OK


def _command_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    result = run_project(
        config,
        resume=not args.no_resume,
        selected_stages=args.stages,
    )
    payload = result.to_dict(root=config.root_dir)
    if args.json:
        _print_json(payload)
    else:
        print(f"Run {result.run_id}: {result.status}")
        if result.executed_stages:
            print("Executed: " + ", ".join(result.executed_stages))
        if result.resumed_stages:
            print("Resumed: " + ", ".join(result.resumed_stages))
        print(f"Manifest: {payload['manifest']}")
    return EXIT_OK


def _source_validation_issues(config: ProjectConfig) -> list[ValidationIssue]:
    registry = SourceRegistry(config.sources, config.data_dir)
    records = registry.inventory()
    issues: list[ValidationIssue] = []
    for spec in config.sources:
        record = records[spec.id]
        if record.status == "missing":
            severity = "error" if spec.required else "warning"
            issues.append(ValidationIssue(severity, "source-missing", f"{spec.id} is missing"))
        elif record.status == "mismatch":
            issues.append(
                ValidationIssue("error", "source-mismatch", f"{spec.id} fails SHA-256 verification")
            )
        if spec.acquisition == "download" and spec.sha256 is None:
            issues.append(
                ValidationIssue(
                    "warning", "source-unpinned", f"{spec.id} has no registered SHA-256 digest"
                )
            )
        if spec.redistribution == "unknown":
            issues.append(
                ValidationIssue(
                    "warning",
                    "licence-unconfirmed",
                    f"{spec.id} redistribution status is not confirmed",
                )
            )
    return issues


def _command_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    issues: list[ValidationIssue] = []
    if not args.config_only and args.run is None and args.manifest is None:
        issues.extend(_source_validation_issues(config))
    manifest_path = _run_manifest_path(config, args.run) if args.run is not None else args.manifest
    if manifest_path is not None:
        report = validate_run_manifest(
            manifest_path,
            project_root=config.root_dir,
            data_root=config.data_dir,
        )
        issues.extend(report.issues)
    if args.web:
        issues.extend(
            ValidationIssue("error", "web-export", problem)
            for problem in verify_web_export(config.public_data_dir, export_config=config.export)
        )
    report = ValidationReport(tuple(issues))
    payload = report.to_dict()
    if args.json:
        _print_json(payload)
    elif report.issues:
        for issue in report.issues:
            print(f"{issue.severity.upper()} [{issue.code}] {issue.message}")
        print(f"Validation: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    else:
        print("Validation: OK")
    return EXIT_OK if report.ok else EXIT_VALIDATION


def _demo_web_payload(config: ProjectConfig) -> Mapping[str, Any]:
    from .demo import web_export_payload

    demo_config = demo_project_config(config)
    return web_export_payload(
        config_sha256=content_hash(demo_config.to_dict()),
    )


def _command_export_web(args: argparse.Namespace) -> int:
    config = load_config(args.config, data_root=args.data_root)
    if args.demo:
        payload = _demo_web_payload(config)
    elif args.run is not None:
        payload = load_web_payload(
            _run_output_path(
                config,
                args.run,
                stage_name="export-outputs",
                output_name="web_payload",
            )
        )
    else:
        payload = load_web_payload(args.input)
    output_dir = (args.output or config.public_data_dir).expanduser().resolve()
    if not output_dir.is_relative_to(config.root_dir):
        raise ExportError("web output must remain inside the project directory")
    result = export_web_payload(
        payload,
        export_config=config.export,
        output_dir=output_dir,
        source_specs=config.sources,
    )
    result_payload = result.to_dict(root=config.root_dir)
    if args.json:
        _print_json(result_payload)
    else:
        print(f"Web data exported to {result_payload['output_dir']}")
        print(f"Manifest SHA-256: {result.manifest.sha256}")
    return EXIT_OK


def _command_demo(args: argparse.Namespace) -> int:
    base_config = load_config(args.config, data_root=args.data_root)
    config = demo_project_config(base_config)
    run = run_project(
        config,
        registry=demo_stage_registry(),
        resume=not args.no_resume,
    )
    evidence_path = _run_output_path(
        config, run.run_id, stage_name="appraisal-uncertainty-validation", output_name="evidence"
    )
    result = read_json(evidence_path)
    payload: dict[str, Any] = {
        "run": run.to_dict(root=config.root_dir),
        "analysis": result,
    }
    if args.output is not None:
        destination = args.output.expanduser().resolve()
        write_json_atomic(destination, result)
        payload["analysis_output"] = _portable_user_path(destination, root=Path.cwd())
    if args.export_web:
        web_payload_path = _run_output_path(
            config, run.run_id, stage_name="export-outputs", output_name="web_payload"
        )
        export = export_web_payload(
            load_web_payload(web_payload_path),
            export_config=config.export,
            output_dir=config.public_data_dir,
            source_specs=config.sources,
        )
        payload["web_export"] = export.to_dict(root=config.root_dir)
    if args.json:
        _print_json(payload)
    elif args.output is not None or args.export_web:
        if args.output is not None:
            print(f"Demo analysis written to {payload['analysis_output']}")
        if args.export_web:
            print(f"Demo web data exported to {payload['web_export']['output_dir']}")
    else:
        _print_json(payload)
    return EXIT_OK


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "data" and args.data_command == "fetch":
        return _command_data_fetch(args)
    if args.command == "data" and args.data_command == "prepare-at-counters":
        return _command_prepare_at_counters(args)
    if args.command == "data" and args.data_command == "prepare-at-transit":
        return _command_prepare_at_transit(args)
    if args.command == "data" and args.data_command == "prepare-cas-safety":
        return _command_prepare_cas_safety(args)
    if args.command == "run":
        return _command_run(args)
    if args.command == "validate":
        return _command_validate(args)
    if args.command == "export-web":
        return _command_export_web(args)
    if args.command == "demo":
        return _command_demo(args)
    raise ConfigError("unsupported command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (
        ConfigError,
        CounterSourceError,
        SafetySourceError,
        TransitSourceError,
        SourceError,
        ExportError,
        ProvenanceError,
    ) as exc:
        if args.debug:
            raise
        print(f"Input error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except MissingSourcesError as exc:
        if args.debug:
            raise
        print(f"Input error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except PipelineError as exc:
        if args.debug:
            raise
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return EXIT_PIPELINE


__all__ = ["build_parser", "main"]
