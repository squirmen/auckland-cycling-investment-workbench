# Interface and experience review

## Release decision

The 29 August 2026 interface review accepts the current frontend as the local
research-release candidate. It is designed for a planner who needs to move from
a question to a defensible screen without first learning the model's internal
schema. The review does not claim universal usability or replace observation
with representative end users.

## Interaction model

The primary workflow is intentionally ordered:

1. choose a demand scenario and plainly named planning lens;
2. set an illustrative capital budget; and
3. compare the mapped portfolio, Pareto trade-offs, and candidate evidence.

Advanced map layers and corridor sketching use progressive disclosure. The
scenario, lens, budget, selected candidate, active result view, layer state,
and sketch are represented in a shareable URL. Reset is one action, print/PDF
is explicit, and exports contain the declared portfolio or exact sketched edge
set rather than an arbitrary visible-row subset.

The portfolio is searchable over its complete selection. Rendering is bounded
to 100 rows at a time with an explicit “show more” control and a visible count;
the analytical set is never truncated. The Pareto frontier uses an exact
O(n log n) calculation. Its plot renders every frontier member plus a
deterministic visual sample capped at 1,500 points, with the full eligible count
and calculation scope stated beside the chart.

## Comprehension and trust

- The interface says “Planning lens”, “capital screen”, and “lifecycle cost
  screen” instead of implying a funding recommendation.
- The 8% commute sensitivity is explicitly distinguished from TERP.
- Data status, run ID, model version, units, routing coverage, attribution, and
  unavailable indicators remain visible.
- Equity and Appraisal controls are disabled when the export capability is
  withheld. The sanitized Auckland asset contains null BCR fields, so this is
  a data contract rather than presentation-only hiding.
- Candidate evidence separates modelled outcome, exact-edge provenance,
  evidence coverage, uncertainty stability, and warnings.
- Zero budget has a genuine empty state; exports are disabled when neither a
  portfolio nor a valid sketch exists.
- Load failures identify the missing or invalid contract and provide a clear
  reload action instead of leaving a plausible but partial map.

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
- Playwright reports 13 applicable passes and nine intentional cross-project
  skips. Tested behaviour includes scenarios, lenses, budget/reset, full-set
  search, Pareto selection, optional layers, exact-selection export,
  graph-snapped sketching, keyboard use, responsive overflow, hostile strings,
  and all seven screenshot states.
- Desktop and mobile axe scans report zero automatically detectable
  violations.
- All seven release screenshots load the sanitized Auckland asset with the
  expected run ID, no console or page errors, and no external requests.

## Known experience constraints

The Auckland export is 308.6 MB uncompressed because candidate metrics and
geometry remain in one 207.7 MB layer and the exact-edge network is 88.7 MB.
The compressed release asset is 18.9 MB, but first use still requires parsing
the expanded layers; local testing took roughly 7–8 seconds on the review
machine. Loading state and failure recovery are present, but a future schema
should split geometry from scenario metrics and stream or index candidate
records. That optimisation must preserve checksums, full-set search, exact
exports, and deterministic screenshots.

Formal moderated testing with Auckland planners, accessibility users, and
mobile users remains recommended after a Pages preview exists. Findings can be
addressed without changing the analytical contract.
