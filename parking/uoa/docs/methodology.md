# STAND methodology

Secure Two-wheeler Access Network Design: siting secure public bike docks on the University of
Auckland's City, Grafton and Newmarket campuses. Better Places Lab, September 2026. Version 0.1.0.

STAND is part of SPAN (Spending Priorities for Active Networks), the Better Places Lab's open tool for
deciding where to invest in cycling. It is SPAN's first bike parking tool. It takes each street's Level
of Traffic Stress from SPAN, and routes riders with SPAN's costs for stress and gradient (section 4).

This note records every step, parameter and source so the result can be reproduced, challenged and
improved. Parameters live in `config/model.json` and `config/portals.json`; nothing is hard-coded in
the scripts that is not also described here.

## 1. The question and the framing

The question is where, on each campus, a short list of secure public bike docks should go, with a
rationale. A good site for a secure public dock:

1. is where cycling trips end: within a short walk of many people's destination buildings;
2. is on the way in: on the paths and streets riders already use to approach the campus, so it asks for
   no detour;
3. is reached calmly: the last few hundred metres are on low-stress links, or will be;
4. is safe to leave a bike at: overlooked by busy frontages and footpaths, open to view, lit at night
   (riders cite theft as a reason they stop cycling. In a survey of 1,821 theft victims in North
   America, 45 % rode less or stopped riding afterwards: Cohen et al. 2024, *International Journal of
   Sustainable Transportation* 18(5), doi:10.1080/15568318.2024.2350946);
5. can physically take a station: a 4.8 × 2.2 m footprint (a Bikeep 5-bike station fits a car space),
   flat ground, and mains power within reach (the Glen Eden pilot found solar power alone is not enough
   at a busy site);
6. adds to what exists: open racks nearby show revealed demand; a card-access University store next
   door lowers the marginal value.

These six ideas become the eight indicators in section 6. Everything else (the network, the flows, the
optimisation) exists to measure them without hand-drawing.

## 2. Study area and data

Study window: longitude 174.735–174.800, latitude −36.890 to −36.835 (about 6 × 6 km), covering all
three campuses with a 1.5–2.5 km approach buffer. Study areas per campus are generous rectangles;
campus footprints are derived from the data (section 3).

| Layer | Source | Notes |
| --- | --- | --- |
| Buildings, building parts | Overture Maps 2026-09-23.1, buildings theme (OpenStreetMap and Esri Community Maps) | 5,690 footprints in and within 400 m of the campus study areas (2,286 inside them): 5,339 from OpenStreetMap and 351 from Esri Community Maps. All 126 University buildings come from OpenStreetMap. Names, subtype, floors and heights where mapped |
| Roads, paths, rail segments and connectors | Overture transportation theme (OSM-derived) | 9,813 segments in the buffered study areas, split into 23,625 edges at connectors; OSM way ids kept |
| POIs | Overture places theme (Meta, Foursquare, Microsoft and AllThePlaces) | 8,889 near the campuses; used for active frontage and stations |
| Bike parking, lamps, bus stops, crossings, car parks, benches | Overture base/infrastructure (OSM) | 289 bicycle-parking points, 557 street lamps near the campuses |
| Land use, campus relation | Overture base/land_use (OSM) | the University's OSM relation gives the Grafton and City extents |
| Addresses | Overture addresses theme (LINZ) | labels for unnamed buildings |
| Ground elevation, slope | LINZ Auckland Part 1 LiDAR 1 m DEM (2024), tiles BA31/BA32 | via the nz-elevation open bucket on AWS |
| Surface model, building heights, sightlines | LINZ Auckland Part 1 LiDAR 1 m DSM (2024) | normalised height = DSM − DEM |
| Aerial imagery patches | LINZ Auckland 0.075 m urban aerials (2024–25), resampled to 0.4 m | one patch per campus for the Aerial basemap |
| Cycle counts | Auckland Transport daily cycle counts, 86 counter sites, from the lab's Cycleway dashboard extract, updated July 2026. Each daily average is over that counter's whole record: January 2016 to July 2026 for most of the counters named here, with gaps for some; July 2016 to December 2018 for Quay St Totem, whose record stops there; January 2019 to July 2026 for the Lightpath. Quay St Totem 849, Tāmaki Dr 1,126, Nelson St 691, Lightpath 552, Grafton Bridge 514, K Rd 495, Grafton Gully 375, Beach Rd 310, Symonds St 267, Upper Queen St 238, Carlton Gore Rd 235, Grafton Rd 154, Great South Rd 98 riders/day | weights for corridor portals; counter layer on the map |
| Traffic stress per OSM way | SPAN's `span_lts_by_way.csv` (124,068 ways, LTS 1–4 with share of length), from SPAN's traffic-stress network, which applies the AT cycle-facility overrides | joined on OSM way id; overrides the class-and-speed rules |
| AT cycle facility network | Auckland Transport CyclingService layer (2,166 features: type of facility, status, year), the lab's extract | map overlay |
| Pilot evidence | Welch (2024) and addendum (2025), Suburban Micromobility Hub Network Pilot, Glen Eden, for Waka Kotahi NZTA; the Locky Dock session log (330 sessions) | the operator's session log, not published; findings used in section 1 |
| University facilities | University of Auckland bike-store and sustainable-commuting pages; OSM cages | `data/inputs/uoa_bike_stores.csv`: 14 card-access stores, ten on the City campus, one at Grafton, three at Newmarket. Four are mapped in OSM and use those positions; ten are placed at their building or address, flagged as approximate |
| Existing Locky Docks | Locky Dock's own station map (September 2026): 17 stations across Auckland. Three are mapped in OSM as Locky Docks and keep those positions; one of them, on Lorne St, is in the campus study areas. The other 14 are placed from Overture addresses and places (2026-09-23.1) and OSM, and checked on LINZ aerial photos (2024–25) | `data/inputs/locky_docks_existing.csv`, source cited per row, coordinates flagged by quality; map layer |

Not available to this run: Stats NZ census and NZDep by SA1 (only SA2 margins), use data from secure
public bike parking in Auckland beyond the Glen Eden pilot, and any record-level theft data.

### Basemap (`build_basemap.py`)

The map's background is built from the same open data rather than third-party tiles, so it also works
where tile hosts are blocked (offline or sandboxed copies). It covers a wide window, longitude 174.700–174.840,
latitude −36.925 to −36.828 (about 12.5 × 10.8 km), pulled with `fetch_overture.py --bbox … --out
$STAND_DATA/overture_wide --lite`: 129,052 buildings, 44,185 transportation segments, 9,891 land-use
and 12,118 land features, 2,972 water features (including the ocean polygon, about a fifth of the window)
and 45 division points, of which 35 suburbs (Overture `macrohood`) fall inside it.

*Plain* is drawn with matplotlib (Agg) in EPSG:3857 in the Better Places Lab palette (land #eef0ee,
water #cfdde4 with a darker shore, parks and green land use #dfe7da, buildings #d7dad7 with a #c9cdc9
hairline, white roads, motorway and trunk #f3efe6, rail #b9bec2). Road widths follow the class at
roughly their real width (motorway 17 m, primary 13.5 m, residential 8.5 m, service 4 m, link roads
at 60 %); footways, paths and cycleways are a faint dotted white, sidewalks and crossings are left out,
and tunnels, indoor, abandoned and under-construction parts of segments are cut out using Overture's
road flags. Two levels keep every image inside a phone GPU's 4096 px texture limit: an overview of
the whole window at 6 m per pixel (2,079 × 1,801 px) shown at every zoom, and a 3 × 3 grid over the study
window at 1.2 m (4,824 × 5,102 px in tiles of at most 1,608 × 1,701) shown from zoom 13.5. All ten
images share one 64-colour palette, so no colour changes across a tile edge. There is no text in the
images: suburb names (ranked by population: 15,000+, 4,000+, other) show from zoom 12 to 15.5, and the
313 named motorway, trunk, primary, secondary and tertiary roads, merged by name and simplified to 5 m,
are placed along their lines from zoom 14.5; below them, the network's own street names fill in from
zoom 15.5.

*Aerial* is a mosaic of the LINZ Auckland 0.075 m Urban Aerial Photos (2024–25). The 421 1:1000 sheets
(480 × 720 m) that touch the window are read at their 1/32 overview (2.4 m), which falls exactly on the
sheet grid in NZTM2000, then reprojected (bilinear) to web mercator at 2.5 m per ground pixel: 4,988 ×
4,320 px in nine JPEGs at quality 72. The urban capture covers 97.5 % of the window; the rest is open
harbour north of Ōkahu Bay and Mission Bay beyond the capture. None of the four 0.25 m rural 2024 sheets
in the window covers that gap, so it is filled with a smooth local average of the surrounding imaged
water (sampled inside the Overture ocean polygon), feathered into the photograph over about 30 m. The
0.4 m campus patches are drawn on top. Each patch is a reprojected mosaic with black no-data at its
edges, so it is trimmed by repeatedly dropping the edge row or column with the most no-data until every
edge is at least 98 % imaged: City 3,528 × 3,713 px, Grafton 3,529 × 3,621 px, Newmarket 3,405 × 3,427 px.

Each image's corners are computed from its exact EPSG:3857 extent on a grid snapped to whole pixels, and
handed to MapLibre as an image source (top-left, top-right, bottom-right, bottom-left), so the basemap
registers with the analysis layers to within a pixel; `web/data/basemap/basemap.json` records the
corners, pixel sizes, bytes and minimum zoom of every image.

The hosted map offers three basemaps. *Plain*, the default, and *Aerial* are these images, served with
the map; Aerial shows the wide mosaic at every zoom, with the campus patches on top. *Streets* is
OpenStreetMap's standard tile layer (tile.openstreetmap.org, © OpenStreetMap contributors). The browser
asks for those tiles only while Streets is shown, and STAND does not bundle or prefetch them, as
OpenStreetMap's tile usage policy asks. The map uses no CARTO or Esri tiles. The offline one-file map
offers Plain and Aerial only.

## 3. Layers (`build_layers.py`)

- **Campus assignment.** Buildings inside any study area are assigned to the nearest campus anchor
  (City 174.7695, −36.8520; Grafton 174.7685, −36.8615; Newmarket 174.7735, −36.8660) because the
  study rectangles overlap.
- **University buildings.** Buildings tagged education/university or education/library inside the study
  areas, minus other institutions matched by name (AUT, Massey, Otago, Victoria, UUNZ, Yoobee, NZMA,
  Whitireia, the College of Law, the Mind Lab, Wesley, St Peter's, Auckland Grammar, Newmarket School,
  the Mondrian building), minus anything inside the AUT relation; plus buildings whose name marks them as
  the University's (Engineering 4xx, Science Centre, Owen G Glenn, Kate Edger, Clock Tower, Social
  Sciences, halls, Structures 9xx, Ray Meyer, and so on). 126 buildings.
- **Floors and floor area.** Observed floors where mapped; else mapped height / 3.5; else the LiDAR
  building height (60th percentile of DSM − DEM inside the footprint, shrunk 1.5 m) / 3.6 where the
  building is at least 2.5 m tall; else a default by subtype (education 3, commercial 3, residential 2).
  Gross floor area = footprint × floors. `floors_source` records which rule applied.
- **Campus footprint.** University buildings buffered 20 m, unioned with the OSM university land-use
  relation buffered 5 m, dissolved, parts under 1,500 m² dropped. The relation also takes in the Epsom
  campus and a small site near Mt Eden, both more than a kilometre outside the study areas. The model
  and the map drop any footprint part with less than half its area within 100 m of the study areas, so
  those two add no candidates and no hexagons.
- **Infrastructure points.** OSM bicycle parking (with `is_locky_dock`, `is_uoa_cage`, `is_scooter_bay`
  flags from names), street lamps, bus stops, crossings, signals, benches, car parks and spaces, parking
  entrances, platforms, bollards, gates.
- **Edges.** Each Overture segment is cut at its connectors (Overture stores the fraction along the line
  for each connector), giving a topological edge list keyed by connector ids. Flags (bridge, tunnel,
  under construction), access restrictions, level and posted speed are carried through.

## 4. Network (`build_network.py`)

- **Grades.** Elevation at each edge end from the 1 m DEM; grade = Δz / length, clipped ±30 %, forced to
  0 on bridges and tunnels (the DEM is the ground). Median absolute grade 2.2 %, 90th percentile 9.8 %.
- **Level of Traffic Stress.** SPAN's segment rules (Better Places Lab, `stress.py`) for mixed traffic,
  with SPAN's per-class imputation of lanes and daily volume (arterial 4 lanes / 15,000; collector 2 /
  7,000; local 2 / 3,000; service 1 / 1,000) and Overture's posted speed where present (else SPAN's
  imputed 60 / 50 / 40 / 30 km/h): LTS 1 if ≤ 30 km/h, ≤ 2 lanes, ≤ 2,000 veh; 2 if ≤ 40 / ≤ 2 / ≤ 4,000;
  3 if ≤ 50 / ≤ 3 / ≤ 12,000; else 4. Cycleways, paths, footways and pedestrian streets are LTS 1;
  living streets 1 at ≤ 30 km/h; motorways and trunk roads 4 and closed to bikes. On roads (service
  lanes and living streets included) and cycleways that SPAN's way-level table has
  (`data/inputs/span_lts_by_way.csv`), the class covering most of the way's length replaces the rule
  (ties go to the higher class); footways, paths, pedestrian streets, steps and tracks keep LTS 1. This
  carries the AT cycle-facility overrides SPAN applies (protected lanes on Grafton Rd, Beach Rd, K Rd and
  so on).
  `lts_source` on every edge says which applied; shares by LTS are in
  `data/derived/build_network_summary.json`.
- **Permissions.** Each link starts from a default for its class: bikes may use every class except
    motorways, trunk roads and steps, and people on foot every class except motorways and trunk roads.
    Overture's access rules for the link then decide, for each mode and, for bikes, each direction
    (`pipeline/access_rules.py`):
    - a rule binds bikes when it names no mode, names bicycles or names vehicles (Overture's "vehicle"
      includes bicycles). It binds walking when it names no mode or names people on foot. Rules that name
      only motor vehicles, cars, buses or heavy vehicles bind neither;
    - a rule with a heading (a direction of travel) binds bikes going that way only, and never binds
      walking: a one-way street is one-way for bikes, and people may walk along it both ways;
    - rules limited to a time of day, to certain users (private, customers, staff or destination traffic)
      or to vehicle size or weight bind no one here; they neither open nor close a link to the public. A
      rule for part of a segment binds only the links in that part;
    - where several rules bind, the most specific wins: a heading counts 2, a named mode 1, and a tie goes
      to the later rule. Overture writes a one-way street as a rule that denies one heading to every mode
      (it counts 2), and OpenStreetMap's bicycle=yes or bicycle=designated as a rule that allows bicycles
      with no heading (it counts 1). So bicycle=yes gives bikes access but does not lift a one-way. Only a
      rule that names both the heading and bicycles ("one-way except bicycles", which counts 3) would open
      the other direction to bikes. In this Overture release the only such exemptions in the study area
      are for buses, so no contraflow is open to bikes;
    - foot=no reaches Overture as a rule that denies people on foot, so a cycleway tagged foot=no is
      closed to walking;
    - motorway and trunk links at LTS 4 stay closed to bikes whatever their rules say. In this run no
      motorway or trunk link is open to bikes.

    In this run 21,732 of the 22,918 links are open to bikes in at least one direction, 2,745 of them
    (80 km) in one direction only, and 22,237 are open to walking; 276 cycleways (9.5 km) are closed to
    walking by foot=no. Bikes may use footways and pedestrian streets at a dismount penalty (×1.6).
    Parking aisles are walkable. Walking cost is the length ×1.5 on steps, ×1.0 on footways, paths,
    cycleways, pedestrian streets, living streets and service lanes (parking aisles included), and ×1.2 on
    roads.

- **Cycling cost per edge (SPAN's form).** c = ℓ · m(LTS) · (1 + 4.0·max(0, g) + 0.5·max(0, −g)) ·
  dismount, with m = (1.0, 1.25, 1.8, 3.0) for LTS 1–4 and g the grade as a fraction, direction-specific.

## 5. Demand: where riders arrive (`build_demand.py`)

- **Destinations.** University buildings except halls of residence and structures whose names mark them
  as underpasses, overpasses, bridges, car parks or parking, substations or plant rooms (on the City
  campus, Northern Underpass and Overbridge). The test looks for those words anywhere in a name, not
  as whole words, so it also leaves out Pembridge, a 1,078 m² University building on the City campus,
  whose name contains "bridge" (section 9). That leaves 115 destinations. Weight W_j = GFA_j × use factor
  (1.0 teaching, library and student-facing; 0.7 research, office and workshop; 0.8 recreation). Campus
  arrivals A_c (typical weekday cyclist arrivals) are split across buildings in proportion to W_j.
  A_c in this run: City 900, Grafton 140, Newmarket 90, derived as on-campus population on a typical day
  × cycling share (students 1.5–2 %, staff 5–6 %, from the AT 2018 tertiary survey's 1 % for UoA students
  and growth since; see `config/model.json` for the arithmetic). They scale the flows and the coverage
  numbers; site rankings are insensitive to them, dock counts are not.
- **Entrances.** For each destination, the network nodes within 25 m of the footprint (up to eight),
  or the nearest node. Walking distance to a building is the shortest walk to any of its entrance nodes.
- **Main network.** Routing uses only the main cycling network, its largest strongly connected part:
  every node on it can reach, and be reached from, every other one, one-way links included. The rest is
  284 small islands (713 of 15,359 nodes): short service lanes and footpath stubs cut off from everything
  else, and one-way stubs that cannot be ridden back out of. Riders are routed to a building's first
  entrance on the main network, or, if it has none, to the main-network node nearest the building. For
  12 of the 115 buildings the nearest entrance is on an island, among them Engineering 405, the Park Road
  frontage building at Grafton and two Khyber Pass Road buildings at Newmarket. Routed there, 223 of the
  1,130 daily arrivals (20 %) could not be reached from any origin and would add nothing to the flows.
  All 12 have another entrance on the main network. The entrance list itself does not change, so walking
  distances and coverage do not either.
- **Origins.** (a) Residential buildings within 400 m of the three campus study areas (about 2.4 by
  3.6 km), weighted by GFA (halls ×1.5), snapped to the
  nearest main-network node within 150 m (snapped to the nearest node of any part, 11 of the 592 home
  nodes, holding 6 % of the residential weight, sat on islands); (b) ten corridor portals
  (`config/portals.json`) at the points where the main cycling corridors enter the window. Eight of the
  ten portal weights are based on AT counter daily averages from the Cycleway dashboard extract. Two of
  those blend two counters (Quay St Totem with Tāmaki Dr, and Nelson St with the Lightpath), and
  Remuera Rd uses the Carlton Gore Road counter. Broadway and Parnell Rd have no counter; their weights
  are analyst judgements (flagged in `config/portals.json`). The busiest, Quay St and Tāmaki Drive at
  1,000 riders a day, enters where Tāmaki Drive meets the eastern edge of the study network. A share
  `portal_share` = 0.6 of the origin weight goes to the portals: most riders live further out than the
  residential origins reach (typical Auckland cycle commutes are 4–6 km). The portals are further from
  the campuses, so the distance decay (below) gives them a little less than that share of the trips. In
  this run 585 of the 1,130 daily arrivals (52 %) come through the portals, most through Quay St and
  Tāmaki Drive (167 a day), Nelson St and the Lightpath (110), Karangahape Rd (92) and Grafton Gully
  (80), and 545 come from homes near the campuses.
- **Portal snapping.** Each portal joins the network at the nearest node of the main network, so no
  portal can land on a short stub of road or path that does not reach the campuses. The Remuera Rd
  portal stands on Remuera Road at Dilworth Avenue (174.7847, −36.8749), where riders from Remuera join
  the modelled network, which runs on for only a few hundred metres further east. In this run the snaps
  are 2 to 69 m, Remuera Rd 5 m. The run stops if a portal
  does not snap within 400 m or if no campus can be reached from it, and prints a warning with totals
  if any arrivals or origin weight still cannot be routed.
- **Gravity.** For destination j, origin i's share ∝ O_i · exp(−c_ij / λ) with c_ij the perceived
  cycling cost (section 4) and λ = 3,000 m. Trips T_ij = A_j × share.
- **Accumulation.** Trips are pushed down the shortest-path trees (Dijkstra from each destination on the
  reversed graph; far nodes first, Brandes-style) giving cyclists/day on each edge (`flow_edges`) and
  passing flow at each node (`flow_nodes`). In this run all 1,130 daily arrivals are routed, and the
  modelled trips add up to about 2,030 km of riding a day on the network (1.8 km per trip on average).
  The busiest links carry roughly 200 to 240 riders a day: the Churchill Street shared path about 240,
  the footpaths at the corner of Symonds Street and Wellesley Street East about 220, and the Grafton
  Gully cycleway about 210. The eastern portal weight moves mainly the Churchill Street path, where most
  riders come in from Tāmaki Drive. Rerun with the Quay St and Tāmaki Drive portal at half its weight
  (500 a day), that path falls to about 180; at a quarter (250 a day), to about 140. Grafton Gully stays
  above 200 in both, and the Symonds Street footpaths rise a little, to about 230.

## 6. Candidates and indicators (`site_model.py`)

**Candidates.** Inside the campus footprint buffered 80 m: every walkable network node not solely on
steps or arterial carriageways; midpoints of walkable footways, paths, cycleways, pedestrian and living
streets, service lanes and residential streets longer than 60 m; existing open racks; car-park polygon
centroids. De-duplicated at 12 m, snapped to the walk graph (≤ 60 m), excluded if inside a building or
on ground steeper than 8 %. This run has 701 candidates: City 395, Grafton 179 and Newmarket 127.

**Indicators.** Each is a score from 0 to 1. Only four parts are min–max scaled per campus, between the
5th and 95th percentiles of that campus's candidates and clipped to 0–1: coverage, log(1 + riders
passing), and two parts of surveillance (footway length, and shops, cafés and bus stops). The others
are fixed formulas, the same on every campus.

| Indicator | Definition | Weight |
| --- | --- | --- |
| coverage | Σ_j A_j · f(d_cj) over the campus's buildings, f = 1 for d ≤ 50 m network walk, falling linearly to 0 at 250 m; min–max scaled | 0.30 |
| arrival_flow | riders passing: the most modelled cyclists/day on any edge within 25 m, taken as log(1 + riders) and min–max scaled | 0.20 |
| approach_lts | share of the modelled flow on edges within 40 m that is on LTS 1–2 edges; 0.5 where no modelled flow passes within 40 m | 0.10 |
| surveillance | 0.4 × footway length within 50 m (footways, paths, cycleways and pedestrian streets; min–max scaled) + 0.3 × (shops and cafés within 75 m + ½ bus stops within 100 m; min–max scaled) + 0.2 × openness + 0.1 × overlooked; openness = share of non-building ground within 20 m with normalised height < 2.5 m (DSM − DEM), 0.5 where not measured; overlooked = buildings within 25 m (capped 3) / 3 | 0.15 |
| lighting | street lamps within 30 m / 3, capped at 1 | 0.08 |
| space_power | 0.5 × space (1 if a mapped car park, car space, parking entrance or plaza is within 15 m, if the bounding box of a service lane, living street or pedestrian street link comes within 6 m, or if the candidate is a car park; else 0.5) + 0.5 × power (1 if the bounding box of any building comes within 30 m, else 0.4). The two bounding-box tests are generous: see section 9 | 0.07 |
| slope | 1 at ≤ 2 % ground slope (1 m DEM, median within 4 m), falling linearly to 0 at 8 %; a slope that could not be measured is taken as 4 % | 0.05 |
| revealed_demand | open racks within 40 m (capped 3) / 3, minus 0.5 if one of the University's 14 card-access bike stores is within 60 m in a straight line, clipped to 0–1. All 14 are used, including the ten at approximate positions, because the test asks whether a store is next door and an approximate position is still at the right building. Each candidate also records the nearest store and its straight-line distance, flagged where that store's position is approximate | 0.05 |

The walking-credit thresholds sit between NZTA's 25 m for public short-stay parking and the longer
walks secure long-stay users accept (CROW; Delft station studies): a shared campus dock serves several
buildings. The weights encode the six ideas of section 1; the map lets users change them live.

## 7. Choosing the docks

For each campus and each k in 1..8, a mixed-integer programme (PuLP, CBC) chooses docks x_c ∈ {0,1}
and assignments z_cj ∈ [0,1]:

maximise Σ_j Σ_c (A_j / A_tot) · f(d_cj) · z_cj + (γ / k) Σ_c S_c · x_c
subject to Σ_c z_cj ≤ 1 for each building (credited once, to its best dock), z_cj ≤ x_c, Σ_c x_c = k,
and x_a + x_b ≤ 1 for any two candidates closer than 110 m.

γ = 0.3. The objective is coverage plus a small suitability bonus. The bonus lets suitability tip a
choice between sites that cover similar demand, but it also means a larger set can occasionally cover
slightly less than a smaller one. In this run no larger set covers less. The best set of k docks covers
these shares of each campus's arrivals:

| Docks (k) | City | Grafton | Newmarket |
| --- | --- | --- | --- |
| 1 | 41.3 % | 49.1 % | 76.4 % |
| 2 | 63.5 % | 76.2 % | 92.0 % |
| 3 | 73.0 % | 83.3 % | 99.9 % |
| 4 | 79.1 % | 89.5 % | 99.9 % |
| 5 | 85.0 % | 92.6 % | 99.9 % |
| 6 | 88.8 % | 95.8 % | 100 % |
| 7 | 91.0 % | 96.7 % | 100 % |
| 8 | 93.5 % | 98.5 % | 100 % |

Each set is optimised afresh, so a larger set can move docks rather than add one. At Newmarket three
docks cover 99.9 %; a fourth or fifth adds nothing, and six or more cover every arrival.

The recommended k (City 6, Grafton 3, Newmarket 3) is a judgement about a first network; the sweep
shows what each further dock adds. The recommended set for each campus is the sweep's own solution at
that k, so the site list and the map always agree. A greedy pass over the chosen set orders it into
phases by marginal newly-covered arrivals. The web map reproduces the greedy selection in the browser
when the weights are changed, so users can explore; the published sets are the exact solutions.

**H3 surface.** For the map's suitability view, a simplified version of the score is computed at the
centroids of H3 resolution-11 hexagons (about 29 m a side, about 50 m across, about 0.002 km²) covering
each campus footprint plus 150 m: 921 hexagons in this run (City 501, Grafton 279, Newmarket 141). It
uses coverage, riders passing, lighting and slope as above (slope as the median within 6 m) and a
simpler surveillance term: 0.6 × footway length within 50 m (min–max scaled) + 0.4 × openness. Approach
LTS, space and power, and open racks are not measured for hexagons; each is held at a neutral 0.5.
The weights are the same as for the candidates. A hexagon whose centre is inside a building gets no
score. Resolution 11 was chosen because resolution-9 cells, about 200 m a side, are wider than a
campus block. The hexagons are written in H3 order, so a rerun on the same inputs writes the same files.

## 8. Dock counts (indicative)

Covered arrivals per site are modelled cyclists whose ride ends within reach. Not all will use a
public dock: regulars with a Campus Card already have ten stores on the City campus. A reasonable
planning share for public docks is 10–15 % of covered arrivals, growing with e-bikes and visitors, plus
NZTA's 10–25 % headroom over peak. For a site covering 150 arrivals/day that is about 17–28 docks
(150 × 10 % × 1.1 to 150 × 15 % × 1.25), or a 10-dock charging station to start, expanded as
utilisation is observed. Glen Eden's five docks ran at 40 % utilisation, and all five were in use at
once at the March 2024 peak.

## 9. Limitations and next steps

- Arrival totals and the portal share are assumptions with stated ranges; they scale coverage and
  dock counts, not the ranking.
- OSM lamp and rack coverage is incomplete, and ten of the 14 University bike stores are placed at
  their building or address rather than surveyed; lighting and revealed demand are soft signals.
- Counter averages span each counter's whole record, so they mix years. The Quay St Totem figure
  comes from July 2016 to December 2018; the Tāmaki Dr counter, 1,126 a day to July 2026, supports
  the same order of weight for that portal.
- Overture drops OSM cycleway tags; SPAN's way-level table supplies the facility-aware stress class for
  the ways it covers, and the class-and-speed rule stands in elsewhere (new or unmatched ways).
- Building entrances are inferred from network nodes near footprints, not surveyed doors.
- Destinations are left out by words in their names (section 5), and the test finds those words
  anywhere in a name. That drops Pembridge, a 1,078 m² University building on the City campus, because
  its name contains "bridge". Counting it would add about 3 of the City's 900 daily arrivals. A test
  that counted it, rerun on this version of the model, left the six City docks and their order
  unchanged; they cover 88.6 % of the City's arrivals rather than 88.8 %. Matching whole words is a
  change for the next version.
- The space and power tests (section 6) use bounding boxes. A service lane, living street or
  pedestrian street link counts as within 6 m, and a building as within 30 m, when its bounding box
  does, so a long lane or a large building can count while lying further away. In this run that gives
  21 candidates a space score of 1 and 16 a power score of 1 that true distances would not. None of
  them is a recommended site. A rerun of this version with true distances left every campus's
  recommended docks and their order unchanged; of the other sets in the sweep, only the seven-dock City
  set changed, by one dock.
- One-way streets. Overture records a one-way street as an access rule for one direction of travel.
  Earlier runs of this model read any rule that denied access without naming a travel mode as closing
  the link to everyone in both directions, so one-way streets, lanes and cycleways were left out of the
  cycling network, and all but the one-way cycleways out of the walking network. This version reads each rule for each mode and direction (section 4): a one-way binds
  bikes in its own direction only and never binds people on foot. Compared with those runs, 2,929 links
  (85 km) opened to bikes, 2,745 of them in one direction only, and no link that was open to bikes both
  ways became one-way. For walking, 2,587 links (73 km) opened, while 276 cycleways (9.5 km) tagged
  foot=no closed. The eastern end of Remuera Road joined the main network. Routes are more direct:
  about 2,030 km of riding a day rather than 2,070. Riders from Tāmaki Drive now keep to the one-way
  waterfront links and a cycleway beside The Strand, so the Beach Road cycleway carries about 50 riders
  a day rather than 250. Walking distances changed where a one-way lane is the short way to a building,
  and the recommended docks moved. The City's six docks now cover 88.8 % of its arrivals rather than
  85.3 %: the service lane between the General Library and the Old Choral Hall and Waterloo Quadrant
  replace Alfred Street and the Thomas Building, and the Wynyard Street dock moves about 25 m. Grafton's
  three cover 83.3 % rather than 83.7 %, at the same three spots, and Newmarket's three 99.9 % rather
  than 98.7 %, with one dock about 30 m from where it was.
- Routing weighs traffic stress and gradient, but the gradient term is mild: a climb costs
  1 + 4 × grade times its length, so a 10 % climb counts as 1.4 times its length. Riders' own route
  choices suggest steep climbs weigh more than that. So some riders are routed up short steep links such
  as Constitution Hill (about 185 m at 13 %), where some would choose a longer, flatter way.
- Evidence on how secure public bike parking is used in Auckland is thin beyond the Glen Eden pilot.
  New utilisation and siting evidence should be read against this model as it appears.
- Every recommended site needs a field check (footprint, power, CCTV, lighting, land ownership and
  consent) and a baseline bike count.
