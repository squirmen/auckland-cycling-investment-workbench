# Curated Auckland web-data asset

## Local release candidate

The exact browser snapshot from `run-224e9baa3be4ef73` has a deterministic,
self-describing release archive. It has not been uploaded or attached to a
GitHub release.

| Field | Value |
| --- | --- |
| Proposed asset name | `ciw-auckland-data-run-224e9baa3be4ef73.tar.gz` |
| Uncompressed browser files and asset notice | 308,550,899 bytes |
| Archive size | 18,921,866 bytes |
| Archive SHA-256 | `1a6ba2b2bbe62b59e4f88934843d4c16c6758ab41f81d225b7e307f2ef3e45e5` |
| Reproducibility | Two independent local packages produced the same byte count and SHA-256 |
| Members | `data/ASSET_NOTICE.json`, `data/manifest.json`, and five GeoJSON layers only |
| Public appraisal capability | `withheld`; BCR fields are null and the Appraisal portfolio is empty |

The archive is generated with:

```sh
uv run python scripts/package_web_release.py \
  runs/run-224e9baa3be4ef73 \
  /path/to/ciw-auckland-data-run-224e9baa3be4ef73.tar.gz
```

The packager verifies every run-declared output before writing, normalises tar
metadata and gzip time for deterministic bytes, rejects paths outside `data/`,
and verifies the completed archive. It also fails closed when a run does not
declare reviewed appraisal inputs: all candidate BCR fields become null, the
Appraisal candidate metric and portfolio become unavailable, and both the
manifest and asset notice record the reason. `ASSET_NOTICE.json` records the
source run manifest hash, every packaged data-file hash, included source IDs,
upstream licences, required attribution, withheld layers, and
research-snapshot limitations.

## Layer decisions

| Layer | SHA-256 | Release treatment |
| --- | --- | --- |
| `cells.geojson` | `92d75e7d82e6c63e4d456dd33cc9d43e3117f1dd5eb8e23dbb8a1e8b7ad0443b` | Include; Stats NZ CC BY 4.0 |
| `network.geojson` | `e14c65043caddb2163166cd226962417a813d4bb4c27c202a4d688b572592cb8` | Include as an OSM-derived database under ODbL 1.0; retain AT and LINZ CC BY attributions |
| `candidates.geojson` | `b32e75232c5eb9858b67a73ae90cc50223b8d5bfb1583b1b47a153905b8fa93b` | Include as an OSM-derived database under ODbL 1.0; retain Stats NZ, Education Counts, AT, and LINZ attributions; transit/equity metrics are absent and unreviewed BCR values are removed |
| `programmes.geojson` | `6d6b80a88dc60e65991d34024fe7cf2eb86531ffba8b75efb697fe0a601f2799` | Empty FeatureCollection; unresolved programme sources withheld |
| `counters.geojson` | `6d6b80a88dc60e65991d34024fe7cf2eb86531ffba8b75efb697fe0a601f2799` | Empty FeatureCollection; unresolved coordinate layer withheld |
| `manifest.json` | `be00d7778034606c090cd2cdbb80580f40ee741923b3bee85870ffe446f5c575` | Include; checksums, source decisions, availability, licences, warnings, and explicit appraisal withholding |

The authoritative source and layer decision chain is
[`public-layer-rights.csv`](public-layer-rights.csv). Methodological fitness is
separate from redistribution permission: the tool and archive remain labelled
as a research snapshot, the full-network connectivity point estimate is
withheld, and screening appraisal values are absent until their evidence gate
is closed.

## Publication gate

Release `v1.0.0` publishes the archive and checksum above. The separately
reviewed `.github/pages-release.json` configuration pins Pages builds to that
exact tag, asset name, and SHA-256. The workflow remains manual-only: merging
the configuration does not deploy Pages, change the custom domain, or retire
the existing site. Those actions remain separately gated.
