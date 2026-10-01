# SPAN follow-up review

24 September 2026. Scope: the SPAN repository and its effective-network research
beta, not the parent project's legacy PCT workbench. Nothing was deployed to the
server as part of this review.

## Changes in the repository update

- The previously local SPAN interface, native network context, demand
  diagnostics, complete-route research engine and intersection beta are
  published together, with tests and reproducible scripts. Existing work is kept.
- Complete journeys are part of the main SPAN map.
- Desktop/mobile browser tests cover the combined views, package
  exports, preserved settings, stale-data rejection and a bounded layer menu.
- Recovered export staging directories are ignored by git. Raw data, source
  runs, private configuration and deployment bundles are not committed.

## Prioritised follow-up work (not done in this review)

| Priority | Improvement and local evidence | Acceptance check |
| --- | --- | --- |
| 1 | **Validate demand support and ranking stability.** The existing ridership audit finds a few source ODs dominate some candidate gains; original within-cell spatial sampling remains sparse. | Paired independent OD-location replicates, reconciled census/suppression denominators, rank/selection stability and held-out observations. A uniform scaling factor is not a fix. |
| 1 | **Validate crossings before intervention claims.** Only 660 of 1,289 AT records pass conservative geometric matching; 629 are held out. The original three CBD examples are ambiguous. | Manually checked multi-node junction crosswalks, AT phase/turn/detection evidence and observed waits. Unknown delay is not recorded as a measured zero. |
| 2 | **Reduce browser payload and parsing cost.** Local `candidates.geojson` is about 224 MiB uncompressed; the browser currently validates candidates during load and parses them again for the model. | Profile initial-load bytes/time/peak memory on a phone; evaluate split geometry/metrics, deduplicated fields, one-time validation and lazy detail loading while keeping integrity hashes and exact rankings. |
| 2 | **Expand research coverage beyond the North Shore crop.** The current complete-route pilot covers 169 records and 195 projects, with a bounded route-choice set. | Multiple representative areas, reported boundary failures, cold/warm timings, memory, search completion and comparison with whole-route greedy and other baselines. No citywide performance claim from this pilot. |
| 2 | **Hash the complete-journey report in the manifest.** The integrated view now rejects mismatched run/topology data, but the report still has no browser-checked content hash. | Add a hashed descriptor and corrupt-response tests alongside existing scope checks and unavailable-report behaviour. |
| 3 | **Broaden release automation.** The real-data smoke check is local; CI uses a small deterministic demo. A passing fixture does not prove a full Auckland release is complete. | Keep synthetic CI, run the full-data smoke test for each release artifact, verify an extracted archive, and record server staging/rollback checks without automatically deploying a research update. |

The two priority 1 items are about validity. Both are needed before the outputs
can be treated as decision-grade recommendations. This review claims no new
calibration, ranking rewrite or server deployment.

## Review evidence

- `web/src/connected.ts` and `web/index.html`: complete journeys in the main map.
- `documentation/audit/span-ridership-audit.json`: concentration and denominators.
- `documentation/research/span-effective-network.md`: matching and sensitivity results.
- `web/src/data.ts`: layer integrity checks and repeated candidate parsing.
- `web/scripts/check-span-release.mjs`: full-data desktop/mobile smoke checks.
- `.github/workflows/ci.yml`: lint, formatting, coverage, deterministic browser and accessibility checks.

The historical 12- and 169-record result summaries remain dated research
evidence; they are not silently rewritten to represent the new intersection-delay
runs. The source repository keeps its historical GitHub/package name, but the
product is SPAN and the intended static host is `span.tfwelch.com`.

See the [interface and TEAM review](span-interface-and-team-review-2026-09-24.md)
for the revised product hierarchy, reuse assessment and remaining gaps.
