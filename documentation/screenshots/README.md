# Release screenshot specification

Screenshots are generated locally from the exact web export proposed for
release. Desktop masters are lossless 1800 × 1100 PNGs at device scale 1 with
browser chrome excluded. The approved current state is offline with only local,
rights-cleared layers; hosted CARTO tiles are disabled and must not be captured.
Any later basemap requires a separately recorded licence and attribution
decision. Keep attribution, legend, scenario, units, data status, and run
identifier visible. Do not expose local paths, tokens, developer panels,
personal details, or restricted data.

The current set was captured from the completed Auckland research snapshot,
run `run-224e9baa3be4ef73`. Each image visibly retains the research-snapshot
status and run identifier. The set does not imply release approval: equity,
appraisal, programme, and public-counter content is omitted or explicitly shown
as withheld where rights, evidence, or lineage remain unresolved.

Store each capture under the same basename in three subdirectories:

- `full/`: lossless 1800 × 1100 PNG master;
- `web/`: optimised WebP copy for the README and documentation; and
- `thumbnails/`: aspect-preserving WebP preview for documentation indexes.

`manifest.csv` records basename, caption, alt text, pixel dimensions, CSS
viewport, device scale, scenario, purpose, budget, selected candidate, run ID,
data status, capture date, basemap state, and master/web/thumbnail SHA-256
checksums. All seven Auckland research-snapshot rows are complete for run
`run-224e9baa3be4ef73`. The responsive capture records its native 390 × 844 CSS
viewport separately from the neutral 1800 × 1100 master canvas.

Required basenames:

| Basename | Required state | Required alt text |
| --- | --- | --- |
| `workbench-overview` | Hero overview with 8% sensitivity, core KPIs, map, selected portfolio, budget, and run identity | “Auckland Cycling Investment Workbench showing the 8% commute sensitivity, model indicators, regional candidate map, and a cumulative 100 million dollar portfolio.” |
| `pareto-frontier` | Go Dutch trade-off view with axes and units visible; dominated and non-dominated candidates distinguishable | “Auckland candidate trade-off plot showing lifecycle cost against additional usual commute cyclists, with the non-dominated frontier highlighted.” |
| `candidate-evidence` | Beach Road exact-edge treatment, counterfactual outcome, evidence profile, public-appraisal gate, and warnings | “Beach Road candidate inspector showing exact-edge treatment, capital and lifecycle cost screens, additional commute cyclists, evidence coverage, frontier stability, and the withheld public appraisal status.” |
| `equity-purpose-portfolio` | School-purpose preset and cumulative portfolio; caption states that equity remains omitted pending NZDep rights | “Auckland school-access portfolio showing a cumulative 100 million dollar screen and person-equivalent impedance improvement; the equity preset is not displayed because NZDep redistribution rights remain unresolved.” |
| `network-validation-overlays` | Exact candidate-edge graph with the unavailable programme and public-counter layers explicitly declared | “Present-day Auckland view showing the exact candidate-edge graph and controls for programme and validation layers, with both overlays explicitly empty pending rights and source-lineage resolution.” |
| `custom-corridor` | Graph-snapped Beach Road path, edge-level status, and the selection/export controls | “Auckland workbench showing a 1.57 kilometre graph-snapped Beach Road corridor, its edge-level screening summary, and controls for exporting the declared portfolio and exact edge identifiers.” |
| `responsive-mobile` | Narrow responsive map and selected-candidate evidence with attribution and run context still usable | “Narrow responsive Auckland workbench showing the regional map, persistent run context, compact attribution, analysis tabs, and Beach Road candidate evidence within a 390 by 844 CSS-pixel viewport.” |

The responsive capture uses its documented narrow CSS viewport and is centred
on a plain neutral 1800 × 1100 master canvas. The recorded CSS viewport and
canvas dimensions remain separate; no device chrome or page-content alteration
is introduced.

Before publication, verify every value against the checksummed export, all
three directories contain all seven basenames in the declared formats, every
checksum is populated, WebP copies remain legible, and the hero WebP is the
file embedded by the root README. These file-integrity checks are complete for
the Auckland research snapshot. Public use still depends on the remaining
method, validation, manual-audit, asset-rights, and Git approval gates.

The captures are reproducible from a local server hosting the built frontend
with the curated Auckland asset extracted over its `data/` directory:

```sh
CIW_SCREENSHOT_BASE_URL=http://127.0.0.1:4175/ \
CIW_EXPECTED_RUN_ID=run-224e9baa3be4ef73 \
npm --prefix web run capture:screenshots
```

The capture script verifies the run identity, rejects runtime or console
errors, rejects external requests, resets the viewport deterministically, and
uses the versioned states in `web/screenshot-states.json`.
