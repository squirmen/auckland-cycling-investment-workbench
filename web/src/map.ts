import L, { type GeoJSON as LeafletGeoJson, type Layer, type PathOptions } from "leaflet";
import "leaflet/dist/leaflet.css";

import { candidatePropertiesSchema, type AppState, type CandidateFeature, type LoadedLayers } from "./types";
import { metricFor, NetworkGraph, type SketchResult } from "./model";

const AUCKLAND_CENTRE: L.LatLngExpression = [-36.855, 174.765];

export interface MapCallbacks {
  onCandidateSelected: (candidateId: string) => void;
  onSketchChanged: (result: SketchResult | null, error?: string) => void;
}

export class WorkbenchMap {
  readonly map: L.Map;
  private readonly groups = new Map<string, L.LayerGroup>();
  private readonly sketchGroup = L.layerGroup();
  private layers: LoadedLayers = {};
  private state: AppState | null = null;
  private networkGraph: NetworkGraph | null = null;
  private sketchPoints: [number, number][] = [];
  private hasFitted = false;

  constructor(element: HTMLElement, private readonly callbacks: MapCallbacks) {
    this.map = L.map(element, {
      center: AUCKLAND_CENTRE,
      zoom: 12,
      minZoom: 9,
      maxZoom: 18,
      preferCanvas: true,
      attributionControl: false,
      zoomControl: true,
    });
    for (const id of ["cells", "network", "candidates", "programmes", "counters"]) {
      const group = L.layerGroup().addTo(this.map);
      this.groups.set(id, group);
    }
    this.sketchGroup.addTo(this.map);
    this.map.on("click", (event: L.LeafletMouseEvent) => this.handleSketchClick(event));
  }

  setLayers(layers: LoadedLayers): void {
    this.layers = layers;
    if (layers.network) this.networkGraph = NetworkGraph.fromGeoJson(layers.network);
    this.render();
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
      this.callbacks.onSketchChanged(
        null,
        error instanceof Error ? error.message : "Unable to route the requested sketch",
      );
    }
  }

  update(state: AppState): void {
    this.state = state;
    this.render();
  }

  clearSketch(): void {
    this.sketchPoints = [];
    this.sketchGroup.clearLayers();
    this.callbacks.onSketchChanged(null);
  }

  private render(): void {
    if (!this.state) return;
    this.renderCells();
    this.renderNetwork();
    this.renderCandidates();
    this.renderProgrammes();
    this.renderCounters();
    if (!this.hasFitted) this.fitToContent();
  }

  private group(id: string): L.LayerGroup {
    const group = this.groups.get(id);
    if (!group) throw new Error(`Map layer group not found: ${id}`);
    return group;
  }

  private isVisible(id: string): boolean {
    return Boolean(this.state?.visibleLayerIds.has(id));
  }

  private renderCells(): void {
    const group = this.group("cells");
    group.clearLayers();
    if (!this.layers.cells || !this.isVisible("cells") || !this.state) return;
    const state = this.state;
    L.geoJSON(this.layers.cells as never, {
      style: (feature) => {
        const values = recordValue(recordValue(feature?.properties).values);
        const scenarioValues = recordValue(values[state.scenario]);
        const rawValue = scenarioValues[state.purpose];
        const value = typeof rawValue === "number" ? rawValue : 0;
        return {
          color: "#ffffff",
          weight: 0.35,
          fillColor: cellColor(value),
          fillOpacity: 0.66,
        };
      },
    }).addTo(group);
  }

  private renderNetwork(): void {
    const group = this.group("network");
    group.clearLayers();
    if (!this.layers.network || !this.isVisible("network")) return;
    L.geoJSON(this.layers.network as never, {
      style: (feature) => {
        const protectedFacility = recordValue(feature?.properties).protected === true;
        return {
          color: protectedFacility ? "#007f73" : "#7b8794",
          weight: protectedFacility ? 3.2 : 1.1,
          opacity: protectedFacility ? 0.9 : 0.4,
          dashArray: protectedFacility ? undefined : "3 5",
        };
      },
    }).addTo(group);
  }

  private renderCandidates(): void {
    const group = this.group("candidates");
    group.clearLayers();
    if (!this.layers.candidates || !this.isVisible("candidates") || !this.state) return;
    const state = this.state;
    const portfolioIds = state.portfolioIds;
    const layer = L.geoJSON(this.layers.candidates as never, {
      style: (feature): PathOptions => {
        const parsed = candidatePropertiesSchema.safeParse(feature?.properties);
        if (!parsed.success) return { color: "#6b7280", weight: 2 };
        const selected = parsed.data.candidateId === state.selectedCandidateId;
        const metric = metricFor(
          { type: "Feature", geometry: feature!.geometry as never, properties: parsed.data } as CandidateFeature,
          state.scenario,
          state.purpose,
        );
        const active = portfolioIds.has(parsed.data.candidateId);
        return {
          color: selected ? "#ea580c" : active ? "#0f5c6e" : "#9ca3af",
          weight:
            selected
              ? 7
              : 3 + Math.min(2.5, (metric.odLowStressShareDelta ?? 0) * 60),
          opacity: selected ? 1 : active ? 0.88 : 0.55,
        };
      },
      onEachFeature: (feature, featureLayer) => {
        const parsed = candidatePropertiesSchema.safeParse(feature.properties);
        if (!parsed.success) return;
        featureLayer.on("click", () => this.callbacks.onCandidateSelected(parsed.data.candidateId));
        if ("setStyle" in featureLayer) {
          featureLayer.on("mouseover", () => (featureLayer as L.Path).setStyle({ weight: 7 }));
          featureLayer.on("mouseout", () => this.renderCandidates());
        }
      },
    });
    layer.addTo(group);
  }

  private renderProgrammes(): void {
    const group = this.group("programmes");
    group.clearLayers();
    if (!this.layers.programmes || !this.isVisible("programmes")) return;
    L.geoJSON(this.layers.programmes as never, {
      style: (feature) => {
        const funded = recordValue(feature?.properties).status === "funded";
        return {
          color: funded ? "#7c3aed" : "#a855f7",
          weight: funded ? 5 : 3,
          opacity: 0.75,
          dashArray: funded ? undefined : "7 7",
        };
      },
    }).addTo(group);
  }

  private renderCounters(): void {
    const group = this.group("counters");
    group.clearLayers();
    if (!this.layers.counters || !this.isVisible("counters")) return;
    L.geoJSON(this.layers.counters as never, {
      pointToLayer: (feature, latlng) => {
        const properties = recordValue(feature.properties);
        const observed = numericValue(properties.observedDaily);
        const modelled = numericValue(properties.modelledDaily);
        const ratio = observed > 0 ? modelled / observed : 0;
        return L.circleMarker(latlng, {
          radius: 4 + Math.min(7, Math.sqrt(observed) / 9),
          color: "#ffffff",
          weight: 1,
          fillColor: ratio > 1.5 ? "#dc2626" : ratio < 0.67 ? "#2563eb" : "#16a34a",
          fillOpacity: 0.85,
        });
      },
    }).addTo(group);
  }

  private fitToContent(): void {
    const bounds = L.latLngBounds([]);
    for (const id of ["cells", "network", "candidates"]) {
      this.group(id).eachLayer((layer: Layer) => {
        if ("getBounds" in layer) bounds.extend((layer as LeafletGeoJson).getBounds());
      });
    }
    if (bounds.isValid()) {
      this.map.fitBounds(bounds.pad(0.06), { maxZoom: 14 });
      this.hasFitted = true;
    }
  }

  private handleSketchClick(event: L.LeafletMouseEvent): void {
    if (!this.state?.sketching || !this.networkGraph) return;
    this.sketchPoints.push([event.latlng.lng, event.latlng.lat]);
    L.circleMarker(event.latlng, {
      radius: 6,
      color: "#ffffff",
      weight: 2,
      fillColor: "#ea580c",
      fillOpacity: 1,
    }).addTo(this.sketchGroup);
    if (this.sketchPoints.length < 2) {
      this.callbacks.onSketchChanged(null);
      return;
    }
    try {
      const result = this.networkGraph.scoreSketch(this.sketchPoints);
      this.drawSketch(result);
      this.callbacks.onSketchChanged(result);
    } catch (error) {
      this.callbacks.onSketchChanged(null, error instanceof Error ? error.message : "Unable to route sketch");
    }
  }

  private drawSketch(result: SketchResult): void {
    this.sketchGroup.clearLayers();
    for (const nodeId of result.nodeIds) {
      const coordinate = this.networkGraph?.nodeCoordinates.get(nodeId);
      if (!coordinate) continue;
      L.circleMarker([coordinate[1], coordinate[0]], {
        radius: 6,
        color: "#ffffff",
        weight: 2,
        fillColor: "#ea580c",
        fillOpacity: 1,
      }).addTo(this.sketchGroup);
    }
    for (const coordinates of result.coordinates) {
      L.polyline(
        coordinates.map(([longitude, latitude]) => [latitude, longitude] as [number, number]),
        { color: "#ea580c", weight: 6, opacity: 0.92 },
      ).addTo(this.sketchGroup);
    }
  }
}

function cellColor(value: number): string {
  const clamped = Math.max(0, Math.min(1, value));
  const palette = ["#edf6f4", "#c7e7df", "#81c8ba", "#35a28f", "#08766c", "#064e4a"];
  return palette[Math.min(palette.length - 1, Math.floor(clamped * palette.length))]!;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function numericValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
