# Release readiness

This is the local pre-publication dossier for version 0.1. A checked item means
the evidence exists in this project; it does not mean the task is merely
planned. A complete Auckland raw-to-web research snapshot and a separate
deterministic synthetic fixture now exist. The Auckland snapshot is suitable
for software and method review, but it is not yet decision-ready or cleared for
public release.

The concise evidence index and separate approval sequence are in
[`release-dossier.md`](release-dossier.md). Test status is recorded in
[`test-evidence.md`](test-evidence.md), and the completed-run evidence and
remaining gaps are recorded in
[`run-manifest-evidence.md`](run-manifest-evidence.md).

## Source-resolution update — 1 September 2026

The prepared source set now resolves the earlier public gaps for AT GTFS and
major transit nodes, NZDep aggregate equity metrics, Future Connect, RLTP,
cycle-counter context, disclosure-safe safety context and research-only
appraisal. Raw CAS records remain restricted and excluded. See
[`source-gap-resolution-2026-09-01.md`](source-gap-resolution-2026-09-01.md).

Full-network CIW OD low-stress connectivity is the sole deliberately deferred
result. It is reserved for integration with Steve Gehrke's sabbatical research,
and the application reports no Auckland point estimate. Clean production run
`run-313e0277521633d3` and all seven replacement screenshots are complete; a
separately approved remote release is still required to replace the public
snapshot.

## Evidence present

- [x] Standalone project boundary and explicit external data root.
- [x] Distinct synthetic-fixture and Auckland research-snapshot status, with an
  appropriate-use boundary in the README and method.
- [x] Versioned configuration, run-manifest, source-registry, and web-export
  schemas.
- [x] Method, parameter register, data dictionary, validation protocol,
  uncertainty framework, limitations, indexed equations, white-paper outline,
  claims/evidence plan, figure/table plan, and venue mapping.
- [x] DOI- or publisher-verified bibliography and an evidence matrix that
  separates supported claims from limitations.
- [x] Five redistributable scholarly PDFs with licence evidence, byte counts,
  and SHA-256 checksums; subscription and licence-unclear works are metadata
  only.
- [x] Separate software, data, map, and publication rights statements.
- [x] Machine-readable rights decisions for all 20 configured Auckland sources
  and every proposed public layer, with unknown/restricted inputs fail-closed.
- [x] Stable command surface for data acquisition, run, validation, web export,
  and deterministic demo.
- [x] Seven checksummed Auckland screenshot states from
  `run-313e0277521633d3`, including the README hero, Pareto frontier, candidate
  evidence, aggregate equity portfolio, programme/counter/safety overlays,
  graph-snapped corridor, and responsive view.

## Required before a public release

- [x] Complete one Auckland raw-to-web research run from immutable,
  checksummed sources. Run `run-313e0277521633d3` succeeded through all nine
  stages; unchanged upstream stages were restored only after content-hash
  verification. Pending public-layer rights remain a separate release gate.
- [x] Pass the corrected journey-to-work demand gate: preserve total-stated and
  bicycle suppression separately; retain the currently observed 28,168
  bicycle-suppressed and 5,453 eligible-total-suppressed Auckland-origin cells;
  sample only joint pairs with bicycle ≤ total stated; keep
  outbound, unresolved-scope, unsnapped, and unreachable records in ledgers;
  and do not hard-balance the approximately 610,101 published internal OD trips
  plus suppression/structural omissions to the differently scoped 874,065
  full-origin margin; distinguish rows removed because total population is below
  six and records omitted because workplace SA2 is unavailable from explicit
  `-999` cells and numeric zero; and report their mass as unresolved coverage
  rather than inventing OD pairs. The run retains 28,168 bicycle-suppressed and
  5,453 eligible-total-suppressed cells.
- [x] Generate separate Auckland commute, school, everyday, and transit markets
  and route them with purpose-specific weights. The preparation stage retains
  569 open schools, 21,463 everyday destinations, and 336 transit destinations;
  the route manifest reports coverage and units separately by purpose. These
  remain modelled markets, not observed trip counts.
- [x] Demonstrate that all production stages execute the substantive methods,
  retain every OD failure, and emit the canonical research outputs. The run
  retains 157 routing failures and the supporting source, demand, route,
  candidate, portfolio, appraisal, uncertainty, and web ledgers.
- [x] Bound the counter evidence to a defensible spatial plausibility check.
  The exact July 2026 AT workbook, explicit 73-site mapping, ten exclusions,
  100 m spatial-coverage gate, and farthest-site review are complete. Regression,
  calibration, error, association, and null-model statistics are not calculated
  because daily all-purpose movements are not comparable with census
  usual-commute people and direction/screenline identity remains unresolved.
- [ ] Complete the remaining stratified visual map audit. Machine checks now
  cover every candidate exact edge, all facility-match bounds, topology
  endpoints and coincident-node identity, all paths at detour ratio ≥ 1.49, all
  paths for ODs snapped ≥ 1,500 m, and the farthest counter matches; geographic
  visual review of route/facility/crossing strata remains open.
- [x] Separate research-only appraisal from decision-use appraisal. The
  prepared public export exposes indicative candidate BCR intervals only for
  the declared evidence scenario and carries the local-cost, maintenance,
  renewal, residual, health, e-bike, price-base and demand-response warning.
  Those inputs and prescribed sensitivities remain mandatory before decision
  use; candidate BCRs are not summed into a programme BCR.
- [ ] Review and accept the implemented uncertainty design across confidentiality, PCT,
  route choice, stress, topology, capital cost, maintenance, benefit,
  discounting, e-bike share, and response. The current deterministic
  1,000-draw Latin-hypercube ensemble reports intervals and frontier stability,
  but expert prior review, convergence evidence, and rank-acceptability rules
  remain open.
- [ ] Complete amd64 container reproduction. An isolated staged-tree checkout
  and digest-pinned Linux arm64 image install the retained locks and pass the
  declared Python, JDK, R5, GDAL, osmium, frontend, offline configuration, and
  embedded rebuild checks below an 8 GiB VM ceiling. Before publishing an
  image, preserve dependency notices and satisfy corresponding-source
  obligations for the redistributed GPL-3.0 `osmium-tool` binary.
- [x] Resolve the prepared browser snapshot's public layer decisions. Cells,
  network, candidates, programmes, approximate counters and disclosure-safe
  safety context have exact source decisions. Transit and aggregate equity
  metrics are enabled. Restricted CAS rows remain outside the asset.
- [x] Complete the independent-method provenance and source-similarity review
  for the current implementation. The review records exact source hashes,
  locked-dependency/import results, normalised comparison statistics, licence
  boundaries, and mandatory repeat conditions without making a legal claim.
- [x] Capture all seven screenshot states from the validated Auckland research
  export. The manifest records run ID, scenario, purpose, viewport, capture
  time, offline/local-layer state, captions, alt text, and all 21 hashes. These
  are labelled research snapshots rather than release or decision evidence.
- [x] Pass the complete Python, schema, frontend, browser, keyboard,
  accessibility, hostile-string, console-error, responsive-layout, Docker, and
  Auckland regression suites in the isolated local release environment. The
  current tree passes 188 Python tests,
  Ruff format/lint, package build,
  configuration validation, 15 frontend unit tests, type/lint/build, 15
  applicable Playwright cases, axe checks, seven full-Auckland browser states,
  and deterministic asset verification. Hosted Linux/x64 run 33273402742 passed
  the preceding release head; repeat hosted checks on the final pull-request
  head and tag candidate.
- [x] Produce the local publication-candidate run manifest containing runtime/model versions,
  implementation checksum, seeds, stage fingerprints, input/output hashes, row
  and failure counts, routing
  coverage, timings, and schema versions; verify every artifact checksum. The
  current run records these fields and its nested route manifest records R5.
  The eventual tagged run must still record a non-null source revision and
  duplicate the nested R5 release in the root runtime summary.
- [ ] Publish the deterministic replacement web-data asset and produce a Pages
  preview, then complete the separately authorised commit, push, review, merge,
  tag, release, deployment, domain, HTTPS, download, and rollback gates. The
  local 23,646,468-byte archive has SHA-256
  `544f920eff526aecaf03176eadceaa5ec42c3dafbe4fd614ce883d6ccc7816b8`.

## Documentation integrity checks

Local audit updated 30 August 2026:

| Check | Result |
| --- | --- |
| Markdown local targets | 45 local targets across 37 candidate-public Markdown files; zero unresolved targets in the exact staged-tree recheck |
| External documentation inventory | 87 unique URLs: 86 ordinary links plus one deliberately disabled CARTO tile template. The last complete live audit, before 12 later authoritative-source links were added, covered 75 URLs: 58 returned HTTP 200, 16 publisher endpoints returned automated-access HTTP 403 only after a valid DOI/authoritative redirect, one was the disabled template, and there were zero 404, DNS, or timeout failures. A live recheck of the current 87-link set remains required |
| DOI resolution | 23 unique DOI identifiers; the last live DOI audit returned 16 HTTP 200 and seven valid publisher redirects followed by automated-access HTTP 403; no unresolved or duplicate DOI identifier |
| Bibliography / evidence coverage | 34 unique BibTeX keys, 34 exactly matching evidence-matrix rows, five open-file records, and 29 restricted or metadata-only acquisition records; the two sets partition the bibliography with no omission or overlap |
| Structured metadata | CFF parsed successfully with all required CFF 1.2.0 fields; the rights register has 33 data rows × 15 columns, including 20 configured sources, and passes the current configuration validator |
| Public-layer rights | 33 unique asset decisions: 30 permit and three exclude; all 20 configured sources are mapped exactly, with restricted CAS microdata omitted and no missing or conflicting dependency reference |
| Equation fragments | 54 unique labels across 12 LaTeX fragments; braces and nested environments balanced |
| Open publications | five readable, unencrypted PDFs; verified licence text, titles/authors/pages, first/last-page rendering, byte counts, and SHA-256 hashes |
| Screenshot evidence | seven complete offline/local-layer-only Auckland research-snapshot states; seven 1800×1100 PNG masters, seven optimised WebP copies, seven thumbnails, run ID, capture timestamp, declared limitations, and all 21 SHA-256 hashes recorded |
| Candidate public text | 144 scoped public text/config files; zero personal absolute-path, credential-pattern, private-key-header, high-confidence token, internal-development marker, or prohibited tool-provenance phrase matches in the exact staged-tree recheck |

An automated-access 403 is not treated as content verification. The DOI or
official record was checked separately, and the evidence matrix states the
verification basis. The present URL inventory is structurally complete, but
its current full live recheck is still open. Repeat every network check because
publisher URLs and access policies can change.

Run these checks again on the exact staged file set and complete Git history
immediately before the first public tag:

- [x] Candidate public text contains no personal absolute filesystem path,
  credential pattern, private key header, or internal development-tool marker.
- [x] Markdown local links resolve, and the embedded hero resolves to the
  checksummed WebP recorded in the Auckland screenshot manifest.
- [x] `CITATION.cff`, CSV files, BibTeX entry structure, DOI uniqueness, and
  LaTeX equation labels pass local structural checks.
- [x] The five open-reference files match the published byte counts and SHA-256
  checksums in `references/open/README.md`.
- [ ] Repeat the scans over the exact staged set and complete history after the
  repository exists; the current filesystem scan cannot audit future history.

No remote publication or domain change is authorised by this dossier.
