#!/usr/bin/env python3
"""Package a completed CIW run as a deterministic web-data release asset."""

from __future__ import annotations

import argparse
import json

from cycling_investment_workbench.release_assets import package_web_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("output")
    args = parser.parse_args()
    result = package_web_release(run_dir=args.run_dir, output_path=args.output)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
