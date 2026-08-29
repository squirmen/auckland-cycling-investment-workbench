# Methodology

## 1. Purpose and inferential boundary

The workbench compares possible cycling-network interventions at metropolitan
screening scale. Its unit of analysis is an origin–destination (OD) movement
assigned to a directed, source-identified network. It estimates how stated
scenarios and treatments change route availability, generalized cycling cost,
network connectivity, and monetised screening outcomes.

The tool does not estimate causal effects from a randomized or
quasi-experimental design. Scenario demand is a constrained allocation informed
by published PCT propensity functions. Candidate results are conditional model
comparisons, not promises of observed patronage or benefit.

## 2. Reproducible analysis contract

Every result must be traceable to:

- checksummed source snapshots and their licences;
- a versioned configuration containing all parameter values and units;
- source code version and dependency lock;
- deterministic topology and tie-breaking rules;
- a recorded random seed for stochastic procedures;
- stage-level counts, exclusions, warnings, and failure reasons; and
- a release manifest linking the analysis output to the published interface.

The pipeline must fail clearly when required fields, coordinate systems, units,
or topology identifiers are missing. Silent unit conversion and silent dataset
substitution are prohibited.

## 3. Demand and confidentiality treatment

### 3.1 OD observations

For OD relation \(i\), let \(E_i\) be total stated journey-to-work trips in the
source cell and \(O_i\) the bicycle subset. Both fields can be
disclosure-controlled; an eligible total marked `-999` is not a known zero or a
known cap. The importer therefore constructs intervals
\([E_i^L,E_i^U]\) and \([O_i^L,O_i^U]\), then selects or samples only from the
joint feasible set \(0\le O_i\le E_i\). Disclosure-controlled counts are not
treated as recovered truth. The principal and bound/sensitivity runs use the
same geography and pipeline, and the manifest records the joint selection rule.

The importer must preserve the difference between a numeric release and an
explicit suppression marker. Under the Stats NZ 2023 Census sensitive-table
rules, a suppressed count is below six and is represented as \([0,5]\). Every
remaining count is fixed-random-rounded to base three and differs from its
confidential source count by no more than two. Accordingly, an unsuppressed
numeric release \(r_i\) has the conservative interval
\([\max(0,r_i-2),r_i+2]\), while an explicit suppression marker has interval
\([0,5]\). In particular, an unsuppressed numeric zero represents \([0,2]\),
not the suppression interval. Bicycle bounds are then intersected with the
eligible-total bounds through the joint constraint. The selected point or draw
is an analysis convention; it is never described as a recovered source count.
Product sensitivity and any table-specific exception must be recorded.

Stats NZ Datafinder table 121988 version 410594 additionally removes rows whose
total population is below six and includes only people whose workplace address
is available at SA2. That structural absence is a third state: it is not an
explicit suppression marker and not a published numeric zero. The workbench
does not materialise a missing OD pair, assign it a destination, or apply the
cell interval above. Missing-row and unlocated-workplace mass is retained in a
source-coverage ledger as unresolved unless publisher totals support a bounded
comparison. Scenario denominators describe the available-address, published
OD universe—not all Auckland commuters.

The SA2 transport-mode margin and the internal Auckland OD table do not have an
interchangeable universe. A direct source audit found 874,065 in the published
full-origin margin field `VAR_2_786`, versus approximately 610,101 published
internal-Auckland OD total trips plus suppressed and structurally omitted
cells. The margin is therefore
a bounded, soft validation diagnostic unless a release documents exact universe
and category reconciliation; it is not a hard allocation constraint. All
source OD records, including outbound records when supplied, and every
unsnapped or unreachable internal record remain in a ledger with a scope or
route status. A missing outbound universe is reported rather than fabricated.

The formal interval definitions are in
`../equations/confidentiality.tex`, and the governing source is Stats NZ
(2024), ISBN 978-1-99-104974-2.

### 3.2 PCT propensity

Published PCT 2020 coefficient sets transform routed distance and hilliness
into a relative spatial propensity. The logit contains distance, square-root
distance, squared distance, centered gradient, and distance–gradient
interactions. Inputs are kilometres and percent gradient. Coefficients and the
equation are recorded in `parameters.md` and `../equations/pct-uptake.tex`.

The imported coefficient sets describe PCT scenarios developed for England.
They are used as transferable prioritisation priors, not as a locally estimated
Auckland behavioural model. External validation and sensitivity tests are
therefore essential.

### 3.3 Explicit commute-cycling sensitivity

The adopted Transport Emissions Reduction Pathway describes a 2030 target of
17% of trips by cycling and micromobility together (and 13% by distance). The
workbench's default 8% commute-cycling share is a configurable modelling
sensitivity. It is neither a standalone adopted target nor a direct crosswalk
from TERP's all-trip denominator to the Census commute denominator.

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
propensity and
\(f(d_i)\) is the declared distance-decay function. Water filling prevents any
OD relation exceeding its eligible population and reports any unallocated
target. The full declared universe remains in the demand ledger; only routable
relations receive path allocation, so routing failures appear as unallocated
demand and explicit coverage rather than silently shrinking the denominator.
This separates the aggregate scenario constraint from the behavioural
propensity used to distribute it.

## 4. Network construction

The graph preserves each OSM node identity, source way identity, legal
direction, bicycle access, and the layer/bridge/tunnel state of every physical
edge. Near-coincident coordinates are never merged merely because they are
close: a bridge and road that cross in plan remain disconnected unless the OSM
ways explicitly share the same source node. A shared source node remains
connected when adjoining ways change layer at a legitimate structure approach.
Physical edges have stable IDs; each permitted direction is a separate
traversal.

Import validation checks, at minimum:

- unique node and edge IDs;
- endpoints present in the node table;
- positive finite length and plausible geometry endpoints;
- direction and access consistency;
- bridge, tunnel, and layer transitions;
- weak components and isolated demand snaps; and
- duplicate geometries without conflating legitimate parallel facilities.

OD endpoints snap only to source-identified CIW nodes that have an unambiguous
endpoint identity in the reconciled R5 graph and belong to a compatible network
component within the documented maximum distance. Routing starts and ends at
those exact R5 vertices; it does not ask a coordinate linker to choose a nearby
edge. Ambiguous source-node/engine-vertex mappings fail closed and are counted.
The result retains CIW node, component, layer, snap distance, route status, and
failure reason.

## 5. Traffic stress and generalized cost

Each edge receives a four-level traffic-stress classification from facility
type, road class, speed, lanes, volume, and intersection stress. The classifier
is inspired by the LTS literature but is an auditable Auckland screening rule,
not an assertion that a US threshold transfers without calibration. Missing
speed, lanes, or volume are conservatively imputed by road class and recorded
per edge.

For directed traversal \(e\), generalized cost is

\[
c_e=\ell_e\,m_{s(e)}
\left(1+w_+\max(0,g_e)+w_-\max(0,-g_e)\right)m_e^{\mathrm{structure}},
\]

where \(\ell_e\) is metres, \(m_{s(e)}\) is the LTS multiplier, \(g_e\) is
directional rise/run, and the structure term records bridge and tunnel
sensitivities. Intersection stress can raise, but not lower, link stress.

R5 supplies directed route searches, but the CIW topology is authoritative for
bicycle access, direction, stress, terrain, structure penalties, and exact
segment identity. Every R5 directed edge is reconciled through OSM way geometry
to an ordered CIW segment sequence. Unmapped engine edges have bicycle and
pedestrian permission removed in the engine-local copy so R5 cannot silently
fall back to walking a bicycle. Any path that cannot be reconciled to one
contiguous, source-identified CIW sequence fails closed.

The first search minimizes generalized cost and a separate search establishes
the shortest physical-distance denominator. Subsequent searches multiply the
cost of previously used engine edges by a declared factor. Up to five distinct
alternatives are retained after generalized-cost, physical-detour, and
shared-edge screens; the Auckland default performs at most four alternative
searches after the base path. This is a deterministic link-penalty choice-set
generator, not an implementation of Yen's algorithm and not a claim that all
behaviourally perceived routes have been enumerated.

Demand-support records are selected by deterministic, seeded simple random
sampling without replacement within each published zonal OD. The default
routes one of the up to 25 spatial disaggregation records in every supported
stratum, retains every selected and unselected record in the OD ledger, and
uses the exact inverse inclusion probability as a Horvitz--Thompson analysis
weight. This is declared probability sampling, not silent truncation. Retained
paths receive path-size-logit probabilities, which reduce independent-
alternative weight for nearly duplicate paths. The choice set, sampling
variance, and utility coefficients remain structural uncertainties until the
specified sensitivity and local validation work is complete.

## 6. Existing network and candidate treatments

An existing low-stress facility must be supported by declared source attributes
or an approved authoritative facility overlay. Painted lanes are not silently
classified as protected. Classification conflicts and overlay matching
tolerances are reported.

Candidate corridors comprise exact physical edge IDs and a declared treatment.
The candidate generator may join high-demand gaps, bridge short network gaps,
and connect termini to the existing network, but each added connector is
visible in the candidate geometry and capital cost. Parallel-facility filtering
must consider topology and access as well as planar distance so a nearby but
inaccessible path is not mistaken for a substitute.

Candidate provenance records seed edges, connectors, excluded duplicates,
treatment, length, source IDs, cost basis, and connectivity to existing
low-stress components. Candidates are hypotheses for investigation, not
engineering alignments.

## 7. Candidate counterfactual

For candidate \(C\), only its exact edge set is changed to the proposed
treatment; the graph is otherwise held fixed. Generalized costs and shortest
paths are recomputed for eligible OD relations. A relation is counted as using
the treatment only when the treated path traverses an edge in \(C\). The model
reports baseline and treated path cost, distance, changed edges, and whether a
path was unavailable in either state.

A continuous, bounded odds-elasticity response translates generalized-cost
change into cycling probability. For baseline probability \(p_0\), baseline
cost \(C_0\), treated cost \(C_1\), and elasticity \(\eta\):

\[
\operatorname{logit}(p_1)=\operatorname{logit}(p_0)+
\eta\log(C_0/C_1).
\]

The result is bounded to the eligible population and produces no benefit when
cost does not improve. A declared small probability floor makes the logit
finite for a disclosure-controlled zero, while the increment is still measured
against the published baseline count so the floor itself is not counted as
cycling. Elasticity and floor are explicit and sensitivity-tested. Benefits are
credited only to modelled incremental activity under this response model;
scenario trips that merely reroute are not automatically counted as newly
induced trips.

The reference graph algorithm performs exact-edge rerouting. The current
Auckland research snapshot instead recomputes generalized costs and path-size
probabilities over each OD's retained set of up to five plausible paths. It can
therefore represent substitution among those paths, but it cannot discover a
new route outside that set. Candidate outputs and the evidence profile identify
this limitation; no full-network connectivity result is substituted.

## 8. Low-stress connectivity

Let \(\Omega\) be a declared analysis set of OD relations. A pair passes when a
directed path exists using edges at or below the LTS threshold and its physical
length is no more than \(\delta\) times the unrestricted feasible route length.
When the full-network calculation has executed, unweighted and demand-weighted
**CIW OD low-stress connectivity shares** are defined as:

\[
\mathrm{LS}_{\mathrm{OD}}=|\Omega|^{-1}\sum_{i\in\Omega}I_i,\qquad
\mathrm{LS}_{\mathrm{OD},w}=\frac{\sum_{i\in\Omega}w_i I_i}{\sum_{i\in\Omega}w_i}.
\]

The current Auckland snapshot withholds both point estimates because the
production full-network reroute has not executed. In a completed calculation,
the denominator includes unreachable pairs unless the release explicitly
reports a second, conditional measure. The selection rule for \(\Omega\), its
size, coverage of total demand, snap failures, and geographic composition are
published to prevent a top-demand subset being read as a population statistic.
The metric is not labelled as a universal network connectivity index and is
not compared across cities unless geography, demand set, weights, routing
coverage, stress threshold, and detour threshold are harmonised.

## 9. Portfolio comparison and cumulative evaluation

Candidate comparison has two transparent views. The Network, Equity, School,
Everyday, Transit, and Appraisal presets apply published weights to
min–max-normalised indicators relevant to the named purpose. A Pareto frontier
separately identifies candidates for which no other candidate is at least as
good on every declared objective and strictly better on one. The interface
shows every component and weight used by a preset.

For the current Auckland snapshot, every cumulative step reapplies all selected
exact-edge treatments and recomputes costs, path probabilities, demand response,
and appraisal over the affected retained path market. This captures overlap and
some complementarity without repeatedly crediting static candidate totals, but
it is not full-network rerouting and cannot reveal paths absent from the retained
choice set. The reference full-network algorithm is separately tested; a future
production run must use it before claiming network-wide route or connectivity
effects. Presets and Pareto membership are decision aids, not proof of a globally
optimal programme. Budget, dependency, deliverability, and geographic
constraints remain explicit scenario inputs.

## 10. Economics

Screening benefits are annualised from incremental quantities on a documented
ramp and discounted over a 40-year default horizon. For a non-commercial
public-sector activity, the principal real discount schedule follows NZTA
General Circular 25/01: 2% in years 1–30 and 1.5% in years 31–40, with the
required constant 8% sensitivity also reported. Capital, operations,
maintenance, renewals, treatment life, and residual value are separate
cash-flow fields in a common real price base. Benefit categories are not
double-counted. An analytically reviewed run may report an indicative lifecycle
benefit–cost ratio, not a formal appraisal BCR. The current public Auckland
research asset does not report that ratio: its appraisal capability is
`withheld`, all BCR fields are null, and the Appraisal lens is disabled until
the local release inputs below pass expert review.

The applicable Waka Kotahi Monetised Benefits and Costs Manual is authoritative
for a formal appraisal. Historical default values retained for reproducibility
are labelled by source version and price base. A current release must not claim
MBCM compliance merely because it uses one value from an older manual.
MBCM v1.7.5 applies to calculations commencing on or after 29 May 2026;
General Circular 26/01 records that version update, while General Circular
25/01 is the authority for the discount schedule above.

## 11. Validation, uncertainty, and reporting

Validation distinguishes present-day observed cycling from future scenario
flows. Counter comparisons use aligned periods, directional definitions,
coverage checks, and spatial matching rules; a future uplift scenario is not
presented as a current-flow prediction. Diagnostics are reported without using
a global ratio as automatic calibration unless that transformation is
pre-registered and out-of-sample performance improves.

Parameter, structural, data, scenario, and spatial uncertainty are different
objects. Principal results are accompanied by confidentiality-bound,
target-share, PCT scenario, stress, response, cost, and discount-rate
sensitivities. Seeded Latin-hypercube parameter designs and rank stability
summarise the declared model space; they do not claim to span every possible
future. See `validation.md`, `uncertainty.md`, and `limitations.md`.

Candidate evidence is communicated as a profile rather than a single summary
grade. The profile reports data completeness, routing coverage, frontier or
rank stability, parameter sensitivity, and explicit warnings. No one component
is presented as a probability that a project will succeed.

## 12. Core references

The main methodological precedents are Lovelace et al. (2017), Goodman et al.
(2019), Mekuria et al. (2012), Lowry et al. (2012), Furth et al. (2016), Lowry
et al. (2016), Buehler and Dill (2016), Yen (1971), Ben-Akiva and Bierlaire
(1999), and Woodcock et al. (2018, 2021). Current appraisal rules are documented
by NZTA's MBCM v1.7.5, General Circular 26/01, and General Circular 25/01.
Area-deprivation interpretation follows Atkinson et al. (2024), with NZDep
treated as contextual geography rather than individual identity. Full records
are in `../references/library.bib`.
