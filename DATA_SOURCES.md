# Data sources

This register defines the source classes needed for a reproducible Auckland
build. Record an immutable snapshot date, source URL, checksum, native CRS, and
licence for every acquired file in the build manifest. Never substitute a
similarly named dataset without recording the change.

The configured source-by-source publication decision is maintained in
[`documentation/audit/public-layer-rights.csv`](documentation/audit/public-layer-rights.csv).
That file covers all 20 configured Auckland sources plus each proposed public
layer, the offline demonstration, hosted basemaps, and screenshots. The source
registry's `redistribution` field is deliberately conservative: `unknown` or
`restricted` fails public export even when a nearby publisher page appears to
describe similar material as open.

| Source | Purpose | Minimum fields or properties | Preferred publisher |
| --- | --- | --- | --- |
| Journey-to-work OD flows | Eligible and observed commute demand | origin, destination, total-stated release and its numeric/suppressed state, bicycle release and its numeric/suppressed state, source-scope flag, geography vintage | Stats NZ |
| Statistical-area boundaries | OD geometry and joins | stable area identifier, geometry, census vintage | Stats NZ |
| Population and employment weights | Within-zone origin and destination disaggregation | stable small-area/site identifier, population or job count, reference year, geography correspondence | Stats NZ or another authoritative documented source |
| NZDep | Distributional context | SA1 identifier, deprivation decile and/or score, reference year | University of Otago / Stats NZ product metadata |
| Street and path network | Routable topology and attributes | source node/way IDs, direction, access, highway class, cycling facility, bridge/tunnel/layer, geometry | OpenStreetMap contributors |
| Existing cycle facilities | Protected-network classification | facility type, status, geometry, update date | Auckland Transport |
| Strategic cycle network | Planning-context overlay only | programme/status, horizon, geometry | Auckland Transport Future Connect |
| Funded/committed active-mode projects | Programme-context overlay only | programme, delivery status, geometry | Auckland Transport / RLTP |
| Elevation | Directional gradient | raster elevation, resolution, vertical datum | LINZ |
| Public-transport schedule | Transit-access context | stops, routes, trips, stop times, service calendar | Auckland Transport GTFS |
| Schools and enrolment | School-access context | site, type, roll/reference year | Ministry of Education |
| Destinations | Everyday-access context | category, geometry, snapshot date | authoritative agency or documented open source |
| Transit demand/opportunity | Bicycle-to-transit demand surface | station/stop, boarding or opportunity weight, service period, access definition | Auckland Transport or documented authoritative source |
| Cycle counters | External validation | site, location, directionality, aggregation period, observed count, completeness | Auckland Transport |
| Crash records | Safety context | location, date, severity, mode, reporting definition | Waka Kotahi / CAS release |
| Unit benefit parameters | Screening economics | value, price base, update factor, appraisal rule | Waka Kotahi MBCM |
| Project cost evidence | Screening capital cost | facility type, base year, inclusions/exclusions | Auckland Transport or published NZ evidence |

## Current configured-source decisions

| Source ID | Decision | Public action | Reason |
| --- | --- | --- | --- |
| `stats_nz_journey_to_work` | permit | include | Exact Datafinder table 121988 version 410594 and CC BY 4.0 terms verified; retained file is hashed |
| `stats_nz_sa2_transport_margins` | permit | include | Exact Stats NZ ArcGIS item and CC BY 4.0 record verified |
| `stats_nz_sa1_geography` | permit | include | Publisher-owned Stats NZ SA1 layer; only `SA12023_V1_00`, `VAR_1_3`, and geometry are acquired |
| `stats_nz_sa2_geography` | permit | include | Publisher-owned Stats NZ SA2 layer with code, name, and geometry |
| `stats_nz_auckland_boundary` | permit | include | Publisher-owned Stats NZ territorial-authority layer filtered to code `076` Auckland |
| `nzdep2023_sa1` | permit | include aggregate only | Public combined SA1/NZDep snapshot is hash-pinned; only aggregate decile 8–10 origin metrics are exported, with University of Otago, Stats NZ and source-service attribution |
| `educationcounts_schools_auckland` | permit | include | Exact Ministry catalogue record is CC BY 4.0; personal and contact fields are excluded |
| `stats_nz_business_demography_sa2_2024` | permit | include | Exact Stats NZ ArcGIS item and CC BY 4.0 record verified |
| `geofabrik_new_zealand_osm` | permit | include | Exact replication timestamp and hash recorded; ODbL obligations apply |
| `auckland_transport_cycle_network` | permit | include | Exact service item states CC BY 4.0 |
| `auckland_transport_future_connect` | permit | include | Immutable 2,005-feature snapshot is hash-pinned and used only as strategic context under AT's open-data CC BY 4.0 statement |
| `auckland_transport_rltp` | permit | include | Exact service endpoint and 12-feature active-mode snapshot are pinned; source `committed` and `planned` values are retained and never relabelled funded |
| `cycle_counter_locations` | permit | include with warning | The 73 project-maintained points are explicitly approximate and lack direction, bearing and screenline identity; spatial plausibility only |
| `cycle_counter_observations` | permit | include | Exact AT July 2026 workbook, period, CC BY 4.0 statement, transformation and source/output hashes are recorded |
| `crash_hazard` | restricted | exclude | Raw local CAS rows, identifiers, exact points and narratives never enter public output |
| `crash_safety_aggregate` | permit | include | Cycle-involved crashes for 2016–2025 are aggregated to 500 m cells; cells below three are suppressed and only severity totals are retained |
| `linz_auckland_dem` | permit | include | Exact LINZ layer and CC BY 4.0 terms verified; 32 raster tiles are individually pinned |
| `linz_auckland_dem_manifest` | permit | include | Schema-1 integrity manifest pins byte counts and SHA-256 hashes for all 32 VRT-referenced tiles |
| `at_gtfs_schedule_2026_09_01` | permit | local source snapshot | Exact AT feed, retrieval date, service dates, feed version and hash are recorded under CC BY 4.0 |
| `major_transit_nodes` | permit | include | Derived 2026-09-02 service-day layer contains 199 consolidated nodes; scheduled stop visits are opportunity weights, not patronage |

These decisions describe rights evidence, not methodological fitness. In
particular, the configured contour-interpolated 8 m DEM is identified by LINZ
as unsuitable for terrain analysis and therefore cannot support publication
grade gradient estimates without replacement or a defensible validation.

### AT counter preparation

`ciw data prepare-at-counters` converts the exact publisher workbook and a
separately supplied, hash-reviewed coordinate registry into the two configured
counter JSON files. The explicit mapping and exclusion ledger is
[`configs/at-cycle-counter-mapping.yml`](configs/at-cycle-counter-mapping.yml).
The command never performs fuzzy name matching, records every daily value and
the exact observation period, and fails if the workbook adds, removes, or
renames a column without a new review decision. See
[`counter-plausibility-audit.md`](documentation/audit/counter-plausibility-audit.md).

## Provenance requirements

For every build, retain a machine-readable manifest containing:

1. the exact source URL and retrieval timestamp;
2. publisher, title, version or reference date, and licence statement;
3. original filename, byte size, and SHA-256 checksum;
4. native and analysis coordinate reference systems;
5. all filters, joins, category mappings, and exclusions;
6. row/feature counts before and after each material transformation; and
7. the configuration, software version, and random seed that produced outputs.

Where an API or rolling feed cannot reproduce a historic snapshot, archive the
permitted raw response or record a publisher-issued snapshot identifier.

Do not publish wildcard API responses when a narrow field set will do. The
school query is restricted to institution and demand-weighting fields. Source
responses containing contact details, named people, internal full-text search
columns, or other unused attributes must not pass into prepared data or web
exports.

Commute, school, everyday, and transit analyses require genuinely separate
source flows or opportunity models, destination weights, route ledgers, and
candidate outputs. A release must not fill a missing purpose input by renaming
or re-ranking commute demand. Intrazonal records are retained and their
representative-point construction is reported.

For 2023 Census counts, importers preserve explicit suppression markers. Under
the Stats NZ sensitive-table rules, a suppression marker denotes a source count
below six; an unsuppressed numeric release is fixed-random-rounded to base three
and differs from the source count by no more than two. See the verified Stats
NZ record in `documentation/references/library.bib`.

Datafinder table 121988 also has structural coverage rules that are not cell
markers: it removes rows whose total population is below six and includes only
individuals whose workplace address is available at SA2. An absent OD pair is
therefore neither an explicit `-999` cell nor a numeric zero. The pipeline does
not create an interval or destination for an absent row; it records missing-row
and unlocated-workplace mass as unresolved source coverage unless exact
publisher totals permit a bounded comparison.

This rule applies to the total-stated field as well as the bicycle subset. A
direct audit of the configured internal-Auckland journey-to-work file found
5,441 `2023_Total_stated` cells marked `-999`; all 5,441 also have a suppressed
bicycle cell. The two intervals must be interpreted jointly and every selected
point or draw must satisfy bicycle \(\le\) total stated.

The exact source universe must be retained. The published full-origin SA2
transport margin `VAR_2_786` sums to 874,065, whereas published internal-
Auckland OD totals sum to approximately 610,101 plus suppressed and
structurally omitted cells. Those
figures are not hard-reconciled: the products' geographic, directional, and
category universes have not been shown to match. The margin is a bounded, soft
validation diagnostic until that reconciliation is documented. All supplied
outbound records and every unsnapped or unreachable internal record remain in
the OD/route ledger with an explicit status; absent outbound records are
reported as a scope limitation rather than reconstructed from the margin.
