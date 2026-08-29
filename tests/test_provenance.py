from __future__ import annotations

import json
from pathlib import Path

import pytest

from cycling_investment_workbench.provenance import (
    ProvenanceError,
    canonical_json,
    content_hash,
    deterministic_run_id,
    hash_path,
    portable_path,
    read_json,
    runtime_provenance,
    write_json_atomic,
)


def test_canonical_json_and_hash_ignore_mapping_insertion_order() -> None:
    left = {"b": [2, 1], "a": {"value": True}}
    right = {"a": {"value": True}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert content_hash(left) == content_hash(right)


def test_atomic_json_round_trip(tmp_path: Path) -> None:
    destination = tmp_path / "nested/result.json"

    write_json_atomic(destination, {"b": 2, "a": 1})

    assert read_json(destination) == {"a": 1, "b": 2}
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert not list(destination.parent.glob("*.tmp"))


def test_tree_hash_changes_with_file_content(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("one", encoding="utf-8")
    first = hash_path(tree)
    (tree / "a.txt").write_text("two", encoding="utf-8")
    second = hash_path(tree)

    assert first.sha256 != second.sha256
    assert first.size == second.size == 3


def test_symbolic_link_artifact_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(source)

    with pytest.raises(ProvenanceError, match="symbolic links"):
        hash_path(link)


def test_portable_path_rejects_external_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ProvenanceError, match="outside the project root"):
        portable_path(tmp_path / "elsewhere", root=project)


def test_run_id_is_stable_and_prefixed() -> None:
    first = deterministic_run_id("a" * 64, {"source": {"sha256": "b" * 64}})
    second = deterministic_run_id("a" * 64, {"source": {"sha256": "b" * 64}})

    assert first == second
    assert first.startswith("run-")
    assert len(first) == 20


def test_runtime_provenance_has_version_slots() -> None:
    runtime = runtime_provenance(packages=("PyYAML", "package-that-is-not-installed"))

    assert runtime["python"]
    assert runtime["packages"]["PyYAML"]
    assert runtime["packages"]["package-that-is-not-installed"] is None
    assert "jvm" in runtime
    assert "r5_engine" in runtime
    json.dumps(runtime)
