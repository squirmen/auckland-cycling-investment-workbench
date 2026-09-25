# SPAN source-cell influence audit

24 September 2026. First completed diagnostic under [priority 1](../roadmap.md).

Several leading individual projects depend heavily on one sampled source OD
cell. Fresh spatial sampling and routing should precede stronger claims about
their ranking. The aggregate programme is less concentrated than these individual
projects, but this audit does not validate the programme or predict actual uptake.

## What was checked

The audit uses source run `run-313e0277521633d3`, scenario `commute_8pct`,
and the published network build-order prefix within a NZ$100m budget:
12 projects costing NZ$97.05m. It reproduces all 12,580 standalone scores,
including 209 unaffected candidates absent from the source counterfactual table.
The joint programme estimate also reconciles with the browser manifest:
548.20 additional usual cycle commuters under the model's response assumption.
This is not an observed count or an annual journey total.

There are 28,056 assigned commute records from 28,056 source OD cells: currently
one sampled record per cell. A cell is an origin–destination demand grouping,
not a person. Its sampled record can represent many weighted commuters.

For each top-12 standalone candidate and each published project, the audit finds
its largest contributing source cell. The resulting 12 distinct cells define
12 tests. Each test removes the same cell from every candidate and evaluates
the fixed programme jointly, without double counting shared journeys.
All other demand weights, routes, costs and response assumptions stay unchanged.

## Findings

Selected individual results are shown below. Ranks compare standalone modelled
benefit across all candidates; they are not positions in a reoptimised build order.
The final column is the worst rank among the 12 targeted tests.

| Project | Baseline rank | Gain from largest cell | Worst tested rank |
| --- | ---: | ---: | ---: |
| Beach Road | 1 | 94.6% | 1,544 |
| Shelly Beach Road | 3 | 99.9% | 8,797 |
| Grand Drive | 4 | 96.1% | 2,192 |
| Hospital Road | 7 | 18.1% | 9 |

These differences identify sampling leverage, not which project is truly best.
Hospital Road's smaller change is only relative to these particular tests.

For the fixed 12-project programme:

- 1,736 source cells contribute positive modelled gain.
- The largest cell contributes 9.5%; the largest three together contribute 27.9%.
- Across the tests, estimated additional usual commuters range from 496.00 to
  548.20, compared with 548.20 before deletion. The largest reduction is 9.5%.
- The effective contributing-cell count is 17.15, calculated as the inverse sum
  of squared contribution shares. This describes concentration, not statistical
  sample size or forecast precision.

Eleven tests retain 11 of the original top 12 standalone candidates; one retains
all 12. This overlap should not obscure the large individual rank changes, and
does not establish the stability of a newly selected investment programme.

## Interpretation limits

Deleting a cell deliberately removes demand; other weights are not redistributed.
It does not represent moving a sampled home or workplace within that cell.
The tests are targeted, not random replicates or confidence intervals. Routes
are retained, the selected programme is fixed, and uptake is not recalibrated.
Omitted and failed demand is not repaired. The reported range covers these tests
only, not all model uncertainty. One-cell-at-a-time results do not bound the
combined influence of several cells.

The next step is the [paired sampling and routing pilot](../roadmap.md#next-implementation-paired-sampling-and-routing-pilot):
preserve source totals and inclusion weights, generate independently seeded
support, route it afresh, and compare fixed and reselected programmes on the same
inputs. A new sample from existing support and new within-cell spatial locations
must be reported as different experiments. Observed-data validation remains a
separate requirement.

## Reproduction and safeguards

From the repository root, with the pinned environment and local source ledgers:

```sh
PYTHONPATH=src .venv/bin/python scripts/audit_span_stability.py \
  --run runs/run-313e0277521633d3 \
  --output build/stability/source-cell-influence.json
```

The [machine-readable report](span-source-cell-influence-2026-09-24.json) records
the parameters, source hashes, implementation hashes, baseline reconciliation,
all audited candidates and all tests. Source ledger checksums are verified before
calculation. Output contains candidate identifiers and aggregate diagnostics,
not raw OD identifiers, source-cell identifiers or coordinates. Anonymous case
labels are local to this report, not persistent source-cell pseudonyms.

The implementation rejects outputs inside the source run or browser tree.
Tests cover grouped records, shared-cell deletions, joint package evaluation,
deterministic ties, empty and invalid inputs, and output protections.
This work does not modify source runs, web data, the live site or its recommendations.

Verification on 24 September: 270 Python tests pass, including 25 new tests;
total coverage is 80.80% against the 80% gate. Lint and formatting checks pass.
Two full Auckland audit runs produce byte-identical reports (SHA-256
`861053a5568df7a82307d5ea27f3b6aef6156fd0a6b15b4fbf736565e027e461`).
