# Validation protocol

Validation is a release gate, not a decorative summary. A build may be
reproducible and still invalid for a proposed use. The release report must show
coverage, errors, exclusions, and adverse results as prominently as favourable
ones.

## 1. Stage-level integrity checks

### Demand

- Eligible-total, bicycle-subset, and scenario quantities are finite and
  non-negative after joint selection.
- Interval ordering is \(0\le E^L\le E^*\le E^U\) and
  \(0\le O^L\le O^*\le O^U\), and every selected pair or uncertainty draw
  satisfies \(O\le E\).
- Import fixtures preserve an explicit suppression marker as 0–5 and an
  unsuppressed fixed-random-rounded numeric zero as 0–2 for both total-stated
  and bicycle fields; missing and suppressed states are never conflated.
- The Auckland source audit reproduces 5,441 internal OD rows with suppressed
  `2023_Total_stated`, all also suppressed in the bicycle field, and verifies
  that no importer converts those cells to observed zero.
- Import fixtures distinguish a row removed under table 121988's below-six
  rule, a record omitted because workplace SA2 is unavailable, an explicit
  `-999` cell, and a numeric zero. Structurally absent pairs are never
  materialised as zero or assigned a fabricated destination.
- The internal OD universe is not forced to the full-origin SA2 transport
  margin. Any comparison is bounded and diagnostic until exact universe and
  category reconciliation is documented.
- Every source OD record remains in the ledger with source-scope,
  target-universe, and route status. Outbound, unsnapped, and unreachable demand
  is counted and reported rather than dropped.
- A separate source-coverage ledger records table/version, included-population
  definition, structural row-removal rule, and bounded or unresolved
  missing-row/unlocated-workplace mass.
- Scenario allocation conserves the achievable target to numerical tolerance.
- No OD allocation exceeds remaining capacity \(E^*-O^*\) for its joint draw.
- Lower/point/upper confidentiality runs use identical geography and routing.
- Report the declared source universe; eligible and bicycle interval totals;
  requested, achieved, and unallocated target; routable and unroutable demand;
  outbound/unresolved-scope records; and the number and share of saturated OD
  relations.

### Topology and routing

- Node and edge IDs are unique; all edge endpoints resolve.
- One-way, bicycle-access, bridge, tunnel, and layer fixtures pass unit tests.
- Geometry endpoints agree with nodes within a declared tolerance.
- Weak components, isolated nodes, and demand snap failures are reported.
- Route edge sequences are contiguous, directionally legal, and sum to their
  stored length and generalized cost.
- Known Auckland grade-separated crossings and harbour barriers are retained as
  qualitative regression cases.

### Treatments and candidates

- Only exact candidate edge IDs change between baseline and treated graphs.
- Candidate length does not double-count shared or bidirectional geometry.
- Parallel-facility screening is manually reviewed on a stratified sample of
  retained and excluded edges.
- Connector provenance is visible and costed; candidates cannot bridge a
  topological barrier by planar proximity alone.
- Re-running with identical inputs produces the same candidate IDs and order.

### Economics and sequence

- All monetary inputs share a documented real price base.
- Present-value identities are checked against simple hand-calculated fixtures.
- Capital, operations, maintenance, renewal, and residual terms have the
  expected signs and timings.
- Marginal portfolio outcomes are recomputed after each applied candidate.
- Cumulative benefit and connectivity never include duplicate credit.
- Tie-breaking is deterministic and recorded.

## 2. External count validation

### Comparable target

Cycle counters observe use at a site and period. They do not directly observe
census commute OD flows or a future policy scenario. The validation target must
therefore be a present-day, purpose- and period-compatible model output. A
future scenario may be plotted for context but must not be used to assert
present-day predictive accuracy.

### Site eligibility

For every counter, record:

- exact observation window, aggregation, direction, and completeness;
- closures, outages, construction, seasonality, and exceptional-event flags;
- spatial match distance, matched edge ID, and bearing compatibility;
- whether adjacent parallel paths or junction geometry make assignment
  ambiguous; and
- a pre-declared inclusion or exclusion reason.

Prefer a strict match tolerance appropriate to network accuracy; wider search
radii are diagnostic only. Do not discard zero model predictions merely to
improve fit.

### Metrics

For all eligible sites and pre-declared strata, report:

- sample size and coverage of total counter observations;
- mean error (bias), median error, MAE, and RMSE;
- Pearson and Spearman correlation with intervals where appropriate;
- observed-versus-modelled slope and intercept;
- calibration plot with a 1:1 line and residual plot;
- error by count volume, facility type, geography, season, and match quality;
  and
- sensitivity to matching tolerance and temporal aggregation.

An \(R^2\) below zero means the predictions perform worse than the observed
mean under that definition. It must not be reframed as agreement. A median
observed/modelled ratio is a scale diagnostic, not validation of spatial rank
or candidate benefits.

### Out-of-sample design

If counter data calibrate any parameter, partition sites spatially before
fitting. Use spatial blocks or leave-one-area-out folds to reduce leakage from
nearby correlated sites. Publish training and test performance separately.
Repeated tuning on the test set invalidates it; create a new holdout or use
nested spatial cross-validation.

## 3. Behavioural and route validation

Where permitted observed traces, stated-preference data, or travel survey
routes exist:

- compare chosen edge overlap and route length against shortest and
  comfort-weighted alternatives;
- estimate whether LTS, gradient, structure, and detour effects have expected
  signs and plausible magnitudes;
- compare top-k path coverage, not only the single best path;
- stratify by trip purpose and bicycle type; and
- keep calibration evidence geographically distinct from final evaluation.

Absent local route-choice evidence, the generalized-cost parameters remain
structural sensitivities rather than calibrated behavioural coefficients.

## 4. Network and candidate face validation

A preregistered expert-review sample should include:

- high-, middle-, and low-ranked candidates;
- all barrier packages and floating components;
- candidates near existing or planned facilities;
- high-imputation and low-imputation areas;
- Māori and high-deprivation communities; and
- candidates whose ranking changes materially under sensitivity tests.

Reviewers record, without seeing the model rank where practical: physical
feasibility, missing crossings, duplicate provision, demand plausibility,
deliverability, omitted projects, and data errors. Review is evidence about
construct validity, not permission to alter individual scores after seeing the
result. Corrections to source data or general rules trigger a complete rerun.

## 5. Sensitivity and falsification tests

The release report includes at least:

- observed-count lower/point/upper runs;
- target-share and PCT coefficient-set alternatives;
- low/high traffic-stress and gradient penalties;
- at least three behavioural response values;
- candidate-generation tolerance alternatives;
- all-feasible versus top-demand connectivity denominators;
- cost, benefit, real discount rate, ramp-up, and asset-life alternatives;
- alternative random seeds and sufficient parameter/scenario draws; and
- leave-one-source-out tests for overlapping network/facility datasets.

Report rank correlation, top-k overlap, sign changes, and threshold-crossing
probability for key decisions. A candidate whose decision class is unstable is
labelled accordingly rather than assigned a precise rank.

## 6. Release acceptance criteria

A tagged public result requires:

- all automated tests passing on supported environments;
- zero unresolved schema, topology, conservation, or licence errors;
- a complete build manifest and output checksums;
- disclosed external-validation coverage and diagnostics;
- a successful clean-room rebuild from documented inputs;
- screenshots generated from the exact exported artifact; and
- a signed release checklist recording any accepted non-fatal warnings.
