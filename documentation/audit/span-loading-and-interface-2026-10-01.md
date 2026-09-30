# SPAN: loading speed and interface fixes

1 October 2026. Follow-up to
[staged loading and tighter search bounds](span-staged-loading-and-stress-bounds-2026-09-26.md).
Model values, rankings and data files are unchanged; every data file keeps its
SHA-256.

## What was wrong on the live site

Measured from Auckland on 30 September against the 24 September deployment:

- The page waited for `candidates.geojson`: 234 MB, sent as 14.0 MB of gzip.
  That download took 31–32 seconds. In one browser test it was cut off at 31
  seconds and the page showed "The data could not be loaded".
- The host sends about 0.5 MB a second to Auckland whatever the file. Two
  images of 2.7 and 2.9 MB arrived at 0.46 and 0.49 MB/s. A 13.4 MB file sent without
  compression arrived at 0.54 MB/s. Four downloads at once shared the same
  total, so the limit is per visitor, not per file. The same computer received
  5.5 MB/s from a content-delivery test file.

So the number of bytes before the first view is what decides how long a visitor
waits, and the server's own compression was not the bottleneck.

## Fewer bytes before the first view

| Before the first view | 24 September site | This release |
| --- | ---: | ---: |
| Manifest | 528 kB | 198 kB |
| Candidate links | 14.0 MB (all 12,580) | 1.31 MB (1,846) |
| Existing low-stress network | 2.46 MB | not waited for |
| Page, scripts and styles | about 0.1 MB | about 0.1 MB |
| Total | about 17 MB | about 1.6 MB |

Three changes make up the difference.

**The page opens on the links it needs.** See the 26 September note. This is
the first release to deploy it.

**Brotli copies made once, at packaging.** `scripts/package_span_site.py` adds a
`name.br` copy of each script, style and data file over 1 kB, compressed at the
highest setting. Each copy is decoded and compared with its source before the
archive is written, and is listed with its own SHA-256 in the release record.
`.htaccess` sends the copy to browsers that accept brotli, with the original
content type, and sends the original to the rest as before. The browser's
integrity check runs on the decoded bytes, so it is unchanged. The canonical
`candidates.geojson` gets no copy because the browser never requests it.

| File | gzip on request | Brotli copy |
| --- | ---: | ---: |
| `manifest.json` | 528 kB | 198 kB |
| `candidates.initial.json` | 1.87 MB | 1.31 MB |
| `candidates.compact.json` (all links) | 12.57 MB | 8.79 MB |
| `existing.geojson` | 2.46 MB | 1.69 MB |
| `network.geojson` | 10.30 MB | 7.45 MB |
| `access-experiment.json` | 704 kB | 68 kB |

**Context layers no longer hold up the page.** Only the links are waited for.
The existing network and any other visible layer load afterwards and are drawn
when they arrive. If one fails, its box is unticked, a message says why, and
the build order still works. Previously a failed required layer stopped the
whole page.

## When the connection fails

A dropped connection, or a 408, 429 or 5xx reply, is retried twice, after 1.5
and 3 seconds. A missing file or a failed integrity check is not retried. If
loading still fails, the panel says so and offers **Try again**.

Downloads of known size report progress: "Loading the links… 62%" while the
page opens, and "Loading all 12,580 links… 62%" for the full set. That message
stays until the download ends; it used to disappear after four seconds while
the download carried on.

The full set is still 8.8 MB, about 18 seconds on this host. Value for money
and Other proposals wait for it. A content-delivery network in front of the
host, or a faster host, is the remaining fix; nothing in the page can remove
that wait without changing what the views show.

## Interface faults fixed

- **Squeezed list rows.** Rows in the best-value list and the connected-groups
  list were shrunk to fit a 260-pixel scrolling box, so 40 rows overlapped.
  They keep their height and the box scrolls.
- **Connected journeys list.** The list held 169 entries named "Journey 1" to
  "Journey 169". Of those, 152 have no route within the limits. The list is now
  grouped under the chosen package: connected by it, needing upgrades outside
  it (with how many), connected without upgrades, and no route. The counts
  match the package totals for all twelve stored packages.
- **Regional view.** The existing network (27,286 streets) and the intersection
  sites were drawn at one weight at every zoom and hid the build order across
  the region. Both are lighter when zoomed out.
- **Shared links.** A link to one upgrade opened on the whole region. It opens
  on the upgrade.
- **Touching candidates.** Most neighbours of a build-order link are outside
  the 1,846 opening links, so the list would have been empty. Opening it loads
  the full set.
- **Print.** The map key was printed on top of the controls and the map showed
  an arbitrary crop. Print now has its own layout: the map in a fixed box,
  fitted to the build order or the selected upgrade, then the key, the panel
  and the link card.
- **Phones.** The full name fits in the header, the map credits take one line,
  and routes are fitted clear of the key and the credits.
- **Smaller things.** Each view opens at its top. The key for an unfunded gap
  is dashed, as on the map. With every layer on, the key scrolls. The opening
  sentence no longer changes once the data arrives. The About note on
  intersections says what the sites are.
- **Link previews.** The page has a title, description and image for messaging
  and social tools.

## Verification

- Python: 400 tests pass, coverage 81.42%; lint and format checks pass. New
  tests cover brotli copies (present, decoding to their source, recorded,
  optional, refused when already in the site), recorded file sizes and archive
  dates.
- Web: typecheck, lint and 64 unit tests pass. New tests cover retries, what is
  not retried, download progress and journey status.
- Browser suite on the synthetic fixture: 61 pass, 9 platform-specific skips.
  New cases cover a slow and a failed context layer, a dropped connection,
  Try again, the print layout and the grouped journey list.
- Release archive served by Apache 2.4 with the bundled `.htaccess`: brotli
  copies are sent with the right type and cache times; a client that accepts
  only gzip, or nothing, gets the original; a file without a copy is
  compressed on request; a subfolder with its own `.htaccess` keeps its own
  headers. The full Auckland desktop and phone check passes through that
  server with no runtime or HTTP errors.

## Reproduce

```sh
npm --prefix web run build
PYTHONPATH=src .venv/bin/python scripts/package_span_site.py \
  --output release-assets/span-site.zip

# Check a served copy: a local server, a staging folder or the live site.
SPAN_CHECK_BASE_URL=https://span.tfwelch.com/ node web/scripts/check-span-release.mjs
```
