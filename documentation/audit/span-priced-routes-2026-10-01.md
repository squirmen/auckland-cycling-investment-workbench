# SPAN: a second way to generate routes

1 October 2026. Follow-up to
[staged loading and tighter search bounds](span-staged-loading-and-stress-bounds-2026-09-26.md),
which found that tighter bounds do not stop the connector search reaching its
cap and proposed testing a different way of generating routes. This note tests
one. These are bounded experiments on the same four area samples, not
replacement public results. The live site's model data and the source run are
unchanged.

## What was tested

The existing label search keeps every route that is not beaten on projects,
distance, time and travel cost together. Along streets with many short
projects, that is a very large set, and most searches stop at their label cap
before all of it is found.

The new search asks a narrower question: for one price on new capital and one
on distance, which single route has the lowest priced score within the
standard and the budget? Labels at a junction movement are compared on score,
distance and time, not on their project sets, so far fewer are kept.

- **Priced paths.** Each journey is searched at 12 prices: six on capital, from
  ignoring it to letting it decide (0, 0.00001, 0.0001, 0.001, 0.01 and 1
  second of travel per NZ$), each with and without a price of 1 second per
  metre on distance.
- **Priced rounds.** The preferred NZ$20m package's projects are then priced at
  zero and the search is repeated for the journeys that package leaves
  unconnected. This looks for routes that reuse what is already funded. It
  stops when a round adds no route, leaves the package unchanged, or reaches
  three rounds.

Every route found passes the same independent checker as the label-search
routes: continuity, direction, turn bans, stress, crossing requirements,
distance, time and cost. Routes are added to the pool and none is removed. All
three investment methods see the same pool at each stage.

The priced search is a heuristic, exact only when capital is unpriced and the
budget does not bind. A project is paid for once, so what a later street costs
depends on the path taken to it, and a label dropped early might have finished
cheaper. One test builds such a case and shows the miss. In another, 420
searches of small random graphs with budgets and funded projects reached the
best score every time; that says little about graphs of 46,000 to 85,000
directed streets.

It does not replace the label search. It returns one route per price, not the
set of alternatives, and gives no sign of how many routes it has not found.

## Results

All settings match the 25 September runs: the same sampled records, 4 km crops,
seed, weights, provisional NZ$6,000 per metre for short connectors, LTS ≤ 2,
1.5 times the shortest legal distance, 30 minutes and assumed intersection
delays. The label search uses 15,000 labels and reproduces the 25 September
columns, stop reasons and every method's package at every budget exactly.

| Area | Sampled records with an acceptable route inside NZ$20m: 15,000 labels → 60,000 labels (25 Sept) → 15,000 labels plus priced | Route columns: before → after | Preferred NZ$20m package: before → after |
| --- | ---: | ---: | --- |
| Ponsonby Road | 17 → 19 → 22 of 24 | 431 → 458 | 8 records, NZ$18.92m → 8 records, same weight, NZ$18.17m |
| Hospital Road | 9 → 11 → 16 of 24 | 239 → 272 | 1 record, NZ$15.67m, unchanged |
| Grand Drive | 13 → 14 → 16 of 24 | 460 → 487 | 3 records, NZ$16.93m, unchanged |
| Shelly Beach Road | 0 → 0 → 0 of 1 | 0 → 0 | none |

Of the records still without a route, one in Ponsonby, two at Hospital Road and
one at Grand Drive have no legal route inside the crop at all.

Records are sampled commute records, not extra cyclists. The objective is
retained eligible-demand weight, not record count.

## What this shows

The capped search under-reports which journeys can be connected. The priced
search found an acceptable route, with its own projects inside NZ$20m, for
five, seven and three more sampled records than the label search at 15,000
labels, and for more than the label search found at 60,000.

The NZ$20m packages connect no more than before. The number of records and the
served weight are unchanged in all four areas: 635.52, 100.80, 56.64 and 0. A
second generator added 27 to 33 routes in each of the three larger areas and
the best access found stayed the same. That is evidence the packages are not an
artefact of the label cap. It is not proof that either pool is complete.

Two smaller results improve. Ponsonby's NZ$20m package costs NZ$0.75m less for
the same weight, because cheaper routes entered the pool. At NZ$5m Ponsonby
connects five records (weight 163.92) instead of four (156.00). No other budget
changes in any area.

Cost, not search, limits access in these samples. For each record the final
package leaves unconnected, the pool holds the least extra capital any of its
routes would need:

| Area | Left in the NZ$20m budget | Cheapest further record in the pool |
| --- | ---: | ---: |
| Ponsonby Road | NZ$1.83m | NZ$3.31m |
| Hospital Road | NZ$4.33m | NZ$6.10m |
| Grand Drive | NZ$3.07m | NZ$6.60m |

The pool is not complete, so the true cheapest addition may be lower. These
costs also rest on the provisional rate for short connectors, which is not a
crossing estimate; see [crossing costs](../research/crossing-cost-evidence.md).

## Keeping a good package when a solve does worse

The roadmap asked for feasible incumbents to be kept. Each later stage now
re-evaluates the earlier stage's preferred package on the larger pool and keeps
it as a candidate, named with the stage it came from. A package that was
affordable stays affordable, and more routes can only connect more journeys
with it, so a stage cannot report less access than the one before.

This mattered at Grand Drive. With 487 columns the time-limited solver returned
three records of the same weight for NZ$19.95m and package greedy for
NZ$19.46m. The package kept from the label search costs NZ$16.93m and remains
preferred. All raw method results are in the report, with `retainedFrom` on
the kept rows.

## Limits

- The priced search stopped at its own limit of 200,000 labels in 28 of 456
  Ponsonby searches and 12 of 516 at Grand Drive. Those searches returned
  nothing. None did at Hospital Road.
- Twelve prices and one package per round are a small set. Other prices, or
  pricing from packages at other budgets, might find different routes.
- Rounds search only for unconnected records. They do not look for a cheaper
  route for a record the package already connects, beyond what the 12 priced
  paths find.
- The samples are 24 records in three areas and one record in the fourth.
  Crops, the assumed delays, the short-connector cost rate and the absence of
  calibrated demand are unchanged from the earlier notes.
- Time-limited solves can return different packages on different runs. The
  preferred results above did not change across three runs.

## Verification and next work

The [aggregate report](span-priced-routes-2026-10-01.json) holds every stage's
columns, search counts and stop reasons, raw and preferred packages at four
budgets, and the pool summaries. It selects aggregate fields only; no sampled
journey, coordinate or source cell is included.

475 Python tests pass with 81.84% coverage; lint and format checks pass. New
tests cover:

- the exact case against a complete label search on 30 random graphs with turn
  bans, crossing projects and preference costs;
- acceptability of every priced route under the independent checker on the
  same graphs with budgets and funded sets;
- the best score in 420 priced searches, and a constructed miss;
- funded projects, budget, detour, time, crossing and turn-ban handling;
- label limits and bad inputs;
- the three stages, a round that reuses a funded project, a round that changes
  the package, the kept package when a later solve is worse, and the aggregate
  export.

Raising label caps further is not the useful next step for these samples: a
second generator agrees on the packages, and cost is what binds. The order is
now crossing and short-link cost evidence from AT, then wider sampling and
graph buffers, then the same comparison on independently drawn records.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-411d92bafee5f5d1 --area-label "Hospital Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --test-short-connectors --budget-short-connectors --connector-priced-routes \
  --output build/pilots/hospital-priced-routes-24.json

PYTHONPATH=src .venv/bin/python scripts/summarise_span_pilots.py \
  --reports build/pilots/ponsonby-priced-routes-24.json \
    build/pilots/hospital-priced-routes-24.json \
    build/pilots/grand-priced-routes-24.json \
    build/pilots/shelly-beach-priced-routes-24.json \
  --output documentation/audit/span-priced-routes-2026-10-01.json
```

Run the other three anchors listed in the aggregate report before summarising.
Each area takes one to three minutes. The Auckland inputs are local research
artifacts, not in GitHub.
