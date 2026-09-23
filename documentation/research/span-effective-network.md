# SPAN effective-network beta

This is an extension of **SPAN: Spending Priorities for Active Networks**, at
`span.tfwelch.com`. The source repository still has its historical
`auckland-cycling-investment-workbench` name. It is not the separate legacy
Python PCT workbench in the parent `car_dependency` project.

## What is implemented

The main explorer has an optional **Intersections and crossing delays · beta**
overlay. It includes all 1,289 records from the Auckland Transport Controlled
Intersections inventory downloaded on 17 September 2026. The source is the
[AT RoadingService layer](https://services2.arcgis.com/JkPEgZJGxhSjYOo0/ArcGIS/rest/services/RoadingService/FeatureServer/2),
recorded under CC BY 4.0. Street topology is derived from OpenStreetMap under
ODbL. The inventory supplies locations and control flags, **not signal timings**.

The separate complete-journey research engine adds delays to directed movement
pairs at matched source junctions. Time includes both street travel and these
waits, and remains distinct from generalized preference cost. A street upgrade
does not erase a crossing delay. The main explorer's candidate rankings,
benefits and portfolio sequences are unchanged by this extension; all existing
map-layer hashes are checked before publishing the overlay.

## Matching and uncertainty

Matching uses the immutable native topology of `run-313e0277521633d3`, with OSM
node identities, one-way directions, bridge/tunnel attributes and layers. It
does not use rounded coordinates to connect streets, infer new links, or
apply the earlier legacy-workbench topology repairs.

A match requires a junction with at least three distinct source neighbours,
within 20 metres of the AT point, and at least a five-metre distance advantage
over the next junction. Structures, flagged complex sites, competing AT records
at the same junction and sites without directed through movements are held out.

| Outcome | AT sites |
| --- | ---: |
| Passed the matching checks | 660 |
| Ambiguous nearest junction | 316 |
| No junction within 20 m | 262 |
| Flagged complex site | 33 |
| Competing records at one junction | 14 |
| Structure review | 4 |

The 660 matches yield 5,210 directed, non-U-turn movement pairs. These are
topology-consistent pairs, **not verified legal turns or signal phases**.
Passing the geometric checks is not a field validation. Divided carriageways,
multi-node junctions and separate cycle crossings require manual review. A
nearest-node match can still be wrong. The 629 held-out sites remain visible
in grey and add no routing penalty; missing delay is unknown, not evidence
that the crossing has no delay.

## Delay assumptions

| AT inventory control flag | Low | Default | High |
| --- | ---: | ---: | ---: |
| Controlled | 20 s | 45 s | 90 s |
| Not recorded as controlled | 0 s | 10 s | 30 s |

These values are deliberately **illustrative, unfitted sensitivities**. Every
represented through movement at a matched site receives the same site default;
that is a limitation, not a model of movement-specific operation. No cycle
length, green split, detection, actuation, phase skipping or time-of-day pattern
is inferred. Real timings and a movement/phase crosswalk from AT/ATOC, together
with observed cyclist waits, are needed before calibration or retiming advice.

The beta does not yet price or optimise crossing interventions, propagate
delay-aware routing through the Auckland-wide demand model, estimate new riders,
or produce safety benefits or benefit–cost ratios for intersection upgrades.
It implements the first testable part of the effective-network proposal, not
the complete proposed model.

## Reproduction

The recorded September 2026 comparison uses the same 169 local OD records,
24,467 native nodes, 47,146 directed arcs and 195 eligible projects throughout.
Within the crop, 24 matched sites contribute 126 movement pairs. All access
searches and preference searches completed at a 50,000-label limit. Initial
15,000-label tests truncated one access search and were superseded.

The generated access alternatives include up to 20, 45 and 90 seconds of
assumed delay in the low, default and high cases respectively. At the tested
budgets of $0, $5m, $10m and $20m, the selected project packages and served
eligible weights did not change across these four runs. At $20m, all cases
served 14 sampled journeys with eligible weight 2,991.72, compared with 11 and
1,635.72 without investment. These are source-record access weights, not new
cyclists. This limited sensitivity does not establish that intersection delays
are unimportant elsewhere: coverage is partial, waits are unfitted, and the
crop is not representative of Auckland.

The three CBD sites in the original concept examples (AT 2921, 2905 and 2052)
all fall into the ambiguous-match review queue. They are not treated as
validated examples or assigned a delay in this beta.

Run these commands from the SPAN repository, using Python 3.11 and Node 24.
Keep the completed source run immutable and ensure its artifacts are local.
The scripts stage and verify exports; output paths must be outside the run.

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

The comparison checks identical graph size, source ledger hashes, journeys,
weights, planning standard and fixed demand across all four runs. Search
completion is disclosed separately from solver optimality over generated routes.
The public research page uses the default sensitivity and links to the full
comparison JSON. The local audit contains the exact junction and arc identities.

## Server handoff

The resulting `release-assets/span-effective-network-beta.zip` is a complete
static **SPAN** site, with main and research pages, hashed assets, browser data,
method notes and Apache `.htaccess`. No Python server, raw source topology,
person-level data or OD ledger is included. The companion JSON records archive
and per-file SHA-256 hashes. Creating the archive does not deploy anything.

Back up the existing SPAN document root. Extract this archive into a separate
staging directory for the **SPAN host**, preserve hidden files, and ensure files
are web-readable. Test the main map, intersection toggle/popups, research page,
route export and documentation before switching the server to the new directory.
Keep the old directory for rollback. Use HTTPS because browser data-integrity
checks require a secure context. Apache must permit the bundled settings; on
other servers configure equivalent MIME types, compression and cache behaviour.
Do not use the parent project's `pct-preview-deploy.zip` or `ataa` deployment
instructions for SPAN.
