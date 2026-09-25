import L, { type PathOptions } from "leaflet";
import "leaflet/dist/leaflet.css";
import "maplibre-gl/dist/maplibre-gl.css";

import { midpoint, NetworkGraph, type SketchResult } from "./model";
import type { AppState, CandidateFeature, GenericFeatureCollection, LoadedLayers, PortfolioStep } from "./types";
import type { ResearchReport, ResearchRoute } from "./research-data";

const AUCKLAND_CENTRE: L.LatLngExpression = [-36.855, 174.765];
const BASEMAP_STYLES = {
  light: "https://tiles.openfreemap.org/styles/positron",
  streets: "https://tiles.openfreemap.org/styles/liberty",
} as const;
const BASEMAP_ATTRIBUTION =
  '<a href="https://openfreemap.org/" target="_blank" rel="noopener noreferrer">OpenFreeMap</a> · ' +
  '© <a href="https://openmaptiles.org/" target="_blank" rel="noopener noreferrer">OpenMapTiles</a>';
const OSM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>';

/** Data colours. The map key in views.ts reads the same values. */
export const COLOURS = {
  build: "#1f7a4d",
  selected: "#ea580c",
  other: "#7d8b91",
  existing: "#334155",
  quiet: "#80aaa4",
  street: "#9aa5ab",
  planned: "#7c3aed",
  strategic: "#a78bfa",
  counter: "#0e7490",
  demand: ["#dbe8f8", "#b7d3f6", "#89b6ec", "#5a98e0", "#2f78d1"],
  crashes: ["#fdba74", "#ef4444", "#991b1b"],
} as const;
export const CRASH_BREAKS = [5, 10] as const;
export const NUMBERED_LINKS = 30;

export const BASEMAP_IDS = ["analysis", "light", "streets"] as const;
export type BasemapId = (typeof BASEMAP_IDS)[number];

export interface MapPadding {
  topLeft: [number, number];
  bottomRight: [number, number];
}

export interface SpanMapOptions {
  allowHostedBasemaps: boolean;
  initialBasemap: BasemapId;
  padding: () => MapPadding;
}

export interface MapCallbacks {
  onCandidateSelected: (candidateId: string) => void;
  onSketchChanged: (result: SketchResult | null, error?: string) => void;
  onBasemapChanged: (basemap: BasemapId) => void;
}

const PANES = [
  ["demand", 350],
  ["context", 380],
  ["others", 400],
  ["build", 420],
  ["selected", 440],
  ["points", 460],
] as const;

export class SpanMap {
  readonly map: L.Map;
  /** Class edges for the demand squares in the current view, and whether any have a value. */
  demandBreaks: number[] = [];
  demandEmpty = true;
  private readonly groups = new Map<string, L.LayerGroup>();
  private readonly sketchGroup = L.layerGroup();
  private layers: LoadedLayers = {};
  private candidates = new Map<string, CandidateFeature>();
  private othersLayer: L.GeoJSON | null = null;
  private demandLayer: L.GeoJSON | null = null;
  private existingLayer: L.GeoJSON | null = null;
  private highlightedAreas = new Set<string>();
  private highlightedAreaKey = "";
  private pins: Array<{ marker: L.Marker; latLng: L.LatLng }> = [];
  private state: AppState | null = null;
  private steps: PortfolioStep[] = [];
  private networkGraph: NetworkGraph | null = null;
  private sketchPoints: [number, number][] = [];
  private hasFitted = false;
  private demandKey = "";
  private drawn = new Map<string, unknown>();
  private basemapLayer: L.Layer | null = null;
  private basemap: BasemapId = "analysis";
  private loadingBasemap: BasemapId | null = null;
  private basemapRequest = 0;
  private connectedMode = false;
  private readonly connectedGroup = L.featureGroup();
  private rankingView: { centre: L.LatLng; zoom: number } | null = null;

  constructor(
    element: HTMLElement,
    private readonly callbacks: MapCallbacks,
    private readonly options: SpanMapOptions,
  ) {
    this.map = L.map(element, {
      center: AUCKLAND_CENTRE,
      zoom: 11,
      minZoom: 9,
      maxZoom: 18,
      preferCanvas: true,
      zoomAnimation: false,
      attributionControl: true,
      zoomControl: false,
    });
    this.map.attributionControl.setPrefix(false);
    this.map.attributionControl.addAttribution(OSM_ATTRIBUTION);
    L.control.zoom({ position: "bottomright" }).addTo(this.map);
    for (const [name, zIndex] of PANES) this.map.createPane(name).style.zIndex = String(zIndex);
    this.setBasemap(options.initialBasemap, false);
    for (const id of ["cells", "existing", "network", "programmes", "safety", "build", "badges", "selected", "counters", "intersections"]) {
      this.groups.set(id, L.layerGroup().addTo(this.map));
    }
    this.sketchGroup.addTo(this.map);
    this.map.on("click", (event: L.LeafletMouseEvent) => this.handleSketchClick(event));
    this.map.on("zoomend", () => {
      this.layoutPins();
      this.demandLayer?.setStyle({ fillOpacity: this.demandOpacity() });
    });
  }

  /** Demand squares overlap, so they fade as the map zooms in on the links. */
  private demandOpacity(): number {
    const zoom = this.map.getZoom();
    return zoom >= 15 ? 0.2 : zoom >= 13 ? 0.34 : 0.55;
  }

  /** Numbered pins that would overlap give way to the lower number. */
  private layoutPins(): void {
    const badges = this.group("badges");
    badges.clearLayers();
    const placed: L.Point[] = [];
    for (const pin of this.pins) {
      const point = this.map.latLngToLayerPoint(pin.latLng);
      if (placed.some((other) => other.distanceTo(point) < 24)) continue;
      placed.push(point);
      pin.marker.addTo(badges);
    }
  }

  get activeBasemap(): BasemapId {
    return this.basemap;
  }

  get hasNetwork(): boolean {
    return this.networkGraph !== null;
  }

  setBasemap(requestedBasemap: BasemapId, notify = true): void {
    const nextBasemap =
      this.options.allowHostedBasemaps || requestedBasemap === "analysis" ? requestedBasemap : "analysis";
    if (
      nextBasemap === this.basemap &&
      (nextBasemap === "analysis" || this.basemapLayer || this.loadingBasemap === nextBasemap)
    ) return;
    this.basemapRequest += 1;
    const request = this.basemapRequest;
    if (this.basemapLayer) {
      this.map.removeLayer(this.basemapLayer);
      this.basemapLayer = null;
    }
    this.loadingBasemap = null;
    this.basemap = nextBasemap;
    if (nextBasemap !== "analysis") {
      this.loadingBasemap = nextBasemap;
      void this.addHostedBasemap(nextBasemap, request);
    }
    if (notify) this.callbacks.onBasemapChanged(nextBasemap);
  }

  private async addHostedBasemap(basemap: Exclude<BasemapId, "analysis">, request: number): Promise<void> {
    // MapLibre 6 finds its worker from a URL built at run time, which the bundler
    // cannot see. Bundle the worker here and hand over its address before any
    // basemap is made; without it no vector tiles load and the basemap stays blank.
    const [{ maplibreGL }, maplibre, worker] = await Promise.all([
      import("@maplibre/maplibre-gl-leaflet"),
      import("maplibre-gl"),
      import("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url"),
    ]);
    maplibre.setWorkerUrl(worker.default);
    if (request !== this.basemapRequest || basemap !== this.basemap) return;
    this.basemapLayer = maplibreGL({
      style: BASEMAP_STYLES[basemap],
      attributionControl: { compact: true, customAttribution: BASEMAP_ATTRIBUTION },
    }).addTo(this.map);
    this.loadingBasemap = null;
  }

  setData(layers: LoadedLayers, candidates: CandidateFeature[]): void {
    this.layers = layers;
    if (layers.network && !this.networkGraph) this.networkGraph = NetworkGraph.fromGeoJson(layers.network);
    if (candidates.length !== this.candidates.size) {
      this.candidates = new Map(candidates.map((item) => [item.properties.candidateId, item]));
      this.othersLayer = null;
    }
    this.drawn.clear();
    this.demandKey = "";
    this.render();
  }

  update(state: AppState, steps: PortfolioStep[]): void {
    this.state = state;
    this.steps = steps;
    this.render();
  }

  /** Both investment views use this map and its current basemap. */
  setConnectedMode(active: boolean): void {
    if (active === this.connectedMode) return;
    this.map.stop();
    this.map.closePopup();
    this.connectedMode = active;
    if (active) {
      this.rankingView = { centre: this.map.getCenter(), zoom: this.map.getZoom() };
      for (const group of this.groups.values()) group.remove();
      this.othersLayer?.remove();
      this.sketchGroup.remove();
      this.connectedGroup.addTo(this.map);
    } else {
      this.connectedGroup.remove();
      for (const group of this.groups.values()) group.addTo(this.map);
      this.sketchGroup.addTo(this.map);
      this.render();
      if (this.rankingView) this.map.setView(this.rankingView.centre, this.rankingView.zoom, { animate: false });
    }
  }

  showConnectedRoute(report: ResearchReport, route?: ResearchRoute, fundedProjects: readonly string[] = []): void {
    if (!this.connectedMode) return;
    this.map.stop();
    this.connectedGroup.clearLayers();
    if (!route) {
      this.map.setView([report.centre[1], report.centre[0]], 13, { animate: false });
      return;
    }
    const points = (coordinates: number[][]): L.LatLngExpression[] => coordinates.map(p => [p[1]!, p[0]!]);
    for (const project of report.projects.filter(p => route.projectIds.includes(p.id))) {
      L.polyline(points(project.coordinates), { color: COLOURS.selected, weight: 3, dashArray: "5 5", opacity: 0.65 }).addTo(this.connectedGroup);
    }
    for (const segment of route.segments) {
      L.polyline(points(segment.coordinates), { color: "white", weight: 8, interactive: false }).addTo(this.connectedGroup);
    }
    for (const segment of route.segments) {
      const missing = segment.projectId && !fundedProjects.includes(segment.projectId);
      L.polyline(points(segment.coordinates), { color: missing ? "#b42318" : segment.projectId ? COLOURS.selected : segment.existingCycleway ? COLOURS.build : COLOURS.street, weight: 5, dashArray: missing ? "6 6" : undefined, className: "connected-route-line" }).addTo(this.connectedGroup);
    }
    const ends = [route.segments[0]?.coordinates[0], route.segments.at(-1)?.coordinates.at(-1)];
    ends.forEach((p, i) => { if (p) L.marker([p[1], p[0]], { icon: L.divIcon({ className: "connected-end", html: i === 0 ? "A" : "B", iconSize: [26, 26] }), title: i === 0 ? "Journey start" : "Journey end" }).addTo(this.connectedGroup); });
    const bounds = this.connectedGroup.getBounds();
    if (bounds.isValid()) this.map.fitBounds(bounds, { ...this.paddingOptions(), maxZoom: 16, animate: false });
  }

  showConnectedPackage(report: ResearchReport, fundedProjects: readonly string[], inspectProject: (id: string) => void): void {
    if (!this.connectedMode) return;
    this.map.stop();
    this.connectedGroup.clearLayers();
    const projects = report.projects.filter(project => fundedProjects.includes(project.id));
    for (const [index, project] of projects.entries()) {
      const coordinates: L.LatLngExpression[] = project.coordinates.map(p => [p[1], p[0]]);
      L.polyline(coordinates, { color: "white", weight: 9, interactive: false }).addTo(this.connectedGroup);
      const line = L.polyline(coordinates, { color: COLOURS.selected, weight: 5 }).addTo(this.connectedGroup);
      const label = document.createElement("span"); label.textContent = project.name;
      line.bindTooltip(label, { sticky: true });
      line.on("click", () => inspectProject(project.id));
      const centre = line.getCenter();
      L.marker(centre, { icon: L.divIcon({ className: "connected-package-pin", html: String(index + 1), iconSize: [24, 24] }), title: `Inspect ${project.name}` }).on("click", () => inspectProject(project.id)).addTo(this.connectedGroup);
    }
    const bounds = this.connectedGroup.getBounds();
    if (bounds.isValid()) this.map.fitBounds(bounds, { ...this.paddingOptions(), maxZoom: 16, animate: false });
    else this.map.setView([report.centre[1], report.centre[0]], 13, { animate: false });
  }

  /** Show the whole build order, clear of the panels. */
  fitBuildOrder(): void {
    const bounds = L.latLngBounds([]);
    for (const step of this.steps) {
      const feature = this.candidates.get(step.candidateId);
      if (feature) bounds.extend(L.geoJSON(feature as never).getBounds());
    }
    if (!bounds.isValid()) {
      for (const feature of this.candidates.values()) bounds.extend(L.geoJSON(feature as never).getBounds());
    }
    if (bounds.isValid()) this.map.fitBounds(bounds, { ...this.paddingOptions(), maxZoom: 15 });
  }

  focusCandidate(candidateId: string): void {
    const feature = this.candidates.get(candidateId);
    if (!feature) return;
    const bounds = L.geoJSON(feature as never).getBounds();
    const current = this.map.getBounds();
    if (current.contains(bounds) && this.map.getZoom() >= 13) return;
    this.map.flyToBounds(bounds.pad(0.25), { ...this.paddingOptions(), maxZoom: 16, duration: 0.6 });
  }

  focusCandidates(candidateIds: string[]): void {
    const bounds = L.latLngBounds([]);
    for (const id of candidateIds) {
      const feature = this.candidates.get(id);
      if (feature) bounds.extend(L.geoJSON(feature as never).getBounds());
    }
    if (bounds.isValid()) this.map.flyToBounds(bounds.pad(0.15), { ...this.paddingOptions(), maxZoom: 15, duration: 0.6 });
  }

  private paddingOptions(): L.FitBoundsOptions {
    const padding = this.options.padding();
    return { paddingTopLeft: padding.topLeft, paddingBottomRight: padding.bottomRight };
  }

  setSketchNodes(nodeIds: string[]): void {
    this.sketchPoints = [];
    this.sketchGroup.clearLayers();
    if (nodeIds.length < 2 || !this.networkGraph) {
      this.callbacks.onSketchChanged(null);
      return;
    }
    try {
      const result = this.networkGraph.scoreSketchNodes(nodeIds);
      this.drawSketch(result);
      this.callbacks.onSketchChanged(result);
    } catch (error) {
      this.callbacks.onSketchChanged(null, error instanceof Error ? error.message : "Unable to join those points");
    }
  }

  clearSketch(): void {
    this.sketchPoints = [];
    this.sketchGroup.clearLayers();
    this.callbacks.onSketchChanged(null);
  }

  private render(): void {
    if (!this.state || this.connectedMode) return;
    this.renderDemand();
    this.renderOnce("existing", () => this.drawExisting());
    this.highlightExisting();
    this.renderOnce("network", () => this.drawNetwork());
    this.renderOnce("programmes", () => this.drawProgrammes());
    this.renderOnce("safety", () => this.drawSafety());
    this.renderOnce("counters", () => this.drawCounters());
    this.renderOnce("intersections", () => this.drawIntersections());
    this.renderOthers();
    this.renderBuildOrder();
    this.renderSelected();
    if (!this.hasFitted && this.candidates.size) {
      this.hasFitted = true;
      this.fitBuildOrder();
    }
  }

  private visible(id: string): boolean {
    return Boolean(this.state?.visibleLayerIds.has(id));
  }

  private group(id: string): L.LayerGroup {
    const group = this.groups.get(id);
    if (!group) throw new Error(`Map layer group not found: ${id}`);
    return group;
  }

  /** Context layers do not change with the view, so they are drawn once and toggled. */
  private renderOnce(id: keyof LoadedLayers, draw: () => L.Layer): void {
    const group = this.group(id);
    const source = this.layers[id];
    if (!source || !this.visible(id)) {
      group.clearLayers();
      this.drawn.delete(id);
      return;
    }
    if (this.drawn.get(id) === source) return;
    group.clearLayers();
    draw().addTo(group);
    this.drawn.set(id, source);
  }

  private renderDemand(): void {
    const state = this.state!;
    const cells = this.layers.cells;
    const key = `${String(Boolean(cells))}|${String(this.visible("cells"))}|${state.scenario}|${state.purpose}`;
    if (key === this.demandKey) return;
    this.demandKey = key;
    const group = this.group("cells");
    group.clearLayers();
    this.demandLayer = null;
    const values = (feature: { properties?: unknown } | undefined): number => {
      const byScenario = recordValue(recordValue(recordValue(feature?.properties).values)[state.scenario]);
      return numericValue(byScenario[state.purpose]);
    };
    const positive = (cells?.features ?? []).map(values).filter((value) => value > 0).sort((a, b) => a - b);
    this.demandEmpty = positive.length === 0;
    this.demandBreaks = [0.2, 0.4, 0.6, 0.8].map((q) => positive[Math.floor(q * (positive.length - 1))] ?? 0);
    if (!cells || !this.visible("cells") || this.demandEmpty) return;
    this.demandLayer = L.geoJSON(cells as never, {
      pane: "demand",
      interactive: false,
      filter: (feature) => values(feature) > 0,
      style: (feature) => ({
        stroke: false,
        fillColor: COLOURS.demand[classify(values(feature), this.demandBreaks)],
        fillOpacity: this.demandOpacity(),
      }),
    }).addTo(group);
  }

  private renderOthers(): void {
    const show = this.visible("candidates");
    if (!show) {
      if (this.othersLayer) this.map.removeLayer(this.othersLayer);
      return;
    }
    if (!this.othersLayer) {
      const collection = { type: "FeatureCollection", features: [...this.candidates.values()] };
      this.othersLayer = L.geoJSON(collection as never, {
        pane: "others",
        style: { color: COLOURS.other, weight: 1.6, opacity: 0.55 },
        onEachFeature: (feature, layer) => {
          const id = candidateId(feature);
          layer.on("click", (event: L.LeafletMouseEvent) => {
            if (this.state?.sketching) return;
            L.DomEvent.stopPropagation(event);
            this.callbacks.onCandidateSelected(id);
          });
          layer.bindTooltip(tooltipText(this.candidates.get(id)), { sticky: true });
        },
      });
    }
    if (!this.map.hasLayer(this.othersLayer)) this.othersLayer.addTo(this.map);
  }

  private renderBuildOrder(): void {
    const lines = this.group("build");
    const badges = this.group("badges");
    lines.clearLayers();
    badges.clearLayers();
    this.pins = [];
    for (const step of this.steps) {
      const feature = this.candidates.get(step.candidateId);
      if (!feature) continue;
      const latLngs = toLatLngs(feature);
      L.polyline(latLngs, { pane: "build", color: "#ffffff", weight: 7, opacity: 0.9, interactive: false }).addTo(lines);
      const line = L.polyline(latLngs, { pane: "build", color: COLOURS.build, weight: 4, opacity: 1 });
      line.bindTooltip(`${String(step.step)}. ${tooltipText(feature)}`, { sticky: true });
      line.on("click", (event: L.LeafletMouseEvent) => this.select(event, step.candidateId));
      line.on("mouseover", () => line.setStyle({ weight: 6 }));
      line.on("mouseout", () => line.setStyle({ weight: 4 }));
      line.addTo(lines);
      if (step.step <= NUMBERED_LINKS) {
        const [longitude, latitude] = midpoint(feature.geometry);
        const pin = L.marker([latitude, longitude], {
          icon: L.divIcon({ className: "rank-pin", html: `<span>${String(step.step)}</span>`, iconSize: [22, 22] }),
          keyboard: false,
          title: `${String(step.step)}. ${feature.properties.name}`,
          riseOnHover: true,
        });
        pin.on("click", (event: L.LeafletMouseEvent) => this.select(event, step.candidateId));
        this.pins.push({ marker: pin, latLng: L.latLng(latitude, longitude) });
      }
    }
    this.layoutPins();
  }

  private renderSelected(): void {
    const group = this.group("selected");
    group.clearLayers();
    for (const id of this.state?.focusedGroupIds ?? []) {
      if (id === this.state?.selectedCandidateId) continue;
      const member = this.candidates.get(id);
      if (!member) continue;
      const line = L.polyline(toLatLngs(member), { pane: "selected", color: COLOURS.selected, weight: 5, opacity: 0.85 });
      line.on("click", (event: L.LeafletMouseEvent) => this.select(event, id));
      line.addTo(group);
    }
    const feature = this.state?.selectedCandidateId ? this.candidates.get(this.state.selectedCandidateId) : undefined;
    if (!feature) return;
    const latLngs = toLatLngs(feature);
    L.polyline(latLngs, { pane: "selected", color: "#ffffff", weight: 10, opacity: 0.95, interactive: false }).addTo(group);
    L.polyline(latLngs, { pane: "selected", color: COLOURS.selected, weight: 6, opacity: 1, interactive: false }).addTo(group);
    for (const contact of feature.properties.networkContext?.contacts ?? []) {
      L.circleMarker([contact.coordinates[1], contact.coordinates[0]], {
        pane: "selected", radius: 4, color: "#ffffff", weight: 1.5,
        fillColor: COLOURS.counter, fillOpacity: 1,
      }).bindTooltip("Junction with an existing low-stress street or path").addTo(group);
    }
    for (const endpoint of feature.properties.networkContext?.endpoints ?? []) {
      const marker = L.marker([endpoint.coordinates[1], endpoint.coordinates[0]], {
        pane: "points",
        icon: L.divIcon({ className: "endpoint-pin", html: `<span>${endpoint.label}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        title: `${endpoint.label}: ${endpoint.componentId ? "existing low-stress connection" : "no low-stress street at this end"}`,
      });
      marker.bindTooltip(marker.options.title ?? "").addTo(group);
    }
  }

  private select(event: L.LeafletMouseEvent, id: string): void {
    if (this.state?.sketching) return;
    L.DomEvent.stopPropagation(event);
    this.callbacks.onCandidateSelected(id);
  }

  private drawExisting(): L.Layer {
    this.existingLayer = L.geoJSON(this.layers.existing as never, {
      pane: "context",
      interactive: false,
      style: (feature): PathOptions => this.existingStyle(feature?.properties),
    });
    return this.existingLayer;
  }

  private existingStyle(properties: unknown): PathOptions {
    const props = recordValue(properties);
    const selected = this.highlightedAreas.has(stringValue(props.componentId, ""));
    const separated = props.kind === "separated";
    return {
      color: selected ? COLOURS.counter : separated ? COLOURS.existing : COLOURS.quiet,
      weight: selected ? 2.5 : separated ? 2.6 : 1.4,
      opacity: selected ? 0.95 : this.highlightedAreas.size ? 0.3 : separated ? 0.9 : 0.65,
    };
  }

  private highlightExisting(): void {
    const ids = this.state?.focusedGroupIds.size ? [...this.state.focusedGroupIds]
      : this.state?.selectedCandidateId ? [this.state.selectedCandidateId] : [];
    const areas = new Set(ids.flatMap((id) => this.candidates.get(id)?.properties.networkContext?.componentIds ?? []));
    const key = [...areas].sort().join("|");
    if (key === this.highlightedAreaKey) return;
    this.highlightedAreas = areas;
    this.highlightedAreaKey = key;
    this.existingLayer?.setStyle((feature) => this.existingStyle(feature?.properties));
  }

  private drawNetwork(): L.Layer {
    return L.geoJSON(this.layers.network as never, {
      pane: "context",
      interactive: false,
      style: (feature): PathOptions => {
        const existing = recordValue(feature?.properties).protected === true;
        return existing
          ? { color: COLOURS.existing, weight: 2.4, opacity: 0.9 }
          : { color: COLOURS.street, weight: 1, opacity: 0.5, dashArray: "3 5" };
      },
    });
  }

  private drawProgrammes(): L.Layer {
    return L.geoJSON(this.layers.programmes as never, {
      pane: "context",
      style: (feature): PathOptions => {
        const project = recordValue(feature?.properties).status !== "strategic";
        return project
          ? { color: COLOURS.planned, weight: 4, opacity: 0.85 }
          : { color: COLOURS.strategic, weight: 2.5, opacity: 0.8, dashArray: "6 6" };
      },
      onEachFeature: (feature, layer) => {
        const properties = recordValue(feature.properties);
        const label = document.createElement("span");
        label.textContent = `${stringValue(properties.name, "AT route")}: ${programmeStatusText(properties.status)}`;
        layer.bindTooltip(label, { sticky: true });
      },
    });
  }

  private drawSafety(): L.Layer {
    return L.geoJSON(this.layers.safety as never, {
      pane: "context",
      style: (feature): PathOptions => {
        const count = numericValue(recordValue(feature?.properties).crashCount);
        return {
          color: "#7f1d1d",
          weight: 0.6,
          fillColor: COLOURS.crashes[classify(count, [...CRASH_BREAKS])],
          fillOpacity: 0.5,
        };
      },
      onEachFeature: (feature, layer) => {
        const properties = recordValue(feature.properties);
        const label = document.createElement("span");
        const serious = numericValue(properties.fatalSeriousCount);
        label.textContent =
          `${String(numericValue(properties.crashCount))} crashes involving a bike, 2016–2025` +
          (serious ? `, ${String(serious)} fatal or serious` : "");
        layer.bindTooltip(label, { sticky: true });
      },
    });
  }

  private drawIntersections(): L.Layer {
    return L.geoJSON(this.layers.intersections as never, {
      pane: "points",
      pointToLayer: (feature, latlng) => {
        const p = recordValue(feature.properties);
        const matched = p.matchStatus === "matched";
        const marker = L.circleMarker(latlng, {
          pane: "points", radius: matched ? 5 : 3.5, weight: 1.2, color: "#ffffff",
          fillColor: matched ? (p.controlled ? "#7c3aed" : "#b45309") : "#64748b",
          fillOpacity: 0.9,
        });
        const label = document.createElement("span");
        label.textContent = stringValue(p.name, "AT intersection");
        marker.bindTooltip(label);
        const popup = document.createElement("div");
        popup.className = "intersection-popup";
        const title = document.createElement("strong");
        title.textContent = label.textContent;
        popup.append(title);
        const status = document.createElement("p");
        status.textContent = matched
          ? `Matched to a SPAN junction, ${numericValue(p.matchDistanceM).toFixed(1)} m from the AT point. ${String(numericValue(p.movementCount))} directed movements represented.`
          : `Needs review: ${String(p.matchStatus).replaceAll("_", " ")}. No delay applied.`;
        popup.append(status);
        if (matched) {
          const delay = document.createElement("p");
          delay.textContent = `Assumed delay: ${String(numericValue(p.delayS))} seconds per passage; sensitivity range ${String(numericValue(p.delayLowS))}–${String(numericValue(p.delayHighS))} seconds. ${p.controlled ? "AT records signal control." : "AT does not record signal control."}`;
          popup.append(delay);
        }
        const note = document.createElement("p");
        note.textContent = "These are screening assumptions. Actual phases, bicycle detection and waiting times require AT data. The main build order does not include these delays.";
        popup.append(note);
        marker.bindPopup(popup, { maxWidth: 310 });
        return marker;
      },
    });
  }

  private drawCounters(): L.Layer {
    return L.geoJSON(this.layers.counters as never, {
      pane: "points",
      pointToLayer: (feature, latlng) => {
        const properties = recordValue(feature.properties);
        const observed = numericValue(properties.observedDaily);
        const marker = L.circleMarker(latlng, {
          pane: "points",
          radius: 3.5 + Math.min(6, Math.sqrt(observed) / 6),
          color: "#ffffff",
          weight: 1.5,
          fillColor: COLOURS.counter,
          fillOpacity: 0.9,
        });
        const label = document.createElement("span");
        label.textContent = `${stringValue(properties.siteName, "Counter")}: about ${Math.round(observed).toLocaleString("en-NZ")} bikes a day`;
        marker.bindTooltip(label);
        return marker;
      },
    });
  }

  private handleSketchClick(event: L.LeafletMouseEvent): void {
    if (this.connectedMode) return;
    if (!this.state?.sketching || !this.networkGraph) return;
    this.sketchPoints.push([event.latlng.lng, event.latlng.lat]);
    L.circleMarker(event.latlng, sketchPoint()).addTo(this.sketchGroup);
    if (this.sketchPoints.length < 2) {
      this.callbacks.onSketchChanged(null);
      return;
    }
    try {
      const result = this.networkGraph.scoreSketch(this.sketchPoints);
      this.drawSketch(result);
      this.callbacks.onSketchChanged(result);
    } catch (error) {
      this.callbacks.onSketchChanged(null, error instanceof Error ? error.message : "Unable to join those points");
    }
  }

  private drawSketch(result: SketchResult): void {
    this.sketchGroup.clearLayers();
    for (const coordinates of result.coordinates) {
      L.polyline(
        coordinates.map(([longitude, latitude]) => [latitude, longitude] as [number, number]),
        { pane: "selected", color: COLOURS.selected, weight: 6, opacity: 0.92, dashArray: "10 6" },
      ).addTo(this.sketchGroup);
    }
    for (const nodeId of result.nodeIds) {
      const coordinate = this.networkGraph?.nodeCoordinates.get(nodeId);
      if (coordinate) L.circleMarker([coordinate[1], coordinate[0]], sketchPoint()).addTo(this.sketchGroup);
    }
  }
}

export function classify(value: number, breaks: readonly number[]): number {
  const index = breaks.findIndex((edge) => value < edge);
  return index === -1 ? breaks.length : index;
}

export function programmeStatusText(status: unknown): string {
  if (status === "committed") return "committed AT project";
  if (status === "planned") return "planned AT project";
  return "Future Connect route";
}

function sketchPoint(): L.CircleMarkerOptions {
  return { pane: "points", radius: 6, color: "#ffffff", weight: 2, fillColor: COLOURS.selected, fillOpacity: 1 };
}

function toLatLngs(feature: CandidateFeature): L.LatLngExpression[][] {
  const parts = feature.geometry.type === "LineString" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  return parts.map((part) => part.map(([longitude, latitude]) => [latitude, longitude] as [number, number]));
}

function tooltipText(feature: CandidateFeature | undefined): string {
  if (!feature) return "Candidate link";
  return /^Candidate candidate-/.test(feature.properties.name) ? "Unnamed street" : feature.properties.name;
}

function candidateId(feature: { properties?: unknown }): string {
  return stringValue(recordValue(feature.properties).candidateId, "");
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function numericValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export type { GenericFeatureCollection };
