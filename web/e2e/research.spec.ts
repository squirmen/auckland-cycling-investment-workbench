import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

const hash = "a".repeat(64);
const route = {
  projectIds: ["P"], distanceM: 100, timeS: 60, intersectionDelayS: 10,
  capitalCost: 5, existingCyclewayM: 0,
  segments: [{ projectId: "P", existingCycleway: false, coordinates: [[174.7, -36.8], [174.701, -36.8]] }],
};
// Browser-only synthetic evidence. Never copied into public/data or a release.
const report = {
  schemaVersion: "1.0.0", status: "local_research_pilot", runId: "synthetic-cranc-test",
  centre: [174.7, -36.8], radiusM: 4000, seed: 1, elapsedS: 1, searchComplete: true,
  graph: { nodes: 2, directedArcs: 1, projects: 1 },
  intersectionContext: { scenario: "default", matchedSitesCitywide: 1, sitesInCrop: 1, directedMovementsInCrop: 1, evidenceSha256: hash, note: "Synthetic only" },
  sample: { selected: 1, eligibleWithinArea: 1, weightedDemand: 10, citywideRepresentative: false },
  standard: { maximum_stress: 2, maximum_detour: 1.5, maximum_time_s: 1800 },
  sourceHashes: { topology: hash, odLedger: hash, candidateLedger: hash, scenarioOdLedger: hash, origins: hash, originWeights: hash },
  implementationHash: hash, experimentScriptHash: hash,
  baseline: { weight: 0, journeys: 0 },
  solutions: [0, 10].map(budget => ({ budget, method: "route_packages_milp", selected: budget ? ["P"] : [], capital_cost: budget ? 5 : 0, served_weight: budget ? 10 : 0, served_journeys: budget ? 1 : 0, optimal_within_columns: true, assignmentKey: String(budget) })),
  journeys: [{ name: "Synthetic journey", weight: 10, searchComplete: true, stopReason: "exhausted", shortestLegalDistanceM: 100, alternatives: [route] }],
  projects: [{ id: "P", name: "Synthetic proposal", cost: 5, lengthM: 100, coordinates: route.segments[0]!.coordinates }],
  ridershipForecast: null, limitations: ["Synthetic browser fixture only"],
  assignment: { status: "fixed_demand_illustrative_preferences", scenarioId: "synthetic", totalDemand: 1, profiles: [], portfolios: [] },
};
const comparison = {
  schemaVersion: "span.cranc-access.v1",
  provider: { name: "CRANC", version: "synthetic-test", attribution: "Synthetic test only · Steve Gehrke and collaborators" },
  scope: { runId: report.runId, baseNetworkHash: hash, originsHash: hash, weightingHash: hash, opportunitiesHash: hash, profile: "ibc", profileHash: hash, timeLimitS: 900, reverseFlow: false, category: "synthetic jobs", unit: "reachable_opportunities_per_origin", aggregation: "weighted_mean", crs: "EPSG:4326", stressTransferValidation: { status: "validated_for_auckland", evidence: "Synthetic test; no actual validation" } },
  baseline: { scenarioId: "baseline", networkScenarioHash: hash, projectIds: [], value: 10 },
  investment: { scenarioId: "investment", networkScenarioHash: "b".repeat(64), projectIds: ["P"], value: 20, crosswalkHash: hash },
};

test.beforeEach(async ({ page }) => {
  await page.route("**/data/access-experiment.json", route => route.fulfill({ json: report }));
  await page.goto("/research.html#cranc-accessibility");
  await expect(page.locator("#research-status")).toContainText("All sampled route searches completed");
});

test("labels the CRANC integration point and exports only a scoped request", async ({ page }) => {
  await expect(page.locator("#cranc-accessibility")).toContainText("live CRANC service not connected");
  const download = page.waitForEvent("download");
  await page.locator("#cranc-request").click();
  const file = await (await download).path();
  const request = JSON.parse(await readFile(file, "utf8")) as Record<string, unknown>;
  expect(request).toMatchObject({ schemaVersion: "span.cranc-request.v1", runId: report.runId, investmentProjectIds: ["P"] });
  expect(request).not.toHaveProperty("origins");
  expect(request).not.toHaveProperty("value");
  await expect(page.locator("#cranc-accessibility")).toContainText("does not yet verify matching crop, speed or intersection-delay assumptions");
});

test("shows attributed local results and rejects a stale investment selection", async ({ page }) => {
  await page.locator("#cranc-import").setInputFiles({ name: "synthetic.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(comparison)) });
  await expect(page.locator("#cranc-status")).toContainText("10 → 20 reachable opportunities per origin");
  await expect(page.locator("#cranc-status")).toContainText("Synthetic test only");
  await page.locator("#research-budget").selectOption("0");
  await expect(page.locator("#cranc-status")).toContainText("different investment package");
  await expect(page.locator("#cranc-status")).not.toContainText("10 → 20");
  await page.locator("#research-budget").selectOption("10");
  await expect(page.locator("#cranc-status")).toContainText("10 → 20");
  await page.locator("#cranc-import").setInputFiles({ name: "invalid.json", mimeType: "application/json", buffer: Buffer.from("{}") });
  await expect(page.locator("#cranc-status")).toContainText("return contract was not met");
  await page.locator("#research-budget").selectOption("0");
  await expect(page.locator("#cranc-status")).toContainText("No CRANC comparison loaded");
});
