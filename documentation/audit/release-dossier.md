# Local release dossier index

This index identifies the evidence that must be reviewed before any public
release. It is not a release approval. A complete local Auckland raw-to-web
research snapshot succeeded as run `run-224e9baa3be4ef73`; the remaining
method, validation, manual-audit, rights, container, and remote-publication
gates remain explicit.

## Review packet

| Evidence | Record | Current state |
| --- | --- | --- |
| Legacy and method resolution | [`audit-resolution-matrix.md`](audit-resolution-matrix.md) | Mixed: closed method decisions and explicit release gates |
| PCT implementation provenance | [`pct-provenance-review.md`](pct-provenance-review.md) | Current source hashes, dependency scan, and source-similarity scan recorded; repeat if code changes before a tag |
| Source and public-layer rights | [`public-layer-rights.csv`](public-layer-rights.csv) and [`../../DATA_LICENSES.md`](../../DATA_LICENSES.md) | 30 explicit decisions; pending sources/layers remain blocked or omitted |
| Container reproduction | [`container-reproduction.md`](container-reproduction.md) | Isolated staged-tree arm64 build/runtime evidence passes; CI/amd64 and licence-obligation checks remain unmet |
| Tests and integrity scans | [`test-evidence.md`](test-evidence.md) | Isolated locked installs, 185 Python tests with 80.27% branch coverage, Python format/lint/package build, frontend type/lint/unit/build, Playwright, production dependency audit, container, artifact audits, and live browser checks pass locally; CI/amd64 remains unmet |
| Interface and experience | [`ui-ux-review.md`](ui-ux-review.md) | Guided desktop/mobile workflow accepted locally; accessibility and interaction suites pass; formal user testing remains recommended |
| Auckland real-stage evidence | [`auckland-real-stage-evidence.md`](auckland-real-stage-evidence.md) and [`run-manifest-evidence.md`](run-manifest-evidence.md) | Corrected raw-to-web run succeeded; five unavailable optional inputs and the resulting validation/rights limitations remain declared |
| Analytical artifact review | [`auckland-artifact-audit.md`](auckland-artifact-audit.md) and [`counter-plausibility-audit.md`](counter-plausibility-audit.md) | Exact candidate and defined extreme-route checks pass; counter evidence is spatial plausibility only; visual map audit remains open |
| Curated web-data asset | [`public-release-asset.md`](public-release-asset.md) | Deterministic local archive complete; no release or upload authorised |
| Screenshot record | [`../screenshots/manifest.csv`](../screenshots/manifest.csv) | Seven complete, checksummed Auckland research-snapshot masters plus WebP copies and thumbnails; withheld layers are identified rather than simulated |
| Overall release gates | [`release-readiness.md`](release-readiness.md) | Local software release candidate; Auckland decision-use evidence remains deliberately incomplete |

## Approval sequence

Each action requires a separate, explicit maintainer approval. Approval of one
step does not authorise a later step:

1. approve the exact local staging set after reviewing this dossier;
2. approve the commit and its message;
3. approve the first remote push and branch target;
4. approve opening the draft pull request;
5. approve merging after required checks pass;
6. approve tag creation and the release assets;
7. approve Pages deployment;
8. approve the custom-domain and DNS switch only after preview verification;
9. approve retirement of the rollback deployment after HTTPS, downloads, and
   the public build are rechecked.

No item above is authorised by this document. The existing host remains the
rollback until the replacement has been separately accepted.

## Remaining Auckland evidence and release gates

- Run `run-224e9baa3be4ef73` passed all nine configured stages and artifact
  validation with zero errors. Its 156 routing failures remain in the failure
  ledger, and its nested route manifest records R5 7.5.1-r5py, r5py 1.1.7,
  exact-edge reconciliation, sampling, coverage, and hashes.
- Full-network CIW OD low-stress connectivity rerouting remains pending. The
  browser therefore displays no connectivity share and does not substitute an
  edge-attribute sum.
- Optional NZDep, Future Connect, and RLTP inputs are absent. Exact July 2026
  AT counter observations have been prepared and audited, but their unit and
  purpose do not match census usual-commute people; the result is spatial
  plausibility evidence, not calibration or predictive validation. Equity is
  disabled, and programme and public-counter layers are empty.
- The 1,000-draw uncertainty ensemble and indicative MBCM v1.7.5 screening BCRs
  execute in the immutable analytical run, but the public asset removes those
  values and disables Appraisal. Local capital/maintenance/renewal evidence,
  price-base reconciliation, parameter-prior review, and geographic manual
  audits remain open for any future decision-use release.
- The sanitized 308.6 MB Auckland browser snapshot is packaged locally as a
  deterministic 18,921,866-byte archive. Isolated Linux arm64 container checks
  pass; hosted CI/amd64, remaining ODbL/corresponding-source duties,
  and the separate stage,
  commit, push, PR, merge, tag, release, Pages, domain, and rollback approvals
  remain outstanding.
