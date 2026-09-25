# SPAN: short connections excluded from the candidate network

25 September 2026. Follow-up to the [four-area checks](span-follow-up-progress-2026-09-24.md).

## Finding

The source model's 100 m minimum candidate length excludes connections that
matter to complete journeys. This is not just a map presentation issue.
Reintroducing complete short excluded chains in a separate all-projects-funded
diagnostic produces acceptable routes for many previously disconnected sampled
journeys, without relaxing the original route standards.

This does **not** establish that those routes are affordable, buildable or optimal.
The published candidate universe, budgeted portfolios and live site are unchanged.

## Where the gaps come from

The audit joins physical edges to the checksummed original candidate and
candidate-exclusion ledgers. It distinguishes a whole source project crossing
the crop boundary, an explicit source exclusion, and an edge absent from both
ledgers. It does not infer an exclusion reason for the last category.

Citywide, the source exclusion ledger contains 19,714 chains below the 100 m
minimum, 2,261 with no exposure in the retained purpose-market routes, and 18
closed components without unambiguous terminals. These categories are the
first failing rule, not a complete list of every rule a chain might fail.
In particular, the length test happens before the route-exposure test.

Among the high-stress diagnostic witnesses found in the four paired area tests:

| Area | Witnesses containing short exclusions | Witnesses containing crop-excluded projects | Witnesses with an unlisted edge |
| --- | ---: | ---: | ---: |
| Ponsonby Road | 16 | 0 | 0 |
| Hospital Road | 19 | 0 | 1 |
| Grand Drive | 20 | 2 | 0 |
| Shelly Beach Road | 0 | 0 | 0 |

Counts are journeys, not distinct links or minimum treatment sets. A journey can
appear in several columns. No found witness contains an edge explicitly excluded
for no retained-route exposure, but this small test does not vindicate that rule.
Boundary exclusions exist elsewhere in these crops even where the witness count
is zero. An alternative route may avoid any particular witness gap.

## Test: put the short connections back

The opt-in `--test-short-connectors` diagnostic makes a separate graph. It adds
only whole chains recorded as excluded for minimum length, with every physical
edge inside the crop. It retains exact geometry, directions, travel times,
intersection stress, crossing delays and turn prohibitions. No additional
treatments are applied to unlisted edges or other exclusion categories.

All original projects and these hypothetical connectors are funded for this
test. The original LTS ≤ 2, 30-minute and 1.5-times-shortest-in-crop-route limits
remain in force. Searches still have a 15,000-label cap.

| Area | Previously no-route journeys tested | Acceptable route found | Conclusively no route | Search capped |
| --- | ---: | ---: | ---: | ---: |
| Ponsonby Road | 19 | 16 | 1 | 2 |
| Hospital Road | 24 | 19 | 5 | 0 |
| Grand Drive | 23 | 19 | 3 | 1 |
| Shelly Beach Road | 0 | — | — | — |

Every newly found route follows a **conclusive** failure in the original
all-projects-funded graph, not just a previously capped search. Shelly Beach
already has an acceptable original all-project route, so it needs no connector
test; its NZ$20m programme still fails to connect the one sampled journey.

The diagnostic adds 1,660 hypothetical short projects in Ponsonby, 1,177 at
Hospital Road and 1,587 at Grand Drive. At the original provisional NZ$6,000/m
screening rate, their aggregate additional costs are approximately NZ$430m,
NZ$307m and NZ$362m respectively. These deliberately unrestricted totals are
**not proposed programmes**. They underline why the next test must select a
budgeted package, not present the diagnostic route counts as a NZ$20m result.
Short junction works may also need different cost structures from linear lanes.

The same sampled origins, weights, project selections, served counts and costs
in the original budgeted runs reconcile with the preceding four-area reports
(costs compared within NZ$0.000001 for floating-point summation). Diagnostics
do not change those runs' treatment eligibility or assignments.

The [aggregate report](span-candidate-coverage-2026-09-25.json) retains source,
implementation and report hashes, area centres, search caps and runtime. Raw
journey identifiers and geometries remain in ignored local build outputs.
The four new runs took approximately 12–39 seconds each on this machine.

## What to change next

1. Prototype short connectors as explicit, shared-cost options in the **budgeted**
   complete-route search. Retain the current candidate set as a paired baseline.
   A length cutoff should not silently make a network gap impossible to treat.
2. Separate street segments from actual crossing treatments. Check junction
   stress, legal movements, existing facilities and realistic project cost ranges
   before treating the experimental connectors as buildable interventions.
3. Compare the same journeys, budgets and costs using whole-route greedy and the
   package optimiser. Report search caps and failure cases; do not infer new
   cyclists from newly feasible model journeys.
4. Test larger graph buffers on fixed sampled journeys, particularly at Grand
   Drive, and audit high-stress edges absent from both candidate ledgers.

This advances candidate-coverage diagnosis, not engineering validation, demand
calibration or a claim that SPAN outperforms other planning tools.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-411d92bafee5f5d1 --area-label "Hospital Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --test-short-connectors --output build/pilots/hospital-connectors-24.json
```

Repeat with the other anchor IDs in the aggregate report, then run
`scripts/summarise_span_pilots.py --reports ... --output ...`. The summary refuses
mismatched budgets, source ledgers, routing settings, intersection evidence or
connector assumptions. Disabling the flag leaves the added diagnostic absent.
It never adds connectors to the budgeted portfolio or writes to browser data by
default. Source inputs must be locally available.

## Verification

324 Python tests pass with 81.07% coverage against the 80% gate. Lint and format
checks pass. Tests distinguish source exclusions, crop boundaries and unknowns;
reject overlapping assets and invalid costs; preserve whole-project charging;
retain intersection stress, turn bans and time limits; and reject unpaired
summary inputs. The original public browser manifest checksum is unchanged.
No browser source, production candidate rule or deployed file changed in this pass.
