# Claims and evidence matrix

No quantitative claim enters the abstract, executive brief, README, or figure
caption unless it is generated from the tagged release manifest or a cited
external source. “Required evidence” is a publication gate.

| Proposed claim | Permitted strength | Required evidence | Main caveat |
| --- | --- | --- | --- |
| The workbench is reproducible from declared inputs | Demonstrated for a named release | Clean rebuild on supported environments; source/config/lock/output checksums; archived manifest; CI result | Some source snapshots may require separate acquisition rights |
| PCT propensity is independently implemented | Exact functional equivalence for tested fixtures | Equation transcription audit; coefficient source; cross-language fixture values and boundary tests | Transfer to Auckland behaviour is not validated by code agreement |
| Disclosure-controlled counts and structurally absent rows are handled consistently with the published 2023 Census product rules | Method and implementation property | Preserve total-stated and bicycle marker states; numeric zero and explicit `-999` fixtures; 5,441-row Auckland import audit; joint draws with bicycle ≤ total stated; separate fixtures for below-six row removal and unavailable workplace SA2; source-coverage ledger; end-to-end bound runs | Cell bounds do not recover confidential values; structurally missing locations and mass can remain unresolved outside the ensemble |
| Aggregate allocation satisfies target and capacity constraints for its declared OD universe | Mathematical and tested property | Proof/derivation; unit and property tests including zero weight, saturation, and infeasible target; source-scope and route-failure ledger; no hard balancing to an unreconciled full-origin margin; no invented absent OD pairs | Target is a scenario assumption over people with workplace SA2 available in the published table, not all commuters; outbound and internal-only universes are not interchangeable |
| Purpose surfaces represent distinct demand markets | Demonstrated for each named purpose | Separate source/weight provenance, OD ledger, intrazonal cases, routes, candidate network, coverage, and conservation test for commute, school, everyday, and transit | Opportunity models are not observed trips unless their source actually measures trips |
| Topology respects direction and grade separation | Demonstrated on imports and fixtures | One-way/bridge/tunnel/layer tests; import warnings; known-crossing regression cases | Source topology can still be wrong or incomplete |
| Treatment effects are corridor-specific | Conditional model result | Diff showing only exact candidate edges changed; treated path uses candidate; rerouting fixtures | Network-wide or land-use responses remain omitted |
| Response is continuous and bounded | Mathematical/model property | Equation, monotonicity/bounds tests, low/principal/high elasticity runs | Elasticity requires local evidence |
| Candidate set reduces duplicate or disconnected proposals | Screening performance claim | Stratified manual audit with precision/recall-style counts for exclusions and connectors | “Duplicate” depends on access, function, and topology, not distance alone |
| Weighted low-stress connectivity changes after treatment | Conditional network result | Declared OD denominator/weights; baseline and treated path checks; demand coverage | CIW OD low-stress connectivity share, not a harmonised universal city index |
| Cumulative retained-path recomputation changes portfolio outcomes | Empirical research-snapshot result | Compare cumulative versus static aggregation; marginal path-choice and demand-response changes after every step and order sensitivity | It is not full-network rerouting; presets and Pareto membership do not prove a global optimum |
| A candidate has an indicative lifecycle ratio above a threshold | Conditional screening result | Common price base; full cash flows; cost source; current stepped discount schedule plus 8% sensitivity; parameter distribution; probability of threshold crossing | Not a formal business-case BCR |
| Results are externally consistent with observed counts | Use only the metric-specific statement supported | Comparable present-day quantity; site coverage; bias, MAE, RMSE, correlation, calibration, residuals; spatial holdout | Counters are sparse and selected; future scenarios are not current observations |
| Candidate priority is robust | Stable within declared plausible model space | Rank acceptability/top-k inclusion; confidentiality, demand, routing, response, cost, and structural sensitivities | Unmodelled futures remain outside the range |
| Results reveal distributional context | Descriptive area-level statement | Population/demand-weighted distribution by declared geography; missingness and uncertainty | Area deprivation is not individual identity or experienced benefit |
| The method transfers to other regions | Design-level proposition, not demonstrated outcome | Portable schemas/config; second-region reproducibility test; local parameter/data replacement guide | Auckland parameter validity does not transfer automatically |

## Language to use

- “scenario,” “conditional estimate,” “screening result,” “modelled response,”
  “demand-weighted OD connectivity,” “indicative lifecycle ratio,” “named
  preset,” “Pareto non-dominated,” “cumulatively recomputed retained-path
  portfolio,” “stable
  across the declared sensitivity set.”
- “associated with” only for observed associations; “caused” only with a valid
  causal design.
- State denominator, unit, year, scenario, price base, and uncertainty type next
  to every headline quantity.

## Language to avoid

- “the TERP 8% cycling target”; “predicted demand” for constrained scenarios;
  “actual route”; “optimal programme”; “proven BCR”; “validated” without naming
  target and metrics; “confidence interval” for a structural scenario range;
  “equity benefit” from an area-deprivation overlay alone; universal comparisons
  of differently defined low-stress connectivity values.
- Do not use “full-network rerouting” for the Auckland snapshot until a tagged
  run records that execution; its current portfolio engine reweights the
  retained plausible path set.

## Evidence still needed before submission

- Local evidence or a transparent prior range for the odds elasticity.
- Current Auckland treatment-cost distributions and lifecycle components.
- Auckland employment, school/enrolment, everyday-destination, and transit
  demand inputs and purpose-specific validation.
- MBCM v1.7.5 parameter extraction, General Circular 26/01 version/applicability
  verification, General Circular 25/01 discount-schedule verification, and an
  independent appraisal review.
- A quality-screened present-day model/counter validation dataset.
- A complete table-121988 source-coverage ledger and either a demonstrated
  universe reconciliation between the OD table and SA2 transport margins or
  published evidence that the margins remain bounded/soft only; complete
  structurally omitted/unlocated-workplace, outbound, unsnapped, and
  unreachable coverage evidence.
- Manual topology and candidate audit by reviewers blinded to rank where
  feasible.
- Stable final run across supported environments and a public archival release.
