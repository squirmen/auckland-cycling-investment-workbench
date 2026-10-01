# SPAN interface and TEAM reuse review

24 September 2026. This supersedes the earlier separate research-page interface.

## What SPAN needs to help a visitor decide

A visitor needs to see which cycling upgrades are worth investigating, what they
would connect, and what a budget can achieve. A map of ranked fragments does not
show this. The investment should make sense before the visitor opens a method note.

The initial Auckland programme at NZ$100m contains 12 upgrades in 11 physical
groups. It is not one continuous network, and the interface must not suggest it
is. Citywide link ranking and whole-route package selection currently have
different coverage and methods. Showing them in one workspace does not make
them equivalent.

## Changes in this revision

- One map with three views: Build order, Value for money, Connected journeys.
  Basemap choice is kept across views. The old research URL only redirects.
- Link detail starts with cost, length, proposed treatment and connections.
  One preliminary modelled outcome follows. Sampling sensitivity, annual journey
  conversions and parameter tests sit behind “How this was estimated”.
- Layer names are short and the menu has a bounded width and height. Dates,
  matching counts and limitations belong in About, not in the menu.
- The programme states when its upgrades form separate groups and provides
  group inspection and a whole-programme map control.
- Complete journeys show A-to-B routes, required upgrades and funding status.
  The view states that coverage is local and that these are not new cyclist
  forecasts. A whole-package map shows every funded upgrade with a numbered
  street list; selecting a street opens a complete journey that uses
  that funded upgrade. The 4 km-radius crop is centred at 174.69295, -36.80338
  and includes both sides of the upper harbour, so the interface does not label
  it as North Shore only.
- The journey view rejects mismatched run/topology data before showing results.

## TEAM: inspected sources and useful crossover

This was a read-only review of the sibling `transport-equity-access-model`
repository: its `web/js/map.js`, `src/team/export.py`, and source and method
documentation. The real local outputs are under `../team/site/data/`, not the
synthetic fixtures in the TEAM repository. The inspected summary reports build
2026-09-13 and routing date 2026-09-15.

| TEAM material | Useful role in SPAN | Boundary |
| --- | --- | --- |
| Basemap selector and map conventions | Consistent Light/Streets controls and familiar lab presentation | SPAN keeps its working OpenFreeMap backgrounds and offline Plain option. Sharing controls does not need a new map engine. |
| `destinations.json`: 1,488 named locations with service categories | Context showing schools, shops and services near a proposed connection; potential common opportunity inventory for future access calculations | A nearby point is not proof a project improves access. Confirm source dates, licences and routable destination snapping before reuse. |
| `overlays.json`: 48 rail, 31 ferry and 310 frequent-bus features | Optional context for station connections and first/last-mile planning | Use the timetable date and attribution; do not add another always-on map layer. |
| Population, deprivation and no-car households in TEAM cells | Common area context and weighting for a future equity comparison | Reconcile H3 resolution, census denominators and SPAN origin sampling; do not substitute residential population for commuters. |
| TEAM access times, standards and shortfall maps | Identify places needing further investigation | Baseline R5 accessibility is not SPAN's after-investment result. An intervention needs rerouting with a verified common scenario. |
| TEAM cycling overlay | Potential visual context | SPAN already has an exact-topology network. Do not duplicate it or substitute a differently classified layer. |

No TEAM data was copied into the SPAN release and no TEAM files were changed.
The highest-value next reuse is destination context, once it is linked to the
journeys being explained. Importing every layer now would bring back the
overcrowding problem.

## Work still needed beyond this interface pass

1. Extend complete-route evaluation beyond the local sample before offering a
   citywide package-first workflow. The current link ranking should not be
   presented as a connected-network recommendation.
2. Add checked origin/destination place labels and route-level before/after
   comparisons. A numbered sampled journey can be traced, but it explains little.
3. Show concept treatments with site-specific widths and crossing proposals
   only once design evidence exists. The current protected-cycleway treatment
   is a cost and model assumption, not a design illustration.
4. Validate demand and ranking stability, crossing quality and cost assumptions.
5. Profile the 224 MiB uncompressed candidate payload. Its size is a separate
   obstacle to a clear, quick first visit, especially on phones.

This pass revised the interface for review. It is not a new calibration or a
server deployment.
