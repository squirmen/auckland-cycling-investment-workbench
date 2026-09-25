# Local release dossier index

This index identifies the evidence that must be reviewed before any public
release. It is not a release approval. A complete local Auckland raw-to-web
research snapshot succeeded as run `run-313e0277521633d3`; the remaining
decision-use, manual-audit, container, and remote-publication gates remain
explicit. This run incorporates the 1 September source resolution and replaces
the older snapshot as the local evidence baseline.

## Review packet

| Evidence | Record | Current state |
| --- | --- | --- |
| Legacy and method resolution | [`audit-resolution-matrix.md`](audit-resolution-matrix.md) | Mixed: closed method decisions and explicit release gates |
| PCT implementation provenance | [`pct-provenance-review.md`](pct-provenance-review.md) | Current source hashes, dependency scan, and source-similarity scan recorded; repeat if code changes before a tag |
| Source and public-layer rights | [`public-layer-rights.csv`](public-layer-rights.csv) and [`../../DATA_LICENSES.md`](../../DATA_LICENSES.md) | 33 explicit decisions covering all 20 configured sources; restricted CAS microdata is omitted |
| Container reproduction | [`container-reproduction.md`](container-reproduction.md) | Isolated staged-tree arm64 build/runtime evidence passes; independent container amd64 and licence-obligation checks remain unmet |
| Tests and integrity scans | [`test-evidence.md`](test-evidence.md) | 188 Python tests, Python format/lint, frontend type/lint/unit/build, 15 applicable Playwright checks, exact schema validation, deterministic packaging, and seven full-Auckland browser states pass locally; repeat hosted checks on the eventual PR head |
| Interface and experience | [`ui-ux-review.md`](ui-ux-review.md) | Guided desktop/mobile workflow accepted locally; accessibility and interaction suites pass; formal user testing remains recommended |
| Auckland real-stage evidence | [`auckland-real-stage-evidence.md`](auckland-real-stage-evidence.md) and [`run-manifest-evidence.md`](run-manifest-evidence.md) | Source-resolution raw-to-web run succeeded; GTFS/transit, equity, programmes, counters, safety and research-only appraisal are present; low-stress connectivity remains deliberately unreported |
| Analytical artifact review | [`auckland-artifact-audit.md`](auckland-artifact-audit.md) and [`counter-plausibility-audit.md`](counter-plausibility-audit.md) | Exact candidate and defined extreme-route checks pass; counter evidence is spatial plausibility only; visual map audit remains open |
| Curated web-data asset | [`public-release-asset.md`](public-release-asset.md) | Deterministic local archive complete; no release or upload authorised |
| Screenshot record | [`../screenshots/manifest.csv`](../screenshots/manifest.csv) | Seven complete, checksummed source-resolution masters plus WebP copies and thumbnails; all available context is shown and low-stress connectivity is left blank |
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

- Run `run-313e0277521633d3` passed all nine configured stages and exact web
  validation with zero errors and zero warnings. Its 157 routing failures remain in the failure
  ledger, and its nested route manifest records R5 7.5.1-r5py, r5py 1.1.7,
  exact-edge reconciliation, sampling, coverage, and hashes.
- Full-network CIW OD low-stress connectivity is intentionally reserved for
  integration with Steve Gehrke's sabbatical research. The browser therefore
  displays no Auckland connectivity share and does not substitute an
  edge-attribute sum.
- NZDep aggregate equity metrics, Future Connect, RLTP, AT GTFS major nodes,
  approximate counter sites and a disclosure-safe safety grid are included.
  Counter evidence remains spatial plausibility, not calibration or predictive
  validation.
- The 1,000-draw uncertainty ensemble and indicative MBCM v1.7.5 screening BCRs
  are exposed as research-only for the declared evidence scenario. Local
  capital/maintenance/renewal evidence,
  price-base reconciliation, parameter-prior review, and geographic manual
  audits remain open for any future decision-use release.
- The 326,076,352-byte Auckland browser snapshot is packaged locally as a
  deterministic 23,646,468-byte archive with SHA-256
  `544f920eff526aecaf03176eadceaa5ec42c3dafbe4fd614ce883d6ccc7816b8`.
  Isolated Linux arm64 container checks
  pass; hosted Linux/x64 CI passes; independent container amd64,
  remaining ODbL/corresponding-source duties,
  and the separate stage,
  commit, push, PR, merge, tag, release, Pages, domain, and rollback approvals
  remain outstanding.
