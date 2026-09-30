# SPAN methodology review and research contribution

17 September 2026. Implementation audit, targeted primary-source review and local
experiment. This is not evidence that SPAN has surpassed the state of the art.

## Finding

SPAN now has its own functioning directed, resource-constrained route engine.
It searches streets rather than drawing connections between ranked links. It
keeps shared investment requirements, physical distance, time and preference
cost separate. The software is real; algorithmic uniqueness is not established.
Neither A*, Pareto labels, path-size logit nor mixed-integer network investment
is new. A publishable contribution must be demonstrated against capable
baselines and observed data, not inferred from combining these components.

The most useful research question is whether preserving whole-route investment
dependencies, heterogeneous preferences and OD uncertainty together produces
more reliable, explainable portfolios than simpler network heuristics. This is
a hypothesis to test. It is not a claim that no one has attempted the combination.

## What the literature changes about our approach

| Primary source | Established capability | Consequence for SPAN |
| --- | --- | --- |
| [Lim et al., Bicycle Network Improvement Problem](https://arxiv.org/abs/2107.04451), revised 2022 | Safety, detours and budgeted network improvement; Benders decomposition | Whole-route gap completion is a sound foundation, but cannot be our novelty claim. Benchmark against this family. |
| [Fluschnik, Safe Bicycle Network with Bounded Detours](https://arxiv.org/abs/2608.09472), August 2026 preprint | Complexity analysis, exact algorithms and preprocessing for safe routes with bounded detours | Exhaustively enumerating all paths is not a scalable research strategy. Use admissible bounds and retain explicit optimality limits. This is a preprint, not settled performance evidence. |
| [Broach, Gliebe and Dill, calibrated route-set generation](https://ppms.trec.pdx.edu/media/project_files/TRB2010_A%20calibrated%20labeling%20method%20for%20generating%20bicyclist%20route%20choice%20sets%20incorporating%20unbiased%20attribute%20variation.pdf), 2010 | Alternative generation matters for estimating bicycle route choice | One shortest path is insufficient for behavioural claims. Diverse alternatives and held-out observed routes are necessary. |
| [Steinacker et al., Robust design of bicycle infrastructure networks](https://www.nature.com/articles/s41598-025-99976-9), 2025 | Dynamic rerouting, demand response, welfare optimisation and simpler percolation methods; input sensitivity | More complexity is not automatically better. Compare simple whole-route selection as well as weak single-link selection, and report ties or failures. |
| [Lovelace et al., Propensity to Cycle Tool](https://arxiv.org/abs/1509.04425) and [Woodcock et al., underlying uptake model](https://pmc.ncbi.nlm.nih.gov/articles/PMC8463831/) | Cycling scenarios mapped from OD demand to routes and networks | PCT already includes route-network allocation. SPAN's intended extension is explicit investment counterfactuals and route dependencies; do not portray PCT as only OD totals. Imported propensity is not Auckland calibration. |
| [NAU CRANC project description](https://www.ceias.nau.edu/cs/CS_Capstone/Projects/F25/7.CRANC_Gehrke.pdf) | Profile-specific cycling accessibility and destination opportunities | Preserve CRANC's authorship and use its accessibility outputs beside SPAN's investment and demand measures. |

## The implemented chain and its limits

The main Auckland explorer and the experimental routing page are **different
analyses** of the same source run. New research results do not silently replace
the established scenario rankings or their appraisal values.

| Stage | Implemented | Still needed for decision-grade use |
| --- | --- | --- |
| Demand support | Checksummed source OD/scenario ledgers, exclusions and weights; concentration diagnostics | More spatial samples within source cells, independent replicates, confidentiality sensitivity and reconciled source universes |
| Directed routing | Exact source arcs, street/turn stress, turn bans, physical time and detour limits, bounded label search | Auckland movement-specific evidence; full-network checks beyond the crop; validated speed and effort terms |
| Preferences | Three explicitly unfitted facility/stress sensitivity cases; fresh routing after each distinct investment | Local GPS/route observations, diverse choice-set validation, estimated coefficients and rider-type shares |
| Assignment | Distinct profile-optimum routes, overlap correction, conservation of fixed scenario cycling; unassigned demand retained | Richer alternatives, observed counts and route shares, separate outbound/return and purpose models |
| Uptake | Existing production sensitivity, exposed separately from assignment | Calibrated mode-choice response; uncertainty intervals reflecting sampling and parameters; evaluation against interventions |
| Investment | Shared project costs, complete-route access, exact master within generated routes, single-link and route-package baselines | Feasible multiple facility options, committed schemes, sequencing, distributional constraints and robustness across OD replicates |
| Appraisal | Existing indicative production scenario calculations | Locally defensible treatment costs, safety effects, appraisal inputs and benefits without double counting |
| Planning workflow | Full route and project geometry, before/after access, controls, GeoJSON with provenance, scoped CRANC exchange | Planner task studies, independently checked schemes and a documented operational acceptance process |

### Route search

An arc preserves physical distance and time. A fixed-investment preference case
adds non-negative penalties in equivalent seconds:

`cost = time_weight × physical_seconds + distance_km × (distance_penalty + facility_penalty + stress_penalty)`.

Turn delay contributes separately. Protected facilities can have a lower
penalty than painted lanes or mixed traffic; no negative edge reward is used.
The current sensitivity cases hold the physical speed model constant and do not
estimate crash risk. Grade affects physical time through the existing transparent
uphill speed assumption, not a calibrated energy-expenditure model.

Labels preserve distance, time, preference cost, incoming movement and project
requirements. A label is dominated only when another compatible label requires
a subset of its projects and has no larger resource/cost values. A slower or
longer route with a lower preference cost therefore survives. Reverse distance,
time and cost bounds ignore restrictions that could only raise remaining cost;
they cannot make an infeasible route pass the forward checks. An LRU cache bounds
the number of stored reverse searches, avoiding growth with every destination.

Investment discovery retains nondominated project requirements under the hard
access standard. Preference routing first materialises the whole selected
investment on the graph, then searches again. This applies treatment consistently
to every affected arc; it does not merely discount routes retained before the
investment. A separate crossing is unchanged unless its own treatment is selected.

For fixed-investment routing, the first destination removed from the admissible
cost-bound queue is a minimum-cost feasible witness within that graph and declared
constraints, provided the search has not truncated. It is not an exhaustive route
choice set. Preference-cost resource dominance and minima are checked against
exhaustive small-graph enumeration; label caps remain visible.

### Assignment and induced cycling

For each OD/investment, take the distinct minimum-cost routes found by the three
preference cases. Assign the same source `commute_8pct` cycling total separately
under each case, using path-size logit. Arc sharing reduces the overrepresentation
of overlapping alternatives. Duplicate routes are removed before assignment.

`assigned commuters + unassigned commuters = supplied scenario commuters`.

This tests route allocation under three assumptions; the three cases must never
be summed. Their coefficients and route-choice scale are published in the UI.
Unassigned demand means no acceptable route was found under the current crop,
investment and constraints. It is not a prediction that these people stop cycling.
Newly accommodating fixed scenario demand is not induced cycling. The research
report deliberately has `additionalCyclists: null` and no BCR.

## Expanded local experiment

The run uses all 169 eligible, previously assigned commute OD records whose
endpoints lie in the 4 km North Shore crop: 24,467 nodes, 47,146 directed arcs,
195 complete candidate projects. It retains source weights without another
pilot expansion. Total eligible weight is 10,058.64; it is not a census of every
local journey or representative of Auckland. Original within-cell sampling
remains sparse. Eleven records are disconnected inside the cropped graph.

All investment searches finished within the 15,000-label cap. Preference searches
also finished without truncation. The full local execution took about 53 seconds
including loading, investment selection and fresh assignment; this is a recorded
timing, not a comparative speed claim.

| Budget ceiling | Single-link greedy: eligible access | Whole-route greedy | Optimised packages |
| --- | ---: | ---: | ---: |
| $0m | 1,635.72 | 1,635.72 | 1,635.72 |
| $5m | 2,205.96 | 2,205.96 | 2,205.96 |
| $10m | 2,205.96 | 2,484.72 | 2,484.72 |
| $20m | 2,205.96 | 2,991.72 | 2,991.72 |

At $20m, both whole-route methods select six projects costing $18.741m and serve
14 source ODs, up from 11 without investment. The gain is 1,356 eligible commute
weight. The exact optimiser does **not** improve on whole-route greedy in this
expanded case. Its proof applies to generated route columns, not the uncropped
city or different treatment assumptions. Budget solutions are independent.

The fixed 8% scenario contains 1,286.22 cycle commuters in these records. The
number assigned to acceptable routes increases from 255.34 to 443.34, leaving
842.87 unassigned. These totals agree across preference cases because the hard
standard is shared; route shares can differ. Seven ODs have more than one route
in the combined preference choice set. The gain of about 188 assigned commuters
is **not a forecast of new riders**.

Results and source fingerprints are in `access-experiment-169-result.json`.
The previous 12-record pilot is retained as historical evidence; it is not the
current research-page dataset.

## Publication and planning acceptance gates

1. **Sampling:** generate several spatial OD supports within each source cell,
   preserving totals and disclosure intervals. Use paired independent replicates
   across all methods. Report effective concentration, rank/selection stability
   and distribution of portfolio regret. Increasing the number of local source
   records alone does not solve within-cell sampling uncertainty.
2. **Behaviour:** obtain suitable local observed routes and counts; define a
   holdout before estimation. Test shortest-distance, fastest, low-stress and
   estimated preference models on route coverage, likelihood, length/grade and
   facility exposure. Do not tune to the evaluation set.
3. **Investment:** compare whole-route greedy, exact access optimisation, a BNIP
   implementation and a dynamic network heuristic at the same costs and demand.
   Include unit, sampling, treatment and budget sensitivity. Report cases in which
   a simple method ties or wins, and enforce construction feasibility.
4. **Efficiency:** separate graph loading, preprocessing, cold query, warm query,
   assignment and optimisation. Record hardware, memory, labels, timing quantiles,
   caps, solver gaps and crop failures. Ablate bounds, preference dimensions and
   reuse. A few small exact tests do not establish citywide scalability.
5. **Planning outcomes:** confirm existing/programmed infrastructure and crossings;
   compare who reaches which destinations and which groups remain excluded.
   Validate costs and observed intervention response before welfare or BCR claims.
   Have planners complete realistic tasks and record errors and time to decision.

A microsimulation layer should be added only for a specified mechanism and a
validation dataset—such as departure timing, interactions or household constraints.
It would not, by itself, solve sparse demand or uncalibrated uptake.

## CRANC

Both supplied archives were inspected read-only. SPAN now exports a comparison
request and can import a scoped, attributed accessibility comparison locally.
It does not execute CRANC, copy its coefficients into SPAN, transmit ODs or claim
to have implemented investment scenarios in CRANC. The native service interfaces
and Auckland transfer issue are documented in [the integration review](cranc-integration.md).

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 --sample-size 169
PYTHONPATH=src .venv/bin/python -m pytest tests/test_active_search.py tests/test_route_preferences.py
```

Inputs must be locally readable. This session used a checksummed temporary copy
outside Dropbox File Provider; original run artifacts and production rankings
were not rewritten. Serve `web/` with Vite and open `research.html`.
