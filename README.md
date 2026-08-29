# Auckland Cycling Investment Workbench

The Auckland Cycling Investment Workbench is a transparent, regional-scale
screening tool for exploring where connected, low-stress cycling investments
could unlock the greatest public value. It combines scenario demand, a
direction-aware street and path network, candidate-corridor testing, network
connectivity, distributional context, and screening economics in an
interactive map.

The workbench supports early option development. It does **not** replace site
investigation, consultation, detailed design, safety audit, demand forecasting,
or a formal business case.

> **Release status:** a complete local Auckland raw-to-web research snapshot
> succeeded as run `run-224e9baa3be4ef73`. A sanitized, deterministic public
> asset and the source tree are local release candidates; neither has been
> committed or published. The snapshot is not a decision-ready investment
> result. Comparable predictive validation, full-network low-stress rerouting,
> local appraisal evidence, and geographic audit remain explicit limitations.
> The repository continues to ship the deterministic miniature city as its
> default test data; the 308.6 MB Auckland browser snapshot remains outside Git.

## What it provides

- Standard PCT distance and hilliness scenarios, plus an explicitly named 8%
  commute-cycling sensitivity that is not presented as an adopted target.
- Routing on source-identified, direction- and layer-aware network topology.
- Low-stress and detour attributes for the retained plausible-path market; the
  full-network OD low-stress connectivity share is withheld pending rerouting.
- Corridor counterfactuals that reweight the retained plausible route set after
  exact-edge treatment.
- Cumulative recomputation over overlapping retained OD choice sets, a multi-objective Pareto
  frontier, and named transparent priority presets.
- Equity, safety, everyday-access, school-access, and public-transport context.
- Reproducible parameters, validation diagnostics, uncertainty labels, and a
  machine-readable evidence register.
- A guided three-step interface with searchable portfolios, shareable views,
  exact-selection exports, progressive advanced controls, keyboard access, and
  responsive map/result navigation.

## Tool in action

![Auckland Cycling Investment Workbench showing the 8% commute sensitivity, model indicators, regional candidate map, and a cumulative 100 million dollar portfolio.](documentation/screenshots/web/workbench-overview.webp)

This checksummed capture comes from the completed Auckland research snapshot,
run `run-224e9baa3be4ef73`. It is an indicative screening result, not an
investment recommendation or business case. Public appraisal values are
withheld until their release inputs pass expert review. The lossless master and six
additional views—including trade-offs, candidate evidence, declared rights
withholdings, graph-snapped corridor export, and mobile layout—are retained in
the [`documentation/screenshots`](documentation/screenshots) record.

The local run retained 780,060 disaggregated purpose records, routed 42,498 of
42,654 selected records, generated 12,578 exact-edge candidates, evaluated
3,771 cumulative portfolio steps, and produced a 1,000-draw Latin-hypercube
uncertainty ensemble. The route artifact records 99.6% estimated commute
routing coverage over the attempted market. These figures describe pipeline
coverage and output scale; they do not validate behavioural accuracy.

## Reproduce a build

The release pins Python 3.11 and Node.js 24 LTS. From a clean checkout with
`uv` and Node installed:

```sh
uv sync --locked --all-extras
uv run pytest
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
```

For an isolated runtime, build the pinned Docker image:

```sh
docker build --tag auckland-cycling-investment-workbench:local .
docker run --rm auckland-cycling-investment-workbench:local --help
```

The command-line interface and Auckland configuration are the authoritative
source for build commands and required inputs:

```sh
uv run ciw data fetch --config configs/auckland.yml --data-root /path/to/ciw-data
uv run ciw data prepare-at-counters --config configs/auckland.yml --data-root /path/to/ciw-data --workbook /path/to/at-cycle-counts.xlsx --coordinate-registry /path/to/reviewed-counter-points.json
uv run ciw run --config configs/auckland.yml --data-root /path/to/ciw-data
uv run ciw validate --config configs/auckland.yml --data-root /path/to/ciw-data --run <run-id>
uv run ciw export-web --config configs/auckland.yml --data-root /path/to/ciw-data --run <run-id>
uv run ciw demo --export-web
```

`ciw demo` uses a deterministic miniature city and is suitable for interface
and integration testing only. It is not Auckland evidence. A production run
must use a data root outside the checkout and must pass validation before its
web export is treated as a release artifact.

## Versioned outputs

A completed run records its configuration snapshot, input inventory, runtime
versions, seeds, stage fingerprints, timings, row and failure counts, and
checksums in `runs/<run-id>/manifest.json`. The analytical outputs include the
complete OD/path ledger, routable edges and stress components, exact-edge candidates,
scenario and purpose metrics, cumulative portfolio and Pareto results,
appraisal and uncertainty summaries, validation diagnostics, failure ledgers,
and a checksummed lazy-load manifest for browser layers. Availability depends
on the completed pipeline stages, evidence gates, and rights attached to each
input. A public research snapshot suppresses unreviewed BCR fields in the asset
itself and disables the Appraisal lens rather than relying on presentation-only
hiding.

Source datasets are not silently bundled. Obtain them from their publishers,
record the snapshot and licence, then provide their paths through a versioned
configuration. Start with [`DATA_SOURCES.md`](DATA_SOURCES.md),
[`DATA_LICENSES.md`](DATA_LICENSES.md), and the
[`documentation/methodology`](documentation/methodology) specifications. The
machine-readable
[`public-layer-rights.csv`](documentation/audit/public-layer-rights.csv)
records the current include, omit, and block decision for every configured
Auckland source and proposed public layer. Public export fails closed when a
selected layer cites a source that is unknown, restricted, missing from that
decision chain, or attached to an incompatible layer decision. Optional
unresolved sources can remain configured only when their data and UI controls
are absent from the export.

## Interpret results carefully

All project costs, benefits, targets, and behavioural responses are assumptions
for screening unless a release manifest says otherwise. In particular:

- the 8% commute-cycling share is a configurable modelling sensitivity, not a
  verbatim TERP target or a direct crosswalk from TERP's all-trip denominator;
- disclosure control applies to eligible total-stated OD cells as well as
  bicycle cells, and the differently scoped full-origin SA2 margin is only soft
  validation evidence unless its universe is reconciled exactly;
- the commute source excludes low-count OD rows and people without workplace
  SA2, so absent pairs are unresolved coverage—not observed zero or invented
  destinations;
- regional routing uses a declared, seeded within-zonal-OD probability sample
  with exact inverse-probability weights; every sampled and unsampled spatial
  demand record remains in the OD ledger, so this computation control is not a
  hidden truncation;
- monetary values must be refreshed against the applicable Waka Kotahi
  Monetised Benefits and Costs Manual and local project-cost evidence;
- parameter ranges and scenario ensembles express declared epistemic
  uncertainty, not a complete predictive probability distribution; and
- the July 2026 AT counter ledger verifies only spatial proximity to the graph;
  its all-purpose daily movements are not regressed against or used to calibrate
  census usual-commute people; and
- Pareto and preset portfolio views expose trade-offs but do not prove a
  globally optimal investment programme.

## Documentation

The [`documentation`](documentation) directory contains the method,
parameters, data dictionary, validation protocol, uncertainty and limitation
statements, equations, white-paper plan, evidence matrix, and release audit.
The bibliography uses DOI-resolved publication metadata. Open-access articles
are retained only where redistribution terms permit it; restricted works are
represented by citations and acquisition notes only.

## Licence and citation

Software is released under the [MIT License](LICENSE).
Dataset and publication rights remain with their respective providers; see
[`NOTICE.md`](NOTICE.md) and [`DATA_LICENSES.md`](DATA_LICENSES.md).
Citation metadata is supplied in [`CITATION.cff`](CITATION.cff).
The citation file intentionally has no repository URL, release date, or
deployed-site URL until the repository, first public tag, and replacement site
have passed their approval gates.
