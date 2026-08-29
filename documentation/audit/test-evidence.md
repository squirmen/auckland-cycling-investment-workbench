# Test and integrity evidence

This record separates checks that have actually run from the larger release
test matrix. Results are local evidence for the file state described below;
they do not substitute for a clean checkout, CI, container reproduction, or an
Auckland regression run.

## Current recorded checks

| Check | Result | Release interpretation |
| --- | --- | --- |
| Locked Python suite, 2026-08-29 | Python 3.11.16; 176 tests passed | Current-tree local evidence including counter-source, fail-closed appraisal, and deterministic-release-asset tests; repeat in clean CI and container |
| Python quality checks, 2026-08-29 | Ruff format check and lint passed across the complete Python source/test tree | Current-tree local evidence |
| Python package build, 2026-08-24 | Locked build produced both `auckland_cycling_investment_workbench-0.1.0.tar.gz` and a `py3-none-any` wheel in an external temporary directory | Installable-package evidence; repeat from a clean checkout in CI |
| Frontend static and unit checks, 2026-08-29 | ESLint and TypeScript `--noEmit` passed; 15 Vitest assertions passed; Vite production build completed with a 246.27 kB JavaScript bundle (69.71 kB gzip) | Exact Node 24 evidence remains the container/CI gate |
| Browser and accessibility suite, 2026-08-29 | Playwright ran 22 project/test combinations: 13 passed and nine intentional cross-project scope skips; desktop and mobile axe scans reported zero violations; all seven documented states had no console, page, or external-request errors | Local Chromium evidence from the locked frontend dependencies; rerun in CI |
| Deterministic miniature-city pipeline, 2026-08-24 | Run `run-0fcc30c0181f013c` executed all nine stages, then resumed all nine without execution; `ciw validate --web` reported zero errors and zero warnings; web manifest SHA-256 `8caf72988edca9d32f515de7f4cce668e123c3f97fa6550a555b47dfc430d385` | Valid synthetic raw-to-web integration evidence, not Auckland evidence |
| Auckland live browser review, 2026-08-29 | The sanitized 308.6 MB export loaded at desktop and 390×844 responsive viewports; scenario, purpose, budget, Pareto, candidate evidence, exact-edge network, withheld appraisal/equity/overlays, and graph-snapped corridor states were exercised with zero browser warnings or errors | Local interactive evidence for run `run-224e9baa3be4ef73`; repeat in automated clean-browser CI against the pinned release asset |
| Screenshot integrity, 2026-08-29 | Seven 1800×1100 lossless PNG masters, seven optimised WebP copies, and seven 600×367 thumbnails were inspected; all 21 hashes, state fields, run ID, and capture timestamp are recorded | Complete for the Auckland research snapshot; appraisal, equity, and overlay withholdings remain explicit |
| Configuration-only validation | `Validation: OK` after the documented Auckland source-contract and confidentiality corrections | Repeat after the source/export tree is frozen |
| Predecessor Auckland source/topology/demand evidence, 2026-08-24 | All 13 available inputs passed offline hashes; corrected topology completed in 243.04 s with 867,348 source-identity nodes and 899,155 physical edges; demand completed in 39.75 s with 28,272 zonal ODs and 695,492 weighted commute records; three unsupported-destination records representing 669 eligible trips remain explicit coverage failures | Historical full-scale stage evidence now superseded by the successful raw-to-web run; retained for timing and resolution provenance |
| Predecessor R5/exact-edge regional smoke, 2026-08-24 | Pinned R5/r5py/JDK loaded the bounded PBF; a dispersed deterministic 100-OD sample assigned 99, retained one explicit component failure, produced 346 paths and 348,477 exact path-edge rows, verified Parquet round-trips, and routed in 74.73 s after 61.22 s engine startup | Historical adapter evidence now superseded by the complete exact-edge routing artifact; retained as a focused diagnostic benchmark |
| Corrected Auckland raw-to-web run, 2026-08-27 | Run `run-224e9baa3be4ef73` succeeded; cached verified route/candidate artifacts plus executed portfolio, appraisal/uncertainty/validation, output, and web stages produced 42,498 assigned sampled ODs, 12,578 candidates, 3,771 portfolio steps, 12,309,000 uncertainty rows, and 308,957,404 web bytes | Immutable research-snapshot evidence. Current validation correctly reports an implementation mismatch after the 2026-08-28 source corrections; the snapshot is not mislabelled as a current-code rerun |
| Auckland artifact and counter audits, 2026-08-28 | All 12,578 candidates and 191,464 exact candidate-edge rows passed membership, terminal, continuity, length, bridge, and tunnel checks; 1,095 defined extreme route cases passed exact-edge continuity; 56,780 facility matches passed stored overlap/bearing bounds; all 73 retained counter sites fell within 100 m | Structural and extreme-case evidence; visual map sampling, purpose-compatible predictive counter validation, and full-network rerouting remain open |
| Exact staged documentation structure, 2026-08-30 | CFF valid; four CSV registries have consistent widths; 34 BibTeX keys exactly match 34 evidence rows; 54 equation labels are unique; 45 local Markdown targets resolve; all 21 screenshot hashes match | Passed against the final staged archive; live external-link policies remain separately time-sensitive |
| Exact staged publication scan, 2026-08-30 | 185 staged files; zero personal absolute paths, credential patterns, private-key headers, high-confidence token patterns, prohibited provenance phrases, unstaged changes, or files over 10 MB; `git diff --cached --check` passed; repository history is empty and no remote is configured | Passed for the pre-commit release candidate; repeat over the resulting commit and history before push |
| Reference PDFs | Five files readable and unencrypted; licence text, title/author/page evidence, first/last-page rendering, byte counts, and SHA-256 hashes verified | Repeat hashes over the exact staged set |
| Isolated staged-tree container, 2026-08-29 | Staged tree `7fbe94a1fa52cbc8acdf37cb0a1383a03c08b853`; digest-pinned arm64 image `sha256:e0c162a146e32e7517a8c015667d76b3f2ff1038aec8835b1d4af3c25316f5dd`, 566,049,220 bytes; embedded lint, type, 15 unit tests, production build, toolchain versions, configuration validation, R5 7.5.1 class load/checksum, licence-file verification, matching Python implementation digest, and a second in-image frontend build passed with networking disabled | Current isolated Linux arm64 reproduction evidence; repeat on CI/amd64 and close corresponding-source obligations before publishing a container image |
| Deterministic Auckland web asset, 2026-08-29 | Two packages produced an identical 18,921,866-byte archive and SHA-256 `1a6ba2b2bbe62b59e4f88934843d4c16c6758ab41f81d225b7e307f2ef3e45e5`; packaged candidate BCR fields are null and the Appraisal capability is withheld | Local immutable research-snapshot asset only; release attachment and Pages remain separately gated |

## Still required

- repeat the complete suite in hosted CI under its locked Node 24 environment;
- complete amd64 container reproduction and close corresponding-source
  obligations;
- close the declared full-network connectivity, purpose-compatible predictive
  counter validation, local-cost, uncertainty-prior, and visual-map audit gates
  identified by the Auckland snapshot; and
- repeat the publication scan over the resulting commit and complete history
  immediately before push.

The authoritative completion checklist remains
[`release-readiness.md`](release-readiness.md).
