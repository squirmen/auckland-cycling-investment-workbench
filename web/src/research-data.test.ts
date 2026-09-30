import { expect, it } from "vitest";
import { portfolioGeoJson, reportSchema, routeSchema } from "./research-data";

it("exports actual funded projects and identifies unfunded inspected route segments", () => {
  const route = { projectIds: ["Q"], distanceM: 100, timeS: 30, intersectionDelayS: 10, capitalCost: 7, existingCyclewayM: 0, segments: [{ projectId: "Q", existingCycleway: false, coordinates: [[174, -36], [174.001, -36]] }] };
  const report = reportSchema.parse({
    schemaVersion: "1.0.0", status: "local_research_pilot", runId: "test", centre: [174, -36], radiusM: 4000, seed: 1, elapsedS: 1, searchComplete: true,
    intersectionContext: { scenario: "default", matchedSitesCitywide: 1, sitesInCrop: 1, directedMovementsInCrop: 1, evidenceSha256: "test", note: "Illustrative only" },
    graph: { nodes: 2, directedArcs: 1, projects: 2 }, sample: { selected: 1, eligibleWithinArea: 1, weightedDemand: 10, citywideRepresentative: false },
    standard: { maximum_stress: 2, maximum_detour: 1.5, maximum_time_s: 1800 },
    sourceHashes: { topology: "test", odLedger: "test", candidateLedger: "test", scenarioOdLedger: "test", origins: "test", originWeights: "test" }, implementationHash: "test",
    experimentScriptHash: "test", baseline: { weight: 2, journeys: 0 }, solutions: [{ budget: 10, method: "test", selected: ["P"], capital_cost: 5, served_weight: 10, served_journeys: 1, optimal_within_columns: true, assignmentKey: "test" }],
    journeys: [{ name: "Journey 1", weight: 10, searchComplete: true, stopReason: "exhausted", shortestLegalDistanceM: 100, alternatives: [route] }],
    projects: ["P", "Q"].map(id => ({ id, name: id, cost: id === "P" ? 5 : 7, lengthM: 100, coordinates: [[174, -36], [174.001, -36]] })),
    ridershipForecast: null, limitations: ["Test only"],
    assignment: { status: "fixed_demand_illustrative_preferences", scenarioId: "test", totalDemand: 1, profiles: [], portfolios: [] },
  });
  const solution = report.solutions[0];
  const journey = report.journeys[0];
  if (!solution || !journey) throw new Error("Test fixture must contain a solution and journey");
  const exported = portfolioGeoJson(report, solution, journey.alternatives[0], "b".repeat(64));
  expect(exported).toMatchObject({
    type: "FeatureCollection",
    reportSha256: "b".repeat(64),
    features: [
      { properties: { id: "P", role: "proposed_project", capitalCostNzd: 5 } },
      { properties: { projectId: "Q", role: "inspected_route_segment", projectFunded: false } },
    ],
    span: { capitalCostNzd: 5, baselineEligibleAccessWeight: 2, additionalEligibleAccessWeight: 8, additionalCyclists: null, inspectedRouteTimeS: 30, inspectedRouteIntersectionDelayS: 10, intersectionContext: { scenario: "default" }, limitations: ["Test only"] },
  });
});

it("rejects negative crossing delays", () => {
  expect(routeSchema.safeParse({ projectIds: [], distanceM: 100, timeS: 30, intersectionDelayS: -1, capitalCost: 0, existingCyclewayM: 0, segments: [] }).success).toBe(false);
});
