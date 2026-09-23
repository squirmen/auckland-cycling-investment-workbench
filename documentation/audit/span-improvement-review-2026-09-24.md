# SPAN follow-up review — 24 September 2026

Scope: the actual SPAN repository and its effective-network research beta,
not the parent project's legacy PCT workbench. No server deployment or live
CRANC execution is part of this review.

## Improvements included in the repository update

- Publish the previously local SPAN interface, native network context,
  demand diagnostics, complete-route research engine and intersection beta
  together, with tests and reproducible scripts. Preserve existing work.
- Integrate complete journeys into the main SPAN map. Remove the unfinished
  public CRANC panel; preserve contracts and document its future insertion point.
- Document exact UI, contract, source-ledger and proposed adapter locations;
  make clear which pieces exist and which still require collaborator work.
- Disclose a newly identified scope limitation: the CRANC v1 topology/project
  check does not establish identical crop, speed or crossing-delay assumptions.
  Keep independently attributed accessibility separate from SPAN ridership.
- Add desktop/mobile browser tests for unified views, package exports, preserved
  settings, stale-data rejection and a bounded layer menu. CRANC contract unit
  tests remain; no synthetic accessibility results are published.
- Ignore collaborator ZIPs and recovered staging directories. Do not commit
  raw data, source runs, private configuration or deployment bundles.

## Prioritised follow-up work (not implemented by this review)

| Priority | Improvement and local evidence | Acceptance check |
| --- | --- | --- |
| 1 | **Validate demand support and ranking stability.** The existing ridership audit finds a few source ODs dominate some candidate gains; original within-cell spatial sampling remains sparse. | Paired independent OD-location replicates, reconciled census/suppression denominators, rank/selection stability and held-out observations. Do not fix with a uniform scaling factor. |
| 1 | **Complete the CRANC adapter and scenario contract.** Only exchange validators exist; no public panel, graph construction, project/edge crosswalk or opportunity aggregation is executed. V1 does not bind all effective routing assumptions. | Agreed provider/version/licensing, Auckland stress validation, paired scenario graphs, same origin/weight/opportunity inputs, versioned crop/time/turn/delay scope, no-change and mismatch tests. See the integration checklist. |
| 1 | **Validate crossings before intervention claims.** Only 660 of 1,289 AT records pass conservative geometric matching; 629 are held out. The original three CBD examples are ambiguous. | Manually checked multi-node junction crosswalks, AT phase/turn/detection evidence and observed waits. Do not turn unknown delay into a measured zero. |
| 2 | **Reduce browser payload and parsing cost.** Local `candidates.geojson` is about 224 MiB uncompressed; the browser currently validates candidates during load and parses them again for the model. | Profile initial-load bytes/time/peak memory on a phone; evaluate split geometry/metrics, deduplicated fields, one-time validation and lazy detail loading while retaining integrity hashes and exact rankings. |
| 2 | **Expand research coverage beyond the North Shore crop.** The current complete-route pilot covers 169 records and 195 projects, with a bounded route-choice set. | Multiple representative areas, explicit boundary failures, cold/warm timings, memory, search completion and comparison with whole-route greedy and other baselines. No citywide performance claim from this pilot. |
| 2 | **Hash the complete-journey report in the manifest.** The integrated view now rejects mismatched run/topology data, but the report still has no browser-checked content hash. | Add a hashed descriptor and corrupt-response tests alongside existing scope checks and unavailable-report behaviour. |
| 3 | **Broaden release automation.** The real-data smoke check is local; CI uses a small deterministic demo. A passing fixture does not prove a full Auckland release is complete. | Retain synthetic CI, run the full-data smoke test for each release artifact, verify an extracted archive, and record server staging/rollback checks without automatically deploying a research update. |

The first three items concern validity, not just interface polish. They remain
necessary before treating outputs as decision-grade recommendations. No new
calibration, live provider connection, ranking rewrite or server deployment is
claimed here.

## Review evidence

- `web/src/cranc.ts`, `web/src/connected.ts` and `web/index.html`: contract and future insertion point.
- `documentation/research/cranc-integration.md`: ownership, source review and gates.
- `documentation/audit/span-ridership-audit.json`: concentration and denominators.
- `documentation/research/span-effective-network.md`: matching and sensitivity results.
- `web/src/data.ts`: layer integrity checks and repeated candidate parsing.
- `web/scripts/check-span-release.mjs`: full-data desktop/mobile smoke checks.
- `.github/workflows/ci.yml`: lint, formatting, coverage, deterministic browser and accessibility checks.

Historical 12- and 169-record result summaries remain dated research evidence;
they are not silently rewritten to represent the new intersection-delay runs.
The source repository keeps its historical GitHub/package name, but the product
and intended static host are SPAN / `span.tfwelch.com`.

See [interface and TEAM review](span-interface-and-team-review-2026-09-24.md)
for the revised product hierarchy, reuse assessment and remaining gaps.
