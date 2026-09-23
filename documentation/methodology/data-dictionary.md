# Data dictionary

Names describe the canonical analytical schema. Importers may map publisher
fields to these names, but the mapping and units must appear in the provenance
manifest. Identifiers are strings to prevent truncation and preserve prefixes.

## Network nodes

| Field | Type | Unit | Constraint / meaning |
| --- | --- | --- | --- |
| `node_id` | string | — | Stable source identifier; unique and non-empty |
| `x`, `y` | number | CRS unit | Finite coordinates in the declared analysis CRS |
| `layer` | integer | — | Vertical/topological layer; zero if explicitly at grade |
| `source_dataset` | string | — | Provenance key in the build manifest |

## Physical network edges

| Field | Type | Unit | Constraint / meaning |
| --- | --- | --- | --- |
| `edge_id` | string | — | Stable physical-edge identifier; unique |
| `u`, `v` | string | — | Endpoint node IDs in source orientation |
| `direction` | enum | — | `both`, `forward`, or `reverse` |
| `length_m` | number | m | Positive physical length |
| `geometry` | linestring | analysis CRS | Endpoint alignment checked against `u`, `v` |
| `source_way_id` | string/null | — | Publisher way/link identifier |
| `road_class` | enum | — | motorway, arterial, collector, local, service, path |
| `facility` | enum | — | none, mixed traffic, painted lane, protected lane, shared path, quiet street |
| `speed_kph` | number/null | km/h | Observed or signed speed; null triggers documented imputation |
| `lanes` | integer/null | lanes | Direction convention documented by importer |
| `traffic_volume` | number/null | vehicles/day | Reference period and direction documented |
| `gradient` | number | rise/run | Signed in `u`→`v` direction |
| `intersection_stress` | integer | LTS | 1–4; worst relevant crossing for the edge traversal |
| `bridge`, `tunnel` | boolean | — | Source structure state |
| `lts` | integer | LTS | Derived 1–4 result |
| `imputed_fields` | array[string] | — | Inputs filled by declared defaults |
| `generalized_cost_forward`, `generalized_cost_reverse` | number/null | generalized m | Present only for permitted directions |

## OD demand

| Field | Type | Unit | Constraint / meaning |
| --- | --- | --- | --- |
| `od_id` | string | — | Stable unique relation identifier |
| `origin_area_id`, `destination_area_id` | string | — | Source statistical geography identifiers |
| `origin_node_id`, `destination_node_id` | string/null | — | Resolved graph node; null with failure reason if unsnapped |
| `origin_snap_m`, `destination_snap_m` | number/null | m | Snap distance |
| `source_scope` | enum | — | `internal`, `outbound`, `inbound`, `external`, or a product-specific declared scope; never inferred from a mismatched margin |
| `eligible_published` | number/null | trips in source period | Numeric total-stated release; null for an explicit suppression marker |
| `eligible_release_status` | enum | — | `numeric`, `suppressed`, `missing`, or a product-specific declared state |
| `eligible_lower`, `eligible_point`, `eligible_upper` | number | trips | Jointly interpreted total-stated interval and selected value |
| `observed_cycle_published` | number/null | trips | Numeric disclosure-controlled release; null for an explicit suppression marker |
| `observed_cycle_release_status` | enum | — | `numeric`, `suppressed`, `missing`, or a product-specific declared state |
| `observed_cycle_lower`, `observed_cycle_point`, `observed_cycle_upper` | number | trips | Bicycle-subset interval and selected value, jointly constrained to bicycle ≤ total stated |
| `target_universe_status` | enum | — | `included`, `outside_declared_universe`, or `unresolved_scope`; records are retained regardless |
| `purpose` | enum | — | `commute`, `school`, `everyday`, or `transit`; source and construction method are purpose-specific |
| `intrazonal` | boolean | — | Origin and destination source zones are the same; retained rather than silently discarded |
| `origin_weight_source`, `destination_weight_source` | string | — | Population, employment, enrolment, destination, or transit weighting provenance |
| `distance_km` | number | km | Routed or documented fallback distance |
| `gradient_percent` | number | percent | PCT hilliness input, not rise/run |
| `pct_probability` | number | share | Selected coefficient-set output |
| `scenario_additional` | number | trips | Target-constrained additional cycling |
| `scenario_total` | number | trips | Observed point plus additional, capped at the selected eligible point |
| `route_status` | enum | — | `routed`, `same-node`, `unsnapped`, `unreachable`, `outside_network_scope`, or `excluded` |
| `failure_reason` | string/null | — | Required for every non-routed status; exclusions never delete the ledger row |

## OD source coverage

This ledger describes source-universe omissions that cannot be represented as
ordinary OD rows. It is kept separately so an absent pair is never confused
with an explicit suppression marker or numeric zero.

| Field | Type | Unit | Constraint / meaning |
| --- | --- | --- | --- |
| `source_id`, `source_table`, `source_version` | string | — | Exact product identity; for the current commute input, table 121988 version 410594 |
| `included_population_definition` | string | — | Publisher definition, including the requirement that workplace address is available at SA2 |
| `structural_row_removal_rule` | string | — | Publisher rule for rows omitted before release, including total population below six |
| `published_row_count` | integer | rows | Rows actually present in the immutable source snapshot |
| `missing_row_mass_lower`, `missing_row_mass_upper` | number/null | trips | Bound only when supported by compatible publisher metadata; null means unresolved, not zero |
| `unlocated_workplace_mass_lower`, `unlocated_workplace_mass_upper` | number/null | trips | Compatible bound where available; null means unresolved |
| `coverage_status` | enum | — | `bounded`, `unresolved`, or `not_applicable` |
| `notes` | string | — | Scope mismatches, unavailable totals, and why no destination was fabricated |

## Production OD, path, and exact-edge ledgers

The production routing artifact contains `od_ledger.parquet`,
`path_ledger.parquet`, `path_edge_ledger.parquet`, `edge_flows.parquet`,
`failure_ledger.parquet`, `zonal_market_ledger.parquet`, and a checksummed
`manifest.json`. The OD ledger retains the complete spatialized input, including
records not selected by the declared probability sample.

| Field | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `od_id` | string | — | Parent OD relation |
| `source_cell_id` | string | — | Published zonal-OD stratum identifier |
| `route_sample_selected` | boolean | — | Whether this spatial support record was routed in the declared sample |
| `route_sample_rank` | integer | — | Stable SHA-256 seeded ordering within the stratum |
| `route_stratum_size`, `route_stratum_sample_size` | integer | records | Full and selected spatial support records in the stratum |
| `route_inclusion_probability` | number | probability | Exact without-replacement inclusion probability |
| `analysis_weight` | number | inverse probability | Horvitz--Thompson weight; zero on unselected output rows |
| `weighted_eligible`, `weighted_observed_cycle` | number | trips | Sample-expanded demand on selected records |
| `origin_node_id`, `destination_node_id` | string/null | — | Exact source-identified SPAN snap nodes |
| `origin_snap_distance_m`, `destination_snap_distance_m` | number/null | m | Demand support point to SPAN terminal distance |
| `origin_component`, `destination_component` | string/null | — | Auditable network component identities |
| `origin_layer`, `destination_layer` | integer/null | OSM layer | Terminal layer metadata; source node identity remains authoritative |
| `route_status`, `failure_reason` | enum/string/null | — | `assigned`, `unassigned`, or `not_selected_probability_sample`; every failure is retained |
| `shortest_distance_m` | number/null | m | Separately routed shortest feasible physical distance |
| `path_ids`, `path_probabilities` | array | — / share | Retained paths and conditional probabilities, summing to one for each assigned OD |
| `path_id` | string | — | Stable identifier within the OD choice set |
| `r5_edge_ids`, `r5_osm_way_ids` | array[integer] | — | Ordered engine and source-way audit identities |
| `project_edge_ids`, `project_edge_reversed` | arrays | — | Ordered exact SPAN physical-edge identities and traversal directions |
| `generalized_cost` | number | generalized m | Sum of directed edge cost |
| `length_m` | number | m | Physical path length |
| `detour_ratio` | number | ratio | Path length divided by the shortest physical-distance route |
| `path_probability` | number | share | Conditional probability within the retained plausible-path set; sums to one per routed OD/state |
| `edge_sequence`, `project_edge_id`, `reversed` | integer/string/boolean | — | One ordered row per exact path-edge traversal |
| `estimated_observed_cycle`, `estimated_eligible` | number | trips | Sample-expanded OD demand multiplied by conditional path probability |
| `path_edge_records` | integer | records | Exact path-edge rows aggregated into an edge-flow record |

Uncertainty quantiles such as `flow_p05`, `flow_p50`, and `flow_p95` belong to
the later uncertainty output, not to the baseline routing ledger.

## Optional area context

These fields describe areas, not people. Raw NZDep polygons are not included in
the public browser snapshot; only aggregate subgroup metrics are exported.

| Field | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `area_id` | string | — | Stable source geography identifier |
| `context_source_id`, `context_version` | string | — | Exact contextual dataset and vintage |
| `nzdep_decile` | integer/null | 1–10 relative decile | NZDep2023 area decile in prepared analysis data; raw values are not exported to the public browser layer |
| `nzdep_score` | number/null | index points | NZDep2023 area score in prepared analysis data; never an individual attribute |
| `context_status` | enum | — | `available`, `withheld`, `missing`, `rights_blocked`, or `not_applicable` |

## Candidate corridors

| Field | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `candidate_id` | string | — | Stable unique candidate identifier |
| `name` | string | — | Human-readable label; not used as join key |
| `edge_ids` | array[string] | — | Exact treated physical edges |
| `treatment` | enum | — | Proposed facility state |
| `seed_edge_ids`, `connector_edge_ids` | array[string] | — | Candidate construction provenance |
| `length_m` | number | m | Unique physical treated length |
| `capital_cost_nzd` | number | NZD and stated price base | Non-negative screening cost |
| `connects_to_existing` | boolean | — | Topological connection under stated low-stress rule |
| `baseline_cost_by_od`, `treated_cost_by_od` | object | generalized m | Comparable route cost for evaluated OD relations |
| `changed_edge_ids` | array[string] | — | Edges whose treatment/cost changed |
| `additional_cycle_by_od` | object | trips | Increment attributed by the declared response model |
| `additional_cycle_trips` | number | trips | Sum of the OD-level increments |
| `od_low_stress_share_delta`, `demand_weighted_od_low_stress_share_delta` | number/null | share | Marginal SPAN OD low-stress connectivity share under the complete stated denominator; null when full-network rerouting has not executed |
| `annual_benefit_nzd` | number | NZD/year and stated price base | Incremental monetised categories only |
| `screening_bcr` | number/null | ratio | Present-value benefits divided by present-value costs |
| `uncertainty_*` | number/null | field unit | Clearly named conditional interval metrics |
| `data_completeness` | number/null | share | Share of required candidate evidence present under the declared rule |
| `routing_coverage` | number/null | share | Share of the affected OD market successfully recomputed |
| `frontier_stability` | number/null | share | Fraction of declared uncertainty runs in which the candidate remains non-dominated |
| `rank_stability` | number/null | share | Declared top-k inclusion frequency or other explicitly named rank-stability measure |
| `sensitivity_range` | number/null | declared unit | Range of the named outcome across the declared parameter/structural design |
| `warnings` | array[string] | — | Data, topology, extrapolation, or interpretation flags |

## Cumulative portfolio steps

| Field | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `step` | integer | — | One-based position in the evaluated portfolio |
| `candidate_id` | string | — | Candidate applied at this step |
| `cumulative_candidate_ids` | array[string] | — | User/preset-defined ordered set through this step |
| `marginal_outcomes` | object | declared units | Changes conditional on earlier treatments; the manifest states whether recomputation used the full network or a retained path choice set |
| `cumulative_outcomes` | object | declared units | Outcomes after applying the cumulative set |
| `marginal_cost_nzd`, `cumulative_cost_nzd` | number | NZD and price base | Screening capital cost |
| `portfolio_id` | string | — | Named preset, saved comparison, or scenario identifier |

## Counter validation

| Field | Type | Unit | Meaning |
| --- | --- | --- | --- |
| `counter_id` | string | — | Publisher site identifier |
| `observed` | number | cycles per stated period | Quality-screened count |
| `period_start`, `period_end` | date/time | ISO 8601 | Exact aggregation window |
| `coverage` | number | share | Proportion of expected observations present |
| `bearing_degrees` | number/null | degrees | Direction represented by site |
| `bidirectional` | boolean | — | Whether count includes both directions |
| `matched_edge_id` | string/null | — | Exact matched physical edge |
| `match_distance_m` | number/null | m | Distance from site to edge |
| `direction_compatible` | boolean/null | — | Bearing/direction check |
| `modelled_comparable` | number/null | cycles per same period | Present-day model quantity only |
| `exclusion_reason` | string/null | — | Why site was not used in validation |

## Run manifest

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of the run-manifest contract |
| `run_id` | string | Content-derived build identifier |
| `project_id`, `status` | string/enum | Project identity and run state |
| `created_at`, `updated_at` | datetime | UTC run timestamps |
| `config` | object | Portable source/snapshot paths and executed configuration checksum |
| `model` | object | Package, method, configuration-schema, and manifest-schema versions plus the deterministic Python implementation-source checksum used to validate the complete run tree; stage-cache fingerprints use declared input scopes and explicit semantic stage versions |
| `seeds` | object | Procedure-specific reproducible seeds |
| `sources` | object | Per-source portable path, requirement, availability, byte size, and SHA-256 checksum |
| `runtime` | object | Python, dependency, operating-system, JVM, Java, R5, and other recorded runtime versions where applicable |
| `stages` | object | Status, content fingerprint, timing, metrics, error, and checksummed outputs for every stage |

The public release dossier supplements the run manifest with source titles,
publisher URLs, snapshot dates, licences, and the checksum of each dependency
lock. It must not infer those rights from a file's presence.
