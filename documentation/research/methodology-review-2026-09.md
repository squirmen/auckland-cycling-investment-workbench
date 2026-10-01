# SPAN methodology review

17 September 2026. An audit of the implementation, a targeted review of primary
sources and a local experiment. It is not evidence that SPAN outperforms
published methods.

## Finding

SPAN now has its own working route engine, directed and resource-constrained.
It searches streets instead of drawing connections between ranked links. It
keeps shared investment requirements, physical distance, time and preference
cost separate. The software works, but the algorithm has not been shown to
be unique. A*, Pareto labels, path-size logit and mixed-integer network
investment are all existing methods. A publishable contribution has to be shown
against strong baselines and observed data. Combining these parts does not
establish one.

The most useful research question is whether handling whole-route investment
dependencies, heterogeneous preferences and OD uncertainty together gives more
reliable, explainable portfolios than simpler network heuristics. This is a
hypothesis to test, not a claim that nobody has tried the combination.

## What the literature means for SPAN

| Primary source | Established capability | Consequence for SPAN |
| --- | --- | --- |
| [Lim et al., Bicycle Network Improvement Problem](https://arxiv.org/abs/2107.04451), revised 2022 | Safety, detours and budgeted network improvement; Benders decomposition | Whole-route gap completion is a sound basis but cannot be claimed as new. Benchmark against this family of methods. |
| [Fluschnik, Safe Bicycle Network with Bounded Detours](https://arxiv.org/abs/2608.09472), August 2026 preprint | Complexity analysis, exact algorithms and preprocessing for safe routes with bounded detours | Enumerating every path does not scale. Use admissible bounds and state optimality limits. This is a preprint, not settled performance evidence. |
| [Broach, Gliebe and Dill, calibrated route-set generation](https://ppms.trec.pdx.edu/media/project_files/TRB2010_A%20calibrated%20labeling%20method%20for%20generating%20bicyclist%20route%20choice%20sets%20incorporating%20unbiased%20attribute%20variation.pdf), 2010 | Alternative generation matters for estimating bicycle route choice | One shortest path is not enough for behavioural claims. Diverse alternatives and held-out observed routes are needed. |
| [Steinacker et al., Robust design of bicycle infrastructure networks](https://www.nature.com/articles/s41598-025-99976-9), 2025 | Dynamic rerouting, demand response, welfare optimisation and simpler percolation methods; input sensitivity | More complexity is not automatically better. Compare against simple whole-route selection as well as weak single-link selection, and report ties or failures. |
| [Lovelace et al., Propensity to Cycle Tool](https://arxiv.org/abs/1509.04425) and [Woodcock et al., underlying uptake model](https://pmc.ncbi.nlm.nih.gov/articles/PMC8463831/) | Cycling scenarios mapped from OD demand to routes and networks | PCT already allocates demand to route networks; it is more than OD totals. SPAN aims to add investment counterfactuals and route dependencies. Imported propensity is not Auckland calibration. |

## The implemented chain and its limits

The main Auckland explorer and the experimental routing page are **different
analyses** of the same source run. New research results do not replace the
established scenario rankings or their appraisal values without notice.

| Stage | Implemented | Still needed for decision-grade use |
| --- | --- | --- |
| Demand support | Checksummed source OD/scenario ledgers, exclusions and weights; concentration diagnostics | More spatial samples within source cells, independent replicates, confidentiality sensitivity and reconciled source universes |
| Directed routing | Exact source arcs, street/turn stress, turn bans, physical time and detour limits, bounded label search | Auckland movement-specific evidence; full-network checks beyond the crop; validated speed and effort terms |
| Preferences | Three unfitted facility/stress sensitivity cases; fresh routing after each distinct investment | Local GPS/route observations, diverse choice-set validation, estimated coefficients and rider-type shares |
| Assignment | Distinct profile-optimum routes, overlap correction, conservation of fixed scenario cycling; unassigned demand retained | Richer alternatives, observed counts and route shares, separate outbound/return and purpose models |
| Uptake | Existing production sensitivity, shown separately from assignment | Calibrated mode-choice response; uncertainty intervals reflecting sampling and parameters; evaluation against interventions |
| Investment | Shared project costs, complete-route access, exact master within generated routes, single-link and route-package baselines | Feasible multiple facility options, committed schemes, sequencing, distributional constraints and robustness across OD replicates |
| Appraisal | Existing indicative production scenario calculations | Locally defensible treatment costs, safety effects, appraisal inputs and benefits without double counting |
| Planning workflow | Full route and project geometry, before/after access, controls, GeoJSON with provenance | Planner task studies, independently checked schemes and a documented operational acceptance process |

### Route search

Each arc keeps its physical distance and time. A fixed-investment preference
case adds non-negative penalties in equivalent seconds:

`cost = time_weight × physical_seconds + distance_km × (distance_penalty + facility_penalty + stress_penalty)`.

Turn delay is added separately. Protected facilities can carry a lower penalty
than painted lanes or mixed traffic; no edge has a negative reward. The current
sensitivity cases hold the physical speed model constant and do not estimate
crash risk. Grade affects physical time through the existing uphill speed
assumption, not a calibrated energy-expenditure model.

Labels carry distance, time, preference cost, incoming movement and project
requirements. A label is dominated only when another compatible label requires
a subset of its projects and has no larger resource or cost values, so a slower
or longer route with a lower preference cost survives. Reverse distance, time
and cost bounds ignore restrictions that could only raise the remaining cost;
they cannot make an infeasible route pass the forward checks. An LRU cache caps
the number of stored reverse searches, so they do not grow with every
destination.

Investment discovery keeps nondominated project requirements under the hard
access standard. Preference routing first adds the whole selected investment
to the graph and then searches again, so every affected arc gets the
treatment. It does not just discount routes found before the investment. A separate
crossing is unchanged unless its own treatment is selected.

For fixed-investment routing, the first destination removed from the admissible
cost-bound queue is a minimum-cost feasible witness within that graph and its
declared constraints, provided the search has not truncated. It is not a full
route choice set. Preference-cost resource dominance and minima are checked
against exhaustive enumeration on small graphs; label caps remain visible.

### Assignment and induced cycling

For each OD and investment, the distinct minimum-cost routes found by the three
preference cases form the choice set. The same source `commute_8pct` cycling
total is assigned separately under each case with path-size logit, in which
shared arcs reduce the overrepresentation of overlapping alternatives. Duplicate
routes are removed before assignment.

`assigned commuters + unassigned commuters = supplied scenario commuters`.

This tests route allocation under three assumptions; the three cases must never
be summed. Their coefficients and route-choice scale are shown in the
interface. Unassigned demand means no acceptable route was found under the
current crop, investment and constraints, not that these people stop cycling.
Newly accommodating fixed scenario demand is not induced cycling, so the
research report has `additionalCyclists: null` and no BCR.

## Expanded local experiment

The run uses all 169 eligible, previously assigned commute OD records whose
endpoints lie in the 4 km North Shore crop: 24,467 nodes, 47,146 directed arcs
and 195 complete candidate projects. It keeps source weights with no further
pilot expansion. Total eligible weight is 10,058.64. This is not a census of
every local journey and does not represent Auckland. The original within-cell
sampling is still sparse. Eleven records are disconnected inside the cropped
graph.

All investment searches finished within the 15,000-label cap. Preference
searches also finished without truncation. The full local run took about 53
seconds including loading, investment selection and fresh assignment. That is
one recorded timing, not a speed comparison.

| Budget ceiling | Single-link greedy: eligible access | Whole-route greedy | Optimised packages |
| --- | ---: | ---: | ---: |
| $0m | 1,635.72 | 1,635.72 | 1,635.72 |
| $5m | 2,205.96 | 2,205.96 | 2,205.96 |
| $10m | 2,205.96 | 2,484.72 | 2,484.72 |
| $20m | 2,205.96 | 2,991.72 | 2,991.72 |

At $20m, both whole-route methods select six projects costing $18.741m and serve
14 source ODs, up from 11 without investment. The gain is 1,356 in eligible
commute weight. The exact optimiser does **not** improve on whole-route greedy
in this expanded case. Its optimality proof covers the generated route columns,
not the uncropped city or other treatment assumptions. Each budget is solved
independently.

The fixed 8% scenario contains 1,286.22 cycle commuters in these records. The
number assigned to acceptable routes rises from 255.34 to 443.34, leaving
842.87 unassigned. These totals agree across preference cases because the hard
standard is shared; route shares can differ. Seven ODs have more than one route
in the combined preference choice set. The gain of about 188 assigned commuters
is **not a forecast of new riders**.

Results and source fingerprints are in `access-experiment-169-result.json`.
The earlier 12-record pilot is kept as a historical record; it is not the
current research-page dataset.

## Publication and planning acceptance gates

1. **Sampling:** generate several spatial OD supports within each source cell,
   preserving totals and disclosure intervals. Use paired independent replicates
   across all methods. Report effective concentration, rank and selection
   stability and the distribution of portfolio regret. More local source records
   alone do not solve within-cell sampling uncertainty.
2. **Behaviour:** obtain suitable local observed routes and counts; define a
   holdout before estimation. Test shortest-distance, fastest, low-stress and
   estimated preference models on route coverage, likelihood, length/grade and
   facility exposure. Do not tune to the evaluation set.
3. **Investment:** compare whole-route greedy, exact access optimisation, a BNIP
   implementation and a dynamic network heuristic at the same costs and demand.
   Include unit, sampling, treatment and budget sensitivity. Report cases where
   a simple method ties or wins, and enforce construction feasibility.
4. **Efficiency:** separate graph loading, preprocessing, cold query, warm query,
   assignment and optimisation. Record hardware, memory, labels, timing quantiles,
   caps, solver gaps and crop failures. Ablate bounds, preference dimensions and
   reuse. A few small exact tests do not establish citywide scalability.
5. **Planning outcomes:** confirm existing and programmed infrastructure and
   crossings; compare who reaches which destinations and which groups remain
   excluded. Validate costs and observed intervention response before welfare or
   BCR claims. Have planners complete realistic tasks and record errors and time
   to decision.

Add a microsimulation layer only for a specified mechanism with a validation
dataset, such as departure timing, interactions or household constraints. On
its own it would not solve sparse demand or uncalibrated uptake.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 --sample-size 169
PYTHONPATH=src .venv/bin/python -m pytest tests/test_active_search.py tests/test_route_preferences.py
```

Inputs must be readable locally. The review used a checksummed temporary copy
of the inputs; original run artifacts and production rankings
were not rewritten. Serve `web/` with Vite and open `research.html`.
