# Data and publication licence checklist

The MIT License applies to this software, not automatically to datasets, map
tiles, screenshots, derived databases, or article PDFs. The release manager
must complete this checklist for each tagged release.

The auditable decision register is
[`documentation/audit/public-layer-rights.csv`](documentation/audit/public-layer-rights.csv).
Its decisions have the following release meaning:

- `permit` + `include`: authoritative terms support the stated use, subject to
  the listed attribution and conditions;
- `exclude` + `omit` or `disable`: the public build must not contain or request
  the asset; and
- `pending` + `block`: the asset cannot enter a public export until its exact
  source, licence, snapshot, and attribution are reviewed and the register is
  updated.

The exporter must fail closed. An included layer that cites a source marked
`unknown` or `restricted`, a missing source decision, or a decision that
disagrees with the configuration is an error. An optional unresolved source may
remain in the registry only when no exported layer references it and every
dependent public control is omitted or disabled. A layer deliberately recorded
as `exclude` may be omitted without blocking an otherwise cleared export, but
its public control must also be disabled.

| Material | Typical rights position | Public-repository action |
| --- | --- | --- |
| OpenStreetMap-derived network | ODbL 1.0; attribution and database obligations apply | Retain contributor attribution, describe transformations, and assess whether a distributed derived database must be offered under ODbL |
| Stats NZ data | Product-specific open-data licence and statistical-use conditions | Record the exact product licence; preserve attribution and confidentiality statements |
| LINZ layers | Usually Creative Commons Attribution 4.0, but layer terms control | Cite the layer and LINZ; record the layer licence and snapshot |
| Auckland Council / Auckland Transport data | Dataset-specific terms | Do not assume open redistribution; link or provide a downloader when terms are unclear |
| GTFS | Feed-specific terms | Record the feed terms and snapshot; exclude raw feed if redistribution is not granted |
| Cycle counters | Dataset/API-specific terms | Publish only when the source terms allow redistribution |
| Crash data | Access and redistribution constraints may apply | Do not publish restricted microdata; document aggregation and disclosure controls |
| Basemap tiles | Usually display-only under provider terms | Never commit tile caches; retain visible attribution in screenshots |
| Journal articles | Publisher/repository licence controls | Store only copies with an explicit redistribution licence; otherwise store citation metadata only |
| Derived screenshots | Combine software, data, and basemap rights | Include visible map attribution and verify every displayed layer permits publication |
| GitHub Release / Pages data snapshot | Every included layer retains its source rights | Publish a checksummed per-layer rights manifest; exclude restricted or unclear layers and disable their public controls |

## Verified Auckland source position

Primary publisher records were reviewed on 20 August 2026. This is a scoped
release decision, not a general legal opinion.

- Stats NZ Datafinder table 121988, API version 410594, is the exact
  journey-to-work source and states CC BY 4.0; the retained local file is
  hashed. Its product metadata also controls interpretation: rows with total
  population below six are removed, and only records with workplace address
  available at SA2 are included.
- The exact Stats NZ SA1 population, SA2 geography, Auckland territorial-
  authority boundary, SA2 transport-margin, and 2024 Business Demography items
  state CC BY 4.0. The former mixed Eagle/NZDep service is no longer a required
  input.
- NZDep2023 is a separate optional source. The University of Otago page
  directly publishes the SA1 text/Excel files, and the associated research
  report states CC BY 4.0, but the dataset page does not tie that licence to the
  downloadable data. The exact dataset therefore remains pending; public
  equity data and controls stay disabled until a dataset-specific grant and
  release hash are recorded.
- The Ministry of Education catalogue record for the Schools Directory states
  CC BY 4.0. Only institution identifiers, names, types, locations, status,
  roll date, and total roll are acquired; telephone, email, postal-address,
  website, and named-contact fields are excluded.
- OpenStreetMap data may be used under ODbL 1.0. Public maps must visibly credit
  OpenStreetMap, and any distributed database or produced work must satisfy the
  applicable attribution, share-alike, and reconstruction-offer obligations.
- The exact Auckland Transport Cycle Facility Network item states CC BY 4.0.
  The Future Connect service and local RLTP-derived file do not carry
  sufficiently specific dataset terms and remain pending.
- Auckland Transport's monthly cycle-monitoring page states CC BY 4.0. The
  exact July 2026 workbook, 31-day period, workbook hash, deterministic
  transformation, and derived-observation hash are now recorded. Those
  observations are cleared, but the separately inherited counter-coordinate
  registry lacks exact publisher-file, direction, and screenline lineage; the
  point layer therefore remains local and the public counter layer remains
  empty.
- The NZTA CAS Map item states CC BY 4.0, but the configured large CSV lacks its
  exact portal item and export record. Raw crash rows and identifiers are
  excluded; only disclosure-reviewed aggregates may be reconsidered.
- The exact LINZ 8 m DEM page is CC BY 4.0 and requires LINZ Data Service
  attribution. The external schema-1 tile manifest now pins byte counts and
  SHA-256 hashes for all 32 TIFFs referenced by the VRT. LINZ also describes this
  contour-interpolated product as unsuitable for terrain analysis; a
  publication build must replace it or justify and test that use.
- The official AT GTFS page states CC BY 4.0. The configured derived transit
  node file remains pending until the archived feed's retrieval date, service
  dates, and hash are recorded.
- OpenFreeMap's public vector-tile service is permitted for live contextual
  display under its public-instance terms. The Light and Streets choices must
  retain visible OpenFreeMap, OpenMapTiles, and OpenStreetMap attribution. No
  tiles may be cached, prefetched, bundled, or treated as part of the release
  data. Analysis remains the tile-free fallback and the required mode for
  deterministic release captures.
- CARTO hosted basemaps remain disabled. CARTO's current terms require an
  enterprise licence for commercial use or an approved grant for qualifying
  non-commercial use; neither is recorded for this project.

## Release gate

- [ ] Every bundled file appears in the build manifest with licence evidence.
- [ ] No API key, access token, personal path, restricted microdata, or cached map
      tile is tracked.
- [ ] OpenStreetMap attribution is visible wherever OSM-derived geometry or a
      compliant basemap is displayed.
- [ ] Publisher attributions survive exports and appear on or immediately
      beside screenshots.
- [ ] Data that cannot be redistributed has a documented acquisition path and
      is covered by ignore rules.
- [ ] Article PDFs in `documentation/references/open` have an explicit open
      licence recorded beside their checksum.
- [ ] `documentation/references/restricted` contains metadata only.
- [ ] The release asset and browser manifest expose only layers whose public
      redistribution and display terms are verified.
- [ ] Every included layer cites only `permit` + `include` records in the
      machine-readable rights register; excluded controls are absent or
      disabled and pending sources cause a hard failure.
- [ ] Code licensing and data/database licensing are stated separately in the
      release notes and downloadable asset.
- [ ] Screenshots have seven populated metadata/checksum records and display
      attribution for every visible map/data provider.

An entry marked `redistribution: permitted` in configuration is not sufficient
evidence by itself. The release dossier retains the provider's licence text or
authoritative licence URL, snapshot date, attribution wording, and a reviewer
decision for the exact file distributed.
