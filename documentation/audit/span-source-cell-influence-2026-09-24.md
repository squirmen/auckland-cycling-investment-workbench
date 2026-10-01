# SPAN source-cell influence audit

24 September 2026. First completed diagnostic under [priority 1](../roadmap.md).

Several top-ranked individual projects depend heavily on one sampled source OD
cell. Their rankings need fresh spatial sampling and routing before any
stronger claim is made about them. The programme as a whole is less
concentrated, but this audit does not validate it or predict actual uptake.

## What was checked

The audit uses source run `run-313e0277521633d3`, scenario `commute_8pct`,
and the published network build-order prefix within a NZ$100m budget:
12 projects costing NZ$97.05m. It reproduces all 12,580 standalone scores,
including 209 unaffected candidates absent from the source counterfactual table.
The joint programme estimate also matches the browser manifest: 548.20
additional usual cycle commuters under the model's response assumption. This is
not an observed count or an annual journey total.

There are 28,056 assigned commute records from 28,056 source OD cells,
currently one sampled record per cell. A cell is an origin–destination demand
grouping, not a person, and its sampled record can stand for many weighted
commuters.

For each top-12 standalone candidate and each published project, the audit finds
its largest contributing source cell. That gives 12 distinct cells and so 12
tests. Each test removes the same cell from every candidate and evaluates the
fixed programme jointly, without double counting shared journeys. All other
demand weights, routes, costs and response assumptions stay unchanged.

## Findings

The table shows selected projects. Ranks compare standalone modelled benefit
across all candidates; they are not positions in a reoptimised build order.
The last column is the worst rank across the 12 targeted tests.

| Project | Baseline rank | Gain from largest cell | Worst tested rank |
| --- | ---: | ---: | ---: |
| Beach Road | 1 | 94.6% | 1,544 |
| Shelly Beach Road | 3 | 99.9% | 8,797 |
| Grand Drive | 4 | 96.1% | 2,192 |
| Hospital Road | 7 | 18.1% | 9 |

These differences show how far one sampled cell can move a rank, not which
project is best. Hospital Road's smaller change holds only for these tests.

For the fixed 12-project programme:

- 1,736 source cells contribute positive modelled gain.
- The largest cell contributes 9.5%; the largest three together contribute 27.9%.
- Across the tests, estimated additional usual commuters range from 496.00 to
  548.20, compared with 548.20 before deletion. The largest reduction is 9.5%.
- The effective contributing-cell count is 17.15, calculated as the inverse sum
  of squared contribution shares. This describes concentration, not statistical
  sample size or forecast precision.

Eleven tests keep 11 of the original top 12 standalone candidates; one keeps
all 12. Despite that overlap, individual ranks change a lot, and the overlap
does not show that a newly selected investment programme would be stable.

## Interpretation limits

Deleting a cell removes its demand; other weights are not redistributed. It
does not represent moving a sampled home or workplace within that cell. The
tests are targeted, not random replicates or confidence intervals. Routes are
retained, the selected programme is fixed, and uptake is not recalibrated.
Omitted and failed demand is not repaired. The reported range covers these
tests only, not all model uncertainty. One-cell-at-a-time results do not bound
the combined influence of several cells.

The next step is the [paired sampling and routing pilot](../roadmap.md#next-implementation-paired-sampling-and-routing-pilot):
keep source totals and inclusion weights, generate independently seeded
support, route it afresh, and compare fixed and reselected programmes on the
same inputs. A new sample from existing support and new within-cell spatial
locations are different experiments and must be reported separately.
Validation against observed data is also still required.

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
not raw OD identifiers, source-cell identifiers or coordinates. Case labels are
anonymous and local to this report; they are not persistent source-cell
pseudonyms.

The script refuses to write output inside the source run or browser tree.
Tests cover grouped records, shared-cell deletions, joint package evaluation,
deterministic ties, empty and invalid inputs, and output protections.
This work does not change source runs, web data, the live site or its
recommendations.

Verification on 24 September: 270 Python tests pass, including 25 new tests;
total coverage is 80.80% against the 80% gate. Lint and formatting checks pass.
Two full Auckland audit runs produce byte-identical reports (SHA-256
`861053a5568df7a82307d5ea27f3b6aef6156fd0a6b15b4fbf736565e027e461`).
