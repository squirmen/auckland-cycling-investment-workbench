# Notices and attribution

Copyright © 2026 Tim Welch.

The software is licensed under the MIT License. That licence does not grant
rights to third-party datasets, publications, logos, basemaps, or provider
trademarks.

## Methodological attribution

The scenario-demand approach independently implements equations and methods
described in the published Propensity to Cycle Tool literature and manual. No
PCT source code or user-interface assets are included in this repository. The
licences of the PCT applications and packages therefore do not replace or
extend the licence of this independently implemented software. Users should
cite both this workbench and the relevant PCT publications:

- Lovelace et al. (2017), *The Propensity to Cycle Tool: An open source online
  system for sustainable transport planning*, DOI: 10.5198/jtlu.2016.862.
- Goodman et al. (2019), *Scenarios of cycling to school in England, and
  associated health and carbon impacts*, DOI: 10.1016/j.jth.2019.01.008.
- Propensity to Cycle Tool (2020), *PCT methodology: commuting layer*, user
  manual C1, version 1.4r.

The official PCT application is distributed under GNU Affero General Public
License v3.0; its project description and licence statement are at
[`pct.bike/about`](https://www.pct.bike/about.html). The separate official
[`pct` R package](https://github.com/ITSLeeds/pct) is distributed under GNU
General Public License v3.0. These projects were used as attributed method and
behavioural comparison references, not as CIW software dependencies. Their
licences govern their own code and assets; they neither apply to CIW data nor
replace the licence of independently written CIW source. The project-specific
comparison and release conditions are recorded in
[`documentation/audit/pct-provenance-review.md`](documentation/audit/pct-provenance-review.md).

Low-stress connectivity draws on the lineage established by Mekuria, Furth and
Nixon (2012), Lowry et al. (2012), Furth, Mekuria and Nixon (2016), and Lowry,
Furth and Hadden-Loh (2016). Full references are in
`documentation/references/library.bib`.

The interpretation of 2023 Census suppression and fixed random rounding follows
Stats NZ (2024), *Applying Confidentiality Rules to 2023 Census Data and
Summary of Changes since 2018 and 2013 Censuses*, ISBN
978-1-99-104974-2. This citation does not grant rights to redistribute a Census
product; the terms attached to the exact downloaded product control.

No claim is made that Auckland Council, Auckland Transport, Waka Kotahi NZ
Transport Agency, Stats NZ, Land Information New Zealand, OpenStreetMap
contributors, or the cited authors endorse this software or its findings.

## Data and map attribution

Every published result must retain the attribution required by its input data
and basemap providers. At minimum, applicable builds should acknowledge:

- © OpenStreetMap contributors; data available under the Open Database
  License 1.0;
- OpenFreeMap and © OpenMapTiles when the hosted Light or Streets basemap is
  selected;
- “This work includes Stats NZ data licensed for reuse under CC BY 4.0” for
  adapted or collected Stats NZ content;
- “Contains data sourced from the LINZ Data Service licensed for reuse under
  CC BY 4.0” for the configured elevation source;
- Auckland Transport for any exact AT dataset whose terms permit inclusion;
  and
- any third-party basemap provider exactly as required by that provider.

The Light and Streets choices request vector styles and tiles from
OpenFreeMap's public service; Analysis makes no hosted basemap request. CARTO
hosted tiles remain disabled because no applicable enterprise licence or
qualifying grant is recorded. See `DATA_LICENSES.md` and
`documentation/audit/public-layer-rights.csv` for the release checklist and
per-layer decisions. A derived output does not automatically inherit the
software licence.

For the curated Auckland browser snapshot, `cells.geojson` is distributed
subject to its Stats NZ CC BY 4.0 source terms. `network.geojson` and
`candidates.geojson` contain an OSM-derived database and must be distributed
under ODbL 1.0 with OpenStreetMap attribution, while their Stats NZ, Ministry
of Education, Auckland Transport, and LINZ components retain their own CC BY
4.0 attribution requirements. The exact permitted hashes and deliberately
empty or withheld layers are recorded in
`documentation/audit/public-layer-rights.csv`.

## Frontend map components

The optional hosted basemap view uses MapLibre GL JS 6.6.0 under the
BSD-3-Clause licence and `@maplibre/maplibre-gl-leaflet` 0.1.4 under the ISC
licence. These packages are installed from the locked npm manifest and remain
subject to their own notices and licence terms.

## Container runtime components

The optional reproducibility container installs third-party command-line
programs from the Debian snapshot dated 3 August 2026. They are separate
runtime components, and their own licences govern their binaries and source;
the root MIT licence applies to CIW source and does not replace those terms.

- `osmium-tool` 1.15.0 is distributed under GNU General Public License v3.0.
  Upstream source and licence: [tag
  1.15.0](https://github.com/osmcode/osmium-tool/tree/v1.15.0) and
  [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html).
- GDAL 3.6.2 is distributed under its permissive MIT/X-style licence. Upstream
  source and licence: [tag
  v3.6.2](https://github.com/OSGeo/gdal/tree/v3.6.2) and
  [GDAL licence](https://gdal.org/en/stable/license.html).
- r5py 1.1.7 is dual-licensed under GPL-3.0-or-later or MIT; this distribution
  uses the MIT option. The embedded R5 7.5.1-r5py engine is MIT-licensed. Exact
  licence texts, upstream tags, and the JAR checksum are retained in
  [`third_party/`](third_party/README.md) and copied into the container.

The Debian package copyright files remain the authoritative notices for the
exact installed binaries and their bundled libraries. Before publishing a
container image, preserve those files and complete the corresponding-source
and notice obligations for `osmium-tool` and every other redistributed
dependency. These runtime notices do not imply endorsement or change the
licence of CIW's own source files.
