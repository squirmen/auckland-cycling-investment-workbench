# Figures and tables plan

Every figure is generated from the tagged analytical outputs, not transcribed
from the interface. Captions include release ID, scenario, denominator, units,
data year, and uncertainty type. Maps retain source/basemap attribution.

## Main-text figures

| ID | Figure | Minimum content | Claim supported |
| --- | --- | --- | --- |
| F1 | Reproducible pipeline and inferential boundary | Sources → validation → demand → topology/routing → treatments → response/connectivity → sequence/economics → uncertainty/export; distinguish observation, assumption, and derived result | Transparent integration and auditability |
| F2 | Study area, source coverage, and exclusions | Existing low-stress network, OD origins, counter sites, unsnapped/unreachable demand, source vintages | Geographic/data coverage before results |
| F3 | Demand model, universe, and confidentiality sensitivity | Distance/hilliness propensity curves; total-stated and bicycle joint intervals; distinguish numeric zero, explicit suppression, structurally removed rows, and unavailable workplace SA2; internal/outbound/unrouteable and source-coverage ledgers; soft margin comparison; constrained total | Scenario is bounded and explicit, not a forecast or hard reconciliation of unlike universes |
| F4 | Exact-edge candidate counterfactual | Baseline and treated routes, changed edges, generalized-cost change, continuous probability response | Corridor-specific network mechanism |
| F5 | Connectivity and cumulative portfolios | Weighted low-stress connectivity by cumulative cost; alternative orders/budgets; parameter-scenario envelope | Network complementarity and path dependence |
| F6 | Candidate cost–outcome frontier | Lifecycle cost versus incremental cycling/connectivity; dominance; rank-stability encoding | Trade-offs rather than one brittle rank |
| F7 | External validation | Observed versus present-day model, 1:1 line, residual map, coverage/exclusion inset | Scale and spatial validity with adverse results visible |
| F8 | Global sensitivity and decision stability | Parameter influence plus top-k rank acceptability | Which assumptions drive decisions |
| F9 | Distributional context | Demand/opportunity by deprivation group and geography with missingness | Descriptive distribution, not individual benefit |

## Main-text tables

| ID | Table | Required columns |
| --- | --- | --- |
| T1 | Data and licences | source, publisher, reference date/version, analysis use, features, exclusions, licence, checksum/manifest key |
| T2 | Method components and precedent | component, implementation, literature lineage, Auckland adaptation, validation, remaining limitation |
| T3 | Principal parameters | symbol/key, central value, unit, source/rationale, sensitivity range/distribution |
| T4 | Stage coverage | source universe, internal/outbound/unresolved records, eligible and bicycle interval totals, input count/demand, routed, unsnapped/unreachable, excluded by reason, missing/imputed, geographic coverage, soft margin diagnostic |
| T5 | Validation | sample/coverage, bias, MAE, RMSE, correlation, calibration slope/intercept, spatial holdout, strata |
| T6 | Programme scenarios | budget/objective, projects, cost, weighted/unweighted connectivity, incremental trips, lifecycle ratio, stability |
| T7 | Robustness | sensitivity, affected outcome, rank correlation, top-k overlap, decision-class changes |

## Supplementary figures

- S1 PCT coefficient fixture comparison and probability surfaces.
- S2 Joint total-stated/bicycle interval examples, aggregate bounds, and OD
  versus full-origin-margin universe diagnostic.
- S3 LTS classification decision chart and missing-attribute geography.
- S4 One-way and grade-separated topology validation cases.
- S5 Snap-distance distributions and unreachable OD geography.
- S6 Plausible-path overlap and route-choice parameter sensitivity.
- S7 Candidate generation stages; excluded parallel matches and connectors.
- S8 Static versus cumulative candidate effects.
- S9 Lifecycle cash-flow examples and price-base conversion.
- S10 Simulation convergence by draw count and seed.
- S11 Counter residuals by facility, volume, period, and match quality.
- S12 Candidate rank acceptability for the complete set.

## Supplementary tables

- Full data dictionary and source-field mappings.
- Complete LTS rule and imputation table.
- Candidate provenance: seed, connector, exact edges, source IDs, warnings.
- Counter inclusion/exclusion manifest.
- Complete lifecycle parameters and cash-flow conventions.
- Parameter distributions, correlations, and sensitivity design.
- Complete results for every scenario and candidate.
- Software environment, schema versions, checksums, and reproduction commands.

## README/documentation screenshots

After the screenshot gate closes, the README uses the verified hero WebP in
`../screenshots/web`; seven lossless masters are retained in
`../screenshots/full`, and previews are in `../screenshots/thumbnails`. These
communicate the product; they are not substitutes for analytical paper figures.
Capture requirements and metadata are in `../screenshots/README.md` and
`../screenshots/manifest.csv`.
