# Parameter register

This file records version 0.1 analytical defaults. The executed configuration
and release manifest take precedence. Any changed value must be accompanied by
a rationale and sensitivity comparison.

## Demand

| Key | Default | Unit | Interpretation |
| --- | ---: | --- | --- |
| `target_cycle_share` | 0.08 | share of eligible commute trips | Configurable modelling sensitivity; not a TERP target or direct all-trip-to-commute crosswalk |
| `fixed_random_rounding_base` | 3 | persons/trips | Stats NZ fixed-random-rounding base for unsuppressed 2023 Census counts |
| `fixed_random_rounding_max_error` | 2 | persons/trips | Maximum absolute difference between an unsuppressed published count and source count |
| `suppression_threshold` | 6 | persons/trips | A suppression marker in a sensitive table denotes a source count below this threshold |
| `suppressed_cell_lower`, `suppressed_cell_upper` | 0, 5 | persons/trips | Interval for an explicit suppression marker; not the interval for numeric zero |
| `distance_decay_full_weight_km` | 12 | km | Distance at or below which the allocation decay is one |
| `distance_decay_scale_km` | 5 | km | Exponential scale beyond the full-weight threshold |

An unsuppressed numeric release \(r\) uses
\([\max(0,r-2),r+2]\); therefore numeric zero uses \([0,2]\). This rule
applies separately to the total-stated and bicycle releases, after which a
joint selector or draw enforces bicycle \(\le\) total stated. These bounds
follow Stats NZ's published error guarantee but do not reverse the
confidentiality transformation. Full-origin SA2 margins are soft validation
diagnostics, not balancing controls, unless their universe is reconciled to the
OD table exactly. These cell bounds do not apply to OD rows structurally absent
from table 121988; missing-row and unlocated-workplace mass remains unresolved
coverage rather than a zero or fabricated 0–5 cell.

For \(d>12\), distance decay is \(\exp[-(d-12)/5]\).

### PCT 2020 coefficients

The predictor is
\(\eta=\beta_0+\beta_1d+\beta_2\sqrt d+\beta_3d^2+
\beta_4(g-g_0)+\beta_5d(g-g_0)+\beta_6\sqrt d(g-g_0)\), with distance
in kilometres and gradient in percent.

| Scenario | \(\beta_0\) | \(\beta_1\) | \(\beta_2\) | \(\beta_3\) | \(\beta_4\) | \(g_0\) | \(\beta_5\) | \(\beta_6\) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Government Target 2020 | -4.018 | -0.6369 | 1.988 | 0.008775 | -0.2555 | 0.78 | 0.02006 | -0.1234 |
| Go Dutch 2020 | -1.468 | -0.71726 | 1.988 | 0.008775 | -0.2555 | 0.78 | 0.02006 | -0.1234 |
| E-bike 2020 | -1.468 | -0.66217 | 1.988 | 0.008480 | -0.0743 | 0.78 | 0.02006 | -0.1234 |

The coefficient provenance must be checked against the versioned PCT source
before release. Do not round these values further in computation.

## Stress and routing

| Key | Default | Unit | Sensitivity set |
| --- | ---: | --- | --- |
| `lts_multipliers` | 1.00, 1.25, 1.80, 3.00 | multiplier for LTS 1–4 | published alternative sets plus locally calibrated values |
| `uphill_gradient_weight` | 4.0 | multiplier per unit rise/run | 2, 4, 6 |
| `downhill_gradient_weight` | 0.5 | multiplier per unit fall/run | 0, 0.5, 1 |
| `tunnel_multiplier` | 1.25 | multiplier | 1.0, 1.25, 1.5 |
| `bridge_multiplier` | 1.05 | multiplier | 1.0, 1.05, 1.2 |
| `low_stress_threshold` | 2 | LTS level | 1, 2 |
| `maximum_low_stress_detour` | 1.5 | route-length ratio | 1.25, 1.5, 2.0 |
| `od_snap_max_distance_m` | 1,800 | m | tighter thresholds plus retained-demand coverage |
| `honour_oneway` | true | boolean | mandatory; no undirected headline run |
| `plausible_paths` | 5 | paths per OD | 1, 3, 5, 8 where computationally feasible |
| `route_records_per_zonal_od` | 1 | spatial disaggregation records sampled without replacement per supported zonal OD | 1, 3, 5, complete; report inclusion weights and rank stability |
| `route_sample_seed` | 20260301 | deterministic integer seed | independent registered seeds for sampling sensitivity |
| `maximum_cost_ratio` | 1.5 | ratio to minimum generalized cost | 1.25, 1.5, 2.0 |
| `maximum_detour_ratio` | 1.5 | ratio to shortest physical route | 1.25, 1.5, 2.0 |
| `maximum_shared_edge_ratio` | 0.95 | overlap share | 0.80, 0.90, 0.95 |
| `alternative_penalty_multiplier` | 2.0 | multiplier on engine edges already used by generated alternatives | 1.5, 2.0, 3.0 |
| `maximum_alternative_attempts` | 4 | searches after the base path | 4, 8, 20; compute and choice-set sensitivity |
| `path_size_logit_cost_scale` | 0.002 | inverse generalized m | locally calibrate; broad structural sensitivity |
| `path_size_coefficient` | 1.0 | utility coefficient | 0, 0.5, 1.0, 1.5 |

Conservative missing-attribute defaults used by the classifier:

| Road class | Speed (km/h) | Lanes | Daily traffic volume |
| --- | ---: | ---: | ---: |
| Motorway | 100 | 4 | 30,000 |
| Arterial | 60 | 4 | 15,000 |
| Collector | 50 | 2 | 7,000 |
| Local | 40 | 2 | 3,000 |
| Service | 30 | 1 | 1,000 |
| Path | 20 | 1 | 0 |

These are imputation conventions, not observed Auckland road attributes.

## Candidate and response model

| Key | Default | Unit / meaning | Required sensitivity |
| --- | ---: | --- | --- |
| `candidate_treatment` | protected lane | facility class on exact treated edges | alternative feasible treatments by corridor |
| `maximum_candidate_length_m` | 9,000 | m | shorter caps and candidate-boundary audit |
| `candidate_matching` | exact edge IDs | identity rule | no proximity-only headline result |
| `response_odds_elasticity` | 1.0 | elasticity in \(\operatorname{logit}(p_1)=\operatorname{logit}(p_0)+\eta\log(C_0/C_1)\) | triangular 0.5, 1.0, 2.0 plus evidence-led alternatives |
| `minimum_probability` | 0.00001 | probability floor for a disclosure-controlled zero baseline | vary by confidentiality convention and report attributable increment against the published baseline |

Candidate-generation rules beyond these defaults must be supplied and recorded
by the executed configuration. Duplicate-facility buffers, connector limits,
and gap-priority thresholds require threshold sweeps and manual review of both
retained and excluded cases.

## Connectivity, presets, and portfolios

| Key | Default | Unit | Reporting requirement |
| --- | ---: | --- | --- |
| `connectivity_od_set` | all feasible declared OD pairs | set | Report count, total-demand coverage, unreachable pairs, and any top-demand sensitivity |
| `priority_presets.network` | demand .25; connectivity .60; equity .10; value .05 | normalised weights | Network-screening view; display every component |
| `priority_presets.equity` | demand .15; connectivity .20; equity .55; value .10 | normalised weights | Area context does not establish individual benefit |
| `priority_presets.school` | demand .15; connectivity .20; school .55; value .10 | normalised weights | Requires an independently prepared school-demand surface |
| `priority_presets.everyday` | demand .15; connectivity .20; everyday .55; value .10 | normalised weights | Requires an independently prepared everyday-destination surface |
| `priority_presets.transit` | demand .15; connectivity .20; transit .55; value .10 | normalised weights | Requires an independently prepared bicycle-to-transit surface |
| `priority_presets.appraisal` | demand .15; connectivity .10; equity .05; value .70 | normalised weights | Uses indicative lifecycle value only |

The weights describe the version 0.1 implementation and are transparent value
judgements, not empirically estimated social-welfare weights. Purpose presets
must not be populated by merely relabelling commute demand.

## Screening economics

These defaults implement an indicative lifecycle screening calculation. They
do not establish formal MBCM compliance; each release must verify the manual,
input definitions, price base, and worksheets applicable when analysis starts.

The public-export capability is fail-closed. `reviewed` is the only state that
may expose appraisal values. `research_only`, a missing legacy capability, or
`withheld` causes the release packager to null every candidate BCR field, empty
the Appraisal portfolio, disable the Appraisal lens, and record the unresolved
input warning in the manifest and asset notice. The current Auckland research
asset therefore exposes costs as screening fields but no BCR.

| Key | Default | Unit / price basis | Required release treatment |
| --- | ---: | --- | --- |
| `price_base_year` | 2021 | real NZD | Apply one documented update factor to every compatible value and cost |
| `appraisal_horizon_years` | 40 | years | Test shorter lives and record renewals and terminal residual value |
| `discount_rate_years_1_30` | 0.02 | annual real share | NZTA General Circular 25/01 non-commercial schedule |
| `discount_rate_years_31_100` | 0.015 | annual real share | NZTA General Circular 25/01 non-commercial schedule |
| `discount_rate_years_101_plus` | 0.01 | annual real share | Recorded for completeness; outside the 40-year default horizon |
| `discount_rate_sensitivity` | 0.08 | annual real share | Required non-commercial sensitivity in General Circular 25/01 |
| `ramp_up_years` | 3 | years | Test opening profile and timing |
| `conventional_health_per_km_nzd` | 4.90 | NZD per incremental cycle-km, 2021 prices | Apply only to eligible incremental conventional-cycle activity |
| `ebike_health_per_km_nzd` | 2.50 | NZD per incremental e-bike-km, 2021 prices | Apply only to eligible incremental e-bike activity |
| `conventional_health_cap_per_user_nzd` | 6,200 | NZD per user-year, 2021 prices | Enforce before discounting |
| `ebike_health_cap_per_user_nzd` | 4,600 | NZD per user-year, 2021 prices | Enforce before discounting |
| `emissions_kg_per_vehicle_km` | 0 | kg CO₂e per avoided vehicle-km | Remains zero until fleet, mode substitution, and boundary are sourced |
| `carbon_value_per_kg` | 0 | NZD per kg CO₂e | Remains zero until the compatible appraisal value/profile is sourced |
| `other_benefit_per_avoided_vehicle_km` | 0 | NZD per avoided vehicle-km | Add only with non-overlapping, compatible evidence |

Capital cost, maintenance, renewal timing, residual value, and any other annual
benefit are explicit candidate inputs rather than undocumented unit-rate
defaults. The release must state inclusions, exclusions, update factor, base
year, risk allowance, property, structures, utilities, and maintenance.

MBCM v1.7.5 applies to benefit–cost calculations commencing on or after 29 May
2026; General Circular 26/01 records that update. The separate General Circular
25/01, effective 6 January 2025, sets the stepped public-sector non-commercial
discount schedule and 8% sensitivity. Verify all three at the
[MBCM release page](https://www.nzta.govt.nz/resources/monetised-benefits-and-costs-manual)
and [General Circular 26/01](https://www.nzta.govt.nz/assets/resources/general-circulars/docs/26-01.pdf),
and [General Circular 25/01](https://www.nzta.govt.nz/assets/resources/general-circulars/docs/25-01.pdf).

## Uncertainty and computation

| Key | Default | Interpretation |
| --- | ---: | --- |
| `uncertainty_method` | Latin hypercube | Space-filling design over declared uncertain parameters |
| `uncertainty_draws` | 1,000 | Parameter/scenario draws; confirm convergence for publication |
| `uncertainty_seed` | 20260301 | Reproducible pseudo-random seed; additional seeds test numerical stability |
| `summary_quantiles` | 0.05, 0.50, 0.95 | Ensemble summaries, not universal confidence limits |
