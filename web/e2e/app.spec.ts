import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const dataDirectory = process.env.SPAN_TEST_DATA_DIR ?? path.resolve(import.meta.dirname, "../public/data");
const screenshotStatesPath = path.resolve(import.meta.dirname, "../screenshot-states.json");

async function waitForSpan(page: Page): Promise<void> {
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false");
  // On a phone an open link card replaces the panel, so check the brand is present, not visible.
  await expect(page.locator("#controls-panel h1")).toHaveText("SPAN");
  await expect(page.locator("#data-status")).toHaveText("Synthetic demo");
  await expect(page.locator("#run-summary")).toContainText(/run-[a-f0-9]{16}/);
}

test("loads the default budget and updates every goal and scenario control", async ({ page }) => {
  await page.goto("/?offline=1");
  await waitForSpan(page);
  await expect(page.locator("#budget-output")).toHaveText("$2.0M");
  await expect(page.locator("#portfolio-summary")).toContainText("more people would cycle to work");
  await expect(page.locator("#candidate-list li")).toHaveCount(1);
  await expect(page.locator("#methodology-link")).toHaveAttribute("href", /\/documentation\/methodology\.md$/);

  await page.locator("#scenario-select").selectOption("ebike");
  await expect(page.locator("#scenario-note")).toContainText(/e-bike/i);
  await page.getByRole("radio", { name: "School trips" }).click();
  await expect(page.getByRole("radio", { name: "School trips" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("#purpose-note")).toContainText(/school/i);
  await expect(page.locator("#scenario-select")).toBeDisabled();
  await expect(page.locator("#scenario-note")).toContainText("don't change with the scenario");
  await expect(page.locator("#connectivity-context")).toContainText("traffic stress 2 or lower");
  await expect(page.locator("#connectivity-context")).toContainText("1.5 times the shortest");
  await expect(page.locator("#connectivity-context")).toContainText("could route");
  await expect(page.locator("#connectivity-context")).toContainText("counting every trip");
  await expect(page).toHaveURL(/scenario=ebike/);
  await expect(page).toHaveURL(/purpose=school/);

  await page.getByRole("radio", { name: "Cycling to work" }).click();
  await page.locator("#scenario-select").selectOption("government_target");
  await expect(page.locator("#scenario-select")).toHaveValue("government_target");
  await page.locator("#scenario-select").selectOption("commute_8pct");
  await expect(page.locator("#scenario-note")).toContainText("test case");
  await expect(page.locator("#scenario-note")).not.toContainText(/TERP|CIW/);

  await page.getByRole("radio", { name: "Benefit–cost" }).click();
  await expect(page.locator("#scenario-select")).toHaveValue("commute_8pct");
  await expect(page.locator("#scenario-select")).toBeDisabled();
});

test("supports list search, a true zero-budget state, and a one-action reset", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  await page.goto("/?offline=1&budget=2.8&scenario=go_dutch&purpose=school");
  await waitForSpan(page);
  await expect(page.locator("#candidate-list li")).toHaveCount(2);

  await page.locator("#candidate-search").fill("central");
  await expect(page.locator("#candidate-list li")).toHaveCount(1);
  await expect(page.locator("#portfolio-count")).toHaveText("1 of 2");
  await expect(page.locator("#candidate-list")).toContainText("Central protected crossing");

  await page.locator("#candidate-search").fill("");
  await page.locator("#budget-slider").fill("0");
  await expect(page.locator("#portfolio-count")).toHaveText("0 links");
  await expect(page.locator("#candidate-list")).toContainText("No links fit this budget");
  await expect(page.locator("#portfolio-summary")).toContainText("links fit within $0");
  await expect(page.locator("#download-button")).toBeDisabled();

  await page.locator("#reset-button").click();
  await expect(page.locator("#scenario-select")).toHaveValue("commute_8pct");
  await expect(page.getByRole("radio", { name: "Cycling to work" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("#budget-output")).toHaveText("$2.0M");
  await expect(page.locator("#status-message")).toContainText("Reset to the starting view");
});

test("uses the selected goal in the value view and keeps an out-of-budget selection", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  await page.goto("/?offline=1&view=pareto&budget=0.5&purpose=equity");
  await waitForSpan(page);
  await expect(page.locator("#pareto-chart svg")).toHaveAttribute(
    "aria-label",
    /whole-life cost against extra riders from deprived areas/i,
  );
  await page.locator('#pareto-chart circle[data-candidate-id="central_crossing"]').click();
  await expect(page.locator("#link-card")).toBeVisible();
  await expect(page.locator("#candidate-title")).toHaveText("Central protected crossing");
  await expect(page.locator("#candidate-detail > .facts")).toBeVisible();
  await expect(page.getByRole("heading", { name: "What would be built" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Parameter sensitivity" })).not.toBeVisible();
  await page.locator("#candidate-evidence > summary").click();
  await expect(page.getByRole("heading", { name: "Parameter sensitivity" })).toBeVisible();
  await expect(page.locator("#candidate-detail")).toContainText("Build cost");
  await expect(page.locator("#candidate-detail")).toContainText("$800k");
  await expect(page.locator("#budget-output")).toHaveText("$500k");
  await expect(page).toHaveURL(/budget=0\.5/);
  await expect(page).toHaveURL(/candidate=central_crossing/);

  await page.locator("#link-close").click();
  await expect(page.locator("#link-card")).toBeHidden();
  await expect(page).not.toHaveURL(/candidate=/);
});

test("lazy-loads the programme and counter overlays from verified files", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  const countersLoaded = page.waitForResponse((response) => response.url().endsWith("/data/counters.geojson"));
  const programmesLoaded = page.waitForResponse((response) => response.url().endsWith("/data/programmes.geojson"));
  await page.goto("/?offline=1&layers=cells%2Cnetwork%2Ccandidates%2Cprogrammes%2Ccounters");
  await Promise.all([countersLoaded, programmesLoaded]);
  await waitForSpan(page);
  await expect(page.locator("#layer-programmes")).toBeChecked();
  await expect(page.locator("#layer-counters")).toBeChecked();
  const key = page.locator("#map-legend-items");
  await expect(key).toContainText("AT committed or planned project");
  await expect(key).toContainText("Cycle counter");
  await expect(key).toContainText("2 sites");
  await expect(key).toContainText("no calendar period");
  await expect(key).toContainText("Other links tested");
  await expect(page.locator("#status-message")).not.toHaveClass(/error/);
});

test("starts with only the build order and demand on the map", async ({ page }) => {
  await page.goto("/?offline=1");
  await waitForSpan(page);
  await expect(page.locator("#layer-candidates")).not.toBeChecked();
  await expect(page.locator("#layer-cells")).toBeChecked();
  const key = page.locator("#map-legend-items");
  await expect(key).toContainText("Build order");
  await expect(key).not.toContainText("Other links tested");
});

test("exports exactly the declared build order with its active metrics", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop download coverage");
  await page.goto("/?offline=1&scenario=ebike&purpose=school&budget=2");
  await waitForSpan(page);
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const downloadPath = await (await downloadPromise).path();
  const exported = JSON.parse(await readFile(downloadPath, "utf8")) as {
    features: Array<{ properties: Record<string, unknown> }>;
    span_export: Record<string, unknown>;
  };
  expect(exported.features.map((feature) => feature.properties.candidate_id)).toEqual(["main_street"]);
  expect(exported.features[0]?.properties.scenario).toBe("ebike");
  expect(exported.features[0]?.properties.purpose).toBe("school");
  expect(exported.features[0]?.properties.build_order).toBe(1);
  expect(exported.features[0]?.properties.lifecycle_cost_nzd).toEqual(expect.any(Number));
  expect(exported.features[0]?.properties.od_low_stress_share_delta).toEqual(expect.any(Number));
  expect(exported.span_export.budget_nzd).toBe(2_000_000);
});

test("restores and exports a graph-snapped exact-edge corridor", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop sketch coverage");
  await page.goto("/?offline=1&sketch=A%2CF&budget=2.8");
  await waitForSpan(page);
  await expect(page.locator("#sketch-result .mini-facts")).toBeVisible();
  await expect(page.locator("#sketch-result")).toContainText("Rough build cost");
  await expect(page.locator("#sketch-result")).toContainText("riders are not modelled");
  await expect(page).toHaveURL(/sketch=A%2CF/);

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const downloadPath = await (await downloadPromise).path();
  const exported = JSON.parse(await readFile(downloadPath, "utf8")) as {
    features: Array<{ properties: Record<string, unknown> }>;
    span_export: Record<string, unknown>;
  };
  const sketch = exported.features.find((feature) => feature.properties.candidate_id === "user-sketch");
  expect(sketch?.properties.ordered_edge_ids).toEqual(["ab", "bc", "cf"]);
  expect(sketch?.properties.unique_edge_ids).toEqual(["ab", "bc", "cf"]);
  expect(sketch?.properties.evaluation_status).toBe("requires_pipeline_evaluation");
  expect(sketch?.properties.source_run_id).toBe(exported.span_export.run_id);
  expect(sketch?.properties.config_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(sketch?.properties.daily_trips_delta).toBeUndefined();

  await page.locator("#sketch-clear").click();
  await expect(page.locator("#sketch-result")).toContainText("Choose at least two");
  await expect(page).not.toHaveURL(/sketch=/);
});

test("supports keyboard tab, goal and candidate selection", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop keyboard coverage");
  await page.goto("/?offline=1&view=portfolio");
  await waitForSpan(page);
  const buildTab = page.getByRole("tab", { name: "Build order" });
  await buildTab.focus();
  await buildTab.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Value for money" })).toHaveAttribute("aria-selected", "true");
  const point = page.locator('#pareto-chart circle[data-candidate-id="central_crossing"]');
  await point.focus();
  await point.press("Space");
  await expect(page.locator("#link-card")).toBeVisible();
  await expect(page.locator("#candidate-title")).toHaveText("Central protected crossing");
  await page.keyboard.press("Escape");
  await expect(page.locator("#link-card")).toBeHidden();

  const goal = page.getByRole("radio", { name: "Cycling to work" });
  await goal.focus();
  await goal.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Deprived areas" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("radio", { name: "Deprived areas" })).toBeFocused();
});

test("is responsive without horizontal document overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile project only");
  await page.goto("/?offline=1&scenario=go_dutch&purpose=school");
  await waitForSpan(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await expect(page.locator("#map")).toBeVisible();
  await expect(page.locator("#scenario-select")).toBeVisible();
  await expect(page.locator("#download-button")).toBeVisible();
  await expect(page.locator("#panel-toggle")).toBeVisible();
  await expect(page.locator("#map-legend").getByText("Map key", { exact: true })).toBeVisible();
});

test("keeps map notes accessible and the offline basemap state explicit", async ({ page }) => {
  await page.goto("/?offline=1");
  await waitForSpan(page);
  await expect(page.getByRole("button", { name: "Plain" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Light" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Streets" })).toBeDisabled();

  const infoButton = page.getByRole("button", { name: "About SPAN and its data" });
  await infoButton.click();
  const dialog = page.getByRole("dialog", { name: "About SPAN" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("not an investment business case");
  await expect(dialog).toContainText("Plain shows no background map");
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(infoButton).toBeFocused();
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await page.goto("/?offline=1&candidate=main_street");
  await waitForSpan(page);
  // On a phone the open link card replaces the panel, so the list is present but hidden.
  await expect(page.locator("#candidate-list li").first()).toBeAttached();
  await expect(page.locator("#link-card")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("renders hostile source strings as inert text", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop security coverage");
  const manifest = JSON.parse(await readFile(path.join(dataDirectory, "manifest.json"), "utf8")) as {
    layers: Array<{ id: string; sha256: string }>;
  };
  const candidates = JSON.parse(await readFile(path.join(dataDirectory, "candidates.geojson"), "utf8")) as {
    features: Array<{ properties: Record<string, unknown> }>;
  };
  const hostile = '<img src=x onerror="window.__spanPwned=true">';
  candidates.features[0]!.properties.name = hostile;
  candidates.features[0]!.properties.rationale = `<script>window.__spanPwned=true</script>${hostile}`;
  const candidateBody = JSON.stringify(candidates);
  const layer = manifest.layers.find((item) => item.id === "candidates")!;
  layer.sha256 = createHash("sha256").update(candidateBody).digest("hex");

  await page.route("**/data/manifest.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(manifest) }),
  );
  await page.route("**/data/candidates.geojson", (route) =>
    route.fulfill({ contentType: "application/geo+json", body: candidateBody }),
  );
  await page.goto("/?offline=1&candidate=main_street&view=evidence");
  await waitForSpan(page);
  await expect(page.locator("#candidate-title")).toHaveText(hostile);
  await page.locator("#candidate-evidence > summary").click();
  await expect(page.locator("#candidate-detail .rationale")).toContainText("<script>");
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__spanPwned)).toBeUndefined();
});

test("keeps all seven approved screenshot states free of runtime errors", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "single-project state sweep");
  const registry = JSON.parse(await readFile(screenshotStatesPath, "utf8")) as {
    states: Array<{ basename: string; demoQuery: string; viewport: { width: number; height: number }; scrollTarget?: string }>;
  };
  const manifest = JSON.parse(await readFile(path.join(dataDirectory, "manifest.json"), "utf8")) as {
    runId: string;
    attribution: string[];
  };
  expect(registry.states.map((state) => state.basename)).toEqual([
    "workbench-overview",
    "pareto-frontier",
    "candidate-evidence",
    "equity-purpose-portfolio",
    "network-validation-overlays",
    "custom-corridor",
    "responsive-mobile",
  ]);
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const externalRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== "http://127.0.0.1:4173") externalRequests.push(url.href);
  });
  for (const state of registry.states) {
    await page.setViewportSize(state.viewport);
    await page.goto(`/${state.demoQuery}`);
    await waitForSpan(page);
    if (state.scrollTarget) await page.locator(state.scrollTarget).scrollIntoViewIfNeeded();
    await expect(page.locator("#status-message")).not.toHaveClass(/error/);
    await expect(page.locator(state.basename === "responsive-mobile" ? "#link-close" : "#map-info-button")).toBeVisible();
    if (state.basename === "workbench-overview") {
      await page.locator("#map-info-button").click();
      await expect(page.locator("#map-info-dialog")).toBeVisible();
      await expect(page.locator("#map-info-dialog")).toContainText("not Auckland evidence");
      await expect(page.locator("#map-info-dialog")).toContainText(manifest.runId);
      await expect(page.locator("#map-info-dialog")).toContainText(manifest.attribution[0]!);
      await page.locator("#map-info-close").click();
    }
    if (state.basename === "network-validation-overlays") {
      await expect(page.locator("#map-legend-items")).toContainText("no calendar period");
    }
    if (state.basename === "custom-corridor") {
      await expect(page.locator("#sketch-result")).toContainText("3.00 km");
    }
    if (state.basename === "responsive-mobile") {
      await expect(page.locator("#link-card")).toBeVisible();
      await expect(page.locator("#candidate-title")).toHaveText("Main Street protected lanes");
    }
  }
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(externalRequests).toEqual([]);
});
