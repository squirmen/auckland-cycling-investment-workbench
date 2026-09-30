# Auckland source-gap resolution — 1 September 2026

## Decision

The next Auckland research snapshot includes every prepared public context and
result listed below. Full-network CIW OD low-stress connectivity is the only
deliberately deferred result. It is reserved for integration with Steve
Gehrke's sabbatical research; the web application reports no Auckland
low-stress point estimate in the meantime.

“Available” does not mean “decision-ready.” Each layer retains its stated
scope, provenance and limitations.

## Resolution matrix

| Gap | Resolution | Public status | Important boundary |
| --- | --- | --- | --- |
| Transit | Dated AT GTFS feed converted to 199 consolidated major nodes for the 2 September 2026 service day | available | Scheduled stop visits are opportunity weights, not patronage |
| Equity | NZDep2023 joined to commute origins; aggregate decile 8–10 origin objective added | available | Distributional subgroup view, not a causal equity effect or welfare weight; raw polygons are not exported |
| Strategic and programme context | Future Connect and RLTP active-mode snapshots added with source status retained | available | Future Connect is strategic; RLTP `committed` is not called funded |
| Cycle counters | Exact AT July 2026 workbook joined to 73 reviewed approximate sites | available | Spatial plausibility only; no direction, bearing or screenline identity; not predictive validation |
| Safety | Cycle-involved CAS records aggregated to 500 m NZTM cells; cells below three suppressed | available | Police-reported counts are not exposure-adjusted; microdata, exact points, identifiers and narratives remain excluded |
| Appraisal | MBCM v1.7.5-aligned lifecycle and uncertainty outputs exposed for the declared evidence scenario | research-only | Indicative BCR, not a business-case BCR; local costs, maintenance, renewals and benefit inputs require review before decision use |
| Terrain integrity | Every VRT-referenced LINZ raster pinned by byte count and SHA-256 | available | The 8 m contour-interpolated DEM is a coarse hilliness input and is not treated as precision terrain evidence |
| Source provenance | Twenty configured sources mapped to explicit include, omit or restricted decisions | available | Restricted CAS microdata remains outside all public assets |
| Low-stress connectivity | No Auckland full-network value exported | intentionally deferred | Reserved for the separate sabbatical research integration |

## Immutable prepared inputs

| Prepared input | Count or period | SHA-256 |
| --- | ---: | --- |
| AT GTFS snapshot | 22 August–31 December 2026 feed coverage | `61e325ae455703b92748b9a54745b63c516ab68e59464d19377aed5e924d4644` |
| Major transit nodes | 199 | `319240f6cd44195ec8e631f2b7e956c357e5746e698f08e9dc76d1305428c343` |
| Approximate counter sites | 73 | `15312afd9ccaa997982347d81d21b80891eac3f13acd5d950db029d8be5d4328` |
| Counter observations | 1–31 July 2026 | `6ce1d863487b65bdbf688dfcf4eb29f9b17a638c99493d45a8dfa9ab51c14302` |
| Auckland SA1/NZDep snapshot | 10,355 features | `de7ddb509f56931447a448fac5283cd404285d8e27edc65c009fbd7b466c1dc2` |
| Future Connect snapshot | 2,005 features | `7a0f1bda3a862067033764f73117637094c0de4678796c34079a1f68d8b072bf` |
| RLTP active-mode snapshot | 12 features | `325b9aac3cd3f0cef96f8b0fce604f8c3033f7786b4e4a664b1fb36ac31ecc82` |
| Disclosure-safe crash grid | 250 published cells | `92fce96fd83d063a645ef041dd1a42653c2bc9de6cee1793f87a22fc33159078` |
| LINZ terrain manifest | 32 raster tiles | `1f06ad57623fd6489bf1ee7437f03531123b4f74872ad92b068aaaf745d921ed` |

The clean production build completed as `run-313e0277521633d3`: 780,429
prepared trip-purpose records, 42,708 selected routing records, 42,551 assigned,
157 retained failures, 131,316 plausible paths, 12,580 candidates, and 191,539
exact candidate-edge rows. The web manifest SHA-256 is
`8166ea14b64b6ca36410c4915ffbd66f8c7568db777a8923bb54f918d0a95d40`;
the deterministic local archive SHA-256 is
`544f920eff526aecaf03176eadceaa5ec42c3dafbe4fd614ce883d6ccc7816b8`.
All seven screenshot states and their 21 image hashes are recorded in
[`../screenshots/manifest.csv`](../screenshots/manifest.csv).
