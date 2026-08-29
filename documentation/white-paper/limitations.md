# White-paper limitation checklist

This checklist governs the executive brief and technical paper. The fuller
method limitation statement is in `../methodology/limitations.md`.

## Claims boundary

- [ ] Label the Auckland outputs as a **research snapshot**, identify the exact
  run manifest, and state that counter validation, manual audit, local economic
  evidence, and public-release clearance remain incomplete. Keep the miniature
  fixture explicitly labelled synthetic wherever it is shown.
- [ ] Describe PCT outputs and the 8% commute case as scenarios, not forecasts or
  adopted targets.
- [ ] Describe corridor effects as conditional model comparisons, not causal
  effects of construction.
- [ ] Describe preset scores and Pareto membership as decision aids, not an
  optimal programme.
- [ ] Describe the lifecycle ratio as indicative, not a formal business-case
  BCR or proof of MBCM compliance.

## Data and transferability

- [ ] State that journey-to-work data omit most non-commute trip purposes.
- [ ] State the disclosure-control interpretation, preserve explicit marker
  state for both total-stated and bicycle fields, distinguish numeric
  fixed-random-rounded zero from below-six suppression, enforce bicycle ≤ total
  stated in every point/draw, and show lower/point/upper sensitivity.
- [ ] Distinguish table-121988 rows removed because total population is below
  six and records omitted because workplace SA2 is unavailable from explicit
  `-999` cells and numeric zero. Do not fabricate absent OD pairs; report their
  mass and location as unresolved coverage unless separately bounded.
- [ ] State that the full-origin SA2 margin and internal-Auckland OD table have
  not been shown to share a universe; do not hard-balance them. Report the
  source-scope, outbound/unresolved, unsnapped, and unreachable ledgers and use
  margins only as bounded/soft evidence unless exact reconciliation is shown.
- [ ] Report input vintages, temporal mismatch, missingness, imputation, snap
  failure, unreachable demand, and geographic coverage before results.
- [ ] State that England-derived PCT coefficients and international route-choice
  evidence are not locally estimated Auckland response parameters.
- [ ] State that OSM and agency topology can be incomplete or stale.

## Equity, safety, and community

- [ ] Do not infer individual identity, need, or benefit from area deprivation.
- [ ] Do not equate equal mapped investment with equitable process or outcomes.
- [ ] Do not turn Māori, gender, disability, age, or Pacific community evidence
  into numeric weights without partnership, governance, and empirical basis.
- [ ] Do not infer treatment safety effects from crash clusters alone.
- [ ] Pair regional screening with local co-design, field audit, and feasibility
  work.

## Validation and uncertainty

- [ ] Validate a comparable present-day quantity; do not validate a future
  scenario against today's counters.
- [ ] Publish counter coverage, exclusions, bias, MAE, RMSE, association,
  calibration, and spatial residuals, including poor results.
- [ ] Call parameter/scenario ensembles what they are; do not present subjective
  ranges as complete predictive probabilities.
- [ ] Show structural and spatial alternatives, not only parameter variation.
- [ ] Report rank acceptability and decision-class changes rather than precise
  deterministic ranks alone.

## Economics and delivery

- [ ] Use one documented real price base across benefits and costs.
- [ ] Include ramp-up, capital, maintenance, renewals, asset life, and residual
  value, with the applicable MBCM version.
- [ ] Apply the stepped non-commercial discount schedule and report the required
  8% sensitivity, unless the activity is explicitly classified otherwise.
- [ ] Disclose excluded benefits and costs and guard against double counting.
- [ ] State that generated edge sets are not surveyed designs and omit property,
  utilities, structures, consenting, consultation, and delivery constraints
  unless those are separately evidenced.

## Reproduction and rights

- [ ] Link every number to the tagged manifest and archived release.
- [ ] Publish source/config/lock/output checksums and exact commands.
- [ ] Retain data, basemap, and publication attribution in figures and exports.
- [ ] Keep restricted data, subscription PDFs, cached tiles, credentials, and
  personal paths outside the repository.
