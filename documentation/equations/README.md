# Equation index

The files in this directory are publication-ready LaTeX fragments. They contain
no document preamble so they can be included in a journal template with
`\input{}`. Symbols are defined in `notation.tex`; units and executed parameter
values remain authoritative in `../methodology/parameters.md` and the release
configuration. The fragments require `amsmath`; `confidentiality.tex` also uses
`\mathbb` from `amssymb`.

| File | Equation labels | Symbols and units | Source / assumption | Code and tests |
| --- | --- | --- | --- | --- |
| `confidentiality.tex` | `eq:frr3-bound`–`eq:censored-count-point` | counts in persons/trips | Stats NZ (2024); total-stated and bicycle marker states are preserved and draws satisfy bicycle ≤ total stated | Scalar interval logic in `demand.py`; joint total/subset importer fixtures remain a release gate |
| `pct-uptake.tex` | `eq:pct-predictor`, `eq:pct-probability` | distance km; gradient percent; probability share | PCT manual and Lovelace et al. (2017); transferable scenario prior | `demand.py::pct_probability`; `test_demand.py` |
| `target-allocation.tex` | `eq:target-additional`–`eq:allocation-conservation` | eligible and allocated trips | Declared 8% commute sensitivity over a source-compatible OD universe; bounded allocation; unroutable shortfall retained | `demand.py::allocate_target_scenario`; full-universe ledger integration remains a release gate |
| `purpose-demand.tex` | `eq:purpose-disaggregation`, `eq:purpose-edge-flow` | purpose trips and edge flows | Purpose-specific sources/weights; intrazonal conservation | Synthetic contract in `demo.py`; production adapters and reference fixtures remain a release gate |
| `routing-impedance.tex` | `eq:routing-cost`–`eq:sampled-edge-flow` | length/generalized metres; rise/run; probability share; inverse-probability weight; trips | LTS and revealed-route-choice lineage; parameters and the route sample are declared sensitivities | `stress.py`, `r5_routing.py`, `production_routing_stage.py`; `test_stress.py`, `test_r5_routing.py`, `test_routing.py` |
| `counterfactual.tex` | `eq:treated-cost`–`eq:incremental-trips` | generalized metres; trips | Exact-edge treatment and bounded continuous response | `candidates.py`; `test_candidates.py` |
| `connectivity.tex` | `eq:connectivity-pass`–`eq:portfolio-change` | length ratio and CIW OD low-stress share | Complete declared OD denominator; full-network calculation required; Auckland point estimate reserved for the separate sabbatical research integration | `connectivity.py`; `test_connectivity.py` |
| `equity.tex` | `eq:equity-stratum-total`–`eq:equity-representation-ratio` | outcome and reference shares | Descriptive area context only; no individual inference | Synthetic export contract in `demo.py`; production distribution tests remain a release gate |
| `economics.tex` | `eq:annual-benefit`–`eq:discount-schedule` | real NZD in one price base | MBCM v1.7.5 and update Circular 26/01; discount Circular 25/01; separate conventional/e-bike caps; indicative screening only | `appraisal.py`; `test_appraisal.py` |
| `uncertainty.tex` | `eq:confidentiality-envelope`–`eq:rank-acceptability` | parameter-specific units and rank shares | Declared Latin-hypercube/scenario ensemble, not universal probability | `uncertainty.py`; `test_uncertainty.py` |
| `validation.tex` | `eq:validation-bias`–`eq:validation-null-r2` | cycles per aligned period | Present-day comparable target and spatial holdout | `validation.py`; `test_validation.py` |

Paths in the final column are relative to `src/cycling_investment_workbench/`
and `tests/`. A missing production mapping is stated explicitly rather than
implied by a synthetic fixture.

The aggregate cycling target should be described as the “8% commute-cycling
modelling sensitivity,” not the “TERP cycling target.” TERP's adopted target is
17% of all trips by cycling and micromobility combined; the denominators are not
directly interchangeable.
