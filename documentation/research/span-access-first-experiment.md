# SPAN: complete routes, stable demand and connected investment

16 September 2026. Local experimental implementation; not a calibrated Auckland
travel-demand model, transport recommendation or claim of algorithmic novelty.

**17 September update:** the [current methodology review](methodology-review-2026-09.md)
documents the expanded 169-record run, explicit route preferences, fresh
fixed-demand assignment, planner exports and the implemented CRANC file-exchange
boundary. The 12-record results below are the historical first pilot. Statements
below about absent preference routing or an uninspected CRANC archive describe
that earlier implementation, not the current research page.

## What now runs

`research/active_search.py` searches exact directed street arcs with a maximum
traffic-stress level, a detour limit relative to the shortest legal route, a
travel-time limit and a capital budget. A route carries the identities of all
required projects, including a separate crossing project when supplied.
An existing acceptable street needs no investment. A high-stress street is
usable only if its eligible treatment passes the threshold. A project spanning
several arcs is paid for once. Prohibited turns remain prohibited.

The search retains distance/time/project-set trade-offs. A cheaper route with
different projects cannot automatically discard a more expensive one: the
second route may share investments with another OD. Reverse distance and time
bounds prune impossible continuations; dominance requires a subset of projects
and no greater distance or time. The implementation exposes label counts,
pruning counts, elapsed time and truncation. A label-limited search never claims
its frontier is complete. This is a resource-constrained path algorithm using
established ideas, not enumeration of every possible walk.

`research/investment.py` selects shared projects under a budget with binary
route witnesses. Every required gap must be funded before that OD counts as
served. Each OD and project counts once even when multiple routes use it. HiGHS
first maximises eligible OD weight with a complete route, then minimises cost
without sacrificing that result. Optimality refers only to supplied route
columns. The kernel also supports mutually exclusive project options in the
investment master; route generation currently supplies one treatment per arc.

Two comparison strategies use exactly the same routes and weights: greedy
individual links and greedy complete packages. Every selected route is checked
by another search with only funded treatments enabled. Tests include exhaustive
small-graph path enumeration across every possible project portfolio, directed
turn restrictions, shared project cost, a two-gap complementarity example,
distance/time trade-offs and a bound-pruning ablation.

## The recorded Auckland pilot

Source: `run-313e0277521633d3`. A 4 km circle around the selected Rangatira Road
candidate contains 24,467 graph nodes, 47,146 directed arcs and 195 complete
candidate projects. A deterministic hash ordering (seed 20260915) selects 12
of 169 eligible local source OD records. No additional expansion is applied
for this pilot sample. All 12 searches finished without hitting the 15,000-label
cap. The initial run took about 13 seconds including topology loading; this is
one local timing, not a speed benchmark.

| Budget | Greedy individual links: served OD weight | Greedy packages | Optimised packages |
| --- | ---: | ---: | ---: |
| $0m | 0 | 0 | 0 |
| $5m | 0 | 0 | 0 |
| $10m | 0 | 278.76 | 278.76 |
| $20m | 0 | 278.76 | 298.08 |

At $10m, a two-project package costs $6.205m. At $20m, the optimised solution
instead selects four projects costing $14.850m. These are independently solved
budgets, not an ordered programme with previously committed projects.

The last solution enables one sampled OD route, 1.109 km long. Its 298.08 weight
is **eligible commuting access**, not 298 new cyclists. The two records with
feasible upgrade routes account for about 86% of the entire pilot's weighted
demand. That concentration is a limitation inherited from the source sampling,
not evidence of a robust best investment. Three sampled ODs are disconnected in
the cropped directed graph; the remaining unsuccessful searches find no route
passing all declared limits and available treatments. Boundary effects matter.

The research page shows the complete route, existing facility segments, other
usable streets, required investment and the full extents/costs of each project.
It draws only recorded routes. It does not synthesise routes for failed ODs.

## Why the current rider forecast needs repair

The reproducible [ridership audit](../audit/span-ridership-audit.json) reconciles
61,855 scenario/candidate values with their source counterfactual ledger and
recomputes the 12 leading standalone candidates from checksummed OD/path files.
The first six gains cluster around 51–54 because they are the selected upper
tail. Across all 12,580 candidates, the median additional estimate is 0.259,
the 99th percentile is 15.033 and the maximum is 54.476. There is no 54-person
cap in the response formula.

More seriously, this run samples **one commute record per source OD cell**.
For Beach Road, one record contributes 51.54 of the 54.48 additional commuters
(94.6%). It represents 434.88 eligible commuters after a route-sampling weight
of 24 is applied, has one retained route, and originates in an intrazonal market.
For Shelly Beach Road, one record contributes 99.90% of the gain. These are
concentration diagnostics, not formal sampling standard errors. More records
need not increase every forecast; rankings can move in either direction.

The neutral, uncalibrated response elasticity is also consequential. Holding
Beach Road's OD weights and routes fixed gives 23.74, 54.48 and 135.84 additional
commuters at elasticities 0.5, 1 and 2. These are scenarios, not confidence limits.
The tiny probability floor contributes no Beach Road gain under the 8% scenario;
it therefore does not explain that candidate's result. Some other candidates
receive tiny floor-related additions even at zero elasticity. This behaviour
is disclosed here rather than silently changing the historical run.

The observed baseline uses lower-bound suppressed cycling cells and is not a
reliable street-count baseline. The 8% scenario already introduces assumed
cycling before an upgrade is evaluated. Non-commute access scores are separate
opportunity indices and cannot be added to commute riders or annualised as trips.

## Next model changes and evidence gates

1. **Resolve demand support before calibrating uptake.** Increase spatial OD
   support within each source cell, preserve cell totals and confidentiality
   intervals, use independent replicate seeds, and report concentration and
   rank stability. Do not multiply the existing forecasts to meet expectations.
2. **Discover plausible routes afresh after investment.** Retain the exact
   stress-constrained access calculation, then generate diverse alternatives
   for assignment. Current acceptable streets are equally acceptable under the
   hard threshold; the kernel does not yet estimate behavioural facility
   preference, safety perception or cyclist-type shares.
3. **Estimate heterogeneous route choice.** Distinguish distance, cycling time,
   uphill effort, crossing delay, stress exposure and facility quality. Use
   locally supported cyclist profiles and observed routes; allow bounded
   detours to better facilities. Correct for path overlap and validate on held-out
   routes. Do not invent coefficients and label them realistic.
4. **Separate assignment from induced demand.** First conserve fixed OD cycling
   totals through route assignment; then estimate mode-choice/uptake response.
   Compare existing users, rerouted users and additional cyclists. Add explicit
   purpose-specific calendars only where the underlying data are trip counts
   or person-to-journey assumptions are declared.
5. **Expand treatment choice.** Cost mutually exclusive painted, protected,
   shared-path and crossing options only where width, traffic, gradients and
   design feasibility support them. A cheap painted lane must not automatically
   pass a low-stress threshold on a high-stress arterial. Source candidate
   geometry currently fixes project extent and may fund more street than a
   single witness route uses.
6. **Evaluate robust portfolios.** Reroute and reassign after each package,
   account for projects' shared costs and non-additive gains, then compare access,
   observed/calibrated uptake, equity, cost and benefits. Preserve an access-first
   objective rather than claiming every accessible traveller will cycle.

Publication should test whether this combination improves held-out route fit,
sampling stability and budget outcomes over simpler methods. Benchmark cold and
warm searches separately; report graph/sample limits, hardware, speed, memory,
optimality gaps and failures. Reject the performance claim if pruning does not
improve runtime on representative networks. Reject the policy claim if benefits
disappear under OD replicates, realistic treatment feasibility or held-out
behaviour. A more complicated model is not automatically a better one.

## Prior art and CRANC boundary

This research builds on existing bicycle network design and routing work.
[Lim et al., *The Bicycle Network Improvement Problem*](https://arxiv.org/abs/2107.04451)
already combine budget, safety and detour constraints.
[Lonardi, Szell and De Bacco](https://arxiv.org/abs/2405.02052) study cohesive
bicycle network design through multilayer routing.
[Steinacker et al.](https://arxiv.org/abs/2503.04349) compare complex welfare
optimisation with a simpler network-design approach and find relatively small
improvements in their Copenhagen comparison. None establishes a world-first
claim for SPAN.

CRANC should remain an attributed accessibility provider. Its
[2020 paper](https://experts.nau.edu/en/publications/a-cycling-focused-accessibility-tool-to-support-regional-bike-net/)
and [CRANC 2.0 report](https://rosap.ntl.bts.gov/view/dot/76976/dot_76976_DS1.pdf)
provide the relevant intellectual lineage. The live Access tool exposes rider
profiles and time-based accessibility. The supplied local code archive has not
been used to claim a working API integration.

A useful exchange contract must carry provider/version/attribution, source
network and opportunity-data hashes, profile ID and coefficient version,
departure/time budget, treatment scenario and edge crosswalk, CRS, destination
category, units and before/after accessible opportunities. SPAN should compare
only matched scopes, display CRANC results beside its own access/ridership
metrics, and treat unavailable outputs as unavailable, never zero. A CRANC
accessibility gain must not be presented as a SPAN ridership forecast. No local
OD records are uploaded to the live CRANC service by this implementation.

## Reproduce locally

```sh
PYTHONPATH=src .venv/bin/python scripts/audit_span_ridership.py \
  --run runs/run-313e0277521633d3 \
  --market-run runs/run-313e0277521633d3
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3
```

The access experiment now defaults to `build/pilots/access-experiment.json`;
it does not replace the published browser report. `research.html` redirects to
the single SPAN workspace, where Connected journeys shows the checked published
report. Publishing a new experiment requires a coordinated export, matching
intersection-delay comparison and verified site build, not just serving this
command's output. The scripts do not rewrite original run artifacts. Source
inputs must be readable locally. The original session used a checksummed copy at
`/private/tmp/span-run-313e0277521633d3` to avoid File Provider offloading inputs.
Temporary dependencies outside Dropbox were needed for verification; they are
the same pinned/existing versions, not a change to project dependencies.
