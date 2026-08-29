import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const dataDirectory = path.resolve(import.meta.dirname, "../public/data");
const screenshotStatesPath = path.resolve(import.meta.dirname, "../screenshot-states.json");

async function waitForWorkbench(page: Page): Promise<void> {
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false");
  await expect(page.getByRole("heading", { name: "Auckland Cycling Investment Workbench" })).toBeVisible();
  await expect(page.locator("#data-status")).toHaveText("Synthetic demo");
  await expect(page.locator("#run-summary")).toContainText(/Run run-[a-f0-9]{16}/);
}

test("loads the default budget and updates every scenario-purpose control", async ({ page }) => {
  await page.goto("/?offline=1");
  await waitForWorkbench(page);
  await expect(page.locator("#budget-output")).toHaveText("$2,000,000");
  await expect(page.locator("#headline-kpis .kpi").first()).toContainText(
    "weighted synthetic daily cycle trips",
  );
  await expect(page.locator("#candidate-list li")).toHaveCount(1);
  await expect(page.locator("#methodology-link")).toHaveAttribute(
    "href",
    /\/documentation\/methodology\.md$/,
  );

  await page.locator("#scenario-select").selectOption("ebike");
  await page.locator("#purpose-select").selectOption("school");
  await expect(page.locator("#scenario-note")).toContainText(/e-bike/i);
  await expect(page.locator("#purpose-note")).toContainText(/school/i);
  await expect(page.locator("#scenario-select")).toHaveValue("ebike");
  await expect(page.locator("#purpose-select")).toHaveValue("school");
  await expect(page.locator("#connectivity-context")).toContainText(/School purpose/i);
  await expect(page.locator("#connectivity-context")).toContainText(/complete denominator/i);
  await expect(page.locator("#connectivity-context")).toContainText(/LTS ≤ 2/i);
  await expect(page.locator("#connectivity-context")).toContainText(/detour ≤ 1\.5/i);
  await expect(page.locator("#connectivity-context")).toContainText(/routing coverage/i);
  await expect(page).toHaveURL(/scenario=ebike/);
  await expect(page).toHaveURL(/purpose=school/);

  await page.locator("#scenario-select").selectOption("government_target");
  await expect(page.locator("#scenario-select")).toHaveValue("government_target");
  await page.locator("#scenario-select").selectOption("commute_8pct");
  await expect(page.locator("#scenario-note")).toContainText(/sensitivity/i);
  await expect(page.locator("#scenario-note")).not.toContainText(/TERP model/i);
});

test("supports portfolio search, a true zero-budget state, and a one-action reset", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  await page.goto("/?offline=1&budget=2.8&scenario=go_dutch&purpose=school");
  await waitForWorkbench(page);
  await expect(page.locator("#candidate-list li")).toHaveCount(2);

  await page.locator("#candidate-search").fill("central");
  await expect(page.locator("#candidate-list li")).toHaveCount(1);
  await expect(page.locator("#portfolio-count")).toHaveText("1 of 2");
  await expect(page.locator("#candidate-list")).toContainText("Central protected crossing");

  await page.locator("#candidate-search").fill("");
  await page.locator("#budget-slider").fill("0");
  await expect(page.locator("#portfolio-count")).toHaveText("0 projects");
  await expect(page.locator("#candidate-list")).toContainText("No projects fit this budget");
  await expect(page.locator("#download-button")).toBeDisabled();

  await page.locator("#reset-button").click();
  await expect(page.locator("#scenario-select")).toHaveValue("commute_8pct");
  await expect(page.locator("#purpose-select")).toHaveValue("network");
  await expect(page.locator("#budget-output")).toHaveText("$2,000,000");
  await expect(page.locator("#status-message")).toContainText("reset to the published defaults");
});

test("uses the selected purpose in the Pareto view and preserves out-of-budget selection", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  await page.goto("/?offline=1&view=pareto&budget=0.5&purpose=equity");
  await waitForWorkbench(page);
  await expect(page.locator("#pareto-chart svg")).toHaveAttribute(
    "aria-label",
    /equity benefit per lifecycle dollar/i,
  );
  await page.locator('#pareto-chart circle[data-candidate-id="central_crossing"]').click();
  await expect(page.locator("#candidate-title")).toHaveText("Central protected crossing");
  await expect(page.locator("#candidate-detail .facts")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evidence profile" })).toBeVisible();
  await expect(page.locator("#candidate-detail")).toContainText("Pareto-frontier stability");
  await expect(page.locator("#candidate-detail")).toContainText(
    "Mean uncertainty rank: not available",
  );
  await expect(page.locator("#candidate-detail")).toContainText("$800,000");
  await expect(page.locator("#budget-output")).toHaveText("$500,000");
  await expect(page).toHaveURL(/budget=0\.5/);
});

test("lazy-loads the programme and counter overlays from verified files", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop interaction coverage");
  const countersLoaded = page.waitForResponse((response) => response.url().endsWith("/data/counters.geojson"));
  const programmesLoaded = page.waitForResponse((response) => response.url().endsWith("/data/programmes.geojson"));
  await page.goto(
    "/?offline=1&layers=cells%2Cnetwork%2Ccandidates%2Cprogrammes%2Ccounters",
  );
  await Promise.all([countersLoaded, programmesLoaded]);
  await waitForWorkbench(page);
  await expect(page.locator("#layer-programmes")).toBeChecked();
  await expect(page.locator("#layer-counters")).toBeChecked();
  await expect(page.locator("#overlay-context")).toBeVisible();
  await expect(page.locator("#overlay-context")).toContainText("1 funded of 1 shown");
  await expect(page.locator("#overlay-context")).toContainText("2/2 counter sites matched");
  await expect(page.locator("#overlay-context")).toContainText("no calendar period");
  await expect(page.locator("#status-message")).not.toHaveClass(/error/);
});

test("exports exactly the declared budget portfolio with its active metrics", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop download coverage");
  await page.goto("/?offline=1&scenario=ebike&purpose=school&budget=2");
  await waitForWorkbench(page);
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const exported = JSON.parse(await readFile(downloadPath, "utf8")) as {
    features: Array<{ properties: Record<string, unknown> }>;
    ciw_export: Record<string, unknown>;
  };
  expect(exported.features.map((feature) => feature.properties.candidate_id)).toEqual([
    "main_street",
  ]);
  expect(exported.features[0]?.properties.scenario).toBe("ebike");
  expect(exported.features[0]?.properties.purpose).toBe("school");
  expect(exported.features[0]?.properties.lifecycle_cost_nzd).toEqual(expect.any(Number));
  expect(exported.features[0]?.properties.od_low_stress_share_delta).toEqual(expect.any(Number));
  expect(exported.ciw_export.budget_nzd).toBe(2_000_000);
});

test("restores and exports a graph-snapped exact-edge corridor", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop sketch coverage");
  await page.goto("/?offline=1&sketch=A%2CF&budget=2.8");
  await waitForWorkbench(page);
  await expect(page.locator("#sketch-result .mini-facts")).toBeVisible();
  await expect(page.locator("#sketch-result")).toContainText("Capital screen");
  await expect(page.locator("#sketch-result")).toContainText("not a counterfactual");
  await expect(page).toHaveURL(/sketch=A%2CF/);

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const downloadPath = await (await downloadPromise).path();
  const exported = JSON.parse(await readFile(downloadPath, "utf8")) as {
    features: Array<{ properties: Record<string, unknown> }>;
    ciw_export: Record<string, unknown>;
  };
  const sketch = exported.features.find(
    (feature) => feature.properties.candidate_id === "user-sketch",
  );
  expect(sketch?.properties.ordered_edge_ids).toEqual(["ab", "bc", "cf"]);
  expect(sketch?.properties.unique_edge_ids).toEqual(["ab", "bc", "cf"]);
  expect(sketch?.properties.evaluation_status).toBe("requires_pipeline_evaluation");
  expect(sketch?.properties.source_run_id).toBe(exported.ciw_export.run_id);
  expect(sketch?.properties.config_sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(sketch?.properties.daily_trips_delta).toBeUndefined();

  await page.locator("#sketch-clear").click();
  await expect(page.locator("#sketch-result")).toContainText("Choose at least two");
  await expect(page).not.toHaveURL(/sketch=/);
});

test("supports keyboard tab navigation and keyboard candidate selection", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop keyboard coverage");
  await page.goto("/?offline=1&view=portfolio");
  await waitForWorkbench(page);
  const portfolioTab = page.getByRole("tab", { name: "Portfolio" });
  await portfolioTab.focus();
  await portfolioTab.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Trade-offs" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const point = page.locator('#pareto-chart circle[data-candidate-id="central_crossing"]');
  await point.focus();
  await point.press("Space");
  await expect(page.getByRole("tab", { name: "Evidence" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.locator("#candidate-title")).toHaveText("Central protected crossing");
});

test("is responsive without horizontal document overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "mobile project only");
  await page.goto("/?offline=1&scenario=go_dutch&purpose=school");
  await waitForWorkbench(page);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  await page.locator("#map").scrollIntoViewIfNeeded();
  await expect(page.locator("#map")).toBeVisible();
  await expect(page.locator("#scenario-select")).toBeVisible();
  await expect(page.locator("#download-button")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Workbench sections" })).toBeVisible();
  await expect(page.locator("#map-legend").getByText("Legend", { exact: true })).toBeVisible();
});

test("has no automatically detectable accessibility violations", async ({ page }) => {
  await page.goto("/?offline=1");
  await waitForWorkbench(page);
  await expect(page.locator("#candidate-list li").first()).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("renders hostile source strings as inert text", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop security coverage");
  const manifest = JSON.parse(await readFile(path.join(dataDirectory, "manifest.json"), "utf8")) as {
    layers: Array<{ id: string; sha256: string }>;
  };
  const candidates = JSON.parse(
    await readFile(path.join(dataDirectory, "candidates.geojson"), "utf8"),
  ) as { features: Array<{ properties: Record<string, unknown> }> };
  const hostile = '<img src=x onerror="window.__ciwPwned=true">';
  candidates.features[0]!.properties.name = hostile;
  candidates.features[0]!.properties.rationale = `<script>window.__ciwPwned=true</script>${hostile}`;
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
  await waitForWorkbench(page);
  await expect(page.locator("#candidate-title")).toHaveText(hostile);
  await expect(page.locator("#candidate-detail .rationale")).toContainText("<script>");
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(
    await page.evaluate(() => (window as unknown as Record<string, unknown>).__ciwPwned),
  ).toBeUndefined();
});

test("keeps all seven approved screenshot states free of runtime errors", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "single-project state sweep");
  const registry = JSON.parse(await readFile(screenshotStatesPath, "utf8")) as {
    states: Array<{
      basename: string;
      demoQuery: string;
      viewport: { width: number; height: number };
      scrollTarget?: string;
    }>;
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
    await waitForWorkbench(page);
    if (state.scrollTarget) await page.locator(state.scrollTarget).scrollIntoViewIfNeeded();
    await expect(page.locator("#status-message")).not.toHaveClass(/error/);
    await expect(page.locator("#map-provenance")).toBeVisible();
    await expect(page.locator("#map-provenance")).toContainText("not Auckland evidence");
    await expect(page.locator("#map-provenance")).toContainText(manifest.runId);
    await expect(page.locator("#map-provenance")).toContainText(manifest.attribution[0]!);
    if (state.basename === "network-validation-overlays") {
      await expect(page.locator("#overlay-context")).toContainText("no calendar period");
    }
    if (state.basename === "custom-corridor") {
      await expect(page.locator("#sketch-result")).toContainText("3.00 km");
    }
    if (state.basename === "responsive-mobile") {
      await expect(page.getByRole("tab", { name: "Evidence" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(page.locator("#candidate-title")).toHaveText("Main Street protected lanes");
    }
  }
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
  expect(externalRequests).toEqual([]);
});
