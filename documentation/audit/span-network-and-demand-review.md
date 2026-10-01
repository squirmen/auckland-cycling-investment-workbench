# SPAN network and demand presentation review

## 16 September follow-up: rider concentration and reporting periods

The [reproducible audit](span-ridership-audit.json) now matches all 61,855 available
scenario/candidate commute estimates to source counterfactuals. Recomputing the
top 12 candidates from checksummed OD/path ledgers shows heavy concentration:
one weighted OD gives 94.6% of Beach Road's gain and 99.90% of Shelly Beach
Road's. The run routes one sampled commute record per source OD cell, so
rankings need denser spatial support and replicate sampling before they can be
treated as stable. There is no artificial cap at 54 new commuters.

The interface keeps usual commuters visible and adds illustrative annual,
average-month and cycling-commute-day journey equivalents. The default calendar
matches the run's appraisal assumptions: 220 cycling commute days/year and two
one-way journeys/day. Users can change these display assumptions, and the share
URL keeps them. Changing them does not recompute demand, rankings or BCRs.
Return journeys are assumed, not separately routed. School/everyday/transit
opportunity indices are not annualised.

Beach Road's 54.476 additional commuters correspond to 23,970 annual journeys
under that calendar. Its 145.557 users after investment correspond to 64,045.
The $100m programme has 548.200 additional commuters (241,208 annual equivalents)
and 2,334.952 deduplicated route users (1,027,379 annual equivalents). These are
calculations from a research scenario, not observed annual traffic. Annualising
does not add riders or reduce uncertainty.

Candidate details now show OD concentration and response-elasticity cases when
the recorded audit matches the active run and candidate-layer hash; a stale
diagnostic file is ignored. Beach Road gives about 24, 54 or 136 additional
usual commuters at elasticities 0.5, 1 or 2. These are illustrative
sensitivities, not calibrated estimates or confidence bounds.

The [access-first experiment](../research/span-access-first-experiment.md)
covers the runnable route and package prototype, local results, prior art and
remaining model work.

Reviewed 14 September 2026 against the local Auckland browser snapshot,
`run-313e0277521633d3`, and the current source. Updated 15 September with the
implemented network context and route-use analysis. The source run is
unchanged. The enriched browser export is local and has not been published.

## What is already in place

SPAN has its name, mark, Better Places Lab attribution, map-first layout,
floating controls, selected-link card and mobile sheets. TEAM uses the same
general shell and Inter/navy lab identity, and ALTO has a closely related
explorer and detail-panel pattern. Keep this direction. Shared interface tokens
and component conventions would help later work, though each tool still needs
data colours suited to its subject.

The next substantial improvement is explaining network function and defining
the outcome, not another visual rebrand.

## Findings from the snapshot

### The displayed network omits the existing low-stress network

The browser's `network.geojson` contains 191,539 candidate-edge features:
126,103 at baseline LTS 3 and 65,436 at LTS 4. Every feature has
`protected: false`. It is an exact candidate-edge graph, not the full model
graph or an inventory of existing cycling facilities.

Even so, the previous legend included “Existing protected cycleway”, and the
selected-link card said a high-stress candidate filled a gap in the low-stress
network. Neither showed a usable connection at either end. The exporter builds
this layer only from candidate rows in
[`production_export_stage.py`](../../src/cycling_investment_workbench/production_export_stage.py),
and the manifest states that scope.

In the default 12-link portfolio, only links 9 and 10 share a graph node with
another selected link. This checks direct contact between proposed links only,
ignoring direction. It does not show that the links are isolated from existing
routes, which this browser layer leaves out.

### The headline describes a narrow incremental response

At a $100m budget under the 8% commute scenario, the selected portfolio is:

| Measure | Snapshot value |
| --- | ---: |
| Candidate links | 12 |
| Candidate-edge length | 16.175 km |
| Capital cost | $97.049m |
| Modelled additional usual cycle commuters | 548.200 |
| Capital cost divided by additional commuters | About $177,000 |

These are additional usual commuters above the scenario starting level, not
total route users, daily bicycle journeys or all-purpose cycling. Dividing cost
by commuters does not give a benefit–cost ratio or a cost per journey.

The response in [`candidates.py`](../../src/cycling_investment_workbench/candidates.py)
uses the change in whole-route generalised cost and a bounded odds elasticity.
As an illustration, at elasticity 1, an 8% starting probability and a 5% cut in
whole-route cost give about 3.86 additional cycle commuters per 1,000 eligible
commuters. So the model can show a small gain even when many people would use
or benefit from the improved route. The example is not an Auckland forecast or
a claim about the correct elasticity.

The production portfolio evaluator recomputes demand response and route choice
across affected retained routes at each step. It handles overlapping markets
and some complementarity, but keeps at most five routes per OD pair, so it
cannot find a connection that creates an attractive route outside that set.
Full-network low-stress OD connectivity is not reported.

### The census baseline needs a separate demand audit

The routing manifest records 817.2 usual cycle commuters in the assigned
baseline, against 8,179.5 in the broader source-market bicycle margin.
[`ConfidentialODCell.cycle_interval`](../../src/cycling_investment_workbench/demand.py)
uses the lower point for suppressed bicycle cells. That lower-point rule and
the documented differences between source universes need reconciling before
the baseline is presented as a representative count of cycling today.

The same manifest reports about 99.56% coverage against its prepared internal
commute denominator, but 70.87% against the broader source-market eligible
denominator. The two figures answer different questions. The gap should not be
closed with a single scaling factor, and the 99.56% figure is not coverage of
all Auckland commuting.

The 8% scenario starts with 62,565.38 cyclists in the routed market. Its target
addition is calculated on the broader market and then allocated to routes.
That is another reason to state the baseline, scenario universe and
project-induced response separately, and not to describe 548 as progress from
today towards an 8% target.

Capital cost matters too. Every candidate currently uses a provisional central
rate of $6,000/m ($6m/km), with $3,000–$12,000/m bounds. These are screening
assumptions, not estimates for individual projects. Both the demand basis and
the cost basis are worth reviewing; changing how the headline looks does not
validate either.

## Priorities from the review

1. Make the existing network visible. Export a separate, compact context layer,
   built from the run's complete topology, that distinguishes low-stress
   streets, protected/shared facilities and remaining high-stress gaps. Keep
   the source date and classification provenance. Do not use the
   candidate-only graph in its place, or treat an AT plan alignment as a built
   facility.
2. Explain each link's role in the network. Show endpoint contacts using exact
   node identities, the nearby existing network and the proposed connections.
   Then test and label whether a link joins separate low-stress components,
   extends one, or still needs another gap treated. A contact alone does not
   show a directed, tolerably direct origin-to-destination route.
3. Evaluate connected packages. Offer corridor or area packages alongside the
   regional ranking, so users can compare a coherent route with scattered
   individual improvements. Test the whole package with rerouting and visible
   crossing/dependency assumptions. The present “network” goal maximises
   additional commute activity; it does not require a connected build programme.
4. Separate three outcomes: scenario cyclists using the improved corridor,
   people or destinations gaining a usable low-stress connection, and modelled
   additional cycling. Keep their units and denominators separate. Deduplicate
   people across a portfolio instead of summing edge flows. Keep
   school/everyday/transit access indices apart from observed trip counts.
5. Audit before recalibrating. Reconcile census margins and spatial coverage,
   test suppression assumptions and the probability floor, review local cost
   assumptions, and compare retained-route results with full-network rerouting
   on a small set of complete corridors. Do not raise the elasticity just to
   get a bigger result.

The focus on complete low-stress routes follows the planning question in
[Mekuria, Furth and Nixon (2012)](https://scholarworks.sjsu.edu/urban_plan_pub/13/):
can people travel between origins and destinations without excessive stress
or detour? The UI and implementation choices above are recommendations for
SPAN, not results produced by that method.

## Implemented locally, 15 September 2026

The interface now labels the headline as a modelled increase and explains its
scope in the portfolio and the link card. The cost per extra commuter is still
under “How to read this estimate”, with its denominator explained. The
candidate-only network is labelled as such, the unsupported gap-filling claim
is gone, and higher portfolio gains no longer imply that projects physically
join. “Today” is now “Census baseline”.

The larger change adds:

- A separate `existing.geojson` layer from the full run topology: 583,771
  low-stress source edges, grouped into 26,624 weak components. Display geometry
  is merged within component/facility class and simplified by 2 m; contacts and
  lengths are calculated from the unsimplified source graph. Separated lanes
  and shared paths are distinguished from other low-stress streets.
- Exact-node contacts along each candidate, A/B terminal markers, direction
  labels and directly touching proposals. Selecting a corridor highlights its
  attached existing areas and marks its shared junctions. This shows physical
  continuity only, not directed OD access or crossing quality.
- Physical groups within the chosen programme. The default $100m/8% programme
  has 11 groups across its 12 links, including the two Rangatira Road
  proposals. The regional ranking still maximises commute uptake; it is not a
  connected network optimisation.
- Before/after route use, deduplicated across each portfolio prefix, alongside
  the additional-commuter estimate. The default programme has 1,586.20 route
  users before and 2,334.95 after; additional uptake remains 548.20. The change
  in route use includes rerouting, so it does not equal uptake.
- 1,106 physical package/scenario combinations from the network and appraisal
  sequence prefixes, each evaluated separately. For the two Rangatira links,
  the 8% scenario gives about 382 package users and 77 additional commuters at
  a $12.9m capital cost. Package results must not be added together.
- A visible demand-basis note covering the routed/source census discrepancy,
  internal versus broader coverage and provisional $6m/km costs.

Route use sums, once per OD choice set, the probabilities of retained paths
that use any treated edge, multiplied by that set's scenario cycling activity.
After-treatment use applies the existing joint cost-response and route-choice
model. Each stored cumulative uptake estimate is checked independently before
export, and a mismatch stops generation instead of silently changing a ranking.
No OD records are added to browser data.

Regenerate the local data from the unchanged completed run:

```sh
.venv/bin/python scripts/build_span_context.py \
  --run runs/run-313e0277521633d3 --output web/public/data
```

The script checks source browser-layer hashes, requires local source files,
stages and verifies the new export, then replaces the browser assets. The new
manifest records source, parameter and implementation hashes. Production
`export-outputs` version 4 does the same enrichment; older demo exports without
network context still work. Release packaging includes the extra layer when it
exists.

Validation: 193 Python tests and 16 web tests passed, with lint, TypeScript and
production-build checks. The Auckland view was checked in the browser,
including selection and the Rangatira package.

Remaining model work: reconcile census suppression and source universes before
recalibration; evaluate complete corridors with newly discovered routes and
directed low-stress OD reachability; and compare a package-based selection
strategy with the existing regional greedy sequence. The physical grouping and
route-use figures do not answer those questions.
