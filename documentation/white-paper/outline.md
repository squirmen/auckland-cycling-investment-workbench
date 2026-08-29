# White-paper outline

Use a layered document: an eight-page decision brief that stands alone,
followed by a technical paper/annex that supports peer review and reproduction.
Bullets below are drafting prompts, not finished claims.

## Front matter

- Title focused on transparent network investment screening, not software.
- Named version, Auckland study boundary, data vintage, and analysis date.
- Authors, affiliations, contributions, funding, conflicts, data/code statement.
- One-sentence posture: early option screening, not detailed design or formal
  business case.
- Plain-language glossary: OD, PCT, LTS, generalized cost, connectivity,
  counterfactual, lifecycle BCR, uncertainty.

## Part I — decision-maker brief

### 1. Decision question

- Which connected investments warrant the next stage of investigation?
- Why isolated project scoring misses network complementarity.
- What evidence a decision-maker can and cannot obtain from the workbench.

### 2. Auckland context

- Existing network fragmentation and the policy need for mode shift.
- Future Connect 2023 as the strategic multimodal network and issue framework;
  do not describe its corridors as committed investments.
- RLTP 2024--2034 as the statutory regional investment bid and prioritisation
  context; distinguish listed, prioritised, funded, designed, and delivered
  activities.
- Adopted TERP target: 17% all trips cycling plus micromobility by 2030; 13% by
  distance.
- Explicitly separate that target from the 8% commute-cycling modelling
  sensitivity.
- Data constraints: commute focus, disclosure control, sparse counters,
  incomplete network attributes, unavailable workplace SA2, structurally
  removed low-count OD rows, and non-interchangeable OD/margin universes.

### 3. How to read the workbench

- Map layers: modelled demand, low-stress network, gaps, context, uncertainty.
- Candidate card: treatment, route change, incremental demand, connectivity,
  lifecycle ratio, data completeness, routing coverage, rank/frontier
  stability, sensitivity, and warnings.
- Presets and Pareto frontier: visible value judgements and trade-offs, not one
  supposedly authoritative rank.
- Portfolios: marginal value after cumulative rerouting, not static addition.
- User-drawn corridor: consistent assumptions, exploratory only.

### 4. Release findings

- Populate only from the tagged run manifest.
- Baseline feasible demand and low-stress connectivity, weighted and unweighted.
- Candidate count and geography after feasibility/duplicate screens.
- Cost–outcome frontier and illustrative cumulative programme budgets.
- Rank stability across confidentiality, target, stress, response, cost, and
  discount-rate sensitivities.
- Counter validation coverage and adverse as well as favourable diagnostics.
- Distribution of opportunities and burdens; avoid individual-level inference
  from area deprivation.

### 5. Decision implications

- Robust candidates: stable across plausible assumptions and useful in multiple
  sequences.
- Contingent candidates: depend on preceding links, cost, or response.
- Evidence-first candidates: potentially important but blocked by missing
  topology, counts, design, or cost evidence.
- Recommended next studies: site audit, route survey, concept design, local
  route-choice calibration, and programme constraints.

### 6. Safeguards

- No automatic project approval or cancellation.
- No claim of globally optimal sequence.
- No formal MBCM-compliant BCR unless independently appraised.
- No predictive or causal claim from scenario outputs.
- Release/version/source information accompanies every exported figure.

## Part II — technical paper

### Abstract

- Problem: reproducible network-aware screening under imperfect regional data.
- Method: independent PCT propensity implementation, constrained local
  scenario, layer-aware routing, LTS, exact-edge counterfactuals, continuous
  response, weighted connectivity, cumulative re-routing, lifecycle appraisal,
  and uncertainty.
- Results: four or five manifest-derived quantities with intervals.
- Contribution: methodological integration and auditability; do not claim each
  component is individually novel.
- Limitations and transferability.

### 1. Introduction

- Infrastructure prioritisation is a network problem, not only a segment rank.
- Planning tools must expose target, behavioural, topology, and appraisal
  assumptions.
- Research questions:
  - How can published cycling propensity be adapted without presenting a policy
    target as a forecast?
  - How much do exact-edge treatments change route cost, uptake, and low-stress
    connectivity?
  - How does cumulative re-routing alter project sequence and rank stability?
  - Which uncertainties drive decision class?
- Contributions and explicit non-contributions.

### 2. Literature and method lineage

- PCT scenario planning: Lovelace et al.; Goodman et al.; Woodcock et al.
- Infrastructure and cycling evidence: Buehler and Dill.
- Plausible path generation and overlap-aware route choice: Yen; Ben-Akiva and
  Bierlaire; Broach et al.; Hood et al.
- LTS and network connectivity: Mekuria et al.; Lowry et al.; Furth et al.
- Network design and corridor prioritisation: Lowry et al. 2016; Liu et al.
  2019; Mahfouz et al. 2023.
- Multi-objective comparison, cumulative portfolio effects, and the limits of
  optimisation claims.
- NZDep2023 construction and area-versus-individual interpretation: Atkinson et
  al. (2024).
- Reproducible decision-support and uncertainty gap.

### 3. Study area and data

- Auckland geography, network and topological barriers.
- Policy-layer lineage and vintage: Future Connect 2023 technical report,
  mapping-portal version, final RLTP 2024--2034, and exact project snapshot.
- Source/version/licence table generated from the run manifest.
- OD denominator, disclosure-control interpretation, temporal mismatch.
- Distinguish explicit below-six suppression from numeric fixed-random-rounded
  releases in both total-stated and bicycle fields; a numeric zero is not a
  suppression marker; joint selections satisfy bicycle ≤ total stated.
- Distinguish those published-cell states from a structurally absent OD row;
  report the table-121988 below-six removal rule and workplace-address coverage
  without creating synthetic destinations.
- Report internal/outbound scope and every unsnapped or unreachable record;
  show why full-origin SA2 margins are bounded/soft evidence unless their
  universe is reconciled to the OD table exactly.
- Facility, elevation, transit, safety, destination, equity, and counter data.
- Coordinate systems, transformations, joins, and exclusions.

### 4. Methods

- Independent PCT equation implementation and coefficient verification.
- Target-constrained capped allocation over a declared source-compatible OD
  universe; joint lower/point/upper total-and-bicycle runs; explicit unallocated
  target from route failures.
- Separate commute, school, everyday, and transit demand surfaces with
  purpose-specific origin/destination weights and intrazonal conservation.
- Source-ID, direction-, access-, and layer-aware graph construction.
- Auditable LTS classification, imputation, and continuous routing impedance.
- Candidate generation with exact edge provenance and duplicate audit.
- Exact-edge retained-path recomputation and bounded odds-elasticity response;
  distinguish the current production choice set from the tested full-network
  reference algorithm.
- Demand-weighted OD low-stress connectivity definition with detour cap; state
  why the current Auckland point estimate is withheld.
- Named priority presets, Pareto dominance, and cumulative retained-path
  portfolio recomputation.
- Lifecycle benefits/costs in common real prices, with the current stepped
  non-commercial discount schedule and required 8% sensitivity.
- External validation and spatial holdout.
- Parameter/scenario design, structural scenarios, and rank acceptability.

### 5. Results

- Data coverage, source-universe reconciliation, outbound/unresolved scope,
  route failures, and stage exclusions before maps or rankings.
- Present-day validation and residual geography.
- Baseline scenario and low-stress connectivity.
- Candidate effects and cost–outcome frontier.
- Cumulative programme paths under multiple budgets/objectives.
- Distributional and geographic results.
- Sensitivity drivers, rank stability, and candidates changing decision class.

### 6. Discussion

- What cumulative retained-path recomputation changes relative to independent
  project scoring, and what remains unknown without full-network rerouting.
- Where transferable propensity helps and where local behavioural estimation is
  still needed.
- Meaning of connectivity and why it is not a universal city score.
- Planning value of reproducibility, adverse diagnostics, and explicit
  uncertainty.
- Comparison with PCT and LTS literature without claiming equivalence.
- Generalisability requirements for another New Zealand region.

### 7. Limitations and future research

- Non-commute trip purposes; e-bike/micromobility heterogeneity.
- Local route-choice and intervention-response validation.
- Multi-path assignment, capacity/intersection delay, temporal dynamics.
- Programme optimisation with budgets, dependencies, geographic fairness, and
  delivery constraints.
- Designed project costs and formal appraisal.
- Prospective evaluation after construction.

### 8. Conclusion

- One paragraph on transparent, conditional screening.
- One paragraph on what must happen before investment decisions.
- Reproducibility and release archive statement.

## Technical appendices

- Full equations and notation.
- PCT coefficient verification fixtures.
- LTS rule table and imputation rates.
- Source registry and licence record.
- Candidate-generation diagnostics.
- Validation-site inclusion/exclusion table.
- Parameter distributions and sensitivity design.
- Complete candidate table with warnings and rank acceptability.
- Reproduction commands and release checksums.
