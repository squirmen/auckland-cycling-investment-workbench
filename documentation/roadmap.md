# SPAN priorities

Agreed 24 September 2026, after deployment of commit `0937175`.

## Product aim

Show what a budget builds, which complete journeys it enables, who benefits
and how reliable that result is. Keep SPAN to one workspace that planners can
follow. A more complex model or a bespoke router does not by itself mean better
decisions.

The Auckland-wide results currently use retained R5 routes with SPAN modelling.
Connected journeys uses SPAN's own constrained route search, on a local sample.
Neither is a calibrated forecast of the cycling an intervention would induce.

## Ordered work

| Priority | Work | Acceptance evidence | Status |
| --- | --- | --- | --- |
| 1 | Demand support and ranking stability | Reproduce the current result first; quantify influential source cells; generate independent spatial OD replicates and reroute; compare selection stability and observed behaviour without changing source totals or treating suppression as zero. | Influence audit and 291-pair stored-support rerouting complete; new spatial support and validation outstanding |
| 2 | Broaden complete-route planning | Test contrasting inner-city, suburban and outer Auckland areas; report crop failures, search caps, runtime and memory; only then offer a citywide package workflow. | Four bounded area checks complete; citywide scaling and boundary sensitivity outstanding |
| 3 | Buildable interventions | Checked existing and committed infrastructure, crossing movements and waits, street widths, facility alternatives and defensible cost ranges. Depends on AT evidence and engineering review. | Paired connector, search-limit and hypothetical fixed-cost tests complete in four areas; tighter search bounds tested with little effect; a second, price-guided route generator finds routes for more sampled records and leaves the NZ$20m packages' access unchanged; the crossing-cost evidence needed is listed; engineering and cost evidence outstanding |
| 4 | Tangible access outcomes | Checked place-based journey names, before/after routes and destination access. Reuse TEAM opportunity data where it helps. | Planned |
| 5 | Product reliability and practical use | Profile and reduce the 224 MiB uncompressed candidate payload without changing results; hash the journey report; saved alternatives, include/exclude controls and short comparison exports. | Compact payload verified and cuts raw JSON by 59%; the page opens on 1,846 of 12,580 links and needs about 1.6 MB before the first view, down from about 17 MB; brotli copies, retries and progress in place; report integrity and CLI fixes complete; deployed 1 October, with a first view in 3 to 4 seconds; the 8.8 MB full set takes 5 to 9 seconds, longer when the host is slow; the build order downloads as a table; saved alternatives and include/exclude controls outstanding |
| 6 | Benchmark and planner evaluation | Same inputs and budgets for SPAN, whole-route greedy and strong published methods; compare access, cost, robustness, runtime and planner task success. Report ties and losses as well as wins. | Paired methods compared across search caps, cost cases and two route generators; mixed results, with the best earlier package kept when a later solve is worse; external benchmarks and planner study outstanding |

Design the priority 6 evaluation before tuning priorities 1–3.
Priority 5's integrity and performance fixes do not need new AT data. A new
public control should be added only when a planning task needs it. The separate
research interface will not return.

Latest evidence: [a second way to generate routes](audit/span-priced-routes-2026-10-01.md),
[loading speed and interface fixes](audit/span-loading-and-interface-2026-10-01.md)
and [staged loading and tighter search bounds](audit/span-staged-loading-and-stress-bounds-2026-09-26.md),
following [search limits and cost sensitivity](audit/span-search-and-cost-sensitivity-2026-09-25.md),
[budgeted connectors and smaller candidate loading](audit/span-budgeted-connectors-and-loading-2026-09-25.md),
[short-link diagnosis](audit/span-candidate-coverage-2026-09-25.md) and
[demand-support checks](audit/span-follow-up-progress-2026-09-24.md).

Next: get the [crossing-cost evidence](research/crossing-cost-evidence.md) from
AT before pricing short links. In the four samples, cost, not search, now limits
access. Consider a content-delivery network in front of the host, which sent
0.5 to 2 MB a second to Auckland during testing. Broader sampling and graph
buffers are still needed. Unrestricted diagnostics are not affordable
programmes, and connected sample records are not new cyclists.

## Known issues in the published data (found 2 October 2026)

These need a new export of the same run, reviewed before it replaces the live
data. The interface and method notes now describe them; the numbers are
unchanged.

| Issue | Effect | Fix |
| --- | --- | --- |
| Whole-life cost falls back to capital cost for 271 links with no positive commute response | Those links look about 29% cheaper over 40 years; 5 of 25 School, 5 of 17 Everyday and 3 of 16 Stations best-value links are among them | Compute present-value lifecycle cost for every link, independent of demand |
| The shown benefit–cost ratio is the median of draws with a 1.5–8% discount rate | About 0.84 times the principal-schedule ratio; 34 links reach 1.0 at the principal rate, 20 as shown | Publish the principal and 8% ratios; label the draw range separately |
| Parameter draws scale every link by the same factors | Best-value and top-50 shares are 0% or 100% by construction (now hidden) | Vary response, routing or costs per link, or drop the shares |
| Deprived-areas demand is not written to the start-point layer | The layer is empty for that goal | Add NZDep decile 8–10 commute origins to the cell export |
| Confidentiality-bound and target-share reruns were not run | No envelope for suppressed counts or the 8% share | Run the paired lower and upper cases |

## First implementation: fixed-support influence audit

Run on 24 September:
[results, limits and reproduction](audit/span-source-cell-influence-2026-09-24.md).
All 12,580 standalone candidates and the fixed published programme reconcile
with the source results. In twelve targeted deletions, several leading
individual ranks move substantially. This is the first diagnostic only; it does
not complete priority 1 or validate the current recommendations.

The audit extends the existing concentration diagnostics. It compares the same
candidate universe after removing one influential **source OD cell** at a time,
with each deletion applied to every candidate score. Baseline scores and the
published NZ$100m programme are reconciled against the checksummed source run.

The audit was built to:

- group all sampled records belonging to a source cell;
- evaluate the whole published package once per OD, instead of summing standalone benefits;
- use a deterministic, disclosed rule for choosing cases;
- show changes in standalone ranks and in the existing package's modelled benefit;
- label the results as stress tests, not confidence intervals or a new build order;
- keep raw OD identifiers, coordinates and source-cell identifiers out of reports;
- leave the immutable source run, browser data and live server unchanged.

Deleting a source cell does not simulate a different home or work location
within that cell, and it shrinks the evaluated population without redistributing
it. Independent spatial replicates, fresh routes and held-out validation are
still needed. The audit shows where that work matters most.

## Next implementation: paired sampling and routing pilot

1. Keep the current run as the reference. List the within-cell support pool.
   Keep a new draw from existing locations separate from generating new home
   and work locations.
2. Use independent, recorded seeds with the existing stratified sampling design
   and inclusion weights. Keep source totals, scenario, graph, costs and response
   assumptions fixed across methods. Do not bootstrap a confidence interval from
   one observed record per source cell.
3. Pilot fresh routing on a bounded, disclosed set of contrasting areas before
   committing to citywide replicates. Record routing failures, crop effects,
   time and memory. Do not limit the comparison to successful routes without
   saying so.
4. Evaluate both the fixed published programme and programmes reselected on each
   paired replicate. Report selection frequency, rank changes, complete-journey
   coverage and benefit ranges separately. Include a strong whole-route greedy
   baseline wherever the candidate and journey definitions are comparable.
5. Review convergence and sensitive projects before replacing public results.
   Keep held-out observations for validation; repeated simulations alone do not
   establish calibrated demand or causal uptake.

## Standing decisions

- Inputs stay reproducible, and methods are compared on paired inputs.
- Assumed signal waits are not presented as measured AT timings.
- Fixed-demand route assignment, access gains and new-cyclist forecasts are reported separately.
- No claim that the method is new or better than others without comparative evidence.
- New evidence is reviewed before it replaces the deployed model results.
