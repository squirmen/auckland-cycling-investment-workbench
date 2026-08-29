# AT cycle-counter plausibility audit

## Decision

The July 2026 AT counter workbook is now an exact, reproducible observation
source. The resulting site-to-edge ledger is useful for checking whether known
count locations fall near the routed graph. It is **not** predictive validation
or calibration of CIW demand: AT reports daily all-purpose cycle movements,
whereas the comparable CIW field is a census-derived count of people whose
usual commute mode is bicycle. Error, regression, calibration, and null-model
statistics across those incompatible units are intentionally not reported.

The counter layer remains empty in the public Auckland snapshot. The inherited
coordinate registry has been audited by exact name and geometry, but its exact
AT publisher-file lineage, direction, and screenline identifiers have not been
recovered.

## Immutable evidence

| Item | Record |
| --- | --- |
| Publisher | Auckland Transport |
| Workbook | [Daily Cycle Count Data July 2026](https://at.govt.nz/media/zj0lgcmg/at-daily-cycle-count-data-july-2026.xlsx) |
| Publisher page and terms | [Monthly cycle monitoring](https://at.govt.nz/cycling-walking/research-monitoring/monthly-cycle-monitoring/), CC BY 4.0 |
| Workbook SHA-256 | `f0488b5fd5f315ea71ab2532a5ac402f7194741fb62c2ed9fc8e2d264c64d210` |
| Observation period | 1–31 July 2026; 31 daily rows |
| Published columns | 83 counter columns |
| Coordinate registry | May 2026 legacy dashboard registry; 86 named points; SHA-256 `6004b7c8f534e8c6d41b7b2917e7682a00c5c2822b7846688609a60f1fc0ecbf` |
| Reviewed mapping | [`configs/at-cycle-counter-mapping.yml`](../../configs/at-cycle-counter-mapping.yml) |
| Retained output | 73 sites; location JSON SHA-256 `b0ddc052b851b1302cf622d8b018b2c51b29ef1cc127a4b97eb930d830b2bf09`; observation JSON SHA-256 `7e1ef887f223d7e516a5825d2eb10c74af250b16ac3183a1cb25f3679bf947b8` |

Reproduce the two configured JSON inputs outside Git with:

```sh
uv run ciw data prepare-at-counters \
  --config configs/auckland.yml \
  --data-root /path/to/ciw-data \
  --workbook /path/to/at-daily-cycle-count-data-july-2026.xlsx \
  --coordinate-registry /path/to/reviewed-coordinate-registry.json
```

The command reads the publisher XLSX without a spreadsheet-library dependency,
requires the reviewed coordinate-registry hash, requires one explicit mapping
or exclusion for every publisher column, rejects one coordinate registry entry
being reused for multiple counters, and records daily values, means, period,
licence, source URL, hashes, and exclusions.

## Exclusions resolved during review

Ten workbook columns are excluded:

- `Great North Rd` and `Ti Rakau - Near 210 Cyclist`: no July observations;
- `Gt Sth Rd - Ellerslie`, `Merton Rd Cyclist`, and both Line Road ends: no
  unambiguous distinct point in the inherited registry;
- `Ti Rakau - Roseburn Place Cyclist`: several nearby registry points are
  plausible and no publisher identifier resolves the ambiguity;
- `Great South Rd Manukau`: the inherited unsuffixed Great South Road point
  resolves near Grafton, not the named Manukau site; and
- `SH20A Cyclist` and `SH20B Cyclist`: the registry gives both different
  counters the same coordinate without bearing or screenline identity.

The last three decisions were found by the spatial audit; accepting a fuzzy
name match would have created false evidence.

## Spatial ledger result

All 73 retained points match at least one graph edge within the configured
100 m gate. Match-distance diagnostics are:

| Statistic | Distance |
| --- | ---: |
| Minimum | 0.06 m |
| Median | 2.62 m |
| 90th percentile | 9.64 m |
| Maximum | 56.67 m |

The farthest retained matches were inspected against topology attributes. The
Ti Rakau near-180 point matched an OSM shared path at 56.67 m; Waterview Unitec
matched a shared path at 41.83 m; Grafton Gully matched a shared path at
17.36 m; New Lynn–Avondale matched a shared path at 14.82 m; Mahia Road matched
an arterial mixed-traffic edge at 13.01 m; and Franklin Road matched a protected
lane at 12.51 m. These remain distance-only associations—not audited direction
or screenline matches.

## Release consequence

- The exact observation workbook and derived observation JSON are cleared
  under AT's CC BY 4.0 statement.
- The point layer stays local and the browser exports an empty, checksummed
  counter FeatureCollection.
- No model flow is rescaled from these counts.
- A future predictive validation requires a present-day, purpose- and
  period-compatible model target plus publisher site IDs, bearing/direction,
  and screenline definitions. Spatially blocked holdouts apply only if those
  comparable observations are used for model fitting.
