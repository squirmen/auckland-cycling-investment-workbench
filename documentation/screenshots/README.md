# Release screenshot specification

Screenshots are generated locally from the exact web export proposed for
release. Desktop masters are lossless 1800 × 1100 PNGs at device scale 1,
without browser chrome. The approved capture state is Analysis with local,
rights-cleared layers only. OpenFreeMap is cleared for live contextual use, but
its hosted tiles are not used in the deterministic captures; CARTO remains
disabled. Attribution, legend, scenario, units, data status, and run
identifier stay visible. Local paths, tokens, developer panels, personal
details, and restricted data must not appear.

OpenStreetMap attribution remains on the map itself. The Auckland analysis
shown in these images includes Stats NZ data licensed for reuse under CC BY
4.0, Auckland Transport cycle-facility data, and LINZ elevation data licensed
for reuse under CC BY 4.0. Full dataset and database notices are in
[`../../NOTICE.md`](../../NOTICE.md) and accompany the images when they are
reused.

The checked-in set was captured from the completed source-resolution research
snapshot, run `run-313e0277521633d3`. It shows research-only appraisal,
aggregate equity, programme, approximate counter and disclosure-safe safety
context; none of it is presented as decision-ready. Full-network low-stress
connectivity is not reported.

The seven captures below are the v1.0.0 release record and show the interface
as it was then. The root README now shows the current SPAN interface from
`span/span-link-detail.webp`, captured on 1 October 2026 from the same run at
1440 × 900 with the Plain background, so it contains no hosted map tiles.

Each capture is stored under the same basename in three subdirectories:

- `full/`: lossless 1800 × 1100 PNG master
- `web/`: optimised WebP copy for documentation
- `thumbnails/`: aspect-preserving WebP preview for documentation indexes

`manifest.csv` records basename, caption, alt text, pixel dimensions, CSS
viewport, device scale, scenario, purpose, budget, selected candidate, run ID,
data status, capture date, basemap state, and master/web/thumbnail SHA-256
checksums. All seven Auckland research-snapshot rows are complete for run
`run-313e0277521633d3`. The responsive capture records its native 390 × 844 CSS
viewport separately from the neutral 1800 × 1100 master canvas.

Required basenames:

| Basename | Required state | Required alt text |
| --- | --- | --- |
| `workbench-overview` | Hero overview with 8% sensitivity, core KPIs, map, selected portfolio, budget, and run identity | “Auckland Cycling Investment Workbench showing the 8% commute sensitivity, model indicators, regional candidate map, and a cumulative 100 million dollar portfolio.” |
| `pareto-frontier` | Go Dutch trade-off view with axes and units visible; dominated and non-dominated candidates distinguishable | “Auckland candidate trade-off plot showing lifecycle cost against additional usual commute cyclists, with the non-dominated frontier highlighted.” |
| `candidate-evidence` | Exact-edge treatment, research-only indicative appraisal interval, evidence profile and warnings | “Auckland candidate inspector showing an exact-edge treatment, lifecycle costs, an indicative BCR interval, evidence coverage, frontier stability and the research-only appraisal warning.” |
| `equity-purpose-portfolio` | NZDep decile 8–10 origin objective and cumulative portfolio with the distributional boundary visible | “Auckland equity portfolio showing additional usual commuters from high-deprivation origins, cumulative cost and the warning that the view is not a causal equity effect or welfare weight.” |
| `network-validation-overlays` | Exact candidate-edge graph with Future Connect, RLTP, approximate counter and disclosure-safe safety layers | “Present-day Auckland view showing candidate edges, Future Connect and RLTP context, approximate July 2026 cycle-counter sites and suppressed 500 metre cycle-crash cells.” |
| `custom-corridor` | Graph-snapped Beach Road path, edge-level status, and the selection/export controls | “Auckland workbench showing a 1.57 kilometre graph-snapped Beach Road corridor, its edge-level screening summary, and controls for exporting the declared portfolio and exact edge identifiers.” |
| `responsive-mobile` | Narrow responsive map and selected-candidate evidence with attribution and run context still usable | “Narrow responsive Auckland workbench showing the regional map, persistent run context, compact attribution, analysis tabs, and Beach Road candidate evidence within a 390 by 844 CSS-pixel viewport.” |

The responsive capture is centred on the plain neutral 1800 × 1100 master
canvas, with no device frame and no change to page content.

Before publication, check that every value matches the checksummed export,
that all three directories hold all seven basenames in the declared formats,
that every checksum is filled in, and that the WebP copies are legible. These
file checks are complete for the Auckland research snapshot. Public use still
depends on the remaining method, validation, manual-audit, and asset-rights
gates.

The captures are reproducible from a local server hosting the built frontend
with the curated Auckland asset extracted over its `data/` directory:

```sh
CIW_SCREENSHOT_BASE_URL=http://127.0.0.1:4175/ \
CIW_EXPECTED_RUN_ID=run-313e0277521633d3 \
npm --prefix web run capture:screenshots
```

The capture script checks the run identity, fails on runtime or console errors
and on external requests, resets the viewport the same way each time, and uses
the versioned states in `web/screenshot-states.json`.
