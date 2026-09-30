# STAND: Secure Two-wheeler Access Network Design

*Where secure bike parking should stand.*

STAND is a siting model and live map for secure public bike docks (Locky Dock stations) on the
University of Auckland's City, Grafton and Newmarket campuses. It is built by the
[Better Places Lab](https://www.betterplaces.auckland.ac.nz/).

STAND is part of SPAN (Spending Priorities for Active Networks), the lab's open tool for deciding where
to invest in cycling. It is SPAN's first bike parking tool, and it lives at
[span.tfwelch.com/parking/uoa/](https://span.tfwelch.com/parking/uoa/).

[Open the map](https://span.tfwelch.com/parking/uoa/) · [Read the method](docs/methodology.md) ·
[Read the recommendations](docs/recommendations.md)

## How STAND uses SPAN

STAND is built on SPAN's traffic-stress network (see `pipeline/build_network.py`):

- each road's and cycleway's Level of Traffic Stress comes from SPAN's way-level table
  (`data/inputs/span_lts_by_way.csv`), or from SPAN's class-and-speed rules where the table has no entry
  (footways and paths are LTS 1);
- riders are routed with SPAN's costs for stress (a link's length ×1.0, ×1.25, ×1.8 or ×3.0 for LTS 1
  to 4) and for gradient (×(1 + 4 × grade) uphill and ×(1 + 0.5 × grade) downhill, so a 10 % climb
  counts as 1.4 times its length), as in SPAN's `stress.py`.

The campus layers, the demand model, the candidate sites and the optimisation are STAND's own. STAND
keeps its own name, mark and colours as the University of Auckland Locky Dock tool. A general bike
parking tool for SPAN is planned; its home will be `span.tfwelch.com/parking/`, with STAND under it.

## What it produces

- `web/`: the map (`index.html`, `ld.css`, `js/`, `assets/`). Pick a campus, see the suitability
  surface (H3 resolution-11 hexagons, about 29 m a side and 50 m across), the modelled cyclist
  approach flows, the traffic-stress network, every candidate site and the recommended docks in
  phasing order. Slide the number of docks, re-weight the eight indicators and watch the selection
  update. Click any site for a plain-English case, its scores, the buildings it serves and a checklist
  for the site visit. The About panel holds the method in brief and the data credits.
- `web/data/`: the map's data, written by `make export`.
- `web/docs/`: the method and recommendations pages, rendered from `docs/` by `make docs`.
- `docs/methodology.md`: every parameter, formula, source and limitation.
- `docs/recommendations.md`: the recommended sites per campus, why, how many docks, and what to check
  on site.
- `data/derived/`: GeoParquet layers (NZTM2000) for GIS users: buildings with LiDAR floors, the
  routable network with LTS and grades, approach flows, candidates with all indicators, the hex surface,
  and the run summaries. A model run writes the same files on the same inputs (hexes are sorted,
  whatever `PYTHONHASHSEED` is); only the `built` timestamp in `site_model_results.json` and
  `web/data/results.json` changes.
- `parking/build/site/` and `parking/build/span-parking-site.zip`: the `/parking/` folder of
  span.tfwelch.com, with STAND in `uoa/` (`make site`; see **Publishing**).
- `web/stand_standalone.html`: the same map in one file that opens by double-click (`make standalone`).

`web/data/`, `web/docs/`, `data/derived/`, `parking/build/` and the one-file map are generated (see
**Generated data stays out of git**).

## How the model works, in one paragraph

Each University building draws cyclists in proportion to its floor area and use; campus totals are
scaled to typical-weekday cyclist arrivals (stated assumptions in `config/model.json`). Riders come from
residential floor area near the campuses and, mostly, through ten corridor portals weighted by Auckland
Transport counter volumes. They take least-perceived-cost routes over the Overture / OpenStreetMap
network, where every link carries a Level of Traffic Stress class from SPAN and a gradient from LINZ
1 m LiDAR, and their flows are accumulated on every path. Every walkable spot on a campus becomes a
candidate scored on eight indicators: buildings covered within a short walk, riders passing,
low-stress approach, passive surveillance (footpath density, active frontage, open sightlines from the
LiDAR surface model), lighting, space and power, slope, and revealed demand at existing racks. A
mixed-integer programme then picks k docks per campus that maximise covered arrivals plus suitability
with a minimum spacing, swept over k = 1..8, and a greedy pass orders them into phases.

## Running the model

Needs Python 3.11 or later with the packages in `requirements.txt`, and Node 18 or later for
`make smoke` (npm too for `make vendor`). Run `make` in `parking/uoa`, or `make -C parking/uoa <target>`
from SPAN's root.

```bash
cd parking/uoa
make install                           # Python packages (DuckDB with httpfs and spatial, GeoPandas, PuLP, rasterio, h3, Markdown)
export STAND_DATA=/path/to/stand-data  # where the big inputs go (default: ./data/big)
make fetch                             # about 600 MB: Overture themes for the study window, LINZ LiDAR DEM and DSM, LINZ aerials
make all                               # layers -> network -> demand -> model -> basemap -> export -> standalone
make serve                             # the map at http://localhost:8765/
make smoke                             # syntax checks only: py_compile on pipeline/*.py, node --check on web/js/*.js
```

`STAND_DATA` names the folder for the big inputs (`pipeline/paths.py`). If it is not set, `LD_LOC_DATA`
(the name STAND used before it moved into SPAN) is read instead, and with neither set the data go in
`./data/big`, which is git-ignored.

`make fetch` needs an open network. It reads Overture Maps (release 2026-09-23.1) straight from its
public S3 bucket with DuckDB and bounding-box pruning, LINZ's open elevation and imagery buckets on AWS,
and nothing else. Every fetch script writes under `$STAND_DATA` (the LINZ tile lists
`linz_elevation_tiles.json` and `linz_imagery_tiles.json` sit at its top level). The last fetch step,
`pipeline/crop_imagery.py` (also `make imagery`), trims the black no-data edges off the three campus
aerial patches by peeling the worst edge row or column until every edge is at least 98 % imaged.

Not everything after `fetch` is offline. `make basemap`, which `make all` runs, needs the network too:
it first runs `make fetch-wide` (Overture themes for the wide window, from S3) and then reads the LINZ
aerial overviews online. `make layers`, `network`, `demand`, `model`, `export` and `standalone` run
offline from `$STAND_DATA` and `data/`.

DuckDB's spatial and httpfs extensions come from the `duckdb-extension-spatial` and
`duckdb-extension-httpfs` packages, pinned in `requirements.txt` to the same version as `duckdb`.
`duckdb_connect()` in `pipeline/paths.py` loads the extension file built for the running DuckDB, and
falls back to DuckDB's own `INSTALL` (which downloads from extensions.duckdb.org) if there is none.

Each step checks its inputs first. If a GeoParquet layer in `data/derived` is missing, it stops and
names the make targets to run (for example `run make layers network first (or make all)`); if a big
input under `$STAND_DATA` is missing, it names the file and suggests `make fetch`.
`pipeline/fetch_overture.py` writes each theme to a temporary file and renames it only when the pull
succeeds, and exits non-zero if any theme failed, so a rerun retries exactly the missing themes.

`make demand` stops with an error if a corridor portal in `config/portals.json` does not reach the
cycling network: each portal snaps to the nearest node of the network's largest connected component
(within 400 m), and the run prints every portal's snap distance.

Inputs already in `data/inputs/` (provenance in `docs/methodology.md`):

- `span_lts_by_way.csv`: SPAN's way-level Level of Traffic Stress table; it overrides the
  class-and-speed rules on every matched road and cycleway link (`lts_source = span_lts_by_way`).
- `at_cycling_network.geojson`: Auckland Transport's cycle facility network (map overlay).
- `cycleway_locations.json`, `cycleway_stats.json`, `cycleway_data_monthly.json`: AT counter sites and
  daily averages from the lab's Cycleway dashboard, with each counter's monthly totals (used for the
  counting period shown on the map); they weight the corridor portals in `config/portals.json` and
  appear on the map.
- `at_cycle_counter_locations.json`: the lab's registry of AT counter sites (approximate site points),
  kept for reference; the pipeline reads `cycleway_locations.json` instead.
- `locky_docks_existing.csv`, `uoa_bike_stores.csv`, `building_labels.csv`: hand-assembled, with a
  quality flag per row; edit these to correct positions or names and rerun `make all`.

## Publishing

`make publish` runs these steps in order and stops at the first failure:

1. `make export`: the map's data in `web/data`, with the curated site names (`config/sites.json`).
   It reads the GeoParquet layers in `data/derived` and the big inputs, so run `make all` first in a
   fresh checkout.
2. `make docs`: the public pages in `web/docs`, rendered from `docs/*.md`.
3. `make site`: `pipeline/build_deploy.py` writes the `/parking/` folder of span.tfwelch.com to
   `parking/build/site/`. STAND goes in `uoa/`: the map, its data and pages, `oembed.json` (so a
   WordPress Embed block can show the live map) and `.htaccess` (from `deploy/htaccess`). If
   `parking/index.html` exists, it is copied in as the folder's own page. The same files go in
   `parking/build/span-parking-site.zip`.
4. `make standalone`: `web/stand_standalone.html`.

SPAN's web build picks up `parking/build/site` as its `parking/` folder. To deploy by hand, extract
`span-parking-site.zip` into the `parking/` folder of span.tfwelch.com. SPAN's own `.htaccess` at the
site root applies there too; `deploy/htaccess` adds only what STAND needs on top of it: the map's
content security and permissions policies, open CORS on the data files (for the sandboxed WordPress
embed), types for the glyphs and `oembed.json`, and cache times for STAND's files. STAND's script and
style names do not change between releases, so they are checked hourly rather than kept for a year
like SPAN's.

`python3 pipeline/build_standalone.py --offline` makes a one-file map that needs no network at all. It
also inlines MapLibre GL JS and the Inter font from `build/vendor` (`make vendor` fetches them from the
npm registry, and the MapLibre files must match the Subresource Integrity hashes in `web/index.html`),
and it sets `window.STAND_OFFLINE`, so the map offers only its own Plain and Aerial basemaps.

### Privacy guard

Every public output passes one check, `private_hits()` in `pipeline/build_docs.py`. `build_docs.py`
checks the Markdown and the finished pages; `build_deploy.py` checks every text file in the `/parking/`
folder (`.html`, `.js`, `.json`, `.geojson`, `.css`, `.svg`, `.txt`, `.md` and `.htaccess`);
`build_standalone.py` checks its one file. On a hit the build stops, names the file and the term, and
leaves nothing behind to upload.

Two checks are built in: absolute paths into a home folder, and `file://` URLs that point at a file. The
private words themselves (people's names, private dates, unpublished reports, internal file names) are
not kept in this repository. Keep them in a text file outside it, one term per line (lines that start
with `#` are comments), and name that file in `STAND_PRIVATE_TERMS`:

```bash
export STAND_PRIVATE_TERMS=/path/to/private_terms.txt
make publish
```

Without it, the builds run the built-in checks only and say that the private-term scan was skipped.
The comments above `_BUILT_IN` in `build_docs.py` say how each term is matched.

## Generated data stays out of git

Like SPAN's run outputs, nothing the pipeline writes is committed: `data/big/`, `data/derived/`,
`web/data/`, `web/docs/`, `web/*_standalone.html` and every `build/` folder are git-ignored. `make all`
and `make publish` rebuild them. The map data published at span.tfwelch.com/parking/uoa/ is the output
of a full run on the inputs above: `make fetch`, `make all` and `make publish`.

## Big data

Raw and bulky inputs are never committed. They live under `$STAND_DATA`:

```
$STAND_DATA/overture/*.parquet       Overture extracts for the study window (about 20 MB)
$STAND_DATA/overture_wide/*.parquet  basemap themes for the wide window (about 30 MB; make fetch-wide)
$STAND_DATA/linz/*.tif               1 m DEM, DSM, slope, normalised height (about 470 MB), per-campus aerials
$STAND_DATA/linz_*_tiles.json        LINZ tile lists the LiDAR and aerial fetches read
```

`web/data/` comes to about 25 MB (7 MB of GeoJSON, three campus aerial patches of 2.5 to 3 MB each and
the own-data basemap of about 10 MB); the GeoParquet layers in `data/derived/` to about 18 MB.

## Basemaps

The map's own basemaps do not depend on any tile server. `make basemap` (part of `make all`) pulls
Overture land, water, land use, buildings, roads and place names for a wide window around the campuses
(lon 174.700–174.840, lat −36.925 to −36.828: Ponsonby, Grey Lynn and Kingsland to Remuera and
Ōrākei, the waterfront to Epsom and Greenlane) and `pipeline/build_basemap.py` writes
`web/data/basemap/`: a quiet "Plain" cartographic basemap in the lab's palette (one overview image of the
wide window at 6 m per pixel and a 3 × 3 grid at 1.2 m over the study window, PNG, about 4.9 MB, no text
in the images), suburb and main-road labels as GeoJSON drawn with the map's own fonts, and a LINZ
2024–25 aerial mosaic of the wide window at 2.5 m (nine JPEGs, about 4.5 MB) read from the overviews of
the 0.075 m urban capture. Every image is rendered in web mercator on a grid snapped to whole pixels, so
it sits exactly under the analysis layers.

The hosted map offers three basemaps, in this order:

- **Plain**, the default: the cartographic images above, with their labels.
- **Streets**: OpenStreetMap's standard tile layer from tile.openstreetmap.org, credited
  "© OpenStreetMap contributors". It is optional and used lightly, as OpenStreetMap's tile usage policy
  asks: the browser requests its tiles only while Streets is shown, and STAND does not bundle or
  prefetch them.
- **Aerial**: the wide LINZ mosaic, loaded the first time Aerial is chosen, with the 0.4 m campus
  patches on top. It runs to the last zoom.

STAND uses no CARTO or Esri tiles. The one-file map inlines Plain, the labels and the wide aerial, so
its Plain and Aerial work from the file; Streets still needs the network. The offline one-file map
offers Plain and Aerial only, opens on Plain and keeps the view inside the wide window and around the
17 existing docks (the Takapuna dock lies north of the drawn basemap).

## Data sources and licences

| Data | Source | Licence |
| --- | --- | --- |
| Buildings, paths and roads, bike parking, lamps, bus stops, land use | Overture Maps Foundation, release 2026-09-23.1 | ODbL 1.0: © OpenStreetMap contributors and Esri Community Maps contributors |
| Shops, cafés and stations | Overture Maps places theme | CDLA-Permissive 2.0 and its providers' terms |
| Ground elevation, slope, surface model | Toitū Te Whenua LINZ, Auckland LiDAR 1 m DEM and DSM (2024) | CC BY 4.0 |
| Aerial imagery | Toitū Te Whenua LINZ, Auckland 0.075 m urban aerials (2024–25) | CC BY 4.0 |
| Streets basemap (optional, online) | OpenStreetMap standard tiles, tile.openstreetmap.org | © OpenStreetMap contributors; shown under OpenStreetMap's tile usage policy |
| Cycle counts, cycle facility network | Auckland Transport | CC BY 4.0 |
| Level of Traffic Stress by way | SPAN, from OpenStreetMap and Auckland Transport's cycle facilities | as its sources |
| University bike stores, existing Locky Docks, building labels | University of Auckland web pages, Locky Dock's station map, OpenStreetMap, and Overture addresses and places, cited per row | as their sources |

The Glen Eden pilot figures on the map and in the method come from published reports (Welch 2024, and
its 2025 addendum, for Waka Kotahi NZTA) and from the operator's dock session log, which is not
published.

## Layout

```
parking/uoa/
  config/        model.json (all assumptions), portals.json (corridor entry points and counter weights),
                 sites.json (the recommended sites' curated names)
  pipeline/      fetch_*.py, crop_imagery.py, build_layers.py, access_rules.py, build_network.py,
                 build_demand.py, site_model.py, export_web.py, name_sites.py, build_basemap.py, paths.py;
                 publishing: build_docs.py (with the privacy guard), build_deploy.py, build_standalone.py
  data/inputs/   small inputs with provenance: SPAN's LTS table, AT counters and cycle network, existing
                 Locky Docks, University bike stores, building labels
  data/derived/  GeoParquet outputs (NZTM2000) and run summaries (generated)
  web/           the map: index.html, ld.css, js/, assets/; data/ and docs/ are generated
  docs/          methodology.md, recommendations.md
  deploy/        htaccess: the Apache settings for span.tfwelch.com/parking/uoa/
  build/         build/vendor, filled by make vendor (git-ignored)
```

## Credits and licence

Built by the Better Places Lab, Te Pare School of Architecture, Planning and Design,
Waipapa Taumata Rau | University of Auckland (Dr Timothy F. Welch), September 2026. Code under SPAN's
MIT licence (`LICENSE` at the repository root). Data under the providers' terms (see **Data sources and
licences**). To cite STAND, use `CITATION.cff` in this folder.
