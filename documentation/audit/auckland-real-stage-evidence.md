# Auckland real-stage evidence

This record traces the full-scale local Auckland executions from the first
topology/demand run through the rejected same-node route attempt and the
corrected successful raw-to-web research snapshot. It is analytical evidence,
not release approval. The external input copy and generated `runs/` artifacts
are deliberately outside the proposed public source set.

## Executed run

| Item | Recorded value |
| --- | --- |
| Run ID | `run-61deb30723a774fd` |
| Configuration SHA-256 | `456d2eeaca591eca2a24db1832e1c55a373d9138021a5a6ec8aec85c23a9337f` |
| Implementation SHA-256 | `53c82f3ea465b945291816e5f31a7ed2b6655ac6e20c00da873368677e74ea20` after the self-contained topology rebuild; later route-adapter changes are not represented by this historical run |
| Required-source inventory | 13 of 13 required sources available and hash-verified; five optional sources absent |
| Host runtime limitation | Python 3.11.16; the host manifest reported no Java runtime, so this run did not exercise R5 |
| Memory observation | Approximately 3.0–3.6 GB resident memory during spot checks; this is not a measured peak |

The source-refresh audit also replaced the legacy elevation inventory with a
schema-1 manifest that pins the byte count and SHA-256 of all 32 VRT-referenced
TIFFs. The manifest itself is pinned as
`3176824c30b177015b3641872c78e9686f8b2498000c49921a314a0c4dd3c347`.

## Completed stages

### Topology

- 867,348 source-identity OSM nodes; coincident distinct source nodes remain
  distinct, while 4,767 artificial layer-suffixed node duplicates were removed;
- 899,155 directed physical edges preserving OSM way/node identity;
- 56,780 conservative Auckland Transport facility matches;
- 31,205 versioned destination proxies from OSM nodes, ways, and multipolygon
  relations;
- 895,768 edges with valid sampled gradients and 3,387 missing/nodata edges,
  for 99.62% coverage;
- 243.04 seconds recorded stage duration; and
- self-contained topology directory size 1,058,839,251 bytes, SHA-256
  `9057ac6dccc34f58817a9fc3014c34a7a229a0f50fd66942ffa5a85ab8574542`.

The checksummed topology directory contains both `topology.json` and the exact
bounded OSM PBF required by routing. The PBF is therefore part of the pipeline
artifact contract rather than an untracked sibling file.

The destination adapter was corrected during this audit. It had omitted tagged
multipolygon relations, including Middlemore Hospital, and described every
source as a node even when it was a way. Mapping version 1.1.0 now retains the
OSM object type and ID, includes relation interior points, and recognises
explicitly tagged employment land uses/buildings. Focused regression tests cover
the relation and provenance behaviour.

### Demand preparation

- all 65,056 source journey-to-work rows inspected;
- 28,272 Auckland-origin zonal OD records retained: 28,176 internal and 96
  outbound or special-destination records;
- 28,168 bicycle cells and 5,453 eligible-total cells retained as explicit
  suppression intervals rather than zeros;
- 695,492 weighted disaggregated commute records generated with the declared
  probability sampling design;
- 569 open-school destinations retained and four proposed schools excluded;
- 21,463 independent everyday destinations retained;
- 10,476 Auckland SA1 geographies assigned to 633 SA2 geographies;
- six coastal representative-point overlaps resolved by strict maximum SA1
  polygon overlap, with no missing or unresolved assignments and a minimum
  winning overlap share of 1.0;
- three published OD records whose destinations lack employment-point support
  retained with `unresolved_destination_support` status; these cover two zones
  and 669 eligible-trip point estimates and remain in the coverage denominator;
- 39.75 seconds recorded stage duration; and
- output size 415,279,875 bytes, SHA-256
  `0668964d04e6af2ba030857ff3660bb0f0f09cf99f62b89eb652637472962243`.

The maximum-overlap procedure is deterministic and audited. It resolves a
multiple point match only when one SA2 contains strictly more of the source SA1
polygon; missing matches and overlap ties fail closed.

## Historical production stop

Barrier Islands (`111801`) and Donegal Park East (`158002`) have no retained
employment-point support for three published OD records. The preparation stage
does not invent representative-point destinations. It keeps those records in
the zonal ledger with explicit failure status and includes their 669 eligible
trips in the complete market denominator while spatialising the supportable
records.

This historical run stopped at `assign-routes` with the structured code
`auckland_r5_route_ledger_adapter_pending`. The recorded evidence specifies five
paths per OD, a 1.5 maximum detour ratio, and no synthetic fallback. The complete
run manifest remains valid evidence of that stop; it has not been edited to
pretend the later adapter existed.

## Route-adapter recovery benchmark

The subsequent current-tree adapter was exercised against the same bounded PBF
and 933 MB topology JSON before starting a new content-addressed production run.
This is benchmark evidence, not a completed Auckland route-stage result:

- R5 7.5.1-r5py with r5py 1.1.7 and JDK 21 loaded the bounded network;
- 536,439 of 1,096,570 directed R5 edges reconciled to authoritative CIW
  direction and exact segment sequences;
- 32,784 reconciled directions absent from R5's initial bicycle permissions
  were enabled from the CIW graph, while unmapped directions had bicycle and
  pedestrian permission removed to prevent walk-bike fallback;
- 259,215 project nodes were usable as unambiguous R5 origins and 259,237 as
  destinations; 14 ambiguous source-node/engine-vertex mappings in each role
  were excluded and counted;
- a geographically dispersed, deterministic 100-OD smoke sample assigned 99
  ODs, retained one explicit incompatible-component failure, generated 346
  accepted paths and 348,477 exact path-edge rows, and wrote/read all three
  Parquet schemas successfully; and
- the four-attempt design routed those 100 ODs in 74.73 seconds after a 61.22
  second fixed engine build (0.747 seconds per sampled OD in this diagnostic).

The current Auckland default is a declared one-record simple random sample
without replacement within each supported published zonal OD, with exact
inclusion probabilities and Horvitz--Thompson weights. All 695,492 spatialized
records remain in the complete OD ledger, including unselected records. The
default can retain up to five paths using the base search plus four documented
link-penalty searches; it does not claim a Yen enumeration. A new resumable run
must complete before routing coverage or flow results are accepted.

## Full route-run audit

Run `run-38e20f14d0e189f7` completed its 113 resumable chunks in 16,894.54
seconds. It retained all 695,492 spatialized OD records, selected 28,173 records
under the declared stratified design, assigned 28,061, and retained 112 explicit
routing failures. The output contains 94,771 paths, 94,626,462 ordered
path-edge records, and estimated flows for 478,188 physical edges.

The independent full-ledger audit verified every declared output and chunk hash,
the complete sampling and failure accounting, OD and path probability sums, the
1.5 detour cap, the ordered exact-edge sequences and directions for every
non-empty path, path length and generalized-cost reconstruction, and the full
edge-flow reaggregation. The maximum probability-sum error was
\(4.44\times10^{-16}\), and the largest accepted detour ratio was
1.49999937.

The run is nevertheless **rejected**, not accepted as release evidence. Four
short intrazonal records were labelled assigned after both endpoints snapped to
the same project node. They produced empty, zero-length paths. Their observed
bicycle count was zero, so they did not add flow to an edge, but an assigned
route must contain at least one exact physical edge. The router now searches a
second deterministic node within the shared component and also fails closed if
identical endpoints reach the engine. Focused tests cover both behaviours. The
JSON snapshot loader was also corrected so a value such as `1e-05` remains
numeric during manifest validation.

Because the implementation checksum changed, the corrected router requires a
new content-addressed run after the remaining production stages are frozen. The
rejected artifact and its `routing-audit.json` remain local diagnostic evidence;
neither will be represented as a publishable result.

Purpose-specific OD markets, candidates, cumulative portfolios, appraisal,
uncertainty, counter validation, manual audits, web export, and Auckland
screenshots remain release gates.

## Cache-integrity finding

This run also exposed two distinct provenance needs. The run manifest now
records a hash of the complete Python implementation, so validation rejects a
manifest produced by a different source tree. Resumable stage artifacts use a
separate versioned fingerprint over the stage's declared parameters, source
records, dependency hashes, options, and explicit semantic stage version. This
allows an unrelated documentation or downstream-appraisal change to reuse
verified topology and demand outputs without allowing a relevant input change
to do so. Cache restoration re-hashes every artifact and records `cached` in the
new run manifest. Regression tests cover irrelevant and relevant parameter
changes, explicit stage-version invalidation, checksum verification, and reuse
across distinct run identifiers. Every semantic stage implementation change
therefore requires its configured stage version to be incremented.

## Corrected full raw-to-web research snapshot

The corrected pipeline subsequently completed all nine configured stages as
run `run-224e9baa3be4ef73`. The manifest status is `succeeded`, the configuration
SHA-256 is
`7f54206dfbc585fe9ddfde2ac88579841ca333de6aa80c520fa09f23a69352fa`,
and the complete Python implementation SHA-256 is
`695f1031cee201bf20f7bb4ae07b3ac4944b6026c9a16c97663f7a3d2a2d0a49`.
Content-addressed cache restoration re-verified the unchanged source,
topology, demand, routing, and candidate artifacts; the portfolio, appraisal,
output, and web stages executed against those verified artifacts.

| Stage evidence | Recorded result |
| --- | --- |
| Source inventory | 13 of 18 configured inputs available; five optional inputs absent and declared |
| Topology | 867,348 nodes; 899,155 directed physical edges; 56,780 facility matches |
| Demand | 780,060 disaggregated purpose records across commute, school, everyday, and transit markets |
| Routing | 42,654 selected OD records; 42,498 assigned; 156 failures; 131,214 paths; 100,701,541 ordered path-edge rows |
| Candidates | 12,578 connected candidates; 191,464 exact candidate-edge rows; 21,995 explicit exclusions |
| Counterfactual portfolios | 87,392 candidate counterfactuals; 2,746,183 path-candidate savings; 3,771 cumulative portfolio steps; 20,418.38 seconds |
| Appraisal and uncertainty | 24,618 appraisal cases; 12,309 evidence profiles; 12,309,000 uncertainty draws from 1,000 reproducible Latin-hypercube samples; seed 20260301 |
| Web export | Five declared layers totalling 308,957,404 bytes, each with a manifest hash |

The nested route manifest records R5 `7.5.1-r5py`, r5py `1.1.7`, the bounded
OSM hash, exact graph-to-engine mapping diagnostics, route-choice parameters,
sampling weights, failure ledgers, and output hashes. Estimated commute routing
coverage is 99.56% of the weighted attempted market and 70.87% of the complete
source-market denominator; these deliberately different denominators remain
labelled rather than being conflated.

The production portfolio stage uses an exact sparse incremental greedy
calculation with versioned heap invalidation. It preserves the exhaustive
method's objective values and deterministic tie-breaking while avoiding a full
candidate rescan at every step. Exhaustive-equivalence, budget, tie-breaking,
and disjoint-evaluation-count regression tests cover the optimisation.

The evidence stage applies the registered MBCM v1.7.5 screening parameters and
produces explicitly indicative BCR intervals rather than business-case BCRs.
Its 1,000-draw uncertainty design is deterministic and exercises the declared
parameter groups, but the priors and locally evidenced capital, maintenance,
renewal, residual, health, e-bike, and price-base inputs still require expert
review before decision use.

Validation against the source state that created `run-224e9baa3be4ef73`
reported zero errors and five warnings for unavailable Future Connect, RLTP,
counter-location, counter-observation, and NZDep inputs. Current-tree validation
now correctly adds `implementation-mismatch` because the counter-source and
evidence code changed after the immutable run. The separate July 2026 counter
preparation provides spatial plausibility evidence only. Equity remains
disabled, and programme and public-counter layers remain empty.

This is accepted as a complete local research snapshot and as evidence that the
substantive raw-to-web pipeline executes. It is not yet a decision-ready or
public-release artifact. Full-network low-stress connectivity rerouting,
counter validation, stratified manual audits, local appraisal evidence,
uncertainty-prior review, public-layer/release-asset rights, and clean
container/CI reproduction remain release gates.
