import type {
  CandidateFeature,
  CandidateMetric,
  GenericFeature,
  GenericFeatureCollection,
  Manifest,
  PortfolioStep,
  PurposeId,
  ScenarioId,
} from "./types";

export const nzd = new Intl.NumberFormat("en-NZ", {
  style: "currency",
  currency: "NZD",
  maximumFractionDigits: 0,
});

export const compactNumber = new Intl.NumberFormat("en-NZ", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatCost(value: number): string {
  return nzd.format(value);
}

export function metricFor(candidate: CandidateFeature, scenario: ScenarioId, purpose: PurposeId): CandidateMetric {
  return candidate.properties.metrics[scenario][purpose];
}

export function objectiveValue(metric: CandidateMetric, purpose: PurposeId): number {
  void purpose;
  return metric.available ? (metric.objectiveValue ?? 0) : 0;
}

export function purposeBenefit(metric: CandidateMetric, purpose: PurposeId): number {
  return objectiveValue(metric, purpose);
}

function lineParts(geometry: CandidateFeature["geometry"]): [number, number][][] {
  return geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
}

function segmentKm([x1, y1]: [number, number], [x2, y2]: [number, number]): number {
  const latitude = ((y1 + y2) / 2) * (Math.PI / 180);
  const dx = (x2 - x1) * (Math.PI / 180) * Math.cos(latitude);
  const dy = (y2 - y1) * (Math.PI / 180);
  return Math.hypot(dx, dy) * 6371;
}

/** Physical length of a candidate's geometry in kilometres. */
export function lengthKm(geometry: CandidateFeature["geometry"]): number {
  return lineParts(geometry).reduce(
    (total, part) => total + part.slice(1).reduce((sum, point, index) => sum + segmentKm(part[index]!, point), 0),
    0,
  );
}

/** Physical groups use exact-node contacts through the existing low-stress graph.
 * They do not establish directed OD accessibility or an acceptable detour. */
export function connectedGroups(candidates: CandidateFeature[]): CandidateFeature[][] {
  const parent = new Map(candidates.map((candidate) => [candidate.properties.candidateId, candidate.properties.candidateId]));
  const root = (id: string): string => {
    let current = id;
    while (parent.get(current) !== current) current = parent.get(current)!;
    let next = id;
    while (next !== current) {
      const previous = parent.get(next)!;
      parent.set(next, current);
      next = previous;
    }
    return current;
  };
  const join = (a: string, b: string): void => { parent.set(root(a), root(b)); };
  const areaOwner = new Map<string, string>();
  for (const candidate of candidates) {
    const { candidateId: id, networkContext: context } = candidate.properties;
    for (const area of context?.componentIds ?? []) {
      const other = areaOwner.get(area);
      if (other) join(id, other);
      else areaOwner.set(area, id);
    }
    for (const other of context?.touchingCandidateIds ?? []) if (parent.has(other)) join(id, other);
  }
  const groups = new Map<string, CandidateFeature[]>();
  for (const candidate of candidates) {
    const id = root(candidate.properties.candidateId);
    const group = groups.get(id) ?? [];
    group.push(candidate);
    groups.set(id, group);
  }
  return [...groups.values()];
}

export function packageKey(ids: string[]): string {
  return [...ids].sort().join("|");
}

export function candidateLengthKm(candidate: CandidateFeature): number {
  return candidate.properties.networkContext?.lengthKm ?? lengthKm(candidate.geometry);
}

/** The point halfway along the longest part, as [longitude, latitude]. */
export function midpoint(geometry: CandidateFeature["geometry"]): [number, number] {
  const parts = lineParts(geometry);
  const part = parts.reduce((best, item) => (lengthKm({ type: "LineString", coordinates: item }) >
    lengthKm({ type: "LineString", coordinates: best }) ? item : best), parts[0]!);
  const half = lengthKm({ type: "LineString", coordinates: part }) / 2;
  let travelled = 0;
  for (let index = 1; index < part.length; index += 1) {
    const start = part[index - 1]!;
    const end = part[index]!;
    const step = segmentKm(start, end);
    if (travelled + step >= half && step > 0) {
      const share = (half - travelled) / step;
      return [start[0] + (end[0] - start[0]) * share, start[1] + (end[1] - start[1]) * share];
    }
    travelled += step;
  }
  return part[0]!;
}

export function paretoFront(
  candidates: CandidateFeature[],
  scenario: ScenarioId,
  purpose: PurposeId,
): Set<string> {
  const front = new Set<string>();
  const available = candidates
    .filter((candidate) => metricFor(candidate, scenario, purpose).available)
    .map((candidate) => {
      const metric = metricFor(candidate, scenario, purpose);
      return {
        candidateId: candidate.properties.candidateId,
        cost: metric.lifecycleCostNzd,
        benefit: purposeBenefit(metric, purpose),
      };
    })
    .sort((left, right) =>
      left.cost - right.cost ||
      right.benefit - left.benefit ||
      left.candidateId.localeCompare(right.candidateId)
    );

  let bestBenefitAtLowerCost = Number.NEGATIVE_INFINITY;
  let index = 0;
  while (index < available.length) {
    const cost = available[index]!.cost;
    let groupEnd = index + 1;
    while (groupEnd < available.length && available[groupEnd]!.cost === cost) groupEnd += 1;
    const bestBenefitAtThisCost = available[index]!.benefit;
    if (bestBenefitAtThisCost > bestBenefitAtLowerCost) {
      for (let groupIndex = index; groupIndex < groupEnd; groupIndex += 1) {
        const item = available[groupIndex]!;
        if (item.benefit !== bestBenefitAtThisCost) break;
        front.add(item.candidateId);
      }
    }
    bestBenefitAtLowerCost = Math.max(bestBenefitAtLowerCost, bestBenefitAtThisCost);
    index = groupEnd;
  }
  return front;
}

export function portfolioAtBudget(
  manifest: Manifest,
  scenario: ScenarioId,
  purpose: PurposeId,
  budgetNzd: number,
): PortfolioStep[] {
  return manifest.portfolios[scenario][purpose].filter((step) => step.cumulativeCostNzd <= budgetNzd);
}

export interface GraphEdge {
  edgeId: string;
  u: string;
  v: string;
  direction: "both" | "forward" | "reverse";
  lengthKm: number;
  capitalCostNzd: number;
  dailyTripsPotential: number;
  odLowStressSharePotential: number;
  coordinates: [number, number][];
}

interface AdjacencyEdge {
  node: string;
  edge: GraphEdge;
}

interface TraversedEdge {
  edge: GraphEdge;
  from: string;
  to: string;
}

export interface SketchResult {
  nodeIds: string[];
  /** Traversed edge identifiers in route order; repeated traversals are retained. */
  edgeIds: string[];
  /** Distinct edge identifiers used for the preliminary asset-level screen. */
  uniqueEdgeIds: string[];
  coordinates: [number, number][][];
  lengthKm: number;
  capitalCostNzd: number;
  dailyTripsDelta: number;
  odLowStressShareDelta: number;
}

export class NetworkGraph {
  readonly edges = new Map<string, GraphEdge>();
  readonly nodeCoordinates = new Map<string, [number, number]>();
  private readonly adjacency = new Map<string, AdjacencyEdge[]>();

  static fromGeoJson(collection: GenericFeatureCollection): NetworkGraph {
    const graph = new NetworkGraph();
    for (const feature of collection.features) {
      if (feature.geometry.type !== "LineString") continue;
      const properties = feature.properties;
      const u = stringIdentifier(properties.u);
      const v = stringIdentifier(properties.v);
      const edgeId = stringIdentifier(properties.edgeId ?? properties.edge_id);
      const coordinates = lineCoordinates(feature.geometry.coordinates);
      const lengthKm = finiteNonNegative(properties.lengthKm ?? properties.length_km);
      if (!u || !v || !edgeId || !coordinates || lengthKm <= 0) continue;
      if (graph.edges.has(edgeId)) {
        throw new Error(`Duplicate exported network edge identifier: ${edgeId}`);
      }
      graph.assertNodeCoordinate(u, coordinates[0]!);
      graph.assertNodeCoordinate(v, coordinates[coordinates.length - 1]!);
      const edge: GraphEdge = {
        edgeId,
        u,
        v,
        direction: parseDirection(properties.direction, properties.oneway),
        lengthKm,
        capitalCostNzd: finiteNonNegative(properties.capitalCostNzd ?? properties.capital_cost_nzd),
        dailyTripsPotential: finiteNonNegative(properties.dailyTripsPotential ?? properties.daily_trips_potential),
        odLowStressSharePotential: finiteNonNegative(
          properties.odLowStressSharePotential ?? properties.od_low_stress_share_potential,
        ),
        coordinates,
      };
      graph.addEdge(edge);
    }
    return graph;
  }

  private addEdge(edge: GraphEdge): void {
    this.edges.set(edge.edgeId, edge);
    this.nodeCoordinates.set(edge.u, edge.coordinates[0]!);
    this.nodeCoordinates.set(edge.v, edge.coordinates[edge.coordinates.length - 1]!);
    if (edge.direction !== "reverse") {
      this.adjacency.set(edge.u, [...(this.adjacency.get(edge.u) ?? []), { node: edge.v, edge }]);
    }
    if (edge.direction !== "forward") {
      this.adjacency.set(edge.v, [...(this.adjacency.get(edge.v) ?? []), { node: edge.u, edge }]);
    }
  }

  private assertNodeCoordinate(nodeId: string, coordinate: [number, number]): void {
    const existing = this.nodeCoordinates.get(nodeId);
    if (existing && squaredDistance(existing, coordinate) > 1e-16) {
      throw new Error(`Inconsistent coordinates for exported network node: ${nodeId}`);
    }
  }

  nearestNode(point: [number, number]): string | null {
    let nearest: string | null = null;
    let best = Number.POSITIVE_INFINITY;
    for (const [node, coordinate] of this.nodeCoordinates) {
      const distance = squaredDistance(point, coordinate);
      if (distance < best) {
        best = distance;
        nearest = node;
      }
    }
    return nearest;
  }

  shortestPath(start: string, goal: string): GraphEdge[] {
    return this.shortestTraversals(start, goal).map((step) => step.edge);
  }

  private shortestTraversals(start: string, goal: string): TraversedEdge[] {
    if (start === goal) return [];
    if (!this.nodeCoordinates.has(start) || !this.nodeCoordinates.has(goal)) {
      throw new Error("Selected points do not identify nodes on the exported cycling graph");
    }
    const distances = new Map<string, number>([[start, 0]]);
    const previous = new Map<string, { node: string; edge: GraphEdge }>();
    const pending = new Set<string>([start]);
    while (pending.size) {
      let current: string | null = null;
      let currentDistance = Number.POSITIVE_INFINITY;
      for (const node of pending) {
        const distance = distances.get(node) ?? Number.POSITIVE_INFINITY;
        if (distance < currentDistance) {
          current = node;
          currentDistance = distance;
        }
      }
      if (current === null) break;
      pending.delete(current);
      if (current === goal) break;
      for (const adjacent of this.adjacency.get(current) ?? []) {
        const candidateDistance = currentDistance + adjacent.edge.lengthKm;
        if (candidateDistance < (distances.get(adjacent.node) ?? Number.POSITIVE_INFINITY)) {
          distances.set(adjacent.node, candidateDistance);
          previous.set(adjacent.node, { node: current, edge: adjacent.edge });
          pending.add(adjacent.node);
        }
      }
    }
    if (!previous.has(goal)) throw new Error("Selected points are not connected on the exported cycling graph");
    const path: TraversedEdge[] = [];
    let cursor = goal;
    while (cursor !== start) {
      const step = previous.get(cursor);
      if (!step) throw new Error("Unable to reconstruct corridor path");
      path.push({ edge: step.edge, from: step.node, to: cursor });
      cursor = step.node;
    }
    return path.reverse();
  }

  scoreSketch(points: [number, number][]): SketchResult {
    if (points.length < 2) {
      return { nodeIds: [], edgeIds: [], uniqueEdgeIds: [], coordinates: [], lengthKm: 0, capitalCostNzd: 0, dailyTripsDelta: 0, odLowStressShareDelta: 0 };
    }
    const nodes = points.map((point) => this.nearestNode(point));
    if (nodes.some((node) => node === null)) throw new Error("No routable network is available");
    return this.scoreSketchNodes(nodes as string[]);
  }

  scoreSketchNodes(nodeIds: string[]): SketchResult {
    const nodes = nodeIds.filter((node, index) => index === 0 || node !== nodeIds[index - 1]);
    if (nodes.length < 2) {
      return { nodeIds: nodes, edgeIds: [], uniqueEdgeIds: [], coordinates: [], lengthKm: 0, capitalCostNzd: 0, dailyTripsDelta: 0, odLowStressShareDelta: 0 };
    }
    const selected: TraversedEdge[] = [];
    for (let index = 1; index < nodes.length; index += 1) {
      selected.push(...this.shortestTraversals(nodes[index - 1]!, nodes[index]!));
    }
    const unique = [...new Map(selected.map((step) => [step.edge.edgeId, step.edge])).values()];
    const lengthKm = sum(selected, (step) => step.edge.lengthKm);
    const capitalCostNzd = sum(unique, (edge) => edge.capitalCostNzd);
    const dailyTripsDelta = sum(unique, (edge) => edge.dailyTripsPotential);
    const odLowStressShareDelta = Math.min(
      1,
      sum(unique, (edge) => edge.odLowStressSharePotential),
    );
    return {
      nodeIds: nodes,
      edgeIds: selected.map((step) => step.edge.edgeId),
      uniqueEdgeIds: unique.map((edge) => edge.edgeId),
      coordinates: selected.map((step) =>
        step.from === step.edge.u ? step.edge.coordinates : [...step.edge.coordinates].reverse(),
      ),
      lengthKm,
      capitalCostNzd,
      dailyTripsDelta,
      odLowStressShareDelta,
    };
  }
}

function sum<T>(values: T[], getter: (value: T) => number): number {
  return values.reduce((total, value) => total + getter(value), 0);
}

function squaredDistance(a: [number, number], b: [number, number]): number {
  const latitude = ((a[1] + b[1]) / 2) * (Math.PI / 180);
  const longitudeScale = Math.cos(latitude);
  return ((a[0] - b[0]) * longitudeScale) ** 2 + (a[1] - b[1]) ** 2;
}

function stringIdentifier(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function finiteNonNegative(value: unknown): number {
  const number = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

function lineCoordinates(value: unknown): [number, number][] | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const coordinates: [number, number][] = [];
  for (const position of value) {
    if (!Array.isArray(position) || position.length < 2) return null;
    const longitude = Number(position[0]);
    const latitude = Number(position[1]);
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null;
    if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) return null;
    coordinates.push([longitude, latitude]);
  }
  return coordinates;
}

function parseDirection(value: unknown, legacyOneway: unknown): GraphEdge["direction"] {
  if (value === "both" || value === "forward" || value === "reverse") return value;
  if (legacyOneway === -1 || legacyOneway === "-1" || legacyOneway === "reverse") return "reverse";
  if (legacyOneway === true || legacyOneway === 1 || legacyOneway === "1" || legacyOneway === "yes") return "forward";
  return "both";
}

export function portfolioGeoJson(candidates: CandidateFeature[], selectedIds: Set<string>): GenericFeatureCollection {
  const features: GenericFeature[] = candidates
    .filter((candidate) => selectedIds.has(candidate.properties.candidateId))
    .map((candidate) => ({
      type: "Feature",
      geometry: candidate.geometry,
      properties: {
        candidate_id: candidate.properties.candidateId,
        name: candidate.properties.name,
        facility_type: candidate.properties.facilityType,
        programme_status: candidate.properties.programmeStatus,
        edge_ids: candidate.properties.edgeIds,
      },
    }));
  return { type: "FeatureCollection", features };
}
