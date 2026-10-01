# Methodology

The main explorer uses the method below. A separate local routing experiment
is reported in the [17 September research review](../research/methodology-review-2026-09.md):
fresh preference routing, fixed-demand assignment, an expanded 169-OD pilot,
primary-source comparisons and the remaining validation gates. Its results do
not replace the production forecasts or appraisal outputs.

## 1. Purpose and inferential boundary

SPAN compares possible cycling-network interventions at metropolitan
screening scale. Its unit of analysis is an origin–destination (OD) movement
assigned to a directed, source-identified network. It estimates how stated
scenarios and treatments change route availability, generalized cycling cost,
network connectivity, and monetised screening outcomes.

SPAN does not estimate causal effects from a randomized or quasi-experimental
design. Scenario demand is a constrained allocation guided by published PCT
propensity functions. Candidate results are conditional model comparisons, not
predictions of observed patronage or benefit.

## 2. Reproducible analysis contract

Every result must be traceable to:

- checksummed source snapshots and their licences;
- a versioned configuration containing all parameter values and units;
- source code version and dependency lock;
- deterministic topology and tie-breaking rules;
- a recorded random seed for stochastic procedures;
- stage-level counts, exclusions, warnings, and failure reasons; and
- a release manifest linking the analysis output to the published interface.

The pipeline must stop with a clear error when required fields, coordinate
systems, units or topology identifiers are missing. It must not convert units
or substitute datasets silently.

## 3. Demand and confidentiality treatment

### 3.1 OD observations

For OD relation \(i\), let \(E_i\) be total stated journey-to-work trips in the
source cell and \(O_i\) the bicycle subset. Both fields can be
disclosure-controlled, and an eligible total marked `-999` is neither a known
zero nor a known cap. The importer builds intervals
\([E_i^L,E_i^U]\) and \([O_i^L,O_i^U]\), then selects or samples only from the
joint feasible set \(0\le O_i\le E_i\). The principal and bound/sensitivity
runs use the same geography and pipeline, and the manifest records the joint
selection rule.

The importer must keep a numeric release distinct from an explicit suppression
marker. Under the Stats NZ 2023 Census sensitive-table rules, a suppressed
count is below six and is represented as \([0,5]\). Every other count is
fixed-random-rounded to base three and is within two of its confidential source
count. An unsuppressed numeric release \(r_i\) therefore has the conservative
interval \([\max(0,r_i-2),r_i+2]\), and an explicit suppression marker has
\([0,5]\). An unsuppressed numeric zero is \([0,2]\), not the suppression
interval. Bicycle bounds are then intersected with the eligible-total bounds
through the joint constraint. The selected point or draw is an analysis
convention, never a recovered source count. Product sensitivity and any
table-specific exception must be recorded.

Stats NZ Datafinder table 121988 version 410594 also removes rows whose total
population is below six, and includes only people whose workplace address is
available at SA2. A row missing for these reasons is a third state, neither a
suppression marker nor a published zero. SPAN does not create a missing OD
pair, give it a destination or apply the cell interval above. Missing-row and
unlocated-workplace mass is kept in a source-coverage ledger as unresolved
unless publisher totals support a bounded comparison. Scenario denominators
cover the published OD universe of people with a workplace address at SA2, not
all Auckland commuters.

The SA2 transport-mode margin and the internal Auckland OD table do not cover
the same universe. A source audit found 874,065 in the published full-origin
margin field `VAR_2_786`, against about 610,101 published internal-Auckland OD
total trips plus suppressed and structurally omitted cells. Unless a release
documents an exact reconciliation of universe and categories, the margin is a
bounded, soft validation diagnostic, not a hard allocation constraint. (The
September 2026 Auckland run does use it to size the 8% target; see §3.3.) All
source OD records, including outbound records when supplied, and every
unsnapped or unreachable internal record stay in a ledger with a scope or route
status. A missing outbound universe is reported, not invented.

Formal interval definitions are in `../equations/confidentiality.tex`. The
rules come from Stats NZ (2024), ISBN 978-1-99-104974-2.

### 3.2 PCT propensity

Published PCT 2020 coefficient sets convert routed distance and hilliness into
a relative spatial propensity. The logit contains distance, square-root
distance, squared distance, centered gradient, and distance–gradient
interactions. Inputs are kilometres and percent gradient. Coefficients and the
equation are in `parameters.md` and `../equations/pct-uptake.tex`.

The coefficient sets come from PCT scenarios developed for England. SPAN uses
them as transferable prioritisation priors, not as a locally estimated Auckland
behavioural model, so they need external validation and sensitivity testing.

### 3.3 Commute-cycling sensitivity

The adopted Transport Emissions Reduction Pathway (TERP) has a 2030 target of
17% of trips by cycling and micromobility together (13% by distance). SPAN's
default 8% commute-cycling share is a configurable modelling sensitivity. It is
not an adopted target, and it is not TERP's all-trip target converted to the
Census commute denominator.

For a declared source-compatible OD universe \(\mathcal I\) and confidentiality
draw or point \(b\), required additional cycling is

\[
T_b^+=\max\!\left(0,q\sum_{i\in\mathcal I}E_i^{(b)}
-\sum_{i\in\mathcal I}O_i^{(b)}\right),
\]

where \(q\) is the declared cycling share. Additional trips are distributed by
iterative proportional allocation with capacity
\(K_i^{(b)}=\max(0,E_i^{(b)}-O_i^{(b)})\) and weight
\(W_i^{(b)}=K_i^{(b)} p_i f(d_i)\), where \(p_i\) is the selected PCT
propensity and \(f(d_i)\) is the declared distance-decay function. Water
filling stops any OD relation exceeding its eligible population and reports any
unallocated target. The full declared universe stays in the demand ledger, but
only routable relations receive path allocation. Routing failures show up as
unallocated demand and in the coverage figures; they do not shrink the
denominator.

**As run for `run-313e0277521633d3`.** The routing stage sizes the target from
the full-origin margin, not from the routed universe: \(0.08\times874{,}096 -
8{,}179.5 = 61{,}748\) additional commuters (874,096 is the run's full-origin
total; the source audit above read 874,065 from the margin field). All of it is allocated to the
routed market, which has 619,441 eligible commuters and 817 routed baseline
cyclists. The 8% scenario therefore models about 62,565 cyclists, 10.1% of the
modelled market, and about 27% more additional cycling than the same-universe
formula above (about 48,740). Read it as "8% of all Auckland commuters, placed
on the modelled trips".

## 4. Network construction

The graph keeps each OSM node identity, source way identity, legal direction,
bicycle access, and the layer/bridge/tunnel state of every physical edge. Nodes
are never merged just because their coordinates are close. A bridge and a road
that cross in plan stay disconnected unless their OSM ways share a source node.
A shared source node stays connected where adjoining ways change layer at a
structure approach. Physical edges have stable IDs, and each permitted
direction is a separate traversal.

Import validation checks, at minimum:

- unique node and edge IDs;
- endpoints present in the node table;
- positive finite length and plausible geometry endpoints;
- direction and access consistency;
- bridge, tunnel, and layer transitions;
- weak components and isolated demand snaps; and
- duplicate geometries without conflating legitimate parallel facilities.

OD endpoints snap only to source-identified SPAN nodes that have an unambiguous
endpoint identity in the reconciled R5 graph and belong to a compatible network
component within the documented maximum distance. Routing starts and ends at
those exact R5 vertices; it does not ask a coordinate linker to choose a nearby
edge. Ambiguous mappings between source nodes and engine vertices fail closed
and are counted. Each result keeps the SPAN node, component, layer, snap
distance, route status and failure reason.

## 5. Traffic stress and generalized cost

Each edge gets a four-level traffic-stress (LTS) class from facility type, road
class, speed, lanes, volume and intersection stress. The classifier draws on
the LTS literature but is an auditable Auckland screening rule; it does not
assume US thresholds transfer without calibration. Missing speed, lanes or
volume are imputed conservatively by road class and recorded per edge.

For directed traversal \(e\), generalized cost is

\[
c_e=\ell_e\,m_{s(e)}
\left(1+w_+\max(0,g_e)+w_-\max(0,-g_e)\right)m_e^{\mathrm{structure}},
\]

where \(\ell_e\) is metres, \(m_{s(e)}\) is the LTS multiplier, \(g_e\) is
directional rise/run, and the structure term records bridge and tunnel
sensitivities. Intersection stress can raise, but not lower, link stress.

R5 runs the directed route searches, but the SPAN topology decides bicycle
access, direction, stress, terrain, structure penalties and exact segment
identity. Every R5 directed edge is reconciled through OSM way geometry to an
ordered SPAN segment sequence. Unmapped engine edges lose bicycle and
pedestrian permission in the engine-local copy, so R5 cannot silently fall back
to walking a bicycle. Any path that cannot be reconciled to one contiguous,
source-identified SPAN sequence fails closed.

The first search minimizes generalized cost, and a separate search finds the
shortest physical distance used as the detour denominator. Later searches
multiply the cost of engine edges already used by a declared factor. Up to five
distinct alternatives are kept after generalized-cost, physical-detour and
shared-edge screens; the Auckland default runs at most four alternative
searches after the base path. This is a deterministic link-penalty choice-set
generator. It is not Yen's algorithm, and it does not enumerate every route a
rider might consider.

Demand-support records are chosen by deterministic, seeded simple random
sampling without replacement within each published zonal OD. The Auckland
configuration (`records_per_stratum_by_purpose`) routes one of the up to 25
spatial disaggregation records in each supported commute stratum, and three in
each school, everyday and transit stratum. Every selected and unselected record
stays in the OD ledger, and the exact inverse inclusion probability is used as
a Horvitz--Thompson analysis weight. Retained paths get path-size-logit
probabilities, which give near-duplicate paths less weight than independent
alternatives. The choice set, sampling variance and utility coefficients remain
structural uncertainties until the planned sensitivity and local validation
work is done.

## 6. Existing network and candidate treatments

An existing facility counts as low-stress only when declared source attributes
or an approved authoritative facility overlay support it. Painted lanes are not
silently classified as protected. Classification conflicts and overlay matching
tolerances are reported.

A candidate corridor is a set of exact physical edge IDs plus a declared
treatment. The generator may join high-demand gaps, bridge short network gaps
and connect termini to the existing network, but each added connector shows in
the candidate geometry and capital cost. Parallel-facility filtering must
consider topology and access as well as planar distance, so a nearby path that
cannot be reached is not taken as a substitute.

Candidate provenance records seed edges, connectors, excluded duplicates,
treatment, length, source IDs, cost basis, and connectivity to existing
low-stress components. Candidates are corridors to investigate, not engineering
alignments.

## 7. Candidate counterfactual

For candidate \(C\), only its exact edge set is changed to the proposed
treatment; the graph is otherwise held fixed. Generalized costs and shortest
paths are recomputed for eligible OD relations. A relation is counted as using
the treatment only when the treated path traverses an edge in \(C\). The model
reports baseline and treated path cost, distance, changed edges, and whether a
path was unavailable in either state.

A continuous, bounded odds-elasticity response converts generalized-cost
change into cycling probability. For baseline probability \(p_0\), baseline
cost \(C_0\), treated cost \(C_1\), and elasticity \(\eta\):

\[
\operatorname{logit}(p_1)=\operatorname{logit}(p_0)+
\eta\log(C_0/C_1).
\]

The result is capped at the eligible population and gives no benefit when cost
does not improve. A small declared probability floor keeps the logit finite for
a disclosure-controlled zero. The current implementation measures the increment
against the original baseline, so a small floor-related addition can appear
where cost improves, even at zero elasticity. This is a numerical sensitivity,
not evidence of uptake. The elasticity and floor are declared and
sensitivity-tested. Benefits are credited only to modelled incremental activity
under this response model; scenario trips that only reroute are not
automatically counted as newly induced trips.

The reference graph algorithm performs exact-edge rerouting. The current
Auckland research snapshot instead recomputes generalized costs and path-size
probabilities over each OD's retained set of up to five plausible paths. It can
show switching among those paths but cannot find a new route outside the set.
Candidate outputs and the evidence profile flag this limitation, and no
full-network connectivity result is reported in its place.

## 8. Low-stress connectivity

Let \(\Omega\) be a declared analysis set of OD relations. A pair passes when a
directed path exists using edges at or below the LTS threshold and its physical
length is no more than \(\delta\) times the unrestricted feasible route length.
Once the full-network calculation has run, the unweighted and demand-weighted
**SPAN OD low-stress connectivity shares** are:

\[
\mathrm{LS}_{\mathrm{OD}}=|\Omega|^{-1}\sum_{i\in\Omega}I_i,\qquad
\mathrm{LS}_{\mathrm{OD},w}=\frac{\sum_{i\in\Omega}w_i I_i}{\sum_{i\in\Omega}w_i}.
\]

The current Auckland snapshot withholds both point estimates because the
production full-network reroute has not run. In a completed calculation the
denominator includes unreachable pairs, unless the release reports a second,
conditional measure. The release publishes the selection rule for \(\Omega\),
its size, its coverage of total demand, snap failures and geographic
composition, so a top-demand subset is not read as a population statistic. The
share is not a universal network connectivity index. It is not compared across
cities unless geography, demand set, weights, routing coverage, stress
threshold and detour threshold are harmonised.

## 9. Portfolio comparison and cumulative evaluation

Each goal's build order is a greedy sequence on a single objective, not a
weighted composite. At each step, Cycling to work (`network`) adds the link with
the largest marginal gain in modelled usual cycle commuters. Deprived areas
(`equity`), School trips, Everyday trips and Stations (`transit`) add the
largest marginal gain in their own objective per dollar of capital cost.
Benefit–cost (`appraisal`) adds the most commuters per dollar and then reports
each link's indicative benefit–cost ratio. Sequences are computed once up to
NZ$500m, and a budget takes the part of the sequence that fits. The weighted
min–max presets in `parameters.md` belong to the reference and demo
implementation (`connectivity.py`); the Auckland results do not use them and
the interface shows no weights. A Pareto frontier separately identifies
candidates for which no other candidate is at least as good on every declared
objective and strictly better on one.

For the current Auckland snapshot, every cumulative step reapplies all selected
exact-edge treatments and recomputes costs, path probabilities and demand
response over the affected retained path market. Benefit–cost ratios stay per
link; they are not recomputed for the package. This captures overlap and some
complementarity without crediting static candidate totals more than once. As
in §7, it is not full-network rerouting and cannot find paths outside the
retained choice set. The reference full-network algorithm is tested
separately (see §8). Presets and Pareto membership are decision aids, not
proof of a globally optimal programme. Budget, dependency, deliverability and geographic
constraints remain declared scenario inputs.

## 10. Economics

Screening benefits are annualised from incremental quantities on a documented
ramp and discounted over a 40-year default horizon. For a non-commercial
public-sector activity, the principal real discount schedule follows NZTA
General Circular 25/01: 2% in years 1–30 and 1.5% in years 31–40, with the
required constant 8% sensitivity.

The published Auckland snapshot shows a different figure in the browser: the
median of the 1,000 parameter draws, in which the discount rate varies between
1.5% and 8%. That median is about 0.84 times the principal-schedule ratio. The
principal and 8% ratios are computed in the run's evidence profile but are not
yet published.

Capital, operations, maintenance, renewals, treatment life and residual value
are separate cash-flow fields in one real price base. Benefit categories are
not double-counted. A research snapshot may report an indicative lifecycle
benefit–cost ratio and interval for its declared evidence scenario; this is not
a formal appraisal BCR. The capability is labelled `research_only`: provisional
local cost, maintenance, renewal, residual, benefit, e-bike, price-base and
demand-response inputs must pass expert review before decision use. Candidate
BCRs are not additive and do not form a programme BCR.

A formal appraisal follows the applicable Waka Kotahi Monetised Benefits and
Costs Manual (MBCM). Older default values kept for reproducibility are labelled
with their source version and price base. Using one value from an older manual
does not make a current release MBCM-compliant. MBCM v1.7.5 applies to
calculations starting on or after 29 May 2026. General Circular 26/01 records
that version update; General Circular 25/01 sets the discount schedule above.

## 11. Validation, uncertainty, and reporting

Validation keeps present-day observed cycling separate from future scenario
flows. Counter comparisons use aligned periods, directional definitions,
coverage checks and spatial matching rules. A future uplift scenario is not
presented as a prediction of current flows. A global ratio is not used for
automatic calibration unless that step is pre-registered and improves
out-of-sample performance.

Parameter, structural, data, scenario and spatial uncertainty differ in kind.
Principal results should come with confidentiality-bound, target-share, PCT
scenario, stress, response, cost and discount-rate sensitivities. For
`run-313e0277521633d3` only the PCT scenarios and the Latin-hypercube draws
were run; the confidentiality-bound and target-share reruns are still
outstanding. Each draw scales every candidate by the same factors, so the draws
give a range for each candidate's ratio but cannot change rankings or frontier
membership. Seeded Latin-hypercube designs and rank stability summarise the
declared model space, not every possible future. See `validation.md`,
`uncertainty.md`, and `limitations.md`.

Candidate evidence is shown as a profile, not a single grade. The profile
reports data completeness, routing coverage, frontier or rank stability,
parameter sensitivity and warnings. No component is presented as the
probability that a project will succeed.

## 12. Browser network context and route use

Enriched Auckland exports include a separate display layer of existing streets
and paths at LTS 2 or lower. Weak components are calculated from exact source
node identities, before geometry is simplified for display. Proposals are
grouped when they share a junction or touch the same existing low-stress
component. Contacts along a corridor are kept, not only its two ends. The map
highlights the attached existing areas and marks shared junctions. These groups
describe physical continuity only: they do not establish bicycle direction,
crossing quality, acceptable detour or complete OD accessibility. The regional
build order still maximises its stated objective and does not require all
selected links to form a connected programme.

For commute portfolios, route use and induced uptake are reported separately.
For each OD market, route use is its scenario cycling activity multiplied by
the summed probabilities of retained paths using any treated link. A path
using several treated links counts once. After-treatment use applies the joint
cost response and updated path probabilities. Travellers are therefore counted
once within a programme or package, but separate package totals can overlap
and must not be added. Uptake is the additional usual cycle commuters across
affected markets. Route-use changes also include rerouting, so they need not
equal uptake. Neither measure represents daily journeys or all-purpose cycling.

Physical packages are evaluated independently against the scenario baseline,
using the retained alternatives. Before export, recalculated cumulative uptake
must match the stored portfolio sequence; a mismatch blocks enrichment. Source
ledgers, parameters and implementation are fingerprinted in the context
metadata.

The baseline audit separates routed internal OD demand from the broader source
margins (see §3.1). Suppressed bicycle cells use the lower bound. A high
routing rate within the prepared internal market is not coverage of the full
market, and must not be corrected with an untested global scaling factor.
Provisional capital rates are reported separately from project-specific cost
estimates.

### Journey equivalents and OD concentration

Usual commuters remain the demand unit. The browser also offers illustrative
journey equivalents: people × cycling commute days/year × one-way journeys/day.
Defaults are 220 days and two legs, matching this run's appraisal calendar.
Average months divide annual equivalents by 12; cycling-day equivalents use
the assumed legs per cycling day. Neither adds unique riders or predicts
seasonality. Return routes are not separately assigned. Changing the calendar
in the browser changes the display only; stored demand, rankings and BCR
results stay the same.

Optional OD diagnostics first reproduce candidate uptake from checked ledgers,
then calculate the share contributed by the largest record and by the largest
three records. They are shown only when they match the active run and
candidate-layer hash. Response-elasticity cases are not confidence bounds. The
Monte Carlo parameter-sensitivity percentages hold the OD sample fixed, so they
cannot show sampling stability. The [local research note](../research/span-access-first-experiment.md)
covers the separate complete-route/package experiment and its limits.

## 13. Core references

The main methodological precedents are Lovelace et al. (2017), Goodman et al.
(2019), Mekuria et al. (2012), Lowry et al. (2012), Furth et al. (2016), Lowry
et al. (2016), Buehler and Dill (2016), Yen (1971), Ben-Akiva and Bierlaire
(1999), and Woodcock et al. (2018, 2021). Current appraisal rules are documented
by NZTA's MBCM v1.7.5, General Circular 26/01, and General Circular 25/01.
Area-deprivation interpretation follows Atkinson et al. (2024), with NZDep
treated as contextual geography rather than individual identity. Full records
are in `../references/library.bib`.
