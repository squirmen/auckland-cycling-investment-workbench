import { describe, expect, it } from "vitest";

import {
  NetworkGraph,
  objectiveValue,
  paretoFront,
  portfolioAtBudget,
  portfolioGeoJson,
} from "./model";
import { purposeIds, scenarioIds, type CandidateFeature, type CandidateMetric, type Manifest } from "./types";

function metric(overrides: Partial<CandidateMetric> = {}): CandidateMetric {
  return {
    available: true,
    capitalCostNzd: 1_000_000,
    lifecycleCostNzd: 1_200_000,
    objectiveValue: 100,
    objectiveUnit: "additional cycle users",
    additionalCycleUsers: 100,
    annualBikeKmDelta: 50_000,
    odLowStressShareDelta: 0.02,
    bcrP5: 1.1,
    bcrP50: 1.7,
    bcrP95: 2.4,
    routeCoverage: 0.9,
    meanRank: 2,
    topKProbability: 0.75,
    frontierProbability: 0.7,
    warnings: [],
    ...overrides,
  };
}

function candidate(id: string, overrides: Partial<CandidateMetric> = {}): CandidateFeature {
  const metrics = Object.fromEntries(
    scenarioIds.map((scenario) => [
      scenario,
      Object.fromEntries(purposeIds.map((purpose) => [purpose, metric(overrides)])),
    ]),
  ) as CandidateFeature["properties"]["metrics"];
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: [[174.75, -36.86], [174.76, -36.85]] },
    properties: {
      candidateId: id,
      name: `Candidate ${id}`,
      purposeOrigins: ["network"],
      edgeIds: [`edge-${id}`],
      facilityType: "protected cycleway",
      programmeStatus: "unprogrammed",
      rationale: "Fixture corridor",
      metrics,
    },
  };
}

describe("portfolio model", () => {
  it("computes transparent purpose objectives", () => {
    const value = objectiveValue(
      metric({ objectiveValue: 0.04, objectiveUnit: "share points" }),
      "network",
    );
    expect(value).toBeCloseTo(0.04);
    expect(objectiveValue(metric({ objectiveValue: 2.2, objectiveUnit: "indicative BCR" }), "appraisal")).toBe(2.2);
  });

  it("identifies candidates that are not dominated", () => {
    const cheapStrong = candidate("A", { lifecycleCostNzd: 1_000_000, objectiveValue: 130 });
    const expensiveWeak = candidate("B", { lifecycleCostNzd: 2_000_000, objectiveValue: 80 });
    const specialist = candidate("C", { lifecycleCostNzd: 1_800_000, objectiveValue: 85 });
    const front = paretoFront([cheapStrong, expensiveWeak, specialist], "baseline", "network");
    expect(front.has("A")).toBe(true);
    expect(front.has("B")).toBe(false);
    expect(front.has("C")).toBe(false);
  });

  it("retains exact cost-benefit ties and rejects weaker same-cost options", () => {
    const tieA = candidate("tie-a", { lifecycleCostNzd: 1_000_000, objectiveValue: 100 });
    const tieB = candidate("tie-b", { lifecycleCostNzd: 1_000_000, objectiveValue: 100 });
    const weakerAtSameCost = candidate("weaker", {
      lifecycleCostNzd: 1_000_000,
      objectiveValue: 99,
    });
    const laterImprovement = candidate("later", {
      lifecycleCostNzd: 1_500_000,
      objectiveValue: 130,
    });
    expect(
      paretoFront(
        [laterImprovement, weakerAtSameCost, tieB, tieA],
        "baseline",
        "network",
      ),
    ).toEqual(new Set(["tie-a", "tie-b", "later"]));
  });

  it("uses the selected purpose when constructing the frontier", () => {
    const networkCandidate = candidate("network", {
      lifecycleCostNzd: 1_000_000,
      objectiveValue: 50,
    });
    const equityCandidate = candidate("equity", {
      lifecycleCostNzd: 1_000_000,
      objectiveValue: 80,
    });
    networkCandidate.properties.metrics.baseline.network.objectiveValue = 100;
    networkCandidate.properties.metrics.baseline.equity.objectiveValue = 10;
    equityCandidate.properties.metrics.baseline.network.objectiveValue = 30;
    equityCandidate.properties.metrics.baseline.equity.objectiveValue = 80;
    expect(paretoFront([networkCandidate, equityCandidate], "baseline", "network")).toEqual(
      new Set(["network"]),
    );
    expect(paretoFront([networkCandidate, equityCandidate], "baseline", "equity")).toEqual(
      new Set(["equity"]),
    );
  });

  it("filters a precomputed cumulative sequence by budget", () => {
    const manifest = {
      portfolios: {
        baseline: {
          network: [
            { candidateId: "A", step: 1, cumulativeCostNzd: 1_000_000, marginalObjective: 50, cumulativeObjective: 50, objectiveUnit: "additional cycle users", paretoMember: true },
            { candidateId: "B", step: 2, cumulativeCostNzd: 3_000_000, marginalObjective: 70, cumulativeObjective: 120, objectiveUnit: "additional cycle users", paretoMember: false },
          ],
        },
      },
    } as unknown as Manifest;
    expect(portfolioAtBudget(manifest, "baseline", "network", 2_000_000).map((step) => step.candidateId)).toEqual(["A"]);
  });

  it("exports exactly the selected candidate ids", () => {
    const output = portfolioGeoJson([candidate("A"), candidate("B")], new Set(["B"]));
    expect(output.features).toHaveLength(1);
    expect(output.features[0]?.properties.candidate_id).toBe("B");
  });
});

describe("network sketching", () => {
  const network = {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        geometry: { type: "LineString", coordinates: [[174.75, -36.86], [174.76, -36.86]] },
        properties: { edgeId: "e1", u: "n1", v: "n2", lengthKm: 1, capitalCostNzd: 2_000_000, dailyTripsPotential: 100, odLowStressSharePotential: 0.01 },
      },
      {
        type: "Feature" as const,
        geometry: { type: "LineString", coordinates: [[174.76, -36.86], [174.77, -36.85]] },
        properties: { edgeId: "e2", u: "n2", v: "n3", lengthKm: 1.4, capitalCostNzd: 2_500_000, dailyTripsPotential: 120, odLowStressSharePotential: 0.015 },
      },
    ],
  };

  it("routes selected points over contiguous exact edges", () => {
    const graph = NetworkGraph.fromGeoJson(network);
    const result = graph.scoreSketch([[174.75, -36.86], [174.77, -36.85]]);
    expect(result.edgeIds).toEqual(["e1", "e2"]);
    expect(result.uniqueEdgeIds).toEqual(["e1", "e2"]);
    expect(result.nodeIds).toEqual(["n1", "n3"]);
    expect(result.lengthKm).toBeCloseTo(2.4);
    expect(result.capitalCostNzd).toBe(4_500_000);
    expect(result.dailyTripsDelta).toBeCloseTo(220);
  });

  it("retains ordered repeated traversals while screening each asset once", () => {
    const graph = NetworkGraph.fromGeoJson(network);
    const result = graph.scoreSketchNodes(["n1", "n3", "n1"]);
    expect(result.edgeIds).toEqual(["e1", "e2", "e2", "e1"]);
    expect(result.uniqueEdgeIds).toEqual(["e1", "e2"]);
    expect(result.coordinates).toHaveLength(4);
    expect(result.lengthKm).toBeCloseTo(4.8);
    expect(result.capitalCostNzd).toBe(4_500_000);
  });

  it("respects bicycle direction on one-way edges", () => {
    const directed = structuredClone(network);
    const directedProperties = directed.features[1]!.properties as Record<string, unknown>;
    directedProperties.oneway = true;
    const graph = NetworkGraph.fromGeoJson(directed);
    expect(() => graph.shortestPath("n3", "n1")).toThrow(/not connected/);
  });

  it("respects a reverse-only source edge", () => {
    const directed = structuredClone(network);
    const firstProperties = directed.features[0]!.properties as Record<string, unknown>;
    firstProperties.direction = "reverse";
    const graph = NetworkGraph.fromGeoJson(directed);
    expect(() => graph.shortestPath("n1", "n2")).toThrow(/not connected/);
    expect(graph.shortestPath("n2", "n1").map((edge) => edge.edgeId)).toEqual(["e1"]);
    expect(graph.scoreSketchNodes(["n2", "n1"]).coordinates[0]).toEqual([
      [174.76, -36.86],
      [174.75, -36.86],
    ]);
  });

  it("rejects invalid network coordinates and legacy reverse one-way travel", () => {
    const invalid = structuredClone(network);
    invalid.features[0]!.geometry.coordinates[0] = [Number.NaN, -36.86];
    const graph = NetworkGraph.fromGeoJson(invalid);
    expect(graph.edges.has("e1")).toBe(false);

    const reverse = structuredClone(network);
    const firstProperties = reverse.features[0]!.properties as Record<string, unknown>;
    firstProperties.oneway = "-1";
    const reverseGraph = NetworkGraph.fromGeoJson(reverse);
    expect(() => reverseGraph.shortestPath("n1", "n2")).toThrow(/not connected/);
    expect(reverseGraph.shortestPath("n2", "n1").map((edge) => edge.edgeId)).toEqual(["e1"]);
  });

  it("fails closed on duplicate edge ids or inconsistent node coordinates", () => {
    const duplicate = structuredClone(network);
    duplicate.features[1]!.properties.edgeId = "e1";
    expect(() => NetworkGraph.fromGeoJson(duplicate)).toThrow(/Duplicate exported network edge/);

    const inconsistent = structuredClone(network);
    inconsistent.features[1]!.geometry.coordinates[0] = [175, -36.5];
    expect(() => NetworkGraph.fromGeoJson(inconsistent)).toThrow(/Inconsistent coordinates/);
  });
});
