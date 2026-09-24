# SPAN priorities

Agreed 24 September 2026, after deployment of commit `0937175`.

## Product aim

Show what a budget builds, which complete journeys it enables, who benefits,
and how dependable that conclusion is. Keep one understandable SPAN workspace.
Additional complexity or a bespoke router is not evidence of better decisions.

The Auckland-wide results currently use retained R5 routes with SPAN modelling.
Connected journeys uses SPAN's own constrained route search, on a local sample.
Neither analysis is a calibrated forecast of intervention-induced cycling.

## Ordered work

| Priority | Work | Acceptance evidence | Status |
| --- | --- | --- | --- |
| 1 | Demand support and ranking stability | Reproduce the current result first; quantify influential source cells; generate independent spatial OD replicates and reroute; compare selection stability and observed behaviour without changing source totals or treating suppression as zero. | First audit complete; fresh sampling and validation outstanding |
| 2 | Broaden complete-route planning | Test contrasting inner-city, suburban and outer Auckland areas; disclose crop failures, search caps, runtime and memory; only then offer a citywide package workflow. | Planned |
| 3 | Buildable interventions | Checked existing/committed infrastructure, crossing movements and waits, street widths, facility alternatives and defensible cost ranges. AT evidence and engineering review are dependencies. | Planned |
| 4 | Tangible access outcomes | Checked place-based journey names, before/after routes and destination access. Reuse useful TEAM opportunities; connect CRANC only after scenario, graph, profile and weighting contracts are verified. | Planned |
| 5 | Product reliability and practical use | Profile and reduce the 224 MiB uncompressed candidate payload without changing results; hash the journey report; saved alternatives, include/exclude controls and concise comparison exports. | Planned |
| 6 | Benchmark and planner evaluation | Same inputs and budgets for SPAN, whole-route greedy and capable published methods; compare access, cost, robustness, runtime and planner task success. Report ties and losses as well as wins. | Planned |

Priority 6's evaluation design should inform priorities 1–3, not be added after
tuning the model. Priority 5's integrity and performance fixes can be undertaken
without waiting for new AT data. New public controls should earn their place
through a planning task; do not bring back the separate research interface.

## First implementation: fixed-support influence audit

Implemented and run on 24 September:
[results, limits and reproduction](audit/span-source-cell-influence-2026-09-24.md).
All 12,580 standalone candidates and the fixed published programme reconcile
with the source results. Twelve targeted deletions show substantial sensitivity
in several leading individual ranks. This completes the first diagnostic, not
priority 1 or validation of the current recommendations.

The implementation extends the existing concentration diagnostics to compare the same
candidate universe after removing one influential **source OD cell** at a time.
Apply each deletion consistently across all candidate scores. Reconcile baseline
scores and the published NZ$100m programme against the checksummed source run.

The audit must:

- group all sampled records belonging to a source cell;
- evaluate the whole published package once per OD, not sum standalone benefits;
- use a deterministic, disclosed case-selection rule;
- show changes in standalone ranks and the existing package's modelled benefit;
- label these results as stress tests, not confidence intervals or a new build order;
- keep raw OD identifiers, coordinates and source-cell identifiers out of reports;
- leave the immutable source run, browser data and live server unchanged.

Deleting a source cell does not simulate a different home/work location within
that cell. It also reduces the evaluated population without redistribution.
Independent spatial replicates, fresh routes and held-out validation remain
necessary. This audit identifies where that next work is most important.

## Next implementation: paired sampling and routing pilot

1. Preserve the current run as the reference. Inventory the within-cell support
   pool and distinguish a new draw from existing locations from generation of
   genuinely new home/work locations.
2. Use independent, recorded seeds with the existing stratified sampling design
   and inclusion weights. Keep source totals, scenario, graph, costs and response
   assumptions fixed across methods. Do not bootstrap a confidence interval from
   one observed record per source cell.
3. Pilot fresh routing on a bounded, disclosed set of contrasting areas before
   committing to citywide replicates. Record routing failures, crop effects,
   time and memory; do not silently condition the comparison on successful routes.
4. Compare both the fixed published programme and programmes reselected on each
   paired replicate. Report selection frequency, rank changes, complete-journey
   coverage and benefit ranges separately. Include a strong whole-route greedy
   baseline wherever the candidate and journey definitions are comparable.
5. Review convergence and sensitive projects before replacing public results.
   Keep held-out observations for validation; repeated simulations alone do not
   establish calibrated demand or causal uptake.

## Operational boundaries

- Preserve reproducible inputs and compare methods on paired inputs.
- Do not relabel assumed signal waits as measured AT timings.
- Keep fixed-demand route assignment, access gains and new-cyclist forecasts separate.
- No claim of algorithmic novelty or superiority without comparative evidence.
- GitHub commits and release text must contain no AI tags or co-author trailers.
- Review new evidence before replacing the deployed model results.
