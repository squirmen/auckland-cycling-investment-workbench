# SPAN server handoff

Moved here on 2 October 2026 from `documentation/research/span-effective-network.md`,
which the site serves publicly. Operational notes for packaging and deploying
span.tfwelch.com.

The resulting `release-assets/span-effective-network-beta.zip` is a complete
static **SPAN** site, with one map workspace, an old-URL redirect, hashed assets, browser data,
method notes and Apache `.htaccess`. No Python server, raw source topology,
person-level data or OD ledger is included. The companion JSON records archive
and per-file SHA-256 hashes. Creating the archive does not deploy anything.

The archive also holds a brotli copy (`name.br`) of each script, style and data
file over 1 kB. Each copy is decoded and compared with its source before the
archive is written, and has its own SHA-256 in the record. The bundled
`.htaccess` serves a copy to browsers that accept brotli and the original to
the rest. `--no-brotli` leaves the copies out.

Extract the archive into a separate staging directory, preserve hidden files,
and ensure files are web-readable. Check every file against the record. Test
the main map, intersection toggle/popups, Connected journeys, route export and
documentation from the staging copy; `SPAN_CHECK_BASE_URL=<staging URL> node
web/scripts/check-span-release.mjs` runs the same checks against it. That check
runs in Chrome. Open the staging copy in Safari or WebKit as well, at a desktop
and a phone size, and confirm the map is drawn: a fault on 1 October showed only
there.

The SPAN document root also holds other things: STAND under `parking/` and the
certificate files under `.well-known/`. Do not replace the whole directory.
Move SPAN's own entries (`index.html`, `research.html`, `.htaccess`, `CNAME`,
the two marks, the two PNG icons, `span-preview.jpg`, `span-release.json`,
`assets/`, `data/` and `documentation/`) into a rollback directory and move the staged ones in, with
the page last. Leave everything else where it is, and confirm afterwards that
it has not changed. STAND relies on SPAN's root `.htaccess` for its types,
compression and cache times, so keep those directives.

A package built without STAND has no `parking/` folder; leave the live one in
place. A package built after STAND's `make publish` includes it (see
`parking/README.md` in the repository); `parking/` is then one of the entries
to swap, and the check afterwards should open `/parking/uoa/` as well. The package gives STAND no brotli copies, because its
own `.htaccess` sets headers by file name.

Use HTTPS because browser data-integrity checks require a secure context.
Apache must permit the bundled settings; on other servers configure equivalent
MIME types, compression and cache behaviour. Do not use the parent project's
`pct-preview-deploy.zip` or `ataa` deployment instructions for SPAN.
