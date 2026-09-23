import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

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

test.beforeEach(async ({ page }) => {
  const manifest = JSON.parse(await readFile(new URL("../public/data/manifest.json", import.meta.url), "utf8")) as { runId: string; effectiveNetwork?: { topologySha256: string } };
  await page.route("**/data/access-experiment.json", route => route.fulfill({ json: { ...report, runId: manifest.runId, sourceHashes: { ...report.sourceHashes, topology: manifest.effectiveNetwork?.topologySha256 ?? hash } } }));
});

test("uses one SPAN map for complete journeys and keeps the build-order settings", async ({ page }) => {
  await page.goto("/?offline=1&budget=0.5");
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("tab", { name: "Connected journeys" }).click();
  await expect(page.locator("#connected-status")).toContainText("1 sample journeys");
  await expect(page.locator("#connected-route-detail")).toContainText("This package connects the journey");
  await expect(page.locator("#map .connected-end")).toHaveCount(2);
  await expect(page.locator(".leaflet-container")).toHaveCount(1);
  await expect(page.locator("#basemap-switcher")).toBeVisible();
  await expect(page.getByRole("button", { name: "Plain", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#ranking-controls")).toBeHidden();
  await expect(page.locator("#cranc-accessibility")).toHaveCount(0);
  const download = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const exported = JSON.parse(await readFile(await (await download).path(), "utf8")) as { span: { additionalCyclists: null; selectedProjectIds: string[] } };
  expect(exported.span.additionalCyclists).toBeNull();
  expect(exported.span.selectedProjectIds).toEqual(["P"]);
  await page.locator("#connected-budget").selectOption("0");
  await expect(page.locator("#connected-route-detail")).toContainText("1 upgrade is still needed");
  await page.getByRole("tab", { name: "Build order", exact: true }).click();
  await expect(page.locator("#budget-output")).toHaveText("$500k");
  await expect(page.locator("#ranking-controls")).toBeVisible();
  await expect(page.locator("#map .connected-end")).toHaveCount(0);
  await page.getByRole("tab", { name: "Connected journeys" }).click();
  await expect(page.locator("#connected-budget")).toHaveValue("0");
  await page.reload();
  await expect(page.locator("#connected-budget")).toHaveValue("0");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("redirects old journey links into SPAN", async ({ page }) => {
  await page.goto("/research.html");
  await expect(page).toHaveURL(/view=connected/);
  await expect(page.getByRole("tab", { name: "Connected journeys" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#connected-controls")).toBeVisible();
});

test("rejects a journey report from another release without breaking SPAN", async ({ page }) => {
  await page.route("**/data/access-experiment.json", route => route.fulfill({ json: { ...report, runId: "wrong-release" } }));
  await page.goto("/?offline=1&view=connected");
  await expect(page.locator("#connected-status")).toContainText("different data release");
  await expect(page.locator("#connected-controls")).toBeHidden();
  await expect(page.locator("#download-button")).toBeDisabled();
  await page.getByRole("tab", { name: "Build order", exact: true }).click();
  await expect(page.locator("#portfolio-summary")).not.toBeEmpty();
});

test("keeps layers compact and source notes out of the menu", async ({ page }) => {
  await page.goto("/?offline=1");
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false");
  await page.locator("#layers-disclosure > summary").click();
  const bounds = await page.locator(".layers-body").boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(280);
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  await expect(page.locator("#layer-controls p")).toHaveCount(0);
  await expect(page.locator("#layer-controls")).toContainText("Cycle counters");
});

test("keeps the main tool usable when journey results are absent", async ({ page }) => {
  await page.route("**/data/access-experiment.json", route => route.fulfill({ status: 404, body: "Not included" }));
  await page.goto("/?offline=1&view=connected");
  await expect(page.locator("#connected-status")).toContainText("not available in this release");
  await expect(page.locator("#download-button")).toBeDisabled();
  await page.getByRole("tab", { name: "Build order", exact: true }).click();
  await expect(page.locator("#candidate-list button").first()).toBeVisible();
});

test("a late journey response does not take over the map after leaving the view", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/data/access-experiment.json", async route => { await gate; await route.fallback(); });
  await page.goto("/?offline=1&view=connected");
  await expect(page.locator("#connected-status")).toContainText("Loading");
  await page.getByRole("tab", { name: "Build order", exact: true }).click();
  release();
  await expect(page.locator("#connected-status")).toContainText("1 sample journeys");
  await expect(page.locator("#tab-portfolio")).toBeVisible();
  await expect(page.locator("#map .connected-end")).toHaveCount(0);
  await expect(page.locator("#download-button")).toHaveText("Download build order (GeoJSON)");
});
