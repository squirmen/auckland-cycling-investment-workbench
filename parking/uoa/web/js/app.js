/* STAND: secure bike parking siting for the University of Auckland campuses.
   One file: state, data loading, map layers, panel, inspector, live re-weighting and greedy re-selection. */
(() => {
  "use strict";
  const DATA = "data/";
  const VERSION = "0.1.0";
  const CAMPUS = {
    city: { label: "City Campus", short: "City", centre: [174.7695, -36.8520], zoom: 16.3 },
    grafton: { label: "Grafton Campus", short: "Grafton", centre: [174.7685, -36.8615], zoom: 16.6 },
    newmarket: { label: "Newmarket Campus", short: "Newmarket", centre: [174.7735, -36.8660], zoom: 16.6 },
    all: { label: "All three campuses", short: "All", centre: [174.7710, -36.8590], zoom: 14.4 },
  };
  const RAMP = ["#e6eef8", "#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#0d2f5e"];
  const FLOW = ["#fecbb4", "#f0986f", "#d56326", "#933d09"];
  const LTS = { 1: "#1a7f5a", 2: "#7cb342", 3: "#f08a24", 4: "#9c2f2f" };
  const NAVY = "#0c0c48", TEAL = "#1f6178", DOCK = "#d81b7a";
  // Auckland Transport cycle facilities, matched on the exact "facility" value (web/data/at_cycle_facilities.geojson),
  // most separated first. Greens for riding apart from traffic, purple for paths shared with people walking, amber and
  // rust for painted lanes, grey for traffic calming and anything else. Painted and calmed links are drawn thinner, so
  // the classes differ by width as well as colour (checked for colour-blind separation on the Plain basemap).
  const FAC = [
    { label: "Off-road cycleway", color: "#00704a", w: 1, values: ["Off-road cycleway"] },
    { label: "Protected cycle lane", color: "#2fa35a", w: 1, values: ["On-road protected cycle lane", "On-road protected cycle lane (bi-directional)"] },
    { label: "Shared path", color: "#8a4fbf", w: 1, values: ["Off-road shared path"] },
    { label: "Buffered painted lane", color: "#e0a800", w: 0.8, values: ["On-road buffered cycle lane"] },
    { label: "Painted lane, no buffer", color: "#a93d0a", w: 0.8, values: ["On-road unbuffered cycle lane"] },
  ];
  const FAC_OTHER = { label: "Shared zone, traffic calming or other", color: "#8f8c85", w: 0.65 };  // "Shared zone", "Local area traffic management"
  const facBy = (key) => ["match", ["get", "facility"], ...FAC.flatMap((f) => [f.values, f[key]]), FAC_OTHER[key]];
  const facWidth = (px, extra = 0) => ["match", ["get", "facility"], ...FAC.flatMap((f) => [f.values, px * f.w + extra]), px * FAC_OTHER.w + extra];
  const IND = [
    { key: "coverage", scaled: "s_coverage", label: "Buildings within a short walk", w: 0.30, why: "close to many arrivals" },
    { key: "arrival_flow", scaled: "s_arrival_flow", label: "Riders passing", w: 0.20, why: "on the approach path" },
    { key: "approach_lts", scaled: "approach_lts", label: "Calm approach", w: 0.10, why: "reached on calm links" },
    { key: "surveillance", scaled: "surveillance", label: "Eyes on the street", w: 0.15, why: "busy, overlooked, open sightlines" },
    { key: "lighting", scaled: "lighting", label: "Lighting", w: 0.08, why: "street lamps close by" },
    { key: "space_power", scaled: "space_power", label: "Room and power", w: 0.07, why: "room and mains nearby" },
    { key: "slope", scaled: "slope_score", label: "Flat ground", w: 0.05, why: "flat ground" },
    { key: "revealed_demand", scaled: "revealed_demand", label: "Open racks nearby", w: 0.05, why: "open racks mapped nearby" },
  ];
  const nf = new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 0 });
  // The percent every coverage figure shows, so comparisons match what is read: whole percents, except that a share
  // short of complete that would round up to 100% keeps one decimal (99.9%), so only full coverage reads 100%.
  const pctN = (x) => { const p = Math.round(x * 100); return p === 100 && x < 1 ? Math.min(99.9, Math.round(x * 1000) / 10) : p; };
  const pct = (x) => `${pctN(x)}%`;
  const ordinal = (n) => { const t = n % 100; return `${n}${t >= 11 && t <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th"}`; };
  const article = (n) => { const s = String(n); return s[0] === "8" || (s.length % 3 === 2 && /^1[18]/.test(s)) ? "An" : "A"; };  // "An 8th", "An 11th", "A 7th"
  const $ = (id) => document.getElementById(id);
  const PHONE = () => window.matchMedia("(max-width: 760px)").matches;  // the same breakpoint as ld.css
  // WordPress frames the map with sandbox="allow-scripts": an opaque origin, where the clipboard and new tabs fail silently.
  // A file opened from disk also has self.origin "null" (location.origin "file://") but is not sandboxed.
  const SANDBOXED = self.origin === "null" && location.origin !== "null" && location.protocol !== "file:";

  // Basemaps. Plain (Overture cartography rendered by pipeline/build_basemap.py, the default) and Aerial (the LINZ
  // mosaic with the campus patches on top) are STAND's own images in web/data. Hosted, the map also offers Streets:
  // OpenStreetMap's standard tiles, requested only while Streets is shown, as its tile usage policy asks. There are
  // no CARTO or Esri tiles. An offline build, one that cannot reach tile hosts (such as the one-file map made with
  // pipeline/build_standalone.py --offline), sets window.STAND_OFFLINE and offers only Plain and Aerial.
  const OFFLINE = !!window.STAND_OFFLINE;
  const WIDE = [174.700, -36.925, 174.840, -36.828];  // extent of the own-data basemap (lon0, lat0, lon1, lat1)
  const PLAIN_DETAIL_MINZOOM = 13.5;
  const BASEMAP_LABEL = { plain: "Plain", streets: "Streets", aerial: "Aerial" };
  const TILE_BASEMAPS = OFFLINE ? [] : ["streets"];  // the basemaps drawn from a tile host rather than web/data
  let BASEMAPS = OFFLINE ? ["plain", "aerial"] : ["plain", "streets", "aerial"];
  const state = { campus: "city", view: "suit", k: { city: 6, grafton: 3, newmarket: 3 }, basemap: "plain", site: null,
    weights: Object.fromEntries(IND.map((i) => [i.key, i.w])), custom: false,
    overlays: { uoa: true, candidates: true, parking: true, lamps: false, transit: true, portals: false, patches: true, context: true, counters: false, atfac: false } };
  let map, D = {}, results, byCid = new Map(), destById = new Map(), selection = {}, hoverId = null;
  let placeCampus = null;  // the campus of the site or building open in the place panel

  // ------------------------------------------------------------------ data
  const files = ["study_areas", "campus_footprint", "uoa_buildings", "buildings_context", "flow_edges", "network_lts", "candidates", "hex_suitability",
    "bike_parking_existing", "lamps", "bus_stops", "stations", "portals", "locky_docks_existing", "uoa_bike_stores", "counters", "at_cycle_facilities"];
  const EMPTY_FC = () => ({ type: "FeatureCollection", features: [] });
  const labelFiles = ["labels_suburbs", "labels_roads"];  // web/data/basemap, drawn with the self-hosted glyphs
  async function load() {
    if (window.STAND_DATA) { // single-file build: everything inlined
      results = window.STAND_DATA.results; files.forEach((f) => (D[f] = window.STAND_DATA[f]));
      labelFiles.forEach((f) => (D[f] = window.STAND_DATA[f] || EMPTY_FC()));
      if (results.imagery) for (const v of Object.values(results.imagery)) if (v.file.startsWith("data:")) v.inline = true;
    } else {
      const [res, ...gj] = await Promise.all([fetch(DATA + "results.json").then((r) => r.json()), ...files.map((f) => fetch(`${DATA}${f}.geojson`).then((r) => r.json())),
        ...labelFiles.map((f) => fetch(`${DATA}basemap/${f}.geojson`).then((r) => (r.ok ? r.json() : EMPTY_FC())).catch(() => EMPTY_FC()))]);
      results = res; files.forEach((f, i) => (D[f] = gj[i])); labelFiles.forEach((f, i) => (D[f] = gj[files.length + i]));
    }
    if (!basemapImages("plain").length) BASEMAPS = BASEMAPS.filter((b) => b !== "plain");  // no Plain images: fall back to what exists
    if (!BASEMAPS.includes(state.basemap)) state.basemap = BASEMAPS[0];
    for (const f of D.candidates.features) {
      const p = f.properties; p.coversList = JSON.parse(p.covers || "[]"); p.S = p.suitability; byCid.set(p.cid, f);
    }
    for (const d of results.destinations) destById.set(d.id, d);
    readHash();
    for (const c of ["city", "grafton", "newmarket"]) selection[c] = pickSelection(c, state.k[c]);
  }

  // ------------------------------------------------------------------ scoring and selection
  function rescore() {
    const ws = IND.map((i) => state.weights[i.key]); const tot = ws.reduce((a, b) => a + b, 0) || 1;
    for (const f of D.candidates.features) {
      const p = f.properties; let s = 0;
      IND.forEach((ind, j) => { s += ws[j] * (p[ind.scaled] ?? 0.5); });
      p.S = s / tot;
      if (map && map.getSource("candidates")) map.setFeatureState({ source: "candidates", id: p.cid }, { S: p.S });
    }
    // rank within campus
    for (const c of ["city", "grafton", "newmarket"]) {
      const cs = D.candidates.features.filter((f) => f.properties.campus === c).sort((a, b) => b.properties.S - a.properties.S);
      cs.forEach((f, i) => (f.properties.rankLive = i + 1));
    }
    if (map && map.getSource("hexes")) {
      const wh = { s_coverage: state.weights.coverage, s_arrival_flow: state.weights.arrival_flow, surveillance: state.weights.surveillance, lighting: state.weights.lighting, slope_score: state.weights.slope };
      const th = Object.values(wh).reduce((a, b) => a + b, 0) || 1;
      for (const f of D.hex_suitability.features) {
        const p = f.properties; if (p.suitability == null) continue;
        const sl = Math.max(0, Math.min(1, (8 - (p.slope_pct ?? 4)) / 6));
        const s = (wh.s_coverage * (p.s_coverage ?? 0) + wh.s_arrival_flow * (p.s_arrival_flow ?? 0) + wh.surveillance * (p.surveillance ?? 0.5) + wh.lighting * Math.min(1, (p.lamps_30m ?? 0) / 3) + wh.slope_score * sl) / th;
        map.setFeatureState({ source: "hexes", id: p.h3 }, { S: s });
      }
    }
  }
  function distM(a, b) { const R = 6371000, dLat = (b[1] - a[1]) * Math.PI / 180, dLon = (b[0] - a[0]) * Math.PI / 180, la = a[1] * Math.PI / 180, lb = b[1] * Math.PI / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(la) * Math.cos(lb) * Math.sin(dLon / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); }
  function campusDest(c) { return results.destinations.filter((d) => d.campus === c); }
  function coveredShare(c, cids) {
    const best = new Map(); for (const cid of cids) for (const [j, cr] of byCid.get(cid).properties.coversList) best.set(j, Math.max(best.get(j) || 0, cr));
    let cov = 0, tot = 0; for (const d of campusDest(c)) { tot += d.A_j; cov += d.A_j * (best.get(d.id) || 0); }
    return { covered: cov, total: tot, share: tot ? cov / tot : 0 };
  }
  function greedy(c, k, fixed = []) {
    const cands = D.candidates.features.filter((f) => f.properties.campus === c);
    const A = new Map(campusDest(c).map((d) => [d.id, d.A_j])); const Atot = [...A.values()].reduce((a, b) => a + b, 0);
    const minSp = results.config.min_spacing_m, gamma = 0.3; const best = new Map(); const chosen = [];
    const add = (f) => { chosen.push(f); for (const [j, cr] of f.properties.coversList) best.set(j, Math.max(best.get(j) || 0, cr)); };
    for (const cid of fixed) add(byCid.get(cid));
    while (chosen.length < k) {
      let top = null, topGain = -1;
      for (const f of cands) {
        if (chosen.includes(f)) continue;
        if (chosen.some((g) => distM(g.geometry.coordinates, f.geometry.coordinates) < minSp)) continue;
        let gain = 0; for (const [j, cr] of f.properties.coversList) gain += (A.get(j) || 0) * Math.max(0, cr - (best.get(j) || 0));
        gain += (gamma / k) * f.properties.S * Atot;
        if (gain > topGain) { topGain = gain; top = f; }
      }
      if (!top) break; add(top);
    }
    return chosen.map((f) => f.properties.cid);
  }
  function greedyOrder(c, cids) { // phasing order within a fixed set
    const A = new Map(campusDest(c).map((d) => [d.id, d.A_j])); const best = new Map(); const left = [...cids], order = [];
    while (left.length) {
      let top = null, topGain = -1, topCov = 0;
      for (const cid of left) { let g = 0, cv = 0; for (const [j, cr] of byCid.get(cid).properties.coversList) { g += (A.get(j) || 0) * Math.max(0, cr - (best.get(j) || 0)); cv += (A.get(j) || 0) * cr; }
        if (g > topGain) { topGain = g; top = cid; topCov = cv; } }
      order.push({ cid: top, gain: topGain, cov: topCov }); for (const [j, cr] of byCid.get(top).properties.coversList) best.set(j, Math.max(best.get(j) || 0, cr)); left.splice(left.indexOf(top), 1);
    }
    return order;
  }
  function pickSelection(c, k) {
    let cids, exact = false;
    if (!state.custom) { const sw = (results.k_sweep[c] || []).find((s) => s.k === k); if (sw) { cids = sw.sites; exact = true; } }
    if (!cids) cids = greedy(c, k);
    const order = greedyOrder(c, cids); const cs = coveredShare(c, cids);
    return { campus: c, k, cids, exact, order, ...cs };
  }
  function refreshSelection() { for (const c of ["city", "grafton", "newmarket"]) selection[c] = pickSelection(c, state.k[c]); paintSelection(); renderPanel(); refreshPlace(); }
  // an open site's eyebrow ("Recommended dock 2 of 6") and gain depend on the selection: re-render it when that changes
  function refreshPlace() { if (state.site && !$("place").hidden) openSite(state.site, false, true); }

  // ------------------------------------------------------------------ own-data basemap (web/data/basemap, see pipeline/build_basemap.py)
  // Plain: an overview image of the wide window (~6 m/px) plus a detail grid over the study window (~1.2 m/px, from z13.5).
  // Aerial: the LINZ 2024-25 mosaic of the wide window (~2.5 m/px), added the first time Aerial is chosen, under the 0.4 m campus patches.
  // The mosaic runs to the last zoom, online and offline.
  const bmUrl = (f) => (f.startsWith("data:") ? f : DATA + f);
  function basemapImages(kind) {
    const B = (results && results.basemap) || {};
    if (kind === "plain") return B.plain ? [{ ...B.plain.overview, minzoom: 0 }, ...(B.plain.detail || []).map((v) => ({ ...v, minzoom: PLAIN_DETAIL_MINZOOM }))] : [];
    if (kind === "aerial") return B.aerial ? B.aerial.images || [] : [];
    return [];
  }
  const bmAdded = { plain: false, aerial: false };
  const bmLayerIds = (kind) => basemapImages(kind).map((_, i) => `bm-${kind}-${i}`);
  let patchesAdded = false;
  function ensurePatches() {  // the campus aerial patches, above the wide aerial mosaic and below every analysis layer
    if (patchesAdded || !map || !results.imagery) return; patchesAdded = true;
    for (const [c, v] of Object.entries(results.imagery)) {
      map.addSource(`img-${c}`, { type: "image", url: v.inline ? v.file : DATA + v.file, coordinates: v.coordinates });
      map.addLayer({ id: `img-${c}`, type: "raster", source: `img-${c}`, layout: { visibility: state.basemap === "aerial" && state.overlays.patches ? "visible" : "none" }, paint: { "raster-opacity": 1 } }, "ctx-fill");
    }
  }
  function ensureBasemap(kind) {  // lazy: image sources download as soon as they are added, so only add a set when it is first shown
    if (kind === "aerial") ensurePatches();
    if (bmAdded[kind] || !map) return; bmAdded[kind] = true;
    const before = map.getStyle().layers.map((l) => l.id).find((id) => id.startsWith("img-") || id === "ctx-fill");  // under the campus patches and all analysis layers
    basemapImages(kind).forEach((v, i) => {
      const id = `bm-${kind}-${i}`;
      map.addSource(id, { type: "image", url: bmUrl(v.file), coordinates: v.coordinates });
      map.addLayer({ id, type: "raster", source: id, minzoom: v.minzoom || 0, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } }, before);
    });
  }

  // ------------------------------------------------------------------ map
  // The OSM credit links to its copyright page, except in the sandboxed WordPress frame, where a new tab cannot open.
  // The Streets tiles repeat it word for word, so MapLibre shows it once (it drops a credit contained in another);
  // OpenStreetMap's tile usage policy asks for exactly this credit on its standard tiles.
  // Esri Community Maps is credited beside it: Overture takes some footprints from it (the Other buildings layer and
  // the buildings drawn in the Plain basemap), under the same ODbL.
  const OSM_CREDIT = SANDBOXED ? "© OpenStreetMap contributors" : '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>';
  const ATTRIBUTION = [`${OSM_CREDIT} and Esri Community Maps contributors (ODbL), Overture Maps`, "LINZ CC BY 4.0", "Auckland Transport CC BY 4.0"];
  function baseStyle() {
    // Plain and Aerial come from web/data/basemap (ensureBasemap); only Streets needs a tile source, and only hosted.
    // MapLibre requests a source's tiles only while one of its layers is visible, so Plain and Aerial load no tiles.
    const tiles = { streets: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19, attribution: OSM_CREDIT } };
    const sources = Object.fromEntries(TILE_BASEMAPS.map((k) => [k, tiles[k]]));
    const layers = [{ id: "bg", type: "background", paint: { "background-color": "#e6e6e3" } }];
    for (const k of TILE_BASEMAPS) layers.push({ id: `base-${k}`, type: "raster", source: k, layout: { visibility: k === state.basemap ? "visible" : "none" } });
    // Glyphs are self-hosted (web/assets/font, Noto Sans from maplibre/demotiles, SIL Open Font License 1.1: assets/font/OFL.txt) so labels never depend on a third-party
    // host; the single-file build serves them through a custom protocol from inlined bytes.
    const inlineGlyphs = window.STAND_GLYPHS || (window.STAND_DATA && window.STAND_DATA.glyphs);
    const glyphs = inlineGlyphs ? "standglyph://{fontstack}/{range}.pbf" : new URL("assets/font/{fontstack}/{range}.pbf", location.href).href.replace(/%7B/g, "{").replace(/%7D/g, "}");
    return { version: 8, glyphs, sources, layers };
  }
  function addLayers() {
    const add = (id, data, promote) => map.addSource(id, { type: "geojson", data, ...(promote ? { promoteId: promote } : {}) });
    // The LINZ aerial patches are added by ensurePatches() when Aerial is first shown (an image source downloads as
    // soon as it is added, and the three patches are most of a first visit's bytes).
    add("study", D.study_areas); add("foot", D.campus_footprint); add("uoa", D.uoa_buildings); add("ctx", D.buildings_context);
    add("hexes", D.hex_suitability, "h3"); add("flows", D.flow_edges); add("lts", D.network_lts); add("candidates", D.candidates, "cid");
    add("parking", D.bike_parking_existing); add("lamps", D.lamps); add("stops", D.bus_stops); add("stations", D.stations); add("portals", D.portals); add("docks", D.locky_docks_existing); add("stores", D.uoa_bike_stores);
    add("counters", D.counters); add("atfac", D.at_cycle_facilities);
    map.addSource("selected", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addSource("hover", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    const S = ["coalesce", ["feature-state", "S"], ["get", "suitability"]];
    map.addLayer({ id: "ctx-fill", type: "fill", source: "ctx", paint: { "fill-color": "#cfd2cf", "fill-opacity": 0.45 } });
    map.addLayer({ id: "foot-fill", type: "fill", source: "foot", paint: { "fill-color": NAVY, "fill-opacity": 0.04 } });
    map.addLayer({ id: "hex-fill", type: "fill", source: "hexes", paint: { "fill-color": ["case", ["==", ["get", "suitability"], null], "rgba(0,0,0,0)", ["interpolate", ["linear"], S, 0.15, RAMP[0], 0.3, RAMP[1], 0.45, RAMP[2], 0.6, RAMP[3], 0.72, RAMP[4], 0.85, RAMP[5]]], "fill-opacity": 0.62 } });
    map.addLayer({ id: "hex-line", type: "line", source: "hexes", minzoom: 16.5, paint: { "line-color": "#fff", "line-width": 0.4, "line-opacity": 0.5 } });
    map.addLayer({ id: "foot-line", type: "line", source: "foot", paint: { "line-color": NAVY, "line-width": 1.2, "line-dasharray": [3, 2], "line-opacity": 0.55 } });
    map.addLayer({ id: "uoa-fill", type: "fill", source: "uoa", paint: { "fill-color": NAVY, "fill-opacity": 0.22 } });
    map.addLayer({ id: "uoa-line", type: "line", source: "uoa", paint: { "line-color": NAVY, "line-width": 0.8, "line-opacity": 0.7 } });
    // Plain basemap labels (no text in the raster): suburbs z12-15.5, named main roads from z14.5, and the network's
    // own street names from z15.5 for the streets the road labels do not cover. Above the fills, below building names.
    for (const [id, data] of [["bm-suburbs", D.labels_suburbs], ["bm-roads", D.labels_roads]]) map.addSource(id, { type: "geojson", data });  // credited in ATTRIBUTION
    const roadNames = [...new Set(D.labels_roads.features.map((f) => f.properties.name))];
    map.addLayer({ id: "bm-suburb-labels", type: "symbol", source: "bm-suburbs", minzoom: 12, maxzoom: 15.5, layout: { "text-field": ["get", "name"], "text-font": ["match", ["get", "rank"], 1, ["literal", ["Noto Sans Bold"]], ["literal", ["Noto Sans Regular"]]], "text-size": ["interpolate", ["linear"], ["zoom"], 12, ["match", ["get", "rank"], 1, 11.5, 2, 10.5, 9.5], 15, ["match", ["get", "rank"], 1, 14, 2, 13, 12]], "text-transform": "uppercase", "text-letter-spacing": 0.12, "text-max-width": 8, "text-padding": 6, "symbol-sort-key": ["get", "rank"] }, paint: { "text-color": "#80888e", "text-halo-color": "rgba(238,240,238,0.9)", "text-halo-width": 1.4 } });
    map.addLayer({ id: "bm-road-labels", type: "symbol", source: "bm-roads", minzoom: 14.5, layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": ["interpolate", ["linear"], ["zoom"], 14.5, ["match", ["get", "rank"], [1, 2, 3], 11, 10.5], 18, ["match", ["get", "rank"], [1, 2, 3], 13.5, 12.5]], "symbol-spacing": 320, "text-max-angle": 30, "text-padding": 2, "symbol-sort-key": ["get", "rank"] }, paint: { "text-color": "#646c72", "text-halo-color": "#fbfbfa", "text-halo-width": 1.5 } });
    map.addLayer({ id: "backdrop-names", type: "symbol", source: "lts", minzoom: 15.5, filter: ["all", ["has", "name"], ["!", ["in", ["get", "name"], ["literal", roadNames]]], ["in", ["get", "cls"], ["literal", ["primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "pedestrian"]]]], layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-size": 10, "text-font": ["Noto Sans Regular"], "symbol-spacing": 350 }, paint: { "text-color": "#737b81", "text-halo-color": "#fbfbfa", "text-halo-width": 1.3 } });
    map.addLayer({ id: "uoa-label", type: "symbol", source: "uoa", minzoom: 16.8, layout: { "text-field": ["coalesce", ["get", "name"], ""], "text-size": 10, "text-font": ["Noto Sans Regular"], "text-max-width": 8 }, paint: { "text-color": NAVY, "text-halo-color": "#fff", "text-halo-width": 1.2, "text-opacity": 0.9 } });
    map.addLayer({ id: "lts-line", type: "line", source: "lts", layout: { visibility: "none", "line-cap": "round" }, paint: { "line-color": ["match", ["get", "lts"], 1, LTS[1], 2, LTS[2], 3, LTS[3], LTS[4]], "line-width": ["interpolate", ["linear"], ["zoom"], 14, 1.2, 17, 3.2], "line-opacity": 0.85 } });
    map.addLayer({ id: "flow-line", type: "line", source: "flows", layout: { visibility: "none", "line-cap": "round", "line-join": "round" }, filter: [">=", ["get", "flow_per_day"], 2], paint: { "line-color": ["interpolate", ["linear"], ["get", "flow_per_day"], 2, FLOW[0], 20, FLOW[1], 80, FLOW[2], 200, FLOW[3]], "line-width": ["interpolate", ["linear"], ["get", "flow_per_day"], 2, 1, 20, 2.5, 80, 5, 250, 9], "line-opacity": 0.85 } });
    // all 126 AT facilities in the extract are existing; a white casing keeps the colours legible on every basemap and view
    map.addLayer({ id: "atfac-case", type: "line", source: "atfac", layout: { visibility: "none", "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#fff", "line-width": ["interpolate", ["linear"], ["zoom"], 14, facWidth(2, 2), 17, facWidth(4.5, 2.5)], "line-opacity": 0.85 } });
    map.addLayer({ id: "atfac-line", type: "line", source: "atfac", layout: { visibility: "none", "line-cap": "round", "line-join": "round" }, paint: { "line-color": facBy("color"), "line-width": ["interpolate", ["linear"], ["zoom"], 14, facWidth(2), 17, facWidth(4.5)], "line-opacity": 0.95 } });
    map.addLayer({ id: "counters", type: "circle", source: "counters", layout: { visibility: "none" }, paint: { "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "daily_avg"], 0], 50, 5, 400, 9, 1200, 14], "circle-color": "#0e7490", "circle-opacity": 0.85, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "counters-label", type: "symbol", source: "counters", layout: { visibility: "none", "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["coalesce", ["get", "daily_avg"], "–"]], "/day"], "text-size": 10.5, "text-font": ["Noto Sans Bold"], "text-offset": [0, 1.2], "text-anchor": "top" }, paint: { "text-color": "#0e7490", "text-halo-color": "#fff", "text-halo-width": 1.3 } });
    map.addLayer({ id: "lamps", type: "circle", source: "lamps", layout: { visibility: "none" }, paint: { "circle-radius": 2.4, "circle-color": "#f2c200", "circle-stroke-color": "#7a5c00", "circle-stroke-width": 0.6 } });
    map.addLayer({ id: "stops", type: "circle", source: "stops", minzoom: 15.5, paint: { "circle-radius": 3, "circle-color": "#fff", "circle-stroke-color": "#2b2b2b", "circle-stroke-width": 1.2 } });
    map.addLayer({ id: "stations", type: "circle", source: "stations", paint: { "circle-radius": 6, "circle-color": NAVY, "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    map.addLayer({ id: "stations-label", type: "symbol", source: "stations", layout: { "text-field": ["get", "name"], "text-size": 10.5, "text-font": ["Noto Sans Regular"], "text-offset": [0, 1.1], "text-anchor": "top" }, paint: { "text-color": NAVY, "text-halo-color": "#fff", "text-halo-width": 1.2 } });
    map.addLayer({ id: "parking-open", type: "circle", source: "parking", filter: ["==", ["get", "type"], "open_rack"], minzoom: 15.5, paint: { "circle-radius": 3.2, "circle-color": "#8f8c85", "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });
    map.addLayer({ id: "stores", type: "circle", source: "stores", paint: { "circle-radius": 5.5, "circle-color": "#fff", "circle-stroke-color": NAVY, "circle-stroke-width": 2.2 } });
    map.addLayer({ id: "docks", type: "circle", source: "docks", filter: ["!=", ["get", "coord_quality"], "inferred"], paint: { "circle-radius": 6, "circle-color": "#fff", "circle-stroke-color": DOCK, "circle-stroke-width": 2.4 } });
    // a dock known only from an event listing (coord_quality "inferred") is drawn as a dashed ring: possible, not
    // confirmed. The layer, and its legend key, exist only when the data has such a dock.
    if (hasPossibleDocks()) {
      if (!map.hasImage("dock-possible")) map.addImage("dock-possible", dashedRing(), { pixelRatio: 2 });
      map.addLayer({ id: "docks-possible", type: "symbol", source: "docks", filter: ["==", ["get", "coord_quality"], "inferred"], layout: { "icon-image": "dock-possible", "icon-allow-overlap": true, "icon-ignore-placement": true } });
    }
    map.addLayer({ id: "portals", type: "circle", source: "portals", layout: { visibility: "none" }, paint: { "circle-radius": ["interpolate", ["linear"], ["get", "weight_per_day"], 200, 7, 1500, 16], "circle-color": TEAL, "circle-opacity": 0.85, "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "cand", type: "circle", source: "candidates", minzoom: 15, paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 15, 2.2, 18, 5], "circle-color": ["interpolate", ["linear"], S, 0.2, RAMP[0], 0.35, RAMP[1], 0.5, RAMP[2], 0.62, RAMP[3], 0.74, RAMP[4], 0.85, RAMP[5]], "circle-stroke-color": "#fff", "circle-stroke-width": 0.8, "circle-opacity": 0.9 } });
    map.addLayer({ id: "sel-halo", type: "circle", source: "selected", paint: { "circle-radius": 15, "circle-color": DOCK, "circle-opacity": 0.18 } });
    // the open site: a navy ring just below the recommended docks, so a candidate that is not one is marked too
    map.addLayer({ id: "hover-ring", type: "circle", source: "hover", paint: { "circle-radius": 11, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": NAVY, "circle-stroke-width": 2.5 } });
    map.addLayer({ id: "sel", type: "circle", source: "selected", paint: { "circle-radius": 10, "circle-color": DOCK, "circle-stroke-color": "#fff", "circle-stroke-width": 2.2 } });
    map.addLayer({ id: "sel-label", type: "symbol", source: "selected", layout: { "text-field": ["to-string", ["get", "n"]], "text-size": 11, "text-font": ["Noto Sans Bold"], "text-allow-overlap": true }, paint: { "text-color": "#fff" } });
    map.addLayer({ id: "sel-name", type: "symbol", source: "selected", minzoom: 15.6, layout: { "text-field": ["get", "short"], "text-size": 11, "text-font": ["Noto Sans Bold"], "text-offset": [0, 1.4], "text-anchor": "top", "text-max-width": 10 }, paint: { "text-color": "#9b0f55", "text-halo-color": "#fff", "text-halo-width": 1.4 } });
    if (state.basemap === "plain" || state.basemap === "aerial") ensureBasemap(state.basemap);
    applyView(); applyOverlays(); paintSelection();
    // interactions
    const hoverLayers = ["cand", "sel", "hex-fill", "uoa-fill", "parking-open", "stores", "docks", "docks-possible", "stations", "portals", "flow-line", "lts-line", "counters", "atfac-line", "atfac-case"].filter((l) => map.getLayer(l));  // the casing widens the target of a thin facility line
    for (const l of hoverLayers) { map.on("mouseenter", l, () => (map.getCanvas().style.cursor = "pointer")); map.on("mouseleave", l, () => { map.getCanvas().style.cursor = ""; hideTip(); }); }
    map.on("mousemove", (e) => {
      const fs = map.queryRenderedFeatures(e.point, { layers: hoverLayers });
      if (!fs.length) return hideTip();
      showTip(e.point, tipFor(fs[0]));
    });
    map.on("click", (e) => {
      hideTip();
      const fs = map.queryRenderedFeatures(e.point, { layers: ["sel", "cand"].filter((l) => map.getLayer(l)) });
      if (fs.length) { openSite(fs[0].properties.cid); return; }
      const b = map.queryRenderedFeatures(e.point, { layers: ["uoa-fill"] });
      if (b.length) { openBuilding(b[0].properties, [e.lngLat.lng, e.lngLat.lat]); return; }
    });
  }
  function tipFor(f) {
    const L = f.layer.id; let p = f.properties;
    if (L === "cand" || L === "sel") { const full = byCid.get(p.cid); if (!full) return ""; p = full.properties;  // rendered copies are thin ('sel') or stale (S, rankLive)
      const s = selection[p.campus]; const ph = s ? s.order.findIndex((o) => o.cid === p.cid) + 1 : 0;
      return `<strong>${ph ? `Dock ${ph} · ` : ""}${siteName(p)}</strong>Suitability ${p.S.toFixed(2)} · rank ${p.rankLive || p.rank} of ${countCampus(p.campus)}<span class="tooltip-hint">${nf.format(p.coverage)} arrivals/day within a short walk · ${nf.format(p.arrival_flow)} riders pass · click for the case</span>`; }
    if (L === "hex-fill") return `<strong>${p.suitability == null ? "Inside a building" : "Suitability " + (fsS(f) ?? p.suitability).toFixed(2)}</strong>${nf.format(p.coverage)} arrivals/day within a short walk · ${nf.format(p.arrival_flow)} riders pass<span class="tooltip-hint">Slope ${p.slope_pct == null ? "–" : p.slope_pct.toFixed(1) + "%"} · ${p.lamps_30m} lamps within 30 m</span>`;
    if (L === "uoa-fill") return `<strong>${buildingName(p)}</strong>${p.A_j != null ? nf.format(p.A_j) + " modelled cyclist arrivals/day" : notDestination(p)}<span class="tooltip-hint">${nf.format(p.gfa_m2)} m² floor area · ${floorsText(p)}</span>`;
    if (L === "parking-open") return `<strong>${p.name || "Bike racks"}</strong>OpenStreetMap bicycle parking`;
    if (L === "stores") return `<strong>${storeLabel(p.name)}</strong>University card-access bike store${p.capacity ? " · " + p.capacity + " bikes" : ""}<span class="tooltip-hint">${p.source}</span>`;
    if (L === "docks") return `<strong>${p.name}</strong>Existing Locky Dock${p.year ? " · " + p.year : ""}<span class="tooltip-hint">${(p.coord_quality || "").replace(/_/g, " ")} · ${p.source}</span>`;
    if (L === "docks-possible") return `<strong>${p.name}</strong>Possible Locky Dock (unconfirmed)<span class="tooltip-hint">Inferred from an event listing · ${p.source}</span>`;
    if (L === "stations") return `<strong>${p.name}</strong>${p.category.replace(/_/g, " ")}`;
    if (L === "portals") return `<strong>${p.name}</strong>${nf.format(p.weight_per_day)} riders/day enter here<span class="tooltip-hint">${p.basis}</span>`;
    if (L === "counters") {  // each daily average is over that counter's own record: say which months when the data carries them
      const period = counterPeriod(p);
      return `<strong>${p.name}</strong>AT cycle counter · ${p.daily_avg != null ? `${nf.format(p.daily_avg)} riders/day, ${period || "on average"}` : "no average"}<span class="tooltip-hint">${period ? "Cycleway dashboard" : "Cycleway dashboard: averages over each counter's own record, to July 2026"}</span>`; }
    if (L === "atfac-line" || L === "atfac-case") return `<strong>${p.road || "Cycle facility"}</strong>${p.facility}${p.status ? " · " + p.status : ""}${p.CONSTRUCTIONYEAR ? " · " + p.CONSTRUCTIONYEAR : ""}<span class="tooltip-hint">Auckland Transport cycle facility network</span>`;
    if (L === "flow-line") return `<strong>${p.name || (p.cls || "path")}</strong>${nf.format(p.flow_per_day)} modelled riders/day toward campus · LTS ${p.lts}`;
    if (L === "lts-line") return `<strong>${p.name || (p.cls || "path")}</strong>Level of Traffic Stress ${p.lts} (${p.lts_source === "span_lts_by_way" ? "SPAN" : "class and speed"})${p.maxspeed ? " · " + p.maxspeed + " km/h" : ""}<span class="tooltip-hint">grade ${p.grade_uv_pct == null ? "–" : Math.abs(p.grade_uv_pct).toFixed(1) + "%"}</span>`;
    return "";
  }
  function dashedRing() {  // 16 px icon at 2x: a white disc with a dashed magenta ring
    const r = 2, n = 16 * r, c = document.createElement("canvas"); c.width = c.height = n; const g = c.getContext("2d");
    g.beginPath(); g.arc(n / 2, n / 2, 6.3 * r, 0, 2 * Math.PI); g.fillStyle = "rgba(255,255,255,0.8)"; g.fill();
    g.setLineDash([2.4 * r, 1.7 * r]); g.lineWidth = 2 * r; g.strokeStyle = DOCK; g.stroke();
    return g.getImageData(0, 0, n, n);
  }
  function hasPossibleDocks() { return ((D.locky_docks_existing && D.locky_docks_existing.features) || []).some((f) => f.properties && f.properties.coord_quality === "inferred"); }
  function fsS(f) { const s = map.getFeatureState({ source: "hexes", id: f.properties.h3 }); return s && s.S; }
  function countCampus(c) { return D.candidates.features.filter((f) => f.properties.campus === c).length; }
  function showTip(pt, html) { if (!html) return hideTip(); const t = $("tooltip"); t.innerHTML = html; t.hidden = false; const w = map.getContainer().clientWidth; const flip = pt.x > w - 380; t.style.transform = `translate(${flip ? pt.x - t.offsetWidth - 14 : pt.x + 14}px, ${pt.y + 14}px)`; }
  function hideTip() { $("tooltip").hidden = true; }
  function applyView() {
    const v = state.view;
    map.setLayoutProperty("hex-fill", "visibility", v === "suit" ? "visible" : "none"); map.setLayoutProperty("hex-line", "visibility", v === "suit" ? "visible" : "none");
    map.setLayoutProperty("flow-line", "visibility", v === "flow" ? "visible" : "none"); map.setLayoutProperty("lts-line", "visibility", v === "lts" ? "visible" : "none");
    map.setLayoutProperty("cand", "visibility", state.overlays.candidates && v !== "none" ? "visible" : "none");
    renderLegend();
  }
  function applyOverlays() {
    const o = state.overlays; const vis = (ids, on) => ids.forEach((id) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none"));
    vis(["uoa-fill", "uoa-line", "uoa-label"], o.uoa); vis(["parking-open", "stores", "docks", "docks-possible"], o.parking); vis(["lamps"], o.lamps); vis(["stops", "stations", "stations-label"], o.transit); vis(["portals"], o.portals); vis(["ctx-fill"], o.context);
    vis(["counters", "counters-label"], o.counters); vis(["atfac-case", "atfac-line"], o.atfac);
    vis(["cand"], o.candidates && state.view !== "none");
    if (results.imagery) vis(Object.keys(results.imagery).map((c) => `img-${c}`), o.patches && state.basemap === "aerial");
    const plain = state.basemap === "plain";
    if (bmAdded.plain) vis(bmLayerIds("plain"), plain);
    if (bmAdded.aerial) vis(bmLayerIds("aerial"), o.patches && state.basemap === "aerial");  // the "LINZ 2024 aerials" check covers the wide mosaic too
    vis(["bm-suburb-labels", "bm-road-labels", "backdrop-names"], plain);
  }
  function setBasemap(b) { if (!BASEMAPS.includes(b)) b = BASEMAPS[0]; state.basemap = b; if (b === "plain" || b === "aerial") ensureBasemap(b); for (const k of TILE_BASEMAPS) map.setLayoutProperty(`base-${k}`, "visibility", k === b ? "visible" : "none"); applyOverlays(); document.querySelectorAll("#basemapSeg button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.basemap === b)); writeHash(); }
  function paintSelection() {
    const feats = [];
    for (const c of ["city", "grafton", "newmarket"]) { if (state.campus !== "all" && state.campus !== c) continue; const s = selection[c]; if (!s) continue;
      s.order.forEach((o, i) => { const f = byCid.get(o.cid); feats.push({ type: "Feature", geometry: f.geometry, properties: { cid: o.cid, campus: c, n: i + 1, short: shortName(f.properties) } }); }); }
    map.getSource("selected").setData({ type: "FeatureCollection", features: feats });
  }
  function fitCampus() {
    const phone = PHONE(), pad = phone ? phonePadding() : { top: 30, left: 400, right: 40, bottom: 30 };
    const camps = state.campus === "all" ? ["city", "grafton", "newmarket"] : [state.campus];
    let b = bounds(D.study_areas.features.filter((f) => camps.includes(f.properties.campus)));
    // Above a phone's expanded panel the strip is about 200 px tall: the whole study area would crowd the docks into one
    // another there, so frame the recommended docks with 150 m around them instead
    if (phone && document.body.dataset.panel !== "collapsed" && $("place").hidden) {
      const pts = camps.flatMap((c) => (selection[c] ? selection[c].cids : []).map((cid) => byCid.get(cid).geometry.coordinates));
      if (pts.length) { const d = bounds([{ geometry: { coordinates: pts } }]), dy = 150 / 111320, dx = dy / Math.cos(d[0][1] * Math.PI / 180);
        b = [[d[0][0] - dx, d[0][1] - dy], [d[1][0] + dx, d[1][1] + dy]]; }
    }
    map.fitBounds(b, { padding: pad, duration: 700, maxZoom: 17 });
  }
  // On a phone the campus goes in the clear part of the map: below the map tools, above whichever sheet is up (the
  // expanded panel, its collapsed header or a site) and the scale bar just above it, and left of the zoom buttons.
  // With the panel expanded that strip is short (fitCampus frames the docks in it); where it is too short even for
  // that (a short screen), the panel is collapsed first, so no dock is left under the sheet.
  function phonePadding() {
    const box = map.getContainer().getBoundingClientRect(), W = box.width, H = box.height;
    const rect = (el) => { if (!el || el.closest("[hidden]") || getComputedStyle(el).display === "none") return null; const r = el.getBoundingClientRect(); return r.width && r.height ? r : null; };
    const edges = () => {
      const tools = rect(document.querySelector(".map-tools")), sheet = rect(!$("place").hidden ? $("place") : $("panel"));
      const scale = rect(map.getContainer().querySelector(".maplibregl-ctrl-scale")), credits = rect(map.getContainer().querySelector(".maplibregl-ctrl-attrib.maplibregl-compact-show"));
      const top = (tools ? tools.bottom - box.top : 0) + 12;
      const bottom = Math.min(...[sheet, scale, credits].filter(Boolean).map((r) => r.top - box.top), H) - 12;
      const nav = [...map.getContainer().querySelectorAll(".maplibregl-ctrl-bottom-right > .maplibregl-ctrl")].map(rect).filter((r) => r && r.top - box.top < bottom && r.width < W / 3);
      const right = nav.length ? W - Math.min(...nav.map((r) => r.left - box.left)) + 8 : 16;
      return { top, bottom, right };
    };
    let e = edges();
    if (e.bottom - e.top < 160 && document.body.dataset.panel !== "collapsed" && $("place").hidden) { setPanel(false); e = edges(); }
    const room = e.bottom - e.top, spare = Math.max(0, 60 - room);  // never ask MapLibre for less than 60 px of map
    return { top: Math.max(0, e.top - spare), bottom: Math.max(0, H - e.bottom), left: 16, right: Math.min(e.right, W / 3) };
  }
  function bounds(features) { let w = 180, s = 90, e = -180, n = -90; const walk = (c) => { if (typeof c[0] === "number") { w = Math.min(w, c[0]); e = Math.max(e, c[0]); s = Math.min(s, c[1]); n = Math.max(n, c[1]); } else c.forEach(walk); }; features.forEach((f) => walk(f.geometry.coordinates)); return [[w, s], [e, n]]; }

  // ------------------------------------------------------------------ panel
  function siteName(p) { if (p.site_name) return p.site_name; // the curated name for a recommended site (pipeline/name_sites.py)
    const st = p.street && p.street !== "campus path" ? p.street : "Campus path"; const b = p.nearest_building || "campus";
    if (/^Building at /.test(b)) return `${st}, by ${b.replace(/^Building at /, "")}`;
    if (/storey building off/.test(b)) return `${st}, by the ${b.replace(/ off .*/, "")}`;
    return `${st} at ${b}`; }
  // Store names come from the University's list as "Newmarket secure bike racks Building 901" or "Bike store B201 Level 1 (...)":
  // show them with the comma a reader expects, without changing the data.
  function storeLabel(n) { return String(n || "").replace(/^(Bike (?:store|cage) B?\d+) (?!\()/, "$1, ").replace(/([a-z]) (Building \d+)$/, "$1, $2"); }
  const COUNT_WORD = { 2: "Two", 3: "Three", 4: "Four", 5: "Five" };
  const docksText = (n) => `${n} dock${n === 1 ? "" : "s"}`;
  // floors_source (pipeline/build_layers.py) names the rule that set a building's floor count
  const FLOORS_SOURCE = { observed: "mapped", from_height: "from mapped height", lidar_dsm_2024: "LiDAR\u00a0DSM\u00a02024", default_by_subtype: "default for building type" };  // the source's name kept on one line
  function floorsText(p) {
    if (p.floors_est == null) return "floors unknown";
    const n = Math.round(p.floors_est), src = FLOORS_SOURCE[p.floors_source] || (p.floors_source || "").replace(/_/g, " ");
    return `${nf.format(n)} floor${n === 1 ? "" : "s"}${src ? ` (${src})` : ""}`;
  }
  // A University building with no modelled arrivals: a hall of residence is where rides start; anything else was left
  // out of the destinations by name (pipeline/build_demand.py: underpasses, bridges, car parks and the like)
  const STRUCTURE_RE = /\b(underpass|overpass|overbridge|footbridge|bridge|car ?park|parking|substation|plant room)\b/i;
  function notDestination(p) {  // halls are origins; walkways and car parks are not destinations; anything else was dropped by the model's name filter
    if (p.class === "dormitory") return "Hall of residence (origin)";
    return STRUCTURE_RE.test(p.name || p.label || "") ? "Not modelled as a destination (walkway, bridge or car park)" : "Left out of the destinations by the model's name filter (see the method, section 9)"; }
  // A counter's record as "average Jul 2016 to Dec 2018", from period_start and period_end ("2016-07" or "2016-07-01"
  // read as a month; other text is kept as it is). Null when the data does not carry the period.
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function monthText(s) { const m = /^(\d{4})-(\d{2})/.exec(String(s)); return m && +m[2] >= 1 && +m[2] <= 12 ? `${MONTHS[+m[2] - 1]} ${m[1]}` : String(s); }
  function counterPeriod(p) {
    if (!p.period_start) return null;
    return p.period_end ? `average ${monthText(p.period_start)} to ${monthText(p.period_end)}` : `average since ${monthText(p.period_start)}`;
  }
  // An unnamed building takes the address the model gives it ("Building at 58 Symonds Street"), not a repeat of the eyebrow
  function buildingName(p) { if (p.name) return p.name; const d = destById.get(String(p.id)); return (d && d.label) || p.label || "Unnamed University building"; }
  function shortName(p) { if (p.site_short) return p.site_short; const b = (p.nearest_building || "").replace(/^Building at /, "").replace(/ off .*/, ""); return b.length > 28 ? b.slice(0, 26) + "…" : b; }
  function topReasons(p, n = 2) { return IND.map((i) => ({ i, v: (p[i.scaled] ?? 0) * state.weights[i.key] })).sort((a, b) => b.v - a.v).slice(0, n).map((x) => x.i.why); }
  function renderPanel() {
    const c = state.campus; $("campusValue").textContent = CAMPUS[c].label;
    document.querySelectorAll('[data-group="campus"] .chip').forEach((x) => x.setAttribute("aria-checked", x.dataset.value === c));
    // hero
    if (c === "all") { let cov = 0, tot = 0, k = 0; for (const x of ["city", "grafton", "newmarket"]) { cov += selection[x].covered; tot += selection[x].total; k += selection[x].k; }
      $("heroFigure").textContent = pct(cov / tot); $("heroText").textContent = `of the University's ${nf.format(tot)} estimated daily cyclist arrivals would end within a short walk of one of ${k} docks.`;
      $("heroSub").textContent = `City ${selection.city.k} · Grafton ${selection.grafton.k} · Newmarket ${selection.newmarket.k} docks. ${state.custom ? "Custom weighting, greedy selection." : "Exact optimisation with default weights."}`;
      $("mini").textContent = `${pct(cov / tot)} of arrivals covered by ${docksText(k)}`; $("kRange").parentElement.hidden = true; }
    else { const s = selection[c];
      // "recommended" only for the published set: the default number of docks, chosen with the default weights
      const rec = s.exact && !state.custom && s.k === defaultK(c) ? "recommended " : "";
      $("heroFigure").textContent = pct(s.share); $("heroText").textContent = `of the ${nf.format(s.total)} estimated daily cyclist arrivals at the ${CAMPUS[c].label} would end within a short walk of ${s.k === 1 ? `a single ${rec}dock` : `one of ${s.k} ${rec}docks`}.`;
      $("heroSub").textContent = s.exact ? "Exact optimisation, default weights." : "Greedy selection" + (state.custom ? " with your weighting." : "."); $("mini").textContent = `${CAMPUS[c].short}: ${pct(s.share)} covered by ${docksText(s.k)}`;
      $("kRange").parentElement.hidden = false; $("kRange").value = s.k; $("kValue").textContent = `${docksText(s.k)} · ${pct(s.share)} covered`;
      const sw = results.k_sweep[c] || []; $("kTicks").innerHTML = sw.map((x, i) => `<span class="tick" style="left:${(i / Math.max(1, sw.length - 1)) * 100}%">${pct(sweepShare(c, x))}</span>`).join("");
      $("kNote").textContent = [nextDockNote(c, s), "Coverage counts each building once, to its best dock, with full credit within a 50 m walk and none beyond 250 m."].filter(Boolean).join(" "); }
    // list
    const rows = [];
    const camps = c === "all" ? ["city", "grafton", "newmarket"] : [c];
    for (const x of camps) { const s = selection[x]; s.order.forEach((o, i) => { const p = byCid.get(o.cid).properties;
      rows.push(`<li><button class="rank-row${state.site === o.cid ? " is-focus" : ""}" type="button" data-cid="${o.cid}"><span class="rank-n">${i + 1}</span><span class="rank-name">${siteName(p)}${c === "all" ? ` <span class="badge is-dock">${CAMPUS[x].short}</span>` : ""}</span><span class="rank-meta">${nf.format(o.cov)}/day</span><span class="rank-reason">${topReasons(p).join(" · ")} · +${nf.format(o.gain)} new arrivals covered</span></button></li>`); }); }
    $("siteList").innerHTML = rows.join("");
    $("siteList").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => openSite(b.dataset.cid, true)));
    $("siteNote").textContent = "Docks are numbered in order: each adds the most new coverage given the ones before it. Click a site for the case, or the map for any candidate.";
    renderLegend(); writeHash();
  }
  // a k-sweep entry's share, computed from its sites as the hero computes it (the stored figure is rounded)
  function sweepShare(c, x) { return x.sites && x.sites.every((cid) => byCid.has(cid)) ? coveredShare(c, x.sites).share : x.covered_share; }
  // What one more dock would do. Sets are re-optimised for each k and the optimiser also rewards site quality,
  // so the next set may move docks, and coverage can stay level or even dip. Speak of "an Nth dock" only when the
  // next set keeps every dock shown and adds one; otherwise describe the next set as a set.
  function nextDockNote(c, s) {
    const n = s.k + 1; if (n > +$("kRange").max) return "";
    const next = pickSelection(c, n), now = pctN(s.share), then = pctN(next.share);
    if (s.cids.every((cid) => next.cids.includes(cid))) {
      const one = `${article(n)} ${ordinal(n)} dock`;
      return then > now ? `${one} would lift coverage to ${then}%.` : `${one} would add little here: coverage stays at ${then}%.`;
    }
    const set = next.exact ? `The best ${n}-dock set` : `${article(n)} ${n}-dock set chosen with your weights`;  // "An 8-dock set"
    if (then > now) return `${set} covers ${then}%, with some docks in other places.`;
    if (then === now) return `${set} also covers ${then}%: another dock adds little here.`;
    return `${set} covers ${then}%: the optimiser also weighs site quality, so coverage can dip.`;
  }
  function renderLegend() {
    const v = state.view; let html = "";
    const scale = (ramp, labels, title) => `<div class="legend-title">${title}</div><div class="legend-scale" style="grid-template-columns:repeat(${ramp.length},1fr)">${ramp.map((col, i) => `<div class="legend-step"><span class="legend-swatch" style="background:${col}"></span><span class="legend-label">${labels[i] || ""}</span></div>`).join("")}</div>`;
    if (v === "suit") html += scale(RAMP, ["low", "", "", "", "", "high"], "Site suitability (0–1, weighted indicators; hexagons about 50 m across, candidates as dots)");
    if (v === "flow") html += scale(FLOW, ["2", "20", "80", "200+"], "Modelled riders per day approaching the campus, by path");
    if (v === "lts") html += scale([LTS[1], LTS[2], LTS[3], LTS[4]], ["LTS 1 calm", "LTS 2", "LTS 3", "LTS 4 stressful"], "Level of Traffic Stress on links riders can use");
    if (state.overlays.atfac) html += `<div class="legend-title">Auckland Transport cycle facilities (existing)</div><div class="legend-keys legend-fac">${[...FAC, FAC_OTHER].map((f) => `<span class="legend-key"><span class="key-line" style="background:${f.color};height:${Math.round(4 * f.w)}px"></span>${f.label}</span>`).join("")}</div>`;
    html += `<div class="legend-keys"><span class="legend-key"><span class="key-dot is-dock"></span>Recommended dock (order)</span><span class="legend-key"><span class="key-dot" style="background:#fff;box-shadow:0 0 0 2px ${DOCK}"></span>Existing Locky Dock</span>${hasPossibleDocks() ? '<span class="legend-key"><span class="key-dot is-possible"></span>Possible Locky Dock (unconfirmed)</span>' : ""}<span class="legend-key"><span class="key-dot" style="background:#fff;box-shadow:0 0 0 2px ${NAVY}"></span>University bike store</span><span class="legend-key"><span class="key-dot" style="background:#8f8c85"></span>Open racks (OSM)</span><span class="legend-key"><span class="key-sq" style="background:${NAVY};opacity:.35"></span>University buildings</span><span class="legend-key"><span class="key-dot" style="background:${NAVY}"></span>Station</span></div>`;
    $("legend").innerHTML = html;
  }
  function renderWeights() {
    $("weights").innerHTML = IND.map((i) => `<div class="weight-row"><label for="w-${i.key}">${i.label}</label><input type="range" id="w-${i.key}" min="0" max="0.5" step="0.01" value="${state.weights[i.key]}"><output>${Math.round(state.weights[i.key] * 100)}</output></div>`).join("");
    IND.forEach((i) => { const el = $(`w-${i.key}`); el.addEventListener("input", () => { state.weights[i.key] = +el.value; el.nextElementSibling.textContent = Math.round(el.value * 100); state.custom = !IND.every((j) => Math.abs(state.weights[j.key] - j.w) < 1e-9); rescore(); refreshSelection(); $("weightsNote").textContent = state.custom ? "Custom weights: greedy selection." : "Default weights: exact optimisation."; }); });
  }

  // ------------------------------------------------------------------ inspector
  // The part of the map not under the panel, the inspector or the map tools: on a phone the band between the tools
  // and the bottom sheet, on a desktop the gap between the panel and the inspector.
  function visibleRect() {
    const box = map.getContainer().getBoundingClientRect(), W = box.width, H = box.height, rel = (el) => { const r = el.getBoundingClientRect(); return { left: r.left - box.left, right: r.right - box.left, top: r.top - box.top, bottom: r.bottom - box.top }; };
    const place = $("place"), panel = $("panel"), tools = document.querySelector(".map-tools");
    if (PHONE()) {
      const top = tools ? rel(tools).bottom + 8 : 0;
      const sheet = !place.hidden ? place : getComputedStyle(panel).display !== "none" && document.body.dataset.panel !== "collapsed" ? panel : null;
      return { left: 0, right: W, top, bottom: Math.max(top + 80, sheet ? rel(sheet).top - 8 : H) };
    }
    const left = getComputedStyle(panel).display !== "none" ? rel(panel).right + 8 : 0;
    return { left, right: Math.max(left + 120, place.hidden ? W : rel(place).left - 8), top: 0, bottom: H };
  }
  function visibleOffset() { const v = visibleRect(), box = map.getContainer().getBoundingClientRect(); return [Math.round((v.left + v.right - box.width) / 2), Math.round((v.top + v.bottom - box.height) / 2)]; }
  function inView(lngLat, margin = 24) { const v = visibleRect(), q = map.project(lngLat); return q.x >= v.left + margin && q.x <= v.right - margin && q.y >= v.top + margin && q.y <= v.bottom - margin; }
  // fly: centre on the site in the visible part of the map and zoom in; otherwise pan only if the site ended up hidden
  function bringIntoView(lngLat, fly) {
    if (fly) map.flyTo({ center: lngLat, zoom: Math.max(map.getZoom(), 17.3), offset: visibleOffset(), duration: 600 });
    else if (!inView(lngLat)) map.easeTo({ center: lngLat, offset: visibleOffset(), duration: 400 });
  }
  // Room and power (pipeline/site_model.py): 0.5 x space + 0.5 x power. Space is 1 for a car-park candidate, car parking or
  // a plaza within 15 m, or a service lane whose bounding box comes within 6 m, else 0.5 (to check); power is 1 when a
  // building's bounding box comes within 30 m, else 0.4 (then no building is within 30 m). The box tests can reach further
  // than the distance, so the words say "near" and "close by" for a 1 and give the distance only for a 0.4.
  // Use the parts when the data carries them, else recover them from the score so the words always match the bar.
  function spacePower(p) {
    if (p.space != null && p.power != null) return { space: +p.space, power: +p.power };
    if (p.space_power == null) return null;
    let best = null;
    for (const space of [1, 0.5]) for (const power of [1, 0.4]) { const d = Math.abs(0.5 * space + 0.5 * power - p.space_power); if (!best || d < best.d) best = { d, space, power }; }
    return best;
  }
  function defaultK(c) { const k = results.config && results.config.k_per_campus; return (k && k[c]) || { city: 6, grafton: 3, newmarket: 3 }[c]; }
  function dockEyebrow(p, s, n) {  // stages are curated for the published set only: the default k with the exact optimiser
    if (!(s.exact && s.k === defaultK(p.campus))) return `Dock ${n} of ${s.k}`;
    if (p.stage === "Optional") return `Optional dock ${n} of ${s.k}`;
    return `Recommended dock ${n} of ${s.k}${p.stage ? `\u00a0· ${p.stage.replace(/ /g, "\u00a0")}` : ""}`;  // wraps before the stage, not inside it
  }
  // still: re-render in place (the selection changed under an open site) without moving the map
  function openSite(cid, fly, still) {
    hideTip();
    const f = byCid.get(cid); if (!f) return; const p = f.properties; state.site = cid; placeCampus = p.campus;
    // a candidate clicked on another campus's ground brings that campus into the panel, so the panel, the inspector
    // and the link all describe one campus (the map stays where it is)
    if (state.campus !== "all" && state.campus !== p.campus) { state.campus = p.campus; paintSelection(); renderPanel(); }
    const s = selection[p.campus]; const oi = s.order.findIndex((o) => o.cid === cid); const o = oi >= 0 ? s.order[oi] : null;
    $("placeEyebrow").textContent = o ? dockEyebrow(p, s, oi + 1) : `Candidate · rank ${p.rankLive || p.rank} of ${countCampus(p.campus)}`; $("placeEyebrow").classList.toggle("is-dock", !!o);
    $("placeTitle").textContent = siteName(p); $("placeSub").textContent = `${CAMPUS[p.campus].label} · ${cid} · ${(p.kind || "").replace(/_/g, " ")} · ${f.geometry.coordinates[1].toFixed(5)}, ${f.geometry.coordinates[0].toFixed(5)}`;
    const bars = IND.map((i) => { const v = p[i.scaled] ?? 0; return `<div class="bar-row${v >= 0.7 ? " is-emphasis" : ""}"><span class="bar-label">${i.label}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.round(v * 100)}%"></span></span><span class="bar-value">${v.toFixed(2)} <span class="bar-detail">×${Math.round(state.weights[i.key] * 100)}</span></span></div>`; }).join("");
    const served = p.coversList.map(([j, cr, m]) => ({ d: destById.get(j), cr, m })).filter((x) => x.d).sort((a, b) => b.d.A_j * b.cr - a.d.A_j * a.cr).slice(0, 8);
    const share = s ? (p.coverage / s.total) : 0;
    const why = [];
    // "a short walk" is up to 250 m, the reach of the coverage credit: count every building this spot gives any credit to
    const nNear = p.coversList.filter(([j]) => destById.has(j)).length, beside = p.nearest_building_m != null && p.nearest_building_m < 5;
    const nb = (p.nearest_building || "").replace(/^Building at /, "the building at ").replace(/^(\d+-storey building off )/, "a $1");  // generated names read as phrases
    why.push(`${nNear ? `Within a short walk of ${nNear} University building${nNear === 1 ? "" : "s"}` : "No University building within a short walk"}${nb ? `; ${beside ? `right beside ${nb}` : `the nearest is ${nb}, ${nf.format(p.nearest_building_m)} m away`}` : ""}. Around ${nf.format(p.coverage)} cyclists a day, ${pct(share)} of the campus's arrivals, end their ride within reach of this spot.`);
    // approach_lts is the calm share of the flow within 40 m, and a neutral 0.5 where no modelled rider passes at all
    const calm = `${pct(p.approach_lts)} of them arrive on calm links`;
    why.push(p.arrival_flow >= 5 ? `About ${nf.format(p.arrival_flow)} riders a day pass here on their way in; ${calm}, so the dock sits on the desire line rather than asking for a detour.`
      : !p.arrival_flow && p.approach_lts === 0.5 ? "No modelled riders pass this exact point, so the calm approach score is a neutral 0.50."
      : `Few riders pass this exact point; ${calm}.`);
    why.push(`Eyes on the street: ${p.surveillance >= 0.6 ? "strong" : p.surveillance >= 0.35 ? "moderate" : "weak"}. There ${p.footway_len_50m == null ? "is footpath" : `are ${nf.format(p.footway_len_50m)} m of footpath`} within 50 m, ${p.active_75m} shop${p.active_75m === 1 ? "" : "s"} or café${p.active_75m === 1 ? "" : "s"} and ${p.bus_stops_100m} bus stop${p.bus_stops_100m === 1 ? "" : "s"} nearby, and ${p.openness == null ? "an unknown share" : pct(p.openness)} of the ground within 20 m is open to view.`);
    why.push(p.lamps_30m > 0 ? `${p.lamps_30m} mapped street lamp${p.lamps_30m === 1 ? "" : "s"} within 30 m.` : "No mapped street lamp within 30 m: confirm lighting on site (OpenStreetMap coverage is patchy).");
    const sp = spacePower(p), slope = `Ground slope ${p.slope_pct == null ? "unknown" : p.slope_pct.toFixed(1) + "%"}${p.slope_pct != null && p.slope_pct <= 2 ? ", which is flat" : ""}.`;
    const room = p.kind === "car_park" ? "The spot is in a car park, which gives room for a 4.8 × 2.2 m station"
      : "The spot is near a car space, plaza or service lane, which gives room for a 4.8 × 2.2 m station";
    why.push(sp ? `${sp.space >= 1 ? room : "Room for a 4.8 × 2.2 m station needs checking on the footpath"}; ${sp.power >= 1 ? "a building close by means mains power is near" : "no building within 30 m, so power may need a longer cable run"}. ${slope}` : slope);
    // mapped racks only: OpenStreetMap says a rack is there, not how often it is used
    const nRacks = +p.racks_40m || 0;
    const racks = nRacks === 1 ? "An open rack is mapped within 40 m" : nRacks > 1 ? `${COUNT_WORD[nRacks] || nRacks} open racks are mapped within 40 m` : "No open rack is mapped within 40 m";
    // store_60m counts the card-access stores within 60 m (it can be 2, as beside Hiwa); store_m and store_name describe the nearest
    const nStores = Math.max(+p.store_60m || 0, p.store_m != null && p.store_m <= 60 ? 1 : 0), value = "this dock's value is for visitors, short stays and charging";
    if (p.store_m != null && p.store_name) {
      const away = `${p.store_approx ? "about " : ""}${nf.format(p.store_m)} m away: ${storeLabel(p.store_name)}.`;
      why.push(`${racks}. ${nStores > 1 ? `${COUNT_WORD[nStores] || nStores} University card-access bike stores are within 60 m. The nearest is ${away} They serve regulars, so ${value}.`
        : nStores === 1 ? `A University card-access bike store is ${away} It serves regulars, so ${value}.` : `The nearest University card-access bike store is ${away}`}`);
    } else why.push(`${racks}${nStores > 1 ? `; ${nStores} card-access University bike stores within 60 m serve regulars, so ${value}` : nStores === 1 ? `; a card-access University bike store within 60 m serves regulars, so ${value}` : ""}.`);
    $("placeBody").innerHTML = `
      <div class="place-section"><h3>Why here</h3>${why.map((w) => `<p>${w}</p>`).join("")}${o ? `<p><span class="badge is-dock">Adds ${nf.format(o.gain)} newly covered arrivals/day</span></p>` : ""}</div>
      <div class="place-section"><h3>Scores (0–1) and weights</h3><div class="bars">${bars}</div><div class="kv"><span class="kv-key">Weighted suitability</span><span class="kv-value"><strong>${p.S.toFixed(2)}</strong></span></div></div>
      <div class="place-section"><h3>Buildings served</h3>${served.map((x) => `<div class="kv"><span class="kv-key">${x.d.label}</span><span class="kv-value">${nf.format(x.m)} m · ${nf.format(x.d.A_j * x.cr)}/day</span></div>`).join("") || "<p class='note'>No University building within a 250 m walk.</p>"}</div>
      <div class="place-section"><h3>Before it goes in</h3><p class="note">Field check the exact kerb or plaza position and the 4.8 × 2.2 m footprint, confirm a power connection (a 10-dock charging station draws 1.5 kW; solar alone was not enough at Glen Eden), CCTV and lighting, sightlines from busy frontages, and who owns the ground (University land versus road reserve, which needs Auckland Transport's approval). Count bikes parked nearby for a week to set a baseline.</p></div>`;
    $("place").hidden = false; document.body.dataset.place = "open";
    if (!still) bringIntoView(f.geometry.coordinates, fly);
    map.getSource("hover").setData({ type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: f.geometry.coordinates }, properties: {} }] });
    document.querySelectorAll("#siteList .rank-row").forEach((b) => b.classList.toggle("is-focus", b.dataset.cid === cid)); writeHash();
  }
  function openBuilding(p, lngLat) {
    hideTip();
    const s = selection[p.campus]; let best = null; state.site = null; placeCampus = p.campus || null;
    document.querySelectorAll("#siteList .rank-row").forEach((b) => b.classList.remove("is-focus"));
    if (s) for (const o of s.order) { const c = byCid.get(o.cid).properties.coversList.find((x) => x[0] === String(p.id)); if (c && (!best || c[2] < best.m)) best = { cid: o.cid, m: c[2], cr: c[1] }; }
    let near = null;  // a building that is not a destination has no walk credits: give the straight-line distance instead
    if (!best && p.A_j == null && s && lngLat) for (const o of s.order) { const m = distM(lngLat, byCid.get(o.cid).geometry.coordinates); if (!near || m < near.m) near = { cid: o.cid, m }; }
    $("placeEyebrow").textContent = "University building"; $("placeEyebrow").classList.remove("is-dock"); $("placeTitle").textContent = buildingName(p); $("placeSub").textContent = `${CAMPUS[p.campus] ? CAMPUS[p.campus].label + " · " : ""}${nf.format(p.gfa_m2)} m² over ${floorsText(p)}`;
    $("placeBody").innerHTML = `<div class="place-section"><div class="kv"><span class="kv-key">Modelled cyclist arrivals</span><span class="kv-value">${p.A_j != null ? nf.format(p.A_j) + " / day" : "none"}</span></div><div class="kv"><span class="kv-key">Use factor</span><span class="kv-value">${p.use_factor ?? "–"}</span></div><div class="kv"><span class="kv-key">Nearest recommended dock</span><span class="kv-value">${best ? `${shortName(byCid.get(best.cid).properties)} · ${nf.format(best.m)} m walk (credit ${best.cr.toFixed(2)})` : near ? `${shortName(byCid.get(near.cid).properties)} · about ${nf.format(Math.max(10, Math.round(near.m / 10) * 10))} m in a straight line` : "none within 250 m"}</span></div></div><p class="note">${p.A_j != null ? "Arrivals are the campus total split by floor area and use; they scale the coverage figures and dock counts, not the ranking of sites."
      : `${notDestination(p)}: ${p.class === "dormitory" ? "rides start here, so it" : "it"} adds no arrivals to the coverage figures.`}</p>`;
    $("place").hidden = false; document.body.dataset.place = "open";
    map.getSource("hover").setData({ type: "FeatureCollection", features: [] }); writeHash();  // a building is not a site: drop the site's marker and link
    if (lngLat) bringIntoView(lngLat, false);
  }
  function closePlace() { $("place").hidden = true; document.body.dataset.place = ""; state.site = null; placeCampus = null; map.getSource("hover").setData({ type: "FeatureCollection", features: [] }); document.querySelectorAll("#siteList .rank-row").forEach((b) => b.classList.remove("is-focus")); writeHash(); }

  // ------------------------------------------------------------------ url state
  function writeHash() { const h = new URLSearchParams({ campus: state.campus, view: state.view, k: `${state.k.city}.${state.k.grafton}.${state.k.newmarket}`, basemap: state.basemap }); if (state.site) h.set("site", state.site); try { history.replaceState(null, "", "#" + h.toString()); } catch (e) { /* sandboxed frames may refuse */ } }
  function readHash() { const h = new URLSearchParams(location.hash.slice(1)); if (CAMPUS[h.get("campus")]) state.campus = h.get("campus"); if (["suit", "flow", "lts", "none"].includes(h.get("view"))) state.view = h.get("view"); if (BASEMAPS.includes(h.get("basemap"))) state.basemap = h.get("basemap");
    const k = (h.get("k") || "").split(".").map(Number); if (k.length === 3 && k.every((x) => x >= 1 && x <= 8)) state.k = { city: k[0], grafton: k[1], newmarket: k[2] };
    // the site: a known candidate on the campus shown (or on any, for "all"); a link without one clears it, and a
    // link with a site but no campus opens on the site's own campus
    const f = byCid.get(h.get("site")); if (f && !CAMPUS[h.get("campus")] && state.campus !== "all") state.campus = f.properties.campus;
    state.site = f && (state.campus === "all" || state.campus === f.properties.campus) ? f.properties.cid : null; }
  const siteFits = (c) => !placeCampus || c === "all" || c === placeCampus;  // does what the place panel shows belong to campus c?
  function syncViewButtons() { document.querySelectorAll("#viewSeg button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.view === state.view)); }
  // back, forward or an edited address: take everything from the new hash, including the absence of a site.
  // A hash that carries none of the map's keys (an in-page anchor such as "#panel") is not map state: ignore it
  // and put the map's own hash back, so the open site stays open and a copied link still describes the map.
  const HASH_KEYS = ["campus", "view", "k", "basemap", "site"];
  function onHashChange() {
    const h = new URLSearchParams(location.hash.slice(1));
    if (!HASH_KEYS.some((key) => h.has(key))) { writeHash(); return; }
    const prevCampus = state.campus, prevSite = state.site; readHash();
    for (const c of ["city", "grafton", "newmarket"]) selection[c] = pickSelection(c, state.k[c]);
    syncViewButtons(); paintSelection(); renderPanel(); applyView(); setBasemap(state.basemap);
    if (state.campus !== prevCampus) fitCampus();
    if (state.site) openSite(state.site, state.site !== prevSite || state.campus !== prevCampus);
    else if (!$("place").hidden) closePlace();
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    // switching campus closes a site or building from another campus, so the panel, the map and the link agree
    document.querySelectorAll('[data-group="campus"] .chip').forEach((b) => b.addEventListener("click", () => { state.campus = b.dataset.value; if (!$("place").hidden && !siteFits(state.campus)) closePlace(); paintSelection(); renderPanel(); fitCampus(); }));
    $("kRange").addEventListener("input", () => { if (state.campus === "all") return; state.k[state.campus] = +$("kRange").value; selection[state.campus] = pickSelection(state.campus, state.k[state.campus]); paintSelection(); renderPanel(); refreshPlace(); });
    document.querySelectorAll(".tabs button").forEach((t) => t.addEventListener("click", () => { document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === t)); ["sites", "weights", "evidence"].forEach((v) => ($(`view-${v}`).hidden = v !== t.dataset.tab)); }));
    document.querySelectorAll("#viewSeg button").forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; document.querySelectorAll("#viewSeg button").forEach((x) => x.setAttribute("aria-pressed", x === b)); applyView(); writeHash(); }));
    $("basemapSeg").innerHTML = BASEMAPS.map((b) => `<button type="button" data-basemap="${b}" aria-pressed="${b === state.basemap}">${BASEMAP_LABEL[b]}</button>`).join("");
    $("basemapSeg").hidden = false;  // index.html ships it empty and hidden, so no build shows a basemap it cannot draw
    document.querySelectorAll("#basemapSeg button").forEach((b) => b.addEventListener("click", () => setBasemap(b.dataset.basemap)));
    const overlays = [["uoa", "University buildings"], ["candidates", "All candidate sites"], ["parking", "Existing bike parking and docks"], ["atfac", "AT cycle facilities"], ["counters", "AT cycle counters (riders/day)"], ["lamps", "Street lamps (OSM)"], ["transit", "Stations and bus stops"], ["portals", "Corridor portals (counter weights)"], ["patches", "LINZ 2024 aerials (Aerial basemap)"], ["context", "Other buildings"]];
    $("layerList").innerHTML = overlays.map(([k, l]) => `<label class="check"><input type="checkbox" data-ov="${k}" ${state.overlays[k] ? "checked" : ""}>${l}</label>`).join("");
    $("layerList").querySelectorAll("input").forEach((i) => i.addEventListener("change", () => { state.overlays[i.dataset.ov] = i.checked; applyOverlays(); applyView(); }));
    $("panelToggle").addEventListener("click", () => setPanel(document.body.dataset.panel === "collapsed"));
    $("placeClose").addEventListener("click", closePlace); document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePlace(); });
    $("aboutBtn").addEventListener("click", () => $("about").showModal());
    // Close About from script: WordPress frames the map with sandbox="allow-scripts" and no allow-forms, which blocks
    // even a method="dialog" form, so the close button would do nothing there. A click outside the panel closes it too.
    document.querySelector("#about .about-close-form button").addEventListener("click", (e) => { e.preventDefault(); $("about").close(); });
    $("about").addEventListener("click", (e) => {
      const d = $("about"); if (e.target !== d) return; const r = d.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
    });
    $("shareBtn").addEventListener("click", async () => { try { await navigator.clipboard.writeText(location.href); $("shareBtn").textContent = "Link copied"; setTimeout(() => ($("shareBtn").textContent = "Copy link"), 1600); } catch (e) { try { prompt("Copy this link", location.href); } catch (x) { /* no dialogs here */ } } });
    $("resetWeights").addEventListener("click", () => { IND.forEach((i) => (state.weights[i.key] = i.w)); state.custom = false; renderWeights(); rescore(); refreshSelection(); $("weightsNote").textContent = ""; });
    syncViewButtons();
    document.querySelectorAll("#basemapSeg button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.basemap === state.basemap));
  }
  // The panel's open or collapsed state, and the toggle's state and name to match. It starts collapsed on a phone,
  // where it is a bottom sheet over the map.
  function setPanel(open) {
    document.body.dataset.panel = open ? "open" : "collapsed";
    const t = $("panelToggle"), label = open ? "Collapse panel" : "Expand panel";
    t.setAttribute("aria-expanded", String(open)); t.setAttribute("aria-label", label); t.title = label;
  }
  // "Skip to controls" moves focus to the panel without touching the hash, which holds the map's state (a site a
  // shared link opened stays open). The controls are inside the panel, so a collapsed panel opens first. On a phone
  // an open site's sheet takes the panel's place, so focus goes to that sheet (its first control closes it).
  function wireSkipLink() {
    const a = document.querySelector(".skip-link"); if (!a) return;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      if (PHONE() && !$("place").hidden) { $("place").focus({ preventScroll: true }); return; }
      if (document.body.dataset.panel === "collapsed") setPanel(true);
      $("panel").focus({ preventScroll: true });
    });
  }
  // In the WordPress embed the clipboard, new tabs and leaving the frame fail without a word: hide Copy link, and show
  // the links that would open a tab or leave the frame (every link with a target: the lab, SPAN) as text.
  function quietSandbox() {
    $("shareBtn").hidden = true;
    document.querySelectorAll("a[target]").forEach((a) => { const t = document.createElement("span"); t.className = a.className; t.append(...a.childNodes); a.replaceWith(t); });
  }
  // On a phone the compact attribution starts as its (i) button, not open over the map; a tap opens it.
  // MapLibre opens a compact attribution when it is added and closes it on the first drag.
  function collapseAttribution() {
    const el = map.getContainer().querySelector(".maplibregl-ctrl-attrib.maplibregl-compact"); if (!el) return;
    el.classList.remove("maplibregl-compact-show"); el.removeAttribute("open");
  }

  // On a desktop the open credits wrap beside the scale bar and can take several lines; an open site's panel stops above
  // them (ld.css reads --credits), so neither hides the other. Folded to the (i) button they need no room.
  function watchCredits() {
    const a = map.getContainer().querySelector(".maplibregl-ctrl-attrib"); if (!a || !window.ResizeObserver) return;
    new ResizeObserver(() => document.body.style.setProperty("--credits", `${a.classList.contains("maplibregl-compact-show") ? Math.ceil(a.getBoundingClientRect().height) : 0}px`)).observe(a);
  }

  function registerInlineGlyphs() {
    const g = window.STAND_GLYPHS || (window.STAND_DATA && window.STAND_DATA.glyphs); if (!g || !maplibregl.addProtocol) return;
    maplibregl.addProtocol("standglyph", async (params) => {
      const key = decodeURIComponent(params.url.replace("standglyph://", "")); const b64 = g[key];
      if (!b64) throw new Error("no inline glyphs for " + key);
      const bin = atob(b64); const bytes = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      return { data: bytes.buffer };
    });
  }
  async function main() {
    setPanel(!PHONE()); wireSkipLink(); if (SANDBOXED) quietSandbox();
    if (typeof maplibregl === "undefined") { $("loading").textContent = "The map library could not load. Check your connection and reload."; hideMapTools(); return; }
    await load(); registerInlineGlyphs();
    // offline: the own-data basemap stops at the wide window, so keep the view on it and on every existing dock (a little
    // padding) and no further out than z12
    const wb = (results.basemap && results.basemap.wide_bbox) || WIDE;
    const docksXY = ((D.locky_docks_existing && D.locky_docks_existing.features) || []).map((f) => f.geometry.coordinates);
    const ob = docksXY.reduce((b, [x, y]) => [Math.min(b[0], x), Math.min(b[1], y), Math.max(b[2], x), Math.max(b[3], y)], wb);
    const maxBounds = OFFLINE ? [[ob[0] - 0.004, ob[1] - 0.003], [ob[2] + 0.004, ob[3] + 0.003]] : undefined;
    map = new maplibregl.Map({ container: "map", style: baseStyle(), center: CAMPUS[state.campus].centre, zoom: CAMPUS[state.campus].zoom, minZoom: 12, maxZoom: 20, maxBounds,
      attributionControl: { compact: true, customAttribution: ATTRIBUTION }, dragRotate: false, pitchWithRotate: false });
    map.touchZoomRotate.disableRotation();
    if (PHONE()) collapseAttribution();
    watchCredits();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right"); map.addControl(new maplibregl.ScaleControl({ maxWidth: 120 }), "bottom-left");
    window.STAND = { map, state, selection, data: D, results: () => results };  // for debugging and scripted captures
    map.on("load", () => { addLayers(); rescore(); wire(); renderWeights(); renderPanel(); $("loading").hidden = true;
      if (state.site && byCid.has(state.site)) openSite(state.site, true); else { state.site = null; fitCampus(); } });
    window.addEventListener("hashchange", () => { if (map && map.getSource("selected")) onHashChange(); });
    $("footNote").textContent = `Overture 2026-09-23 · LINZ LiDAR 2024 · AT counts to July 2026 · v${VERSION}`;
  }
  // without a map the basemap and layer controls do nothing: take them away rather than offer them
  function hideMapTools() { const t = document.querySelector(".map-tools"); if (t) t.hidden = true; }
  main().catch((e) => { $("loading").textContent = "Could not load the data: " + e.message; if (!map || !map.getSource("selected")) hideMapTools(); console.error(e); });
})();
