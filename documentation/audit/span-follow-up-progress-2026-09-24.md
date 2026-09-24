# SPAN: demand, area coverage and reliability

24 September 2026. Follow-up to the [priorities](../roadmap.md) and
[source-cell influence audit](span-source-cell-influence-2026-09-24.md).
These are research checks, not a replacement for the deployed recommendations.

Follow-up on 25 September: [candidate coverage tracing and short-connector tests](span-candidate-coverage-2026-09-25.md)
resolve the missing-candidate diagnostic below. The original results in this
note remain the paired reference.

## 1. Fresh routing through the stored demand support

The commute ledger contains 695,488 stored location pairs in 28,173 source OD
cells, with 7–25 distinct pairs per cell. The published routing sample uses one
pair per cell. Of those selected pairs, 28,056 assigned and 117 failed.
These are model records with population weights, not observed individual riders.

The new pilot enumerated every stored pair in the 12 influential cells identified
by the preceding audit: 291 pairs, routed afresh on the full bounded Auckland
network with the pinned R5 adapter and unchanged parameters. There was no local
network crop. All 12 original sampled pairs reproduced their published directed
edge paths, costs and probabilities. Of the 291 attempts, 286 assigned; five
could not find a compatible snap pair and remain explicit unknowns.

For each project below, this table concerns **only its influential source cell**,
not the project's whole market. It measures the source-weighted probability
that a retained baseline route uses any part of the project.

| Project | Original sampled pair | All stored locations in that cell |
| --- | ---: | ---: |
| Beach Road | 100% | 96.0% |
| Shelly Beach Road | 100% | 16.0–36.0% |
| Grand Drive | 100% | 60.5% |
| Hospital Road | 100% | 52.0% |

Shelly Beach Road's interval includes its five routing failures as unknown use.
It is not a confidence interval. The original sample helped select these
influential cells, so this is a targeted check, not an unbiased comparison of
project performance across Auckland.

The pilot also compares one- and five-record draws using three independent
seeds: 20260924, 20260925 and 20260926. All methods use the same enumerated
support, not newly generated addresses. Existing inverse-inclusion weights
are retained. The source support totals stay fixed, but Horvitz–Thompson
estimates of those totals can vary between draws because some stored pairs
have unequal mass; the reports disclose this rather than silently renormalise.

No uptake model or investment ranking was rerun. These route-use percentages
must not be used as multipliers on published additional-cyclist estimates.
Independent new spatial support, broader repeated sampling, scenario rebuilding
and observed validation remain necessary.

The fresh run took 151.5 seconds: 76.1 seconds for topology/engine startup and
17.7 seconds in routing, with the balance mainly reading and checking evidence.
Peak process RSS was about 4.85 GiB, including Python and the JVM; the JVM heap
was limited to 4 GiB. This is one local-machine run, not a citywide performance
forecast. Private record-level caches remain ignored under `build/stability/`.

[Aggregate report and provenance](span-stored-support-pilot-2026-09-24.json).

## 2. Complete-journey checks in four more areas

The experiment now accepts a source candidate as its area anchor, records crop
coverage and search limits, and defaults to an ignored build output instead of
the browser data directory. Candidate IDs and centroid coordinates disambiguate
repeated street names. In particular, the tested Shelly Beach Road is centred at
174.3533, −36.5752; it must not be labelled as central Auckland.

All four tests use a 4 km radius, a requested 24-record sample, seed 20260924,
a NZ$20m cap, default assumed intersection delays, and 15,000 labels per search.
Routes must satisfy LTS ≤ 2, a detour ≤ 1.5 times the shortest legal in-crop route,
and a 30-minute travel-time limit.

| Area anchor | Sample / eligible in crop | Connected before → after | Package cost | Searches hitting cap |
| --- | ---: | ---: | ---: | ---: |
| Ponsonby Road | 24 / 1,751 | 1 → 5 | NZ$18.09m | 4 |
| Shelly Beach Road | 1 / 1 | 0 → 0 | NZ$0 | 0 |
| Hospital Road | 24 / 495 | 0 → 0 | NZ$0 | 0 |
| Grand Drive | 24 / 592 | 0 → 1 | NZ$6.60m | 1 |

These are sampled eligible journeys, not extra cyclists. The sample weights
are not expanded again to represent the whole area. Journeys crossing the crop
boundary are excluded; the report records those counts. Prior routing failures
are also disclosed rather than treated as covered by the area sample.

The package optimiser and whole-route greedy method tie on served weight,
journey counts and cost in all four tests. Single-project greedy misses the
multi-project gains at Ponsonby Road and Grand Drive. This supports the usefulness
of evaluating complete routes but does not demonstrate superiority over a strong
greedy method. Solver optimality applies only to the generated route columns.

### What prevents the other journeys being connected?

A new diagnostic funds every modelled project in the crop, without relaxing the
route standards. It then optionally allows high-stress streets to test whether
a route exists under the same time/detour limits. That second route is strictly
a diagnostic witness, never an acceptable cycling recommendation.

- Hospital Road: none of the 24 sampled journeys becomes acceptable even with
  every in-crop project funded. Nineteen have a route when the stress restriction
  is relaxed.
- Grand Drive: 23 journeys have no acceptable all-project route; 20 have a
  stress-relaxed witness.
- Ponsonby Road: of 19 journeys without a generated route, 18 conclusively lack
  an acceptable all-project route and one all-project search hits its cap.
  Sixteen have a stress-relaxed witness; two relaxed searches hit their caps.
- Shelly Beach Road: the one journey becomes acceptable in the all-project
  diagnostic, but not under the NZ$20m cap.

Every found stress-relaxed witness traverses a high-stress physical edge with
no eligible project in that crop. This does **not yet distinguish** an omitted
citywide candidate from a partial project excluded at the crop boundary.
Nor does it prove that a specific junction or street treatment is buildable.
Tracing those edges to candidate-generation rules and boundary exclusions is
the next diagnostic, ahead of adding speculative crossing projects or costs.

The full area runs took about 12–42 seconds each and peaked at 3.2–3.8 GiB RSS.
Samples are small and some searches are incomplete; these are coverage and
failure-mode checks, not citywide validation.

[Area summaries, paired methods and provenance](span-area-pilots-2026-09-24.json).
The underlying generated reports, including route geometries, remain local.

## 3. Reliability changes

- Build and development manifests now bind the exact complete-journey report
  bytes to a SHA-256 descriptor. The browser verifies the bytes before parsing,
  then checks run and topology. Missing or corrupt journey results do not disable
  Build order. Site packaging refuses missing, stale or mismatched descriptors.
- Journey GeoJSON exports carry the verified report digest. This is an integrity
  check within a release, not a claim of independent source authentication.
- Candidate records are validated once per loaded collection and reused.
  This removes duplicate validation, but does not yet shrink the 224 MiB payload
  or establish a measured loading-speed improvement.
- The demo/export CLI now follows verified manifest paths for cached artifacts,
  instead of assuming their original filenames. A regression test covers reused
  paths and rejects changed bytes.
- Synthetic browser fixtures can be tested in an isolated directory without
  overwriting the Auckland browser data.

The source browser manifest still matches its preceding audit checksum.
No public model result, source run or server deployment was replaced.

## Verification and reproduction

302 Python tests pass, with 80.97% coverage against the 80% gate. Python lint and
formatting checks pass. Web typecheck, lint, build and 42 unit tests pass.
Desktop/mobile browser tests: 31 pass, with nine intentional platform-specific
skips. Full Auckland desktop/mobile map, journey, checksum and export checks
pass without runtime or HTTP errors. The locally built release archive passes
packaging and archive-integrity checks; it has not been deployed.

Fresh stored-support routing (requires the pinned local R5 jar and JDK 21):

```sh
PYTHONPATH=src .venv/bin/python scripts/pilot_span_support.py \
  --run runs/run-313e0277521633d3 \
  --audit documentation/audit/span-source-cell-influence-2026-09-24.json \
  --r5-classpath build/runtime/r5-v7.5.1-r5py-all.jar --max-memory 4G \
  --output build/stability/support-pilot.json
```

Area experiment example:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-296e3eb561e8e2d7 --area-label "Ponsonby Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --output build/pilots/ponsonby-24.json
```

Use the other anchor IDs from the area summary to reproduce those runs.
`scripts/summarise_span_pilots.py` verifies shared settings and source hashes
before producing the aggregate area report. Runtime fields naturally vary.
