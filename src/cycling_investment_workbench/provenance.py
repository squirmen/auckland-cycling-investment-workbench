"""Content hashing and portable run provenance."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ProvenanceError(ValueError):
    """Raised when provenance cannot be represented safely."""


@dataclass(frozen=True)
class ArtifactDigest:
    path: Path
    size: int
    sha256: str

    def to_dict(self, *, root: Path) -> dict[str, Any]:
        return {
            "path": portable_path(self.path, root=root),
            "size": self.size,
            "sha256": self.sha256,
        }


def utc_now() -> str:
    """Return a UTC timestamp in RFC 3339 form."""

    return (
        datetime.now(timezone.utc)  # noqa: UP017 -- keeps local audit tooling on Python 3.10
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: str | Path, *, root: str | Path) -> str:
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ProvenanceError(f"path is outside the project root: {resolved_path}") from exc


def _normalise(value: Any) -> Any:
    if is_dataclass(value):
        return _normalise(asdict(value))
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProvenanceError("canonical mappings must have string keys")
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((_normalise(item) for item in value), key=canonical_json)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise ProvenanceError(f"cannot canonicalise {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Encode a value deterministically for hashing and portable files."""

    return json.dumps(
        _normalise(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def hash_path(path: str | Path) -> ArtifactDigest:
    """Hash one file or a directory tree without following symbolic links."""

    raw_target = Path(path)
    if raw_target.is_symlink():
        raise ProvenanceError(f"symbolic links are not valid artifacts: {raw_target}")
    target = raw_target.resolve()
    if target.is_file():
        return ArtifactDigest(target, target.stat().st_size, sha256_file(target))
    if not target.is_dir():
        raise ProvenanceError(f"artifact does not exist: {target}")

    entries: list[dict[str, Any]] = []
    total_size = 0
    for file_path in sorted(target.rglob("*")):
        if file_path.is_symlink():
            raise ProvenanceError(f"symbolic links are not valid artifacts: {file_path}")
        if not file_path.is_file():
            continue
        size = file_path.stat().st_size
        total_size += size
        entries.append(
            {
                "path": file_path.relative_to(target).as_posix(),
                "size": size,
                "sha256": sha256_file(file_path),
            }
        )
    return ArtifactDigest(target, total_size, content_hash(entries))


def package_versions(names: Iterable[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in sorted(set(names)):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def runtime_provenance(*, packages: Iterable[str] = ()) -> dict[str, Any]:
    revision = os.environ.get("CIW_SOURCE_REVISION") or os.environ.get("GITHUB_SHA")
    try:
        java_process = subprocess.run(
            ["java", "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        java_lines = (java_process.stderr or java_process.stdout).splitlines()
        java_version = java_lines[0].strip() if java_lines else None
    except (OSError, subprocess.SubprocessError):
        java_version = None
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": package_versions(packages),
        "jvm": java_version,
        "r5_engine": os.environ.get("CIW_R5_VERSION"),
        "source_revision": revision,
    }


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"could not read JSON from {path}: {exc}") from exc


def write_json_atomic(path: str | Path, value: Any, *, pretty: bool = True) -> None:
    """Write JSON through an adjacent temporary file and atomic replacement."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(
            _normalise(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        text += "\n"
    else:
        text = canonical_json(value) + "\n"

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def deterministic_run_id(config_digest: str, source_digests: Mapping[str, Any]) -> str:
    digest = content_hash({"config": config_digest, "sources": source_digests})
    return f"run-{digest[:16]}"
