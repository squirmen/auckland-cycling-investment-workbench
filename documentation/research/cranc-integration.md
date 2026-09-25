# CRANC in SPAN: an attributed accessibility provider

17 September 2026. Read-only review of the two user-supplied archives. File and
archive fingerprints are in `cranc-source-review.json`. No CRANC server was
executed, no source code was changed and no OD data was transmitted.

## Useful division of responsibilities

SPAN asks which feasible investment packages complete journeys, how they change
route assignment and who gains access under a fixed budget. CRANC can contribute
Steve Gehrke and collaborators' profile-specific accessibility measurements:
jobs, schools, services or other destinations reachable before and after a
specified investment. A planner should see these results beside SPAN's measures,
with the provider, profile, time cutoff, population weights and opportunity
dataset visible. An opportunity gain is never relabelled as extra cyclists.

The request and comparison validators exist in `web/src/cranc.ts`, with unit
tests for scope matching and invalid results. The earlier public file-exchange
panel was removed on 24 September to keep one understandable SPAN workspace.
There are no CRANC results or integration controls in the public interface.

This is an integration boundary, not a live API connection or a claim that CRANC
natively emits the SPAN envelope. Steve retains ownership of profiles, coefficient
interpretation, accessibility computation and any CRANC-side scenario extension.

## What the supplied code actually exposes

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
longitude/latitude order, a profile and elevation request. It decodes the first
returned path and its LTS/elevation arrays. GraphHopper route time is reported in
milliseconds; SPAN's route representation is seconds. A future route adapter
must perform and test this explicit conversion and preserve geometry/LTS alignment.

`src/isochrone/isochroneApi.ts` requests `isochrone` with `point=latitude,longitude`,
`profile`, `time_limit` in seconds and `reverse_flow=false`. It recognises polygon,
feature-collection and geometry response shapes. The inspected Java resource
also exposes bucket, distance-limit and weight-limit options. The frontend's
`info` request obtains profile and graph metadata.

Native route and polygon outputs are not destination counts. The inspected
frontend does not provide a complete investment-scenario interchange containing
SPAN project IDs, matched opportunity inventories and paired aggregate outcomes.
Do not infer that changing a profile applies a proposed street investment.
CRANC needs either an agreed scenario graph per investment or a validated overlay
mechanism, with a crosswalk from SPAN projects to CRANC's directed edges.

## Auckland transfer issue found in the source

In `OSMLtsRatingParser.java`, an explicit OSM `lts` value of 1–4 takes precedence.
Otherwise the fallback calls `parseMaxspeedMph`, which strips non-numeric text
and uses the resulting number as-is against US mph thresholds; highway defaults
are also expressed in mph. A bare Auckland `maxspeed=50` therefore cannot safely
be interpreted by this fallback as if it were 50 mph. The method's name does not
perform a unit conversion. The inspected parser also defaults missing AADT to
zero, so source completeness affects its inferred stress.

Before Auckland use, agree with Steve on a tested km/h/mph conversion, missing
traffic handling, local classification validation and crossing treatment, or
supply validated explicit LTS tags on the shared source network. SPAN does not
silently repair his engine or label its profiles Auckland-calibrated. The import
envelope requires a transfer-validation declaration and evidence reference;
SPAN verifies their presence, not the truth of that scientific validation.

## Where to connect CRANC

Integration map updated 24 September 2026. The intended integration point is
**Connected journeys in SPAN, after a complete package has been selected**. It is
not a replacement for the main Auckland ranking engine and is not a new source
of cyclist counts.

| Layer | Exact entry point | Status / responsibility |
| --- | --- | --- |
| Planner interface | `web/index.html`, section `#tab-connected` | Future “Access to destinations” result. Do not expose unfinished integration machinery or collaborator biographies in the planning interface. |
| Request and result boundary | `web/src/cranc.ts`: `crancRequest`, `crancComparisonSchema`, `checkCrancScope` | Implemented: run/network/origin/weight/project matching, units and attribution. Keep transport code separate from these validators. |
| Active investment context | `web/src/connected.ts`: `ConnectedJourneys`, `report`, `solution`, `render` | Selected package and source report are available here. Future adapter results must pass the existing validators plus an extended routing-scope check before display. No provider request runs here today. |
| Investment geometry and provenance | `web/src/research-data.ts`: `portfolioGeoJson`; source candidate ledger `ordered_edge_ids` | Implemented SPAN side. Use exact source edge identities for the crosswalk; map lines alone do not identify CRANC edges. |
| CRANC execution adapter | Proposed `src/cycling_investment_workbench/integrations/cranc.py` and `scripts/run_cranc_comparison.py` | **Not implemented.** Run locally/server-side, with an explicitly configured endpoint and approved data sharing. Prepare paired scenarios, call CRANC and wrap validated aggregate outputs. Do not embed credentials or silently upload origins from the browser. |
| CRANC graph/scenario support | Collaborator-owned graph import/scenario mechanism | **Not implemented in SPAN.** Agree with Steve how project treatments and crossing assumptions map onto CRANC's directed graph, then verify that investment actually changes the graph. |
| Accessibility measurement | CRANC isochrones plus agreed opportunity inventory and origin weights | Provider-owned computation. Count opportunities consistently; polygons alone are not counts. Return one attributed profile/category/cutoff comparison per file. |

The intended sequence is:

```text
SPAN selected package + agreed origins/weights/opportunities
  → project-to-CRANC-edge crosswalk + validated baseline/investment scenarios
  → CRANC profile-specific accessibility calculation
  → aggregate comparison envelope
  → SPAN schema/scope checks → accessibility panel (not the ridership score)
```

### Gates before a live adapter

1. Agree reuse terms and a pinned provider version; supplied ZIPs remain local.
2. Agree origin data sharing, opportunity inventory, profile and time cutoff.
3. Resolve Auckland speed/stress transfer, missing AADT and crossing treatment.
4. Verify a directed project/edge crosswalk and actual scenario graph changes.
5. Extend the versioned exchange to declare the **effective routing assumptions**:
   crop extent, delay evidence/hash and low/default/high/no-delay case, along
   with speed/turn treatment. The current v1 source-topology hash does **not**
   fingerprint these additions. Do not present v1 as proving that CRANC used
   SPAN's new delay assumptions or the same cropped route universe.
6. Test baseline and investment on a small matched origin sample, including a
   no-change package, inaccessible origins and stale-result rejection. Only then
   enable a live connection or wider comparisons.

The v1 source/project match is narrower than a full routing-equivalence check.
Keep the public panel disabled until the adapter and extended scope contract
exist. The request object is not directly runnable CRANC input.

## Version 1 exchange contract

The canonical executable validator is `web/src/cranc.ts` (`crancComparisonSchema`).
Only outgoing accessibility, a weighted mean across matched source origins and
reachable opportunities per origin are supported in v1. This intentionally
excludes mixed units, raw polygon imports and unqualified aggregate totals.

| Field | Required meaning |
| --- | --- |
| `schemaVersion` | `span.cranc-access.v1` |
| `provider` | `name: CRANC`, version, human-readable attribution |
| `scope.runId` | The active SPAN source run |
| `scope.baseNetworkHash` | SHA-256 of the same SPAN source topology |
| `scope.originsHash` | Fingerprint of the exact origin population definition |
| `scope.weightingHash` | Fingerprint of the matching eligible-commuter weights |
| `scope.opportunitiesHash` | Fingerprint of one opportunity inventory used for both results |
| `scope.profile`, `profileHash` | CRANC ID (`ibc`, `eac`, `saf`) and versioned profile/coefficient content |
| `scope.timeLimitS`, `reverseFlow` | Positive integer seconds and `false` |
| `scope.category`, `unit`, `aggregation` | Declared category; `reachable_opportunities_per_origin`; `weighted_mean` |
| `scope.crs` | `EPSG:4326` for exchanged geographic context |
| `scope.stressTransferValidation` | `status: validated_for_auckland` plus an evidence reference |
| `baseline` | Scenario ID, network-scenario hash, empty proposed project IDs and non-negative finite value |
| `investment` | Scenario ID, network-scenario hash, exactly the selected project IDs, value and project/edge crosswalk hash |

The origins hash is SPAN's canonical `content_hash` of sorted source origin-node
IDs, retaining repeated origins. The weighting hash covers sorted `(origin ID,
eligible weight)` pairs for the same local records. Compute accessible opportunities
once per distinct origin, then apply the recorded weights; repeated records must
not duplicate destinations within a single origin's catchment. These fingerprints
are identifiers, not enough information to run CRANC. A local collaboration still
needs an agreed origin table, opportunity inventory and graph crosswalk. The
request builder does not export raw OD locations or send them to a server.

Both outcomes share the single scope/provider envelope, so they must use the
same origins, weights, opportunity inventory, profile and cutoff. A nonempty
investment requires a different network-scenario hash. IDs must be unique;
null, negative and non-finite result values are rejected. The scope validator
matches the network, run, origins, weights and exact selected project set.
Passing this validator does not authenticate the producer or independently
validate the underlying measurements. A future results view must explain that.

No default CRANC numbers are shipped. Synthetic contract fixtures exist only in
tests and are labelled as such. Version 1 can be extended later to multiple
profiles/time cutoffs, catchment geometries and distributional summaries after
the provider agrees the schema and the matching rules.

## Practical collaboration sequence

1. Agree one Auckland origin set, opportunity category and time budget with Steve.
2. Resolve the speed/stress transfer issue and record the evidence.
3. Validate a baseline route/catchment sample against the same source network.
4. Crosswalk one SPAN package into a distinct CRANC scenario, verifying crossings
   and facility changes; hold the opportunity inventory fixed.
5. Return the attributed before/after envelope and inspect the result in SPAN.
6. Expand to representative origins, profiles and equity comparisons only after
   baseline and scenario checks agree.

The backend archive includes GraphHopper licence and notice files. No standalone
licence file was found in the supplied frontend archive. This review does not
copy or redistribute either codebase. Attribution and agreed reuse terms should
travel with any future integration; file exchange needs no frontend code copying.
