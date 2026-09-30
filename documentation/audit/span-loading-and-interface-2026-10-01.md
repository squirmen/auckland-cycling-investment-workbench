# SPAN: loading speed and interface fixes

1 October 2026. Follow-up to
[staged loading and tighter search bounds](span-staged-loading-and-stress-bounds-2026-09-26.md).
Model values, rankings and data files are unchanged; every data file keeps its
SHA-256. Commit `701fc6e` was deployed to [span.tfwelch.com](https://span.tfwelch.com)
on 1 October 2026 at 00:26 NZDT. Commit `2a97084` replaced it at 01:01 to fix a
blank map in Safari that the first deployment exposed; see below.

## Result

Four cold visits to the live site from Auckland, in desktop Chrome, straight
after deployment:

| | 24 September site | This release |
| --- | --- | --- |
| First view | 35 seconds or more, or a failure | 3.0–3.7 s |
| Existing network drawn | with the first view | by 3.9–4.3 s |
| All 12,580 links, after opening Value for money | with the first view | 5.2–8.5 s |

The host's speed varies, as the next section shows, so these times will be
longer when it is slow.

## What was wrong on the live site

Measured from Auckland on 30 September against the 24 September deployment:

- The page waited for `candidates.geojson`: 234 MB, sent as 14.0 MB of gzip.
  That download took 31–32 seconds. In one browser test it was cut off at 31
  seconds and the page showed "The data could not be loaded".
- The host was sending about 0.5 MB a second to Auckland whatever the file. Two
  images of 2.7 and 2.9 MB arrived at 0.46 and 0.49 MB/s. A 13.4 MB file sent without
  compression arrived at 0.54 MB/s. Four downloads at once shared the same
  total, so the limit was per visitor, not per file. The same computer received
  5.5 MB/s from a content-delivery test file. About an hour later the host
  was sending 0.9–2.2 MB/s, so its speed varies.

- Scripts were sent at full size with no cache lifetime. The host labels them
  `text/javascript`, which the compression and cache rules did not list. That
  was 0.31 MB for the page's own script and 1.47 MB for the background map's.

So the number of bytes before the first view is what decides how long a visitor
waits, and the server's own compression was not the bottleneck.

## Fewer bytes before the first view

| Before the first view | 24 September site | This release |
| --- | ---: | ---: |
| Manifest | 528 kB | 198 kB |
| Candidate links | 14.0 MB (all 12,580) | 1.31 MB (1,846) |
| Existing low-stress network | 2.46 MB | not waited for |
| Page, script and style | 0.34 MB | 0.10 MB |
| Total | about 17.3 MB | about 1.6 MB |

The background map's script, which loads alongside, falls from 1.47 MB to
0.32 MB. Three changes make up the difference.

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
| Page script | 311 kB, not compressed | 81 kB |
| Background map scripts | 1.47 MB, not compressed | 0.32 MB |

Scripts served from a brotli copy are typed `application/javascript`, so the
one-year cache rule for hashed file names now applies to them. `text/javascript`
is added to the list compressed on request, which also covers scripts elsewhere
on the site. No cache rule is added for that type, because STAND's scripts keep
their names between releases and set their own.

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

The full set is still 8.8 MB. Value for money and Other proposals wait for it:
5 to 9 seconds in the tests above, and about 18 when the host is at its
slowest measured speed. A content-delivery network in front of the host, or a
faster host, is the remaining fix; nothing in the page can remove that wait
without changing what the views show.

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
  and the link card. Shadows are dropped in print, because Chrome prints them
  as grey blocks behind the pins, and a figure stays on the page with its
  heading.
- **Phones.** The full name fits in the header, the map credits take one line,
  and routes are fitted clear of the key and the credits. Text no longer shows
  through a gap between the header and the tabs.
- **Smaller things.** Each view opens at its top. The key for an unfunded gap
  is dashed, as on the map. With every layer on, the key scrolls. The opening
  sentence no longer changes once the data arrives. The About note on
  intersections says what the sites are. Status messages sit clear of the map
  key. The full name fits on a tablet.
- **Value chart.** The chart was drawn 620 units wide and shrunk to the panel,
  which left its labels about 6 pixels high. It is drawn at the panel's width,
  so the labels are about 10 pixels, and link counts have thousands separators.
- **Link previews.** The page has a title, description and image for messaging
  and social tools.

## A table of the build order

The build order could be saved only as GeoJSON. **Download build order as a
table (CSV)** saves the links within the budget, one row each and in order:
name, length, build and whole-life cost, the link's value on its own, what it
adds in the build order and the running totals, its AT plan status and network
role, and the scenario, goal, budget, run and data status the rows came from.

Costs are whole dollars, lengths are to the metre and values to four decimal
places. The file opens in Excel with macrons intact. A street name that a
spreadsheet would read as a formula is written as plain text; the names come
from open map data. The roadmap lists concise exports under priority 5.

## A blank map in Safari, exposed by the faster script

After the first deployment the live site was checked in WebKit, the engine
Safari uses. In 6 of 14 visits the panel worked but the map was blank.

WebKit ran the page's script before the stylesheet was applied. Leaflet then
found a container with no positioning, set `position: relative` on it, and the
map kept a height of zero after the stylesheet arrived.

The fault was already in the 24 September site: with the stylesheet delayed by
1.5 seconds its map is blank in WebKit every time, and with no delay it is
fine. There the script was 311 kB sent at full size and nearly always arrived
after the 18 kB stylesheet. Cutting the script to 81 kB let it arrive first.
For 35 minutes, from 00:26 to 01:01 NZDT, Safari visitors could get a blank map.

Commit `2a97084` fixes it three ways:

- the page sets the map's box itself, so it does not depend on the stylesheet;
- the map is made only once the stylesheet is applied, while the data downloads;
- the position Leaflet adds is removed and the map follows its container's size.

WebKit drew the map in all 30 visits to the fixed build, 12 of them with the
stylesheet delayed by 0.8 to 3 seconds: locally, on the host's staging copy and
on the live site, at desktop and phone sizes. A browser test now removes the
stylesheet and checks that the map still fills the window. Chrome was not
affected: it holds the script until the stylesheet is in.

The release check did not catch this because it runs in Chrome. Checking in
WebKit before promotion is now part of the handoff notes.

## Verification

- Python: 400 tests pass, coverage 81.42%; lint and format checks pass. New
  tests cover brotli copies (present, decoding to their source, recorded,
  optional, refused when already in the site), recorded file sizes and archive
  dates.
- Web: typecheck, lint and 65 unit tests pass. New tests cover retries, what is
  not retried, download progress, journey status and the table export.
- Browser suite on the synthetic fixture: 68 pass in Chrome at desktop and
  phone sizes, 10 platform-specific skips. New cases cover a slow and a failed
  context layer, a dropped connection, Try again, the print layout, the
  grouped journey list, the table download and a missing or late stylesheet.
  CI also runs the stylesheet cases in WebKit.
- Release archive served by Apache 2.4 with the bundled `.htaccess`: brotli
  copies are sent with the right type and cache times; a client that accepts
  only gzip, or nothing, gets the original; a file without a copy is
  compressed on request; a subfolder with its own `.htaccess` keeps its own
  headers. The full Auckland desktop and phone check passes through that
  server with no runtime or HTTP errors.

## Deployment

- The archive is 69.4 MB and holds 50 files and their record. Eighteen are
  brotli copies (252 MB down to 22.5 MB). Archive SHA-256:
  `00c7e721b17eaf15d47b44647646e83aae81ebb83794b98efc15a633534151d7`.
- It was unpacked beside the live site and every file checked against the
  record. A preview folder served it from the same host; the headers, the
  decoded hashes and the full desktop and phone check passed there before
  anything live changed.
- Only SPAN's own entries were swapped. The previous site is kept on the server
  for rollback. STAND under `/parking/` was not touched: 27 requests to it
  returned the same status, headers and content before and after, except that
  its script is now compressed on request.
- The same desktop and phone check then passed against the live address.
- The second archive (`2a97084`, SHA-256
  `7dc53063c63daa853b19899e3d49e24b9ac47cfbcd74fba167f0b35561045f80`) went through
  the same steps, with the WebKit check added on the staging copy and on the
  live site. It is the release now live.

## Reproduce

```sh
npm --prefix web run build
PYTHONPATH=src .venv/bin/python scripts/package_span_site.py \
  --output release-assets/span-site.zip

# Check a served copy: a local server, a staging folder or the live site.
SPAN_CHECK_BASE_URL=https://span.tfwelch.com/ node web/scripts/check-span-release.mjs
```
