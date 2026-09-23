#!/usr/bin/env python3
"""Build the strict CIW terrain manifest for every raster referenced by a VRT."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree import ElementTree

from cycling_investment_workbench.provenance import sha256_file, write_json_atomic


def build_manifest(vrt_path: Path, output_path: Path) -> None:
    root = ElementTree.parse(vrt_path).getroot()
    references = sorted(
        {
            (element.text or "").strip()
            for element in root.iter("SourceFilename")
            if element.get("relativeToVRT") == "1" and (element.text or "").strip()
        }
    )
    if not references:
        raise ValueError("VRT contains no relative source rasters")
    files = []
    for relative in references:
        path = (vrt_path.parent / relative).resolve()
        if not path.is_relative_to(vrt_path.parent.resolve()) or not path.is_file():
            raise ValueError(f"VRT source is missing or unsafe: {relative}")
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    write_json_atomic(output_path, {"schema_version": 1, "files": files})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("vrt", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_manifest(args.vrt.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
