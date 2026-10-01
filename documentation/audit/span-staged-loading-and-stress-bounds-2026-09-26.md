# SPAN: staged candidate loading and tighter connector search bounds

26 September 2026. Follow-up to the
[search-limit and cost-sensitivity tests](span-search-and-cost-sensitivity-2026-09-25.md).
The loading change keeps every published model value. The search change is an
experiment on the same four area samples. Source runs and rankings are unchanged.

## The page opens on the links it needs first

SPAN used to download all 12,580 candidate links before showing anything. The
build now writes a third candidate file, `candidates.initial.json`, holding the
1,846 links the opening views use:

- every link in every build order, for all five scenarios and six goals;
- every best-value (Pareto) link in the full candidate set, for the same 30
  combinations.

A link that another link beats in the full set is also beaten in this subset,
because the link that beats it is always included. So the best-value flag on a
link card is the same before and after the full set arrives. The `verify`
step below checks this for all 30 combinations on the Auckland build.

The full set loads the first time it is needed: opening Value for money,
switching on Other proposals, or following a shared link to a link outside the
initial file. A shared link to Value for money or to the Other proposals layer
skips the initial file and loads the full set once.

| Measure | All links (compact) | Initial links |
| --- | ---: | ---: |
| Links | 12,580 | 1,846 |
| Uncompressed JSON | 96,057,996 bytes | 14,439,517 bytes |
| Locally computed gzip size | 12,568,753 bytes | 1,869,635 bytes |
| Parse and validation, three fresh Node processes | 0.86–0.90 s | 0.16–0.19 s |
| Peak process memory | about 870 MiB | about 300 MiB |

These are local Node measurements. They exclude the network, hashing and map
drawing, and are not browser or phone timings.

The manifest ties the initial file to its own SHA-256, the canonical layer's
SHA-256, its link count and its scope. Before using the file, the browser
checks these four values and confirms that every build-order link is present.
A modified file is refused, with no silent fallback to another file. If the
later full load fails, the build order stays on screen and the action can be
retried. The packaging script repeats the same checks before an archive is
written.

## Tighter search bounds are safe but change little

The connector search prunes a partial route when even an optimistic estimate of
the remaining distance or time breaks the limits. That estimate used every legal
street. The new `--connector-stress-bounds` option uses only streets that are
low-stress already or could be made low-stress by an available project. The
shortest legal distance that defines the detour limit is unchanged.

Every acceptable route still lies inside this relaxed graph, so no acceptable
route is pruned. Tests run complete searches with and without the new bounds
on 20 random graphs with turn bans, crossing projects and preference costs, and
require identical results.

On the four area samples at the 15,000-label limit:

| Area | Searches stopped at the limit: before → after | Labels expanded: before → after | Route columns | NZ$20m package |
| --- | ---: | ---: | ---: | --- |
| Ponsonby Road | 15 → 15 of 24 | 236,326 → 235,525 | 431 → 434 | unchanged: 8 records, NZ$18.92m |
| Hospital Road | 16 → 16 of 24 | 214,297 → 214,411 | 239 → 239 | unchanged: 1 record, NZ$15.67m |
| Grand Drive | 18 → 17 of 24 | 260,100 → 246,557 | 460 → 460 | unchanged: 3 records, NZ$16.93m |
| Shelly Beach Road | 0 → 0 of 1 | 19 → 19 | 0 → 0 | unchanged: none |

One more Grand Drive search finishes. Nothing else changes much, so loose
distance bounds are not what stops these searches. A likely cause, not yet
measured, is the number of project combinations along similar routes. The
option stays off by default. Search convergence is still open; the next step is
to test a different way of generating routes, not a tighter bound.

Records are sampled commute records, not extra cyclists.

## Crossing costs

[Crossing costs: evidence needed](../research/crossing-cost-evidence.md) records
what is public (NZTA's SM014 resources, an indicative 2020 cycle-facility cost
tool named in an OIA response, and AT statements on raised crossings) and what
must be matched before any crossing cost enters the model. No crossing price has
been added. The fixed short-link allowances remain sensitivity tests.

## Verification

- Python: 394 tests pass, coverage 81.42%; lint and format checks pass.
- Web: typecheck, lint and 60 unit tests pass.
- Browser suite on the synthetic fixture: 47 pass, 9 platform-specific skips.
  New cases cover opening on the initial file, a held and a failed full load,
  shared links that need the full set, and a modified initial file.
- Auckland build: `profile-candidates.mjs verify` confirms all 12,580 compact
  and 1,846 initial links match the canonical values, with every build order
  and frontier preserved.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 \
  --anchor-candidate candidate-411d92bafee5f5d1 --area-label "Hospital Road area" \
  --sample-size 24 --seed 20260924 --max-labels 15000 \
  --intersections build/effective-network/intersections.json \
  --test-short-connectors --budget-short-connectors --connector-stress-bounds \
  --output build/pilots/hospital-stress-bounds-24.json

PYTHONPATH=src .venv/bin/python scripts/summarise_span_pilots.py \
  --reports build/pilots/ponsonby-stress-bounds-24.json \
    build/pilots/hospital-stress-bounds-24.json \
    build/pilots/grand-stress-bounds-24.json \
    build/pilots/shelly-beach-stress-bounds-24.json \
  --output documentation/audit/span-stress-bounds-2026-09-26.json

# After building web/dist with Auckland data:
node web/scripts/profile-candidates.mjs verify
node web/scripts/profile-candidates.mjs initial
```

Run the other three anchors in the [aggregate report](span-stress-bounds-2026-09-26.json)
before summarising. The Auckland inputs are local research artifacts, not in
GitHub.
