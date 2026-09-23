# SPAN interface and TEAM reuse review

24 September 2026. This supersedes the earlier separate research-page interface.

## What SPAN needs to help a visitor decide

Which cycling upgrades are worth investigating, what they would connect, and
what can be achieved within a budget. A map of ranked fragments is insufficient.
The investment should be understandable before the visitor opens a method note.

The initial Auckland programme at NZ$100m contains 12 upgrades in 11 physical
groups. It is not one continuous network. The interface must not imply otherwise.
Citywide link ranking and whole-route package selection currently have different
coverage and methods. Putting them in one workspace does not make them equivalent.

## Changes in this revision

- One map with three views: Build order, Value for money, Connected journeys.
  Basemap choice is retained across views. The old research URL only redirects.
- Link detail starts with cost, length, proposed treatment and connections.
  One preliminary modelled outcome follows. Sampling sensitivity, annual journey
  conversions and parameter tests sit behind “How this was estimated”.
- Layer names are short and the menu has a bounded width and height. Dates,
  matching counts and limitations belong in About, not in the menu.
- The programme states when its upgrades form separate groups and provides
  group inspection and a whole-programme map control.
- Complete journeys show A-to-B routes, required upgrades and funding status.
  The local coverage and distinction from new cyclist forecasts stay visible.
- No collaborator biography, provider setup or unfinished CRANC exchange panel
  is exposed in the public site. Contracts and integration notes remain in the repo.
- The journey view rejects mismatched run/topology data before showing results.

## TEAM: inspected sources and useful crossover

Read-only review of sibling `transport-equity-access-model`, its `web/js/map.js`,
`src/team/export.py`, and source/method documentation. The real local outputs are
under `../team/site/data/`, not the synthetic fixtures in the TEAM repository.
The inspected summary reports build 2026-09-13 and routing date 2026-09-15.

| TEAM material | Useful role in SPAN | Boundary |
| --- | --- | --- |
| Basemap selector and map conventions | Consistent Light/Streets controls and familiar lab presentation | SPAN retains its working OpenFreeMap backgrounds and offline Plain option. No need to replace the map engine just to share controls. |
| `destinations.json`: 1,488 named locations with service categories | Context showing schools, shops and services near a proposed connection; potential common opportunity inventory for future access calculations | A nearby point is not proof a project improves access. Confirm source dates, licences and routable destination snapping before reuse. |
| `overlays.json`: 48 rail, 31 ferry and 310 frequent-bus features | Optional context for station connections and first/last-mile planning | Use the timetable date and attribution; do not add another always-on map layer. |
| Population, deprivation and no-car households in TEAM cells | Common area context and weighting for a future equity comparison | Reconcile H3 resolution, census denominators and SPAN origin sampling; do not substitute residential population for commuters. |
| TEAM access times, standards and shortfall maps | Identify places needing further investigation | Baseline R5 accessibility is not SPAN's after-investment result. An intervention needs rerouting with a verified common scenario. |
| TEAM cycling overlay | Potential visual context | SPAN already has an exact-topology network. Do not duplicate or substitute a differently classified layer. |

No TEAM data was copied into the SPAN release and no TEAM files were changed.
The highest-value next reuse is destination context, once linked to the journeys
being explained. Importing every layer now would repeat the overcrowding problem.

## Work still needed beyond this interface pass

1. Extend complete-route evaluation beyond the local sample before offering a
   citywide package-first workflow. Do not silently turn the current link ranking
   into a connected-network recommendation.
2. Add checked origin/destination place labels and route-level before/after
   comparisons. A numbered sampled journey is traceable but not a good narrative.
3. Provide concept treatments with site-specific widths and crossing proposals
   only after design evidence exists. The current protected-cycleway treatment
   is a cost/model assumption, not a design illustration.
4. Validate demand and ranking stability, crossing quality and cost assumptions.
5. Profile the 224 MiB uncompressed candidate payload. The data load remains a
   separate obstacle to a clear, quick first visit, particularly on phones.

This is a revised reviewable interface, not a new calibration or server deployment.
