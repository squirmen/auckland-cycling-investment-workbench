# Documentation map

Notes added for SPAN:

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
- [Junction delays and Connected journeys](research/span-effective-network.md)
- [Server handoff](audit/span-server-handoff.md)
- [SPAN interface and TEAM reuse review](audit/span-interface-and-team-review-2026-09-24.md)
- [CRANC integration guide](research/cranc-integration.md#where-to-connect-cranc)
- [24 September improvement review](audit/span-improvement-review-2026-09-24.md)
- [Complete-route experiment](research/span-access-first-experiment.md)
- [Research methodology review](research/methodology-review-2026-09.md)

| Folder | What it holds |
| --- | --- |
| `methodology/` | The normative method, parameters, validation, uncertainty and limitations |
| `research/` | SPAN research notes: junction delays and Connected journeys, crossing-cost evidence, the September method review |
| `audit/` | Dated evidence: release records, reviews, experiments and the server handoff |
| `equations/` | LaTeX for the model's equations |
| `references/` | The bibliography and evidence matrix |
| `screenshots/` | Release screenshots and their manifest |
| `white-paper/` | Editorial plans for the paper, not results |

`roadmap.md` holds the ordered work and its status.

The public SPAN research beta uses Auckland research snapshot
`run-313e0277521633d3`. Release v2.0.0 (commit `2d9db50`) was deployed to
[span.tfwelch.com](https://span.tfwelch.com) on 1 October 2026, after `701fc6e`,
`2a97084` and `92e2f12` earlier that day and `0937175` from 24 September. All of
them use the same run's model values. Being public does not make the run's
derived values decision-ready or its uptake estimates calibrated. New audit
outputs are repository evidence; they do not change the deployed model.

Release and validation gates are in
[`audit/release-readiness.md`](audit/release-readiness.md). A box is checked
there only when the repository holds the evidence, not when the work is planned.
The authoritative include, omit and block decisions for public data are in
[`audit/public-layer-rights.csv`](audit/public-layer-rights.csv); a
configuration label alone does not clear a layer for publication.
