# SPAN: search limits and short-link cost sensitivity

25 September 2026. Follow-up to the
[budgeted connector tests](span-budgeted-connectors-and-loading-2026-09-25.md).
These are bounded experiments, not replacement public results or engineering
recommendations. The live site and source run are unchanged.

## More searching does not yet establish convergence

The same sampled journeys were searched with 15,000, 30,000 and 60,000 labels.
Each step retains the original route columns and all columns found at earlier
steps. Every retained route is independently checked against the original
direction, stress, time, detour and project-funding requirements. All three
investment methods receive the same route pool at each step.

| Area | Checked route columns: 15k → 30k → 60k | Searches still capped at 60k | Preferred NZ$20m package: connected sample records / cost |
| --- | ---: | ---: | ---: |
| Ponsonby Road | 431 → 715 → 1,265 | 10 of 24 | 8 / NZ$18.92m |
| Hospital Road | 239 → 374 → 761 | 15 of 24 | 1 / NZ$15.67m |
| Grand Drive | 460 → 828 → 1,223 | 16 of 24 | 3 / NZ$16.93m |
| Shelly Beach Road | 0 → 0 → 0 | 0 of 1 | 0 / NZ$0 |

The preferred NZ$20m packages are unchanged across these three search limits.
That is useful stability evidence for these particular samples, not proof of
route-search convergence. Most Hospital Road and Grand Drive searches are still
truncated. The unchanged small Shelly Beach sample is not evidence about that
area's full cycling potential.

All samples, 4 km crops, seed, original 15,000-label searches, demand weights,
source costs, LTS ≤ 2, 1.5-times-shortest legal in-crop distance limit, 30-minute
limit and assumed intersection delays are held fixed. Only the additional
connector route searches receive higher limits. No boundary-crossing partial
projects are added.

## Keep a good feasible result when the solver runs out of time

More route columns make the investment problem harder as well as giving it
more alternatives. At Grand Drive, a time-limited MILP can return less access
or a dearer equal-access package than whole-route greedy. In the recorded
60,000-label run, its incumbent serves weight 15.00 for NZ$18.49m, versus
greedy's 56.64 for NZ$16.93m; neither proves the best possible access at that cap.
Selecting the last solver result unconditionally would discard a better known
feasible package.

The connector experiment now publishes `preferredSolutions`: greatest checked
served weight, then least cost, among the three methods at each budget. The
source method is retained, as are all three raw method outcomes and solver
gaps. A greedy fallback is not relabelled as an optimiser result or an optimal
solution. This safeguard applies to the experimental connector comparison;
it does not change the published portfolio or the underlying MILP algorithm.

The solver's `optimal_within_columns` flag concerns the primary access
objective within the supplied route pool. It does not prove that route
generation is complete or that time-limited secondary cost refinement finished.
Future runs can have different time-limited incumbents and elapsed times.

## Hypothetical fixed costs change the choices

The second test adds NZ$0, NZ$100,000, NZ$250,000 or NZ$500,000 **once per
selected short-chain project**, on top of the provisional NZ$6,000/m rate.
Shared projects are still charged once across journeys. These are arbitrary
stress-test allowances, not AT estimates, uncertainty bounds or crossing prices.
Several short chains can touch the same junction; a chain is not a physical
crossing design.

The highest-cap route pool, geometry, stress and delay assumptions stay fixed.
Each method selects a new package at each price case. Routes are not regenerated
for the new prices, so results remain conditional on the capped pool. The
reference package is the preferred zero-allowance package; its cost and
affordability are tracked separately from the newly selected package.

| Extra allowance per short project | Ponsonby: records / package cost | Hospital: records / package cost | Grand Drive: records / package cost |
| --- | ---: | ---: | ---: |
| NZ$0 | 8 / NZ$18.92m | 1 / NZ$15.67m | 3 / NZ$16.93m |
| NZ$100,000 | 8 / NZ$19.46m | 1 / NZ$16.57m | 3 / NZ$18.23m |
| NZ$250,000 | 7 / NZ$19.35m | 1 / NZ$17.71m | 2 / NZ$16.88m |
| NZ$500,000 | 7 / NZ$19.25m | 1 / NZ$19.46m | 2 / NZ$18.63m |

Shelly Beach remains at zero in all four cases. Records are sampled commute
records, **not extra cyclists**. The objective maximises retained eligible-demand
weights, not record count or benefit per dollar. Counts alone can conceal changes:
Ponsonby's eight connected records have total weight 635.52 at zero allowance
and 629.52 at NZ$100,000. The original Ponsonby package would cost NZ$20.22m
at that allowance and is no longer affordable; the eight-record result requires
reselection. The original Hospital package exceeds NZ$20m at NZ$500,000, and
the original Grand Drive package exceeds it at NZ$250,000.

At Ponsonby's NZ$250,000 allowance, MILP serves weight 621.60 versus whole-route
greedy's 614.52, with seven records in each. That modest 7.08-weight improvement
costs about NZ$2.11m more. At Grand Drive, whole-route greedy supplies more access
or cheaper equal-access packages in time-limited cases. This is a mixed comparison, not
evidence of general algorithmic superiority.

## Evidence, verification and next work

The [aggregate report](span-search-and-cost-sensitivity-2026-09-25.json) includes
every search-cap result, raw method comparison, preferred package, price case,
fixed-package affordability and selected-project overlap. Explicit field
selection keeps sampled journey coordinates out of the public summary.
Source and implementation hashes bind the experiments to their inputs and code.

All 363 Python tests pass with 81.35% coverage; lint and formatting checks pass.
Tests cover nested route retention, invalid limits and prices, one shared fee
per project, fixed versus reselected packages, checked greedy fallback, and
privacy-preserving aggregate export. Web code is unchanged in this checkpoint;
the preceding checkpoint's 55 unit and 35 browser tests passed.

The 15,000-label results and original portfolios are reconciled against the
previous four-area reports. Source/browser data and the live server are not
updated. No new controls or explanatory panels are added to the interface.

Next, improve bounded route generation and retain strong feasible investment
incumbents rather than only increasing search caps. Keep the paired baseline
comparisons. Obtain actual crossing/treatment scope and defensible cost evidence
before treating short links as buildable interventions. Independent spatial
support, wider graph buffers and held-out validation remain necessary.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-411d92bafee5f5d1 --area-label "Hospital Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --test-short-connectors --budget-short-connectors \
  --connector-label-limits 15000 30000 60000 \
  --connector-fixed-costs-nzd 0 100000 250000 500000 \
  --output build/pilots/hospital-search-cost-24.json

PYTHONPATH=src .venv/bin/python scripts/summarise_span_pilots.py \
  --reports build/pilots/ponsonby-search-cost-24.json \
    build/pilots/hospital-search-cost-24.json \
    build/pilots/grand-search-cost-24.json \
    build/pilots/shelly-beach-search-cost-24.json \
  --output documentation/audit/span-search-and-cost-sensitivity-2026-09-25.json
```

Run the other three anchors listed in the aggregate report before summarising.
The immutable Auckland inputs are local research artifacts, not in GitHub.
