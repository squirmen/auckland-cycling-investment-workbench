# SPAN: budgeted connectors and smaller candidate loading

25 September 2026. Follow-up to the [short-link diagnosis](span-candidate-coverage-2026-09-25.md).
The connector results below remain experiments. The loading change preserves
the published model values; neither change has been deployed in this pass.

## Short connections within a budget

The new `--budget-short-connectors` option tests whole excluded short chains in
an additional budgeted portfolio, on the same sampled journeys as the original
experiment. It does not replace the original portfolio, route assignment or
browser report. Every selected short project is charged once, including when
several journeys share it.

Original feasible route columns are retained and checked against the expanded
graph. This prevents a capped search from discarding known alternatives when
more projects become available. All three methods receive the same resulting
route union. Each route is independently checked for directed continuity,
endpoints, required projects, turn prohibitions, intersection stress and delays,
distance, travel time and cost. Every reported served journey must have a fully
funded checked route.

### Paired results at a NZ$20m cap

| Area | Original → connector-enabled sample journeys | Selected package cost | Short connectors selected | Connector cost within package |
| --- | ---: | ---: | ---: | ---: |
| Ponsonby Road | 5 → 8 | NZ$18.92m | 13 | NZ$4.05m |
| Hospital Road | 0 → 1 | NZ$15.67m | 9 | NZ$1.85m |
| Grand Drive | 1 → 3 | NZ$16.93m | 13 | NZ$4.11m |
| Shelly Beach Road | 0 → 0 | NZ$0 | 0 | NZ$0 |

The first three areas each use 24 sampled records; Shelly Beach has only one
eligible record. The objective maximises their retained eligible-demand weights,
not the number of records served. These are **not additional cyclists**, observed
trips or area-wide estimates. They must not be expanded into forecasts.

The package optimiser and whole-route greedy method tie on served weight,
journey count and cost in all four NZ$20m tests. Single-project greedy connects
two Ponsonby records and none in the other areas. There is still no evidence
here of an optimiser advantage over the strong whole-route greedy baseline.

### Important limits

Budgeted connector searches hit the 15,000-label cap for 15/24 Ponsonby records,
16/24 Hospital Road records and 18/24 Grand Drive records. Shelly Beach's single
search completes. The generated route unions contain 431, 239 and 460 columns
in the three urban areas, including 28, zero and three retained original columns.
Solver optimality applies to those route columns, not all possible routes.
Search convergence needs more work before these results can support planning.

The 4 km crops, exact source directions, LTS ≤ 2 threshold, 1.5-times-shortest
in-crop distance limit, 30-minute limit and assumed crossing delays are unchanged.
Partial chains crossing the boundary are not restored. The original provisional
NZ$6,000/m screening rate is used for short works; real crossing treatments,
fixed project costs, street widths and engineering feasibility are not established.

The [aggregate report](span-budgeted-connectors-2026-09-25.json) records original
and connector-enabled portfolios separately, source and implementation hashes,
search limits and checked-witness counts. The public summary explicitly selects
aggregate fields so future private journey diagnostics cannot be copied through
automatically. Source runs and published rankings remain unchanged.

## Smaller candidate data, with the same model values

The release build now produces a versioned compact candidate file alongside the
canonical GeoJSON. Repeated metric objects use a shared table, with field names
defined once by the format version. No coordinates or numeric values are rounded,
and no scenarios or purposes are dropped. Each distinct metric is validated once
on decoding and kept immutable when shared.

The manifest binds the compact bytes to both their own SHA-256 and the canonical
source layer's SHA-256. The browser checks these bindings and the feature count
before using the result. It does not also download the canonical file. A corrupt
compact file fails explicitly; there is no unchecked fallback. Older exports
without the descriptor keep their existing verified GeoJSON loading path.

Every browser-validated field in all 12,580 candidates was compared exactly after
decoding, including metrics, geometry, route use and network context. Canonical
GeoJSON remains bundled for reproducibility and retains its original checksum.
The build stops if the metric schema changes without updating the format.

| Measure | Canonical representation | Compact representation |
| --- | ---: | ---: |
| Uncompressed JSON | 234,894,737 bytes | 96,057,996 bytes |
| Locally computed gzip size | 14,103,477 bytes | 12,568,753 bytes |
| Median parse + validation, three fresh Node processes | 1.140 s | 0.861 s |
| Median peak process RSS | 1,372,048 KiB | 867,312 KiB |

That is about 59% less uncompressed JSON, 11% less estimated gzip transfer,
24% less decode time and 37% lower peak process memory in this local test.
These are not total page-load, browser-heap or real-phone measurements. Timing
excludes hashing, networking, filesystem reads, compression and map rendering.
The candidate dataset is still large; staged loading remains a useful next step.

[Raw measurements, order and limitations](span-candidate-loading-2026-09-25.json).
The browser layout is unchanged: no extra controls, notices or research page.

## Verification and next steps

341 Python tests pass with 81.23% coverage. Web typecheck, lint, production build
and 55 unit tests pass. Desktop/mobile regression tests: 35 pass, with nine
intentional platform-specific skips.

The desktop/mobile suite covers compact loading and rejection of modified bytes,
alongside the existing accessibility, export and state tests. The full Auckland
build passes map, intersection, package, route and export smoke checks without
runtime or HTTP errors; it requests the compact file and not the canonical copy.
The local release archive passes packaging and integrity checks, but is not deployed.

Next: test search-cap convergence on paired journeys, check crossing-specific
treatments and costs, and reduce initial browser work further through staged
data loading. Demand calibration, independent spatial support and external
comparative validation remain priorities; more connected sample records alone
do not establish better real-world investment decisions.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-411d92bafee5f5d1 --area-label "Hospital Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --test-short-connectors --budget-short-connectors \
  --output build/pilots/hospital-budget-connectors-24.json

# After building web/dist with the repository's pinned Node environment:
node web/scripts/profile-candidates.mjs verify
node web/scripts/profile-candidates.mjs canonical
node web/scripts/profile-candidates.mjs compact
```

Use the other anchor IDs in the aggregate report for the paired area runs, and
`scripts/summarise_span_pilots.py` to rebuild the public summary. Runtime results
vary across runs; the canonical and compact payload hashes should not.
