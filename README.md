# Auckland Cycling Investment Workbench

Where might a new cycling connection make the biggest difference?

The Auckland Cycling Investment Workbench is an open research tool for
exploring that question. It brings demand scenarios, street-network conditions,
candidate routes and project sequencing into one interactive map.

[Open the workbench](https://squirmen.github.io/auckland-cycling-investment-workbench/)
· [Download v1.0.0](https://github.com/squirmen/auckland-cycling-investment-workbench/releases/tag/v1.0.0)
· [Read the method](documentation/methodology/methodology.md)

![The Auckland Cycling Investment Workbench showing the regional candidate map and a cumulative portfolio under the 8% commute sensitivity.](documentation/screenshots/web/workbench-overview.webp)

## What you can do

- Compare PCT cycling scenarios, including a separate 8% commute sensitivity.
- Explore candidate links by likely demand, network contribution and purpose.
- Build a portfolio to a chosen budget and see how each addition changes the
  result.
- Compare Network, School, Everyday, Transit, Equity and Appraisal views when
  the required evidence is available.
- Inspect the route and evidence behind a candidate rather than relying on a
  single composite score.
- Sketch a corridor on the routable graph and export the current selection as
  GeoJSON.
- Use the map on a desktop, tablet or phone, with keyboard-accessible controls.

The current Auckland snapshot contains 12,578 candidate links derived from
780,060 disaggregated trip-purpose records. Of the 42,654 records selected for
routing, 42,498 were routed successfully. These numbers describe the scope of
the run, not the accuracy of its forecasts.

## How it works

The analysis starts with census journey-to-work data and a cycling network built
from OpenStreetMap node and way identities. It keeps direction, access,
bridge, tunnel and layer information so that roads crossing at different
levels do not become false junctions.

Demand is assigned across plausible paths rather than a single shortest path.
Candidate projects are made from exact graph edges, then tested against the OD
markets that could use them. Portfolios are presented as trade-offs and named
planning views; the tool does not hide those choices inside a master score.

The methodology, equations and assumptions are documented in
[`documentation/methodology`](documentation/methodology) and
[`documentation/equations`](documentation/equations). The full OD/path ledger,
failure records, source inventory, parameters and checksums are retained with
each run.

## Try it locally

The small demonstration dataset is included in the repository. It exercises
the complete raw-to-web workflow without requiring the Auckland source files.
You will need Python 3.11, [`uv`](https://docs.astral.sh/uv/) and Node.js 24.

```sh
uv sync --locked --all-extras
uv run ciw demo --export-web
npm --prefix web ci
npm --prefix web run build
```

To run the checks used for a release:

```sh
uv run pytest
npm --prefix web test
npm --prefix web run lint
npm --prefix web run typecheck
```

The repository also includes a pinned Docker build for an isolated environment:

```sh
docker build --tag auckland-cycling-investment-workbench:local .
docker run --rm auckland-cycling-investment-workbench:local --help
```

## Run an Auckland build

Raw and licensed data stay outside the repository under a data root chosen by
the user. [`DATA_SOURCES.md`](DATA_SOURCES.md) lists the required files and
[`DATA_LICENSES.md`](DATA_LICENSES.md) records what may be redistributed.

```sh
uv run ciw data fetch --config configs/auckland.yml --data-root /path/to/ciw-data
uv run ciw run --config configs/auckland.yml --data-root /path/to/ciw-data
uv run ciw validate --config configs/auckland.yml --data-root /path/to/ciw-data --run <run-id>
uv run ciw export-web --config configs/auckland.yml --data-root /path/to/ciw-data --run <run-id>
```

Each run writes a manifest with its inputs, versions, random seeds, stage
fingerprints, timings, row counts, failures and output hashes. Interrupted
stages can be resumed without rerunning unaffected work.

## Reading the results

CIW is intended for research and early option development. It is not a list of
approved projects and it is not a substitute for consultation, site work,
detailed design, a safety audit or a business case.

A few current limitations matter in particular:

- The 8% commute share is a modelling sensitivity, not an Auckland Transport
  target or a restatement of TERP.
- The public `v1.0.0` snapshot leaves appraisal and equity results unavailable
  while their local evidence and redistribution checks remain open.
- Auckland cycle counters provide a spatial plausibility check; they do not yet
  provide like-for-like predictive validation of census commute demand.
- Portfolio views show useful trade-offs, but they do not prove a globally
  optimal investment programme.

The detailed limitations and validation record are in
[`documentation/methodology/limitations.md`](documentation/methodology/limitations.md)
and [`documentation/methodology/validation.md`](documentation/methodology/validation.md).

## Release and citation

The source code is released under the [MIT License](LICENSE). Data and
publication rights remain with their providers; see [`NOTICE.md`](NOTICE.md)
and [`DATA_LICENSES.md`](DATA_LICENSES.md).

If you use CIW in research, cite the software using [`CITATION.cff`](CITATION.cff)
and cite the underlying methods and datasets relevant to your analysis.
