# CRANC integration guide

17 September 2026. A read-only review of the two supplied CRANC archives. File
and archive fingerprints are in `cranc-source-review.json`. No CRANC server was
run, no source code was changed and no OD data was sent.

## Who does what

SPAN asks which feasible investment packages complete journeys, how they change
route assignment and who gains access within a fixed budget. CRANC, by Steve
Gehrke and collaborators, can add profile-specific accessibility: the jobs,
schools, services or other destinations reachable before and after a given
investment. A planner should see these results next to SPAN's measures, with
the provider, profile, time cutoff, population weights and opportunity dataset
shown. An opportunity gain is never reported as extra cyclists.

`web/src/cranc.ts` holds a request builder (`crancRequest`, no schema), the
comparison schema (`crancComparisonSchema`) and a scope check
(`checkCrancScope`), with unit tests for scope matching and invalid results.
Nothing in the app calls them. The public file-exchange panel that did was
removed on 24 September (commit `7b8685a`) to keep SPAN to one workspace. The
public interface has no CRANC results or integration controls, and SPAN cannot
currently export a request or import a comparison.

This defines an exchange format, not a live API connection. It does not assume
that CRANC produces the SPAN envelope itself. Steve owns the profiles,
coefficient interpretation, accessibility calculation and any scenario
extension on the CRANC side.

## What the supplied code exposes

The frontend has three profile IDs in `src/shared/config/profiles.ts`:

| ID | CRANC label |
| --- | --- |
| `ibc` | Interested but Concerned |
| `eac` | Enthused and Confident |
| `saf` | Strong and Fearless |

These are not SPAN's illustrative `direct`, `balanced` and `comfort` preference
cases. There is no automatic crosswalk between their coefficients or population
shares.

`src/navigation/navigationApi.ts` sends a POST to `route` with points in
longitude/latitude order, a profile and an elevation request. It decodes the
first returned path and its LTS and elevation arrays. GraphHopper reports route
time in milliseconds; SPAN uses seconds. A future route adapter must convert
and test this, and keep geometry and LTS values aligned.

`src/isochrone/isochroneApi.ts` requests `isochrone` with `point=latitude,longitude`,
`profile`, `time_limit` in seconds and `reverse_flow=false`. It accepts polygon,
feature-collection and geometry responses. The inspected Java resource also
has bucket, distance-limit and weight-limit options. The frontend's `info`
request gets profile and graph metadata.

CRANC's route and polygon outputs are not destination counts. The inspected
frontend has no complete investment-scenario exchange with SPAN project IDs,
matched opportunity inventories and paired aggregate outcomes. Changing a
profile does not apply a proposed street investment. CRANC needs either an
agreed scenario graph for each investment or a validated overlay, plus a
crosswalk from SPAN projects to CRANC's directed edges.

## Auckland transfer issue found in the source

In `OSMLtsRatingParser.java`, an OSM `lts` tag of 1–4 takes precedence.
Otherwise the fallback calls `parseMaxspeedMph`, which strips non-numeric text
and compares the number as-is with US mph thresholds; highway defaults are also
in mph. Despite its name, the method does no unit conversion, so a bare
Auckland `maxspeed=50`, meaning 50 km/h, is treated as 50 mph. The parser also
sets missing AADT to zero, so gaps in the source data change its inferred
stress.

Before CRANC is used in Auckland, agree with Steve on a tested km/h to mph
conversion, how to handle missing traffic data, how to validate the
classification locally and how to treat crossings, or supply validated LTS tags
on the shared source network. SPAN does not patch his engine or describe its
profiles as calibrated for Auckland. The import envelope requires a transfer-validation
declaration and an evidence reference; SPAN checks that they are present, not
that the validation is sound.

## Where to connect CRANC

Updated 24 September 2026. CRANC would connect to **Connected journeys in SPAN,
after a complete package has been selected**. It would not replace the main
Auckland ranking engine or provide cyclist counts.

| Layer | Exact entry point | Status / responsibility |
| --- | --- | --- |
| Planner interface | `web/index.html`, section `#tab-connected` | Future “Access to destinations” result. Keep unfinished integration controls out of the planning interface. |
| Request and result boundary | `web/src/cranc.ts`: `crancRequest`, `crancComparisonSchema`, `checkCrancScope` | Implemented: run/network/origin/weight/project matching, units and attribution. Keep transport code separate from these validators. |
| Active investment context | `web/src/connected.ts`: `ConnectedJourneys`, `report`, `solution`, `render` | The selected package and source report are available here. Future adapter results must pass the existing validators and an extended routing-scope check before display. No provider request runs here now. |
| Investment geometry and provenance | `web/src/research-data.ts`: `portfolioGeoJson`; source candidate ledger `ordered_edge_ids` | Implemented on the SPAN side. The Connected journeys download gives each inspected route segment its `sourceEdgeId` (since 2 October; earlier downloads dropped it). A project's full, ordered edge list is `edgeIds` in the published `data/candidates.geojson` (the candidate ledger's `ordered_edge_ids`); the journey report has edge IDs only for route segments. Use exact source edge identities for the crosswalk; map lines alone do not identify CRANC edges. |
| CRANC execution adapter | Proposed `src/cycling_investment_workbench/integrations/cranc.py` and `scripts/run_cranc_comparison.py` | **Not implemented.** Would run locally or on a server, with a configured endpoint and approved data sharing, to prepare paired scenarios, call CRANC and wrap validated aggregate outputs. Do not embed credentials or upload origins from the browser without telling the user. |
| CRANC graph/scenario support | Collaborator-owned graph import/scenario mechanism | **Not implemented in SPAN.** Agree with Steve how project treatments and crossing assumptions map onto CRANC's directed graph, then check that the investment changes the graph. |
| Accessibility measurement | CRANC isochrones plus agreed opportunity inventory and origin weights | Calculated by the provider. Count opportunities consistently; polygons alone are not counts. Return one attributed profile/category/cutoff comparison per file. |

The intended sequence:

```text
SPAN selected package + agreed origins/weights/opportunities
  → project-to-CRANC-edge crosswalk + validated baseline/investment scenarios
  → CRANC profile-specific accessibility calculation
  → aggregate comparison envelope
  → SPAN schema/scope checks → accessibility panel (not the ridership score)
```

### Gates before a live adapter

1. Agree reuse terms and a pinned provider version; the supplied ZIPs stay local.
2. Agree origin data sharing, opportunity inventory, profile and time cutoff.
3. Resolve the Auckland speed and stress transfer, missing AADT and crossing treatment.
4. Verify a directed project-to-edge crosswalk and that the scenario graph changes.
5. Extend the versioned exchange to declare the **effective routing assumptions**:
   crop extent, delay evidence and its hash, the low, default, high or no-delay
   case, and speed and turn treatment. The current v1 source-topology hash does
   **not** fingerprint these. A v1 match does not show that CRANC used SPAN's
   new delay assumptions or the same cropped route universe.
6. Test baseline and investment on a small matched origin sample, including a
   no-change package, inaccessible origins and rejection of stale results. Only
   then enable a live connection or wider comparisons.

The v1 source and project match is narrower than a full check that both tools
route the same way. Do not restore a public panel until the adapter and the
extended scope contract exist. The request object cannot be run directly as
CRANC input.

## Version 1 exchange contract

The validator in `web/src/cranc.ts` (`crancComparisonSchema`) is the reference.
Version 1 supports only outgoing accessibility, measured as reachable
opportunities per origin and summarised as a weighted mean across matched
source origins. It excludes mixed units, raw polygon imports and unqualified
aggregate totals.

| Field | Required meaning |
| --- | --- |
| `schemaVersion` | `span.cranc-access.v1` |
| `provider` | `name: CRANC`, version, human-readable attribution |
| `scope.runId` | The active SPAN source run |
| `scope.baseNetworkHash` | SHA-256 of the same SPAN source topology |
| `scope.originsHash` | Fingerprint of the origins of the Connected journeys sample (see below) |
| `scope.weightingHash` | Fingerprint of the matching eligible-commuter weights |
| `scope.opportunitiesHash` | Fingerprint of one opportunity inventory used for both results |
| `scope.profile`, `profileHash` | CRANC ID (`ibc`, `eac`, `saf`) and versioned profile/coefficient content |
| `scope.timeLimitS`, `reverseFlow` | Positive integer seconds and `false` |
| `scope.category`, `unit`, `aggregation` | Declared category; `reachable_opportunities_per_origin`; `weighted_mean` |
| `scope.crs` | `EPSG:4326` for exchanged geographic context |
| `scope.stressTransferValidation` | `status: validated_for_auckland` plus an evidence reference |
| `baseline` | Scenario ID, network-scenario hash, empty proposed project IDs and non-negative finite value |
| `investment` | Scenario ID, network-scenario hash, exactly the selected project IDs, value and project/edge crosswalk hash |

### Where the scope values come from

The values to match are in the published journey report,
`data/access-experiment.json` (`sourceHashes`), written by
`scripts/run_access_experiment.py`:

| Contract field | Report field | What it fingerprints |
| --- | --- | --- |
| `scope.runId` | `runId` | The SPAN source run, `run-313e0277521633d3` |
| `scope.baseNetworkHash` | `sourceHashes.topology` | SHA-256 of the run's native topology file |
| `scope.originsHash` | `sourceHashes.origins` | The sorted origin-node IDs of the sampled records, repeats kept |
| `scope.weightingHash` | `sourceHashes.originWeights` | The sorted `(origin-node ID, eligible weight)` pairs of the same records |

The sample is not a population definition. It is the first `--sample-size`
commute records (169 in the published report) whose origin and destination both
lie inside the 4 km crop, after sorting by SHA-256 of `"<seed>:<od_id>"`. A
different seed, crop or sample size gives different hashes.

Both hashes are `content_hash` in `src/cycling_investment_workbench/provenance.py`:
SHA-256 of the UTF-8 bytes of `canonical_json(value)`, which is Python's
`json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
separators=(",", ":"))`. A list of IDs is therefore hashed as
`["id1","id2",…]` with no spaces, and a pair as a two-item array. Weights are
Python floats and print in Python's shortest round-trip form (for example
`1.5`, `12.0`, `0.1`). A producer in another language must print them the same
way, or copy the hashes from the report instead of recomputing them.

Compute accessible opportunities once per distinct origin, then apply the
recorded weights; repeated records must not count destinations twice within one
origin's catchment. These fingerprints identify the inputs but are not enough
to run CRANC. A local collaboration still needs an agreed origin table,
opportunity inventory and graph crosswalk. The request builder does not export
raw OD locations or send them to a server.

Both outcomes share one scope and provider envelope, so they must use the same
origins, weights, opportunity inventory, profile and cutoff. A nonempty
investment requires a different network-scenario hash. IDs must be unique;
null, negative and non-finite result values are rejected. The scope validator
matches the network, run, origins, weights and exact selected project set.
Passing it does not authenticate the producer or independently validate the
underlying measurements, and a future results view must say so.

SPAN ships no default CRANC numbers. Synthetic contract fixtures exist only in
tests and are labelled as synthetic. Once the provider agrees the schema and
matching rules, version 1 can be extended to several profiles and time cutoffs,
catchment geometries and distributional summaries.

## Collaboration sequence

1. Agree one Auckland origin set, opportunity category and time budget with Steve.
2. Resolve the speed and stress transfer issue and record the evidence.
3. Validate a baseline route and catchment sample against the same source network.
4. Crosswalk one SPAN package into a distinct CRANC scenario, checking crossings
   and facility changes; hold the opportunity inventory fixed.
5. Return the attributed before/after envelope and inspect the result in SPAN.
6. Expand to representative origins, profiles and equity comparisons only after
   baseline and scenario checks agree.

The backend archive includes GraphHopper licence and notice files. No
standalone licence file was found in the supplied frontend archive. This review
does not copy or redistribute either codebase. Any future integration should
carry attribution and the agreed reuse terms; exchanging files needs no
frontend code to be copied.
