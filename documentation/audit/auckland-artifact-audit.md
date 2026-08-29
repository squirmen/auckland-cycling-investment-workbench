# Auckland analytical-artifact audit

## Scope and decision

This 28 August 2026 audit checked the immutable analytical artifacts from
`run-224e9baa3be4ef73`. It is a structural and extreme-case audit, not a claim
that every route has been visually inspected or that the research snapshot is
decision-ready.

All declared artifact hashes remained valid. The checks below found no broken
exact-edge candidate, missing topology endpoint, invalid facility-match value,
or disconnected path among the defined detour and snap extremes. The run's 156
routing failures remain explicit. Full-network counterfactual rerouting,
release-specific cost evidence, and stratified visual map review remain open.

## Route and OD ledgers

| Check | Result |
| --- | ---: |
| Complete OD ledger | 780,060 rows |
| Selected for routing | 42,654 rows |
| Assigned | 42,498 rows |
| Explicit failures | 156 rows |
| Complete path ledger | 131,214 paths |
| Maximum paths per OD | 5 |
| Empty paths | 0 |
| Edge/direction list-length mismatches | 0 |
| Paths at detour ratio ≥ 1.49 | 1,048 |
| ODs with either snap distance ≥ 1,500 m | 16 |
| Extreme-case paths checked for edge continuity | 1,095 |
| Extreme-case continuity or missing-edge failures | 0 |

The maximum observed detour ratio was 1.499999372, below the declared 1.5
cap. The maximum selected-OD snap distance was 1,752.88 m, below the declared
1,800 m gate. Five selected everyday ODs share that maximum because they use
the same support point. Four failure reasons account exactly for the 156
unassigned records: 68 without a shared reconciled component, 64 with no
directed R5 path, 16 origins outside the reconciled snap radius, and eight with
both ends outside it.

The extreme set was deliberately exhaustive at the stated thresholds: every
path at detour ratio ≥ 1.49 and every path belonging to an OD with a snap ≥
1,500 m was reconciled against topology edge IDs and traversal directions.

## Candidate ledgers

All 12,578 candidates and all 191,464 candidate-edge rows were checked. For
every candidate:

- edge sequence is zero-based, contiguous, and complete;
- the ordered exact-edge IDs equal the candidate declaration;
- the first and last traversal nodes equal the declared terminals;
- every traversal ends at the next traversal's start node;
- summed edge length equals declared corridor length;
- bridge and tunnel flags equal the edge-ledger evidence; and
- no inferred buffer or parallel-edge membership is substituted.

There were zero exceptions. The set contains 484 candidates with at least one
bridge edge and four with at least one tunnel edge.

## Topology, layers, and facility matches

The topology contains 867,348 OSM-identity nodes and 899,155 physical edges.
All edge endpoints resolve to declared nodes. It retains 5,261 bridge edges,
607 tunnel edges, and 7,811 edges with a non-zero parsed layer.

One pair of distinct OSM nodes has coordinates equal at six decimal places.
The nodes remain separate identities and no edge joins them. This is direct
artifact evidence that coincident coordinates were not merged into a false
connection.

All 56,780 protected-facility matches reference an existing topology edge.
Every overlap ratio lies between 0.600003 and 1.0, every bearing difference is
within the configured 30° limit, and no invalid value was found. These checks
confirm the stored match contract; a future release review should still inspect
a geographic stratified sample against the source geometries.

## Counter-site audit

The separate [`counter-plausibility-audit.md`](counter-plausibility-audit.md)
records the exact AT workbook review, ten explicit exclusions, all 73 retained
site-to-edge distances, and manual inspection of the farthest matches. The
counter locations remain local because publisher-file lineage, direction, and
screenline identity are unresolved.

## Release consequence

This audit closes the machine-checkable artifact-integrity portion of the
manual-audit gate. It does not close the visual route/facility/crossing review,
the present-day predictive-validation design, or the full-network rerouting
limitation. Those items remain visible in the release checklist and browser
evidence profile.
