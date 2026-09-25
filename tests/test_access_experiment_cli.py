import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_access_experiment.py"


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--radius-m", "nan"),
        ("--radius-m", "inf"),
        ("--radius-m", "0"),
        ("--budget-m", "nan"),
        ("--budget-m", "-1"),
        ("--sample-size", "0"),
        ("--max-labels", "0"),
    ],
)
def test_bad_pilot_bounds_rejected_before_reading_data(tmp_path, flag, value):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(tmp_path / "missing"), flag, value],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "pilot bounds must be positive" in result.stderr


def test_research_output_cannot_overwrite_source_run(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run",
            str(tmp_path),
            "--output",
            str(tmp_path / "bad.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "outside the immutable source run" in result.stderr


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--connector-label-limits", "15000", "30000"], "require --budget-short-connectors"),
        (["--connector-fixed-costs-nzd", "100000"], "require --budget-short-connectors"),
        (["--budget-short-connectors", "--connector-label-limits", "30000"], "increase from"),
        (
            ["--budget-short-connectors", "--connector-label-limits", "15000", "10000"],
            "increase from",
        ),
        (
            ["--budget-short-connectors", "--connector-fixed-costs-nzd", "nan"],
            "finite and non-negative",
        ),
        (
            ["--budget-short-connectors", "--connector-fixed-costs-nzd", "-1"],
            "finite and non-negative",
        ),
    ],
)
def test_connector_sensitivity_bounds_checked_before_reading_data(tmp_path, arguments, message):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run", str(tmp_path / "missing"), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr
