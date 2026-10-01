# Documentation map

This directory separates the public method, release evidence, white-paper
planning material, equations, references, and visual record.

Current SPAN additions:

- [Priorities and acceptance criteria](roadmap.md)
- [A second way to generate routes](audit/span-priced-routes-2026-10-01.md)
- [Loading speed and interface fixes](audit/span-loading-and-interface-2026-10-01.md)
- [Staged candidate loading and tighter search bounds](audit/span-staged-loading-and-stress-bounds-2026-09-26.md)
- [Crossing costs: evidence needed](research/crossing-cost-evidence.md)
- [Search limits and short-link cost sensitivity](audit/span-search-and-cost-sensitivity-2026-09-25.md)
- [Budgeted short connectors and smaller candidate loading](audit/span-budgeted-connectors-and-loading-2026-09-25.md)
- [Short-link exclusions and connector diagnostics](audit/span-candidate-coverage-2026-09-25.md)
- [Fresh routing, four-area checks and reliability fixes](audit/span-follow-up-progress-2026-09-24.md)
- [Source-cell influence audit and next sampling work](audit/span-source-cell-influence-2026-09-24.md)
- [Effective-network beta and server handoff](research/span-effective-network.md)
- [SPAN interface and TEAM reuse review](audit/span-interface-and-team-review-2026-09-24.md)
- [CRANC entry points and adapter checklist](research/cranc-integration.md#where-to-connect-cranc)
- [24 September improvement review](audit/span-improvement-review-2026-09-24.md)
- [Complete-route experiment](research/span-access-first-experiment.md)
- [Research methodology review](research/methodology-review-2026-09.md)

| Folder | What it holds |
| --- | --- |
| `methodology/` | The normative method, parameters, validation, uncertainty and limitations |
| `research/` | SPAN research notes: the CRANC integration guide, junction delays and Connected journeys, crossing-cost evidence, the September method review |
| `audit/` | Dated evidence: release records, reviews, experiments and the server handoff |
| `equations/` | LaTeX for the model's equations |
| `references/` | The bibliography and evidence matrix |
| `screenshots/` | Release screenshots and their manifest |
| `white-paper/` | Editorial plans for the paper, not results |

`roadmap.md` holds the ordered work and its status.

The methodology documents are normative for interpretation. The white-paper
files are editorial plans, not results. The Auckland research snapshot
`run-313e0277521633d3` underpins the public SPAN research beta; release
v2.0.0 (commit `2d9db50`) was deployed to [span.tfwelch.com](https://span.tfwelch.com)
on 1 October 2026, after `701fc6e`, `2a97084` and `92e2f12` earlier that day and
`0937175` from 24 September. The model values are the same run. Public availability does not make its derived values
decision-ready or its uptake estimates calibrated. New audit outputs are
repository evidence, not changes to that deployed model.
Release and validation gates are recorded in
[`audit/release-readiness.md`](audit/release-readiness.md); a checked box there
requires repository evidence, not an intention to complete the item later.
The authoritative public-data include, omit, and block decisions are in
[`audit/public-layer-rights.csv`](audit/public-layer-rights.csv); configuration
labels alone do not clear a layer for publication.
