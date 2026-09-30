# Bike parking

This folder holds SPAN's bike parking work. It is published at
[span.tfwelch.com/parking/](https://span.tfwelch.com/parking/).

## What is here

- `uoa/`: STAND (Secure Two-wheeler Access Network Design), the University of Auckland Locky Dock
  tool. STAND is a siting model and live map for secure public bike docks on the City, Grafton and
  Newmarket campuses, from the Better Places Lab. It keeps its own name, mark and tagline ("Where
  secure bike parking should stand") and uses SPAN's traffic-stress network. It is served at
  [span.tfwelch.com/parking/uoa/](https://span.tfwelch.com/parking/uoa/).
  [`uoa/README.md`](uoa/README.md) covers its method, data and commands.
- `index.html`: the page for `/parking/` itself. It says that the wider tool is planned and sends
  visitors on to STAND.
- `build/`: STAND's build output. It is git-ignored.

## The plan

A general bike parking tool for SPAN is planned. It will live at `/parking/` and be STAND's parent.
STAND will stay at `/parking/uoa/` as its University of Auckland part. Until the parent tool exists,
`/parking/` is a short page that points to STAND.

## Building and deploying /parking/

1. In `parking/uoa`, `make publish` rebuilds everything STAND ships (its README lists the inputs it
   needs). Its `make site` step writes the `/parking/` folder to `parking/build/site/`: this
   folder's `index.html`, and STAND in `uoa/` with its data, pages, `oembed.json` and `.htaccess`.
   The same files go in `parking/build/span-parking-site.zip`. The build stops if its privacy check
   finds private text.
2. At the repository root, `npm --prefix web run build` builds SPAN. When
   `parking/build/site/uoa/index.html` exists, the build copies `parking/build/site` into
   `web/dist/parking`, `.htaccess` included. Otherwise it builds SPAN alone and says so.
3. `scripts/package_span_site.py` packages `web/dist` for the server. When `web/dist/parking`
   exists, it first checks that the folder has its own page, STAND's map (with a title that starts
   with "STAND"), `uoa/.htaccess`, `uoa/data/results.json` and an `oembed.json` that embeds only
   pages under `https://span.tfwelch.com/parking/uoa/`. It refuses source files, private files and
   hidden files other than `.htaccess`. The release record lists STAND under `components`, with
   the time its data were built.

The package deploys SPAN and STAND together. To update STAND alone, extract
`parking/build/span-parking-site.zip` into the `parking/` folder of span.tfwelch.com. SPAN's
`.htaccess` at the site root applies there too, and `uoa/.htaccess` adds STAND's own settings.

SPAN's Python tests cover this folder as well: `tests/test_parking_access_rules.py` checks STAND's
Overture access rules, and `tests/test_span_site_package.py` checks how the parking folder is
packaged.
