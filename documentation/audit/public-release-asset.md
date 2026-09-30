# Curated Auckland web-data asset

## Local release candidate

The exact browser snapshot from `run-313e0277521633d3` has been packaged twice
with byte-for-byte identical output. It has not been uploaded or attached to a
GitHub release.

| Field | Value |
| --- | --- |
| Local asset name | `auckland-cycling-investment-workbench-run-313e0277521633d3.tar.gz` |
| Uncompressed members | 326,076,352 bytes |
| Archive size | 23,646,468 bytes |
| Archive SHA-256 | `544f920eff526aecaf03176eadceaa5ec42c3dafbe4fd614ce883d6ccc7816b8` |
| Reproducibility | Two independent local packages produced the same byte count and SHA-256 |
| Members | `data/ASSET_NOTICE.json`, `data/manifest.json`, and six GeoJSON layers |
| Appraisal capability | `research_only`; candidate BCR intervals are exposed only with the declared caveats |
| Equity capability | `available`; aggregate NZDep decile 8–10 origin objective only |
| Low-stress connectivity | Intentionally unreported; all Auckland point-estimate fields remain null |

The packager verifies every run-declared output, normalises tar metadata and
gzip time for deterministic bytes, rejects paths outside `data/`, and verifies
the completed archive. `ASSET_NOTICE.json` records the source run, every
packaged file hash, included source IDs, licences, required attribution and the
research-snapshot limitations.

## Layer decisions

| Layer | SHA-256 | Release treatment |
| --- | --- | --- |
| `cells.geojson` | `d8333ddcc665a631ff8ed0e22c795b4f2974ae1bb2ed8fec8897978419d94cfd` | Include; Stats NZ CC BY 4.0 |
| `network.geojson` | `a8a2d4a84f3c497cf95196ef839a6919b22e83035eac692a96ee6e76d8a9ffe3` | Include as an OSM-derived database under ODbL 1.0; retain AT and LINZ attributions |
| `candidates.geojson` | `34fc6c744bba508cadda8f6c201a23c92bfad3462c07e344f60ab2404d48ee0a` | Include; purpose metrics, aggregate equity and research-only appraisal retain their declared limitations |
| `programmes.geojson` | `09c9a73f978e76c58213b4dcfa941f20ad6eb9625d65be70665c866b92a232c1` | Include 2,017 strategic/planned/committed features; Future Connect is not presented as funded |
| `counters.geojson` | `16b019e47e36a8c4237ae7a101485c854387b9157c40a4cc2f67afb1aae44ecd` | Include 73 approximate July 2026 plausibility sites; not predictive validation |
| `safety.geojson` | `95bb96e3f3a023215d6d274e764def4392f664ec60e176cc152660c2985a5852` | Include 250 disclosure-safe 500 m cells; raw CAS records remain excluded |
| `manifest.json` | `8166ea14b64b6ca36410c4915ffbd66f8c7568db777a8923bb54f918d0a95d40` | Include; checksums, licences, capabilities, warnings and validation status are explicit |

The authoritative decision chain is
[`public-layer-rights.csv`](public-layer-rights.csv). Redistribution permission
does not make a result decision-ready: the asset remains a research snapshot,
cycle counters remain a plausibility check, appraisal remains indicative, and
full-network low-stress connectivity remains reserved for the separate
sabbatical research integration.

## Publication gate

The existing `v1.0.0` release and Pages configuration point to the previous
public snapshot. Replacing that asset or deployment requires a separately
reviewed staging set, commit, push, pull request, release asset and Pages
approval. This document records local evidence only.
