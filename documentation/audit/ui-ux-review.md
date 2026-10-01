# Interface and experience review

## Release decision

The 29 August 2026 interface review accepts the current frontend as the local
research-release candidate. It is built for a planner who wants to go from a
question to a defensible screen without first learning the model's internal
schema. The review does not claim universal usability and does not replace
observation of representative end users.

## Interaction model

The main workflow has three steps, in this order:

1. choose a demand scenario and plainly named planning lens;
2. set an illustrative capital budget; and
3. compare the mapped portfolio, Pareto trade-offs, and candidate evidence.

Advanced map layers and corridor sketching use progressive disclosure. The
scenario, lens, budget, selected candidate, active result view, layer state,
and sketch are stored in a shareable URL. Reset is one action, print/PDF has
its own control, and exports contain the declared portfolio or exact sketched
edge set, not just the rows on screen.

Search covers the complete portfolio selection. The list renders 100 rows at a
time, with a “show more” control and a visible count; the analytical set is
never truncated. The Pareto frontier uses an exact O(n log n) calculation. Its
plot shows every frontier member plus a deterministic visual sample capped at
1,500 points, with the full eligible count and calculation scope stated beside
the chart.

The 31 August interface refinement reduces the desktop masthead to a compact
single-line title and four shallow indicators. On a phone, the same indicators
stay in one row so the page header does not double in height. The map
now offers Analysis, Light, and Streets views; changing the basemap changes
only geographic context, not the analytical state. The mapping engine is
loaded on demand, so the tile-free Analysis view does not pay its JavaScript
download cost.

## Comprehension and trust

- The interface says “Planning lens”, “capital screen”, and “lifecycle cost
  screen” instead of implying a funding recommendation.
- The 8% commute sensitivity is labelled as separate from TERP.
- Data status, run ID, model version, units, routing coverage, attribution, and
  unavailable indicators remain visible.
- Longer source and use notes have moved from a permanent footer and map panel
  into a labelled information button. Its modal separates purpose, limitations,
  data credits, and methods in short sections while keeping basemap attribution
  visible on the map itself.
- Equity and Appraisal controls are disabled when an export capability is not
  available. The source-resolution Auckland asset enables aggregate equity and
  research-only appraisal while retaining their limitations in the data
  contract and interface.
- Candidate evidence separates modelled outcome, exact-edge provenance,
  evidence coverage, uncertainty stability, and warnings.
- Zero budget has a proper empty state; exports are disabled when neither a
  portfolio nor a valid sketch exists.
- Load failures name the missing or invalid contract and offer a reload
  action instead of leaving a plausible but partial map.

## Accessibility and responsive behaviour

- semantic landmarks, headings, labels, tab roles, status regions, skip link,
  and screen-reader announcements;
- complete keyboard operation for controls, tabs, candidate selection, and
  actions;
- visible focus, WCAG AA-oriented colour contrast, inert text construction for
  source strings, and no unsafe HTML interpolation;
- desktop panels scroll independently while keeping the map and decision
  context visible; and
- a 390 × 844 layout adds Set up, Map, and Results navigation plus persistent
  scenario/run context, a usable compact legend and attribution, and no
  horizontal document overflow.

## Verification evidence

- ESLint, TypeScript, and the production build pass.
- Fifteen Vitest assertions pass.
- Playwright reports 15 applicable passes and nine intentional cross-project
  skips. Tested behaviour includes scenarios, lenses, budget/reset, full-set
  search, Pareto selection, optional layers, exact-selection export,
  graph-snapped sketching, keyboard use, responsive overflow, the map-notes
  dialog, the explicit offline-basemap state, hostile strings, and all seven
  screenshot states.
- Desktop and mobile axe scans report zero automatically detectable
  violations.
- All seven release screenshots load the source-resolution Auckland asset with
  the expected run ID, no console or page errors, and no external requests.

## Known experience constraints

The Auckland export is 326.1 MB uncompressed because candidate metrics and
geometry remain in one 217.3 MB layer and the exact-edge network is 88.7 MB.
The compressed release asset is 23.6 MB, but first use still requires parsing
the expanded layers. Local review confirmed visible loading and failure
recovery on the review machine. A future schema should split geometry from
scenario metrics and stream or index candidate records. That change must keep
checksums, full-set search, exact exports, and deterministic screenshots.

Formal moderated testing with Auckland planners, accessibility users, and
mobile users remains recommended after a Pages preview exists. Findings can be
addressed without changing the analytical contract.
