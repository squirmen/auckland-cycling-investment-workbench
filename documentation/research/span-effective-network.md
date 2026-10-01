# SPAN effective-network beta

These notes cover the intersection extension to **SPAN: Spending Priorities for
Active Networks**, at `span.tfwelch.com`. The source repository is
`squirmen/spending-priorities-active-networks`, renamed from
`auckland-cycling-investment-workbench` on 1 October 2026.

## What is implemented

The main explorer has an optional **Intersections** layer, in beta. It shows all
1,289 records in the Auckland Transport Controlled Intersections inventory,
downloaded on 17 September 2026. The source is the
[AT RoadingService layer](https://services2.arcgis.com/JkPEgZJGxhSjYOo0/ArcGIS/rest/services/RoadingService/FeatureServer/2),
recorded under CC BY 4.0. Street topology is derived from OpenStreetMap under
ODbL. The inventory gives locations and control flags, **not signal timings**.

The separate complete-journey research engine adds delays to directed movement
pairs at matched source junctions. Its travel time includes both street travel
and these waits, and stays separate from generalised preference cost. A street
upgrade does not remove a crossing delay. This extension does not change the
main explorer's candidate rankings, benefits or portfolio sequences; all
existing map-layer hashes are checked before the overlay is published.

## Matching and uncertainty

Matching uses the immutable native topology of `run-313e0277521633d3`, with OSM
node identities, one-way directions, bridge/tunnel attributes and layers. It
does not use rounded coordinates to connect streets, infer new links, or
apply topology repairs from the earlier Python workbench.

A match requires a junction with at least three distinct source neighbours,
within 20 metres of the AT point and at least five metres closer to it than the
next-nearest junction. Structures, flagged complex sites, competing AT records
at the same junction and sites without directed through movements are held out.

| Outcome | AT sites |
| --- | ---: |
| Passed the matching checks | 660 |
| Ambiguous nearest junction | 316 |
| No junction within 20 m | 262 |
| Flagged complex site | 33 |
| Competing records at one junction | 14 |
| Structure review | 4 |

The 660 matches give 5,210 directed movement pairs, excluding U-turns. These
pairs are consistent with the topology but are **not verified legal turns or
signal phases**. Passing the geometric checks is not field validation, and a
nearest-node match can still be wrong. Divided carriageways, multi-node
junctions and separate cycle crossings need manual review. The 629 held-out
sites stay visible in grey and add no routing penalty. A missing delay means
the delay is unknown, not that the crossing has none.

## Delay assumptions

| AT inventory control flag | Low | Default | High |
| --- | ---: | ---: | ---: |
| Controlled | 20 s | 45 s | 90 s |
| Not recorded as controlled | 0 s | 10 s | 30 s |

These are **illustrative, unfitted sensitivity values**. Every through movement
represented at a matched site gets the same site value. That is a limitation:
the model does not represent how individual movements operate. No cycle length,
green split, detection, actuation, phase skipping or time-of-day pattern is
inferred. Calibration or retiming advice would need real timings and a
movement-to-phase crosswalk from AT/ATOC, plus observed cyclist waits.

The beta does not yet price or optimise crossing interventions, carry
delay-aware routing into the Auckland-wide demand model, estimate new riders,
or produce safety benefits or benefit–cost ratios for intersection upgrades.
It is the first testable part of the effective-network proposal, not the full
proposed model.

## Reproduction

The recorded September 2026 comparison uses the same 169 local OD records,
24,467 native nodes, 47,146 directed arcs and 195 eligible projects throughout.
Within the crop, 24 matched sites contribute 126 movement pairs. All access
and preference searches completed within a 50,000-label limit. Earlier tests at
15,000 labels truncated one access search and were replaced.

The generated access alternatives include up to 20, 45 and 90 seconds of
assumed delay in the low, default and high cases. At the tested budgets of $0,
$5m, $10m and $20m, the selected project packages and served eligible weights
did not change across these four runs. At $20m, every case served 14 sampled
journeys with eligible weight 2,991.72, compared with 11 and 1,635.72 without
investment. These are access weights for source records, not new cyclists. The
result does not show that intersection delays are unimportant elsewhere:
coverage is partial, waits are unfitted and the crop does not represent
Auckland.

The three CBD sites in the original concept examples (AT 2921, 2905 and 2052)
all fall into the ambiguous-match review queue. This beta does not treat them
as validated examples or give them a delay.

Run these commands from the SPAN repository with Python 3.11 and Node 24. Leave
the completed source run unchanged and make sure its artifacts are stored
locally. The scripts stage and verify exports; output paths must be outside the
run.

```sh
PYTHONPATH=src .venv/bin/python scripts/build_span_intersections.py \
  --run runs/run-313e0277521633d3 \
  --inventory ../raw/auckland/traffic/at_controlled_intersections.geojson

PYTHONPATH=src .venv/bin/python scripts/run_access_experiment.py \
  --run runs/run-313e0277521633d3 --max-labels 50000 \
  --output build/effective-network/access-none.json
```

Repeat the experiment for `low`, `default` and `high`, using
`--intersections build/effective-network/intersections.json`,
`--delay-scenario <scenario>` and output
`build/effective-network/access-<scenario>.json`, keeping `--max-labels 50000`.
Then:

```sh
PYTHONPATH=src .venv/bin/python scripts/compare_span_delays.py
cp build/effective-network/access-default.json web/public/data/access-experiment.json
cp build/effective-network/delay-comparison.json web/public/data/delay-comparison.json
.venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run lint
npm --prefix web run build
node web/scripts/check-span-release.mjs
PYTHONPATH=src .venv/bin/python scripts/package_span_site.py
```

The comparison checks that graph size, source ledger hashes, journeys, weights,
planning standard and fixed demand are identical across all four runs. Search
completion is reported separately from solver optimality over generated routes.
Connected journeys in the main SPAN workspace uses the default delay case. The
full comparison is bundled as `data/delay-comparison.json`. The local audit
holds the exact junction and arc identities.

## Deployment

Packaging and deployment are described in the
[server handoff notes](../audit/span-server-handoff.md) in the repository.
