import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { encodeCompactCandidates } from "../src/candidate-codec";
import { purposeIds, scenarioIds, type CandidateFeature, type Manifest } from "../src/types";

const dataDirectory = process.env.SPAN_TEST_DATA_DIR ?? path.resolve(import.meta.dirname, "../public/data");

for (const corrupt of [false, true]) {
  test(corrupt ? "rejects changed compact candidates without an unchecked fallback" : "loads compact candidates without a second canonical download", async ({ page }) => {
    const manifest = JSON.parse(await readFile(path.join(dataDirectory, "manifest.json"), "utf8")) as {
      layers: { id: string; sha256: string }[]; compactCandidates?: unknown;
    };
    const source = JSON.parse(await readFile(path.join(dataDirectory, "candidates.geojson"), "utf8")) as { features: unknown[] };
    const body = JSON.stringify(encodeCompactCandidates(source.features));
    manifest.compactCandidates = {
      format: "span-candidates-v1", url: "./data/candidates.compact.json",
      sha256: createHash("sha256").update(body).digest("hex"),
      sourceSha256: manifest.layers.find(layer => layer.id === "candidates")!.sha256,
      featureCount: source.features.length,
    };
    let canonicalRequests = 0;
    await page.route("**/data/manifest.json", route => route.fulfill({ json: manifest }));
    await page.route("**/data/candidates.compact.json", route => route.fulfill({ body: body + (corrupt ? " " : ""), contentType: "application/json" }));
    await page.route("**/data/candidates.geojson", route => { canonicalRequests++; return route.abort(); });
    await page.goto("/?offline=1");
    await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false");
    if (corrupt) {
      await expect(page.locator("#loading-panel")).toContainText("Integrity check failed");
    } else {
      await expect(page.locator("#loading-panel")).toBeHidden();
      await expect(page.locator("#candidate-list button").first()).toBeVisible();
    }
    expect(canonicalRequests).toBe(0);
  });
}

async function stagedFixture(page: Page, options: { corruptInitial?: boolean; failFirstFull?: boolean; holdFull?: Promise<void> } = {}) {
  const manifest = JSON.parse(await readFile(path.join(dataDirectory, "manifest.json"), "utf8")) as Manifest;
  const source = JSON.parse(await readFile(path.join(dataDirectory, "candidates.geojson"), "utf8")) as { features: CandidateFeature[] };
  const extra = structuredClone(source.features[0]!);
  extra.id = "extra"; extra.properties.candidateId = "extra"; extra.properties.name = "Extra comparison street";
  for (const s of scenarioIds) for (const p of purposeIds) extra.properties.metrics[s][p].lifecycleCostNzd += 100_000_000;
  const full = JSON.stringify(encodeCompactCandidates([...source.features, extra]));
  const initial = JSON.stringify(encodeCompactCandidates(source.features));
  const sourceSha256 = manifest.layers.find(layer => layer.id === "candidates")!.sha256;
  const descriptor = (body: string, filename: string, count: number) => ({
    format: "span-candidates-v1" as const, url: `./data/${filename}`, sourceSha256,
    sha256: createHash("sha256").update(body).digest("hex"), featureCount: count,
  });
  manifest.compactCandidates = descriptor(full, "candidates.compact.json", source.features.length + 1);
  manifest.initialCandidates = { ...descriptor(initial, "candidates.initial.json", source.features.length), scope: "portfolios_and_frontiers_v1" };
  const counts = { initial: 0, full: 0, canonical: 0 };
  await page.route("**/data/manifest.json", route => route.fulfill({ json: manifest }));
  await page.route("**/data/candidates.initial.json", route => {
    counts.initial++;
    return route.fulfill({ body: initial + (options.corruptInitial ? " " : ""), contentType: "application/json" });
  });
  await page.route("**/data/candidates.compact.json", async route => {
    counts.full++;
    await options.holdFull;
    await route.fulfill({ body: full + (options.failFirstFull && counts.full === 1 ? " " : ""), contentType: "application/json" });
  });
  await page.route("**/data/candidates.geojson", route => { counts.canonical++; return route.abort(); });
  return counts;
}

test("opens on initial candidates and keeps a later view choice while full data loads", async ({ page }) => {
  let release!: () => void;
  const holdFull = new Promise<void>(resolve => { release = resolve; });
  const counts = await stagedFixture(page, { holdFull });
  await page.goto("/?offline=1");
  await expect(page.locator("#loading-panel")).toBeHidden();
  await expect(page.locator("#candidate-list button").first()).toBeVisible();
  await page.locator("#scenario-select").selectOption("ebike");
  expect(counts).toEqual({ initial: 1, full: 0, canonical: 0 });
  await page.getByRole("tab", { name: "Value for money" }).click();
  await expect.poll(() => counts.full).toBe(1);
  await expect(page.getByRole("tab", { name: "Build order" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Connected journeys" }).click();
  release();
  await expect(page.locator("#status-message")).not.toContainText("Loading all");
  await expect(page.getByRole("tab", { name: "Connected journeys" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Value for money" }).click();
  await expect(page.locator("#pareto-chart svg")).toBeVisible();
  expect(counts).toEqual({ initial: 1, full: 1, canonical: 0 });
});

test("a failed full-data switch preserves the build order and can be retried", async ({ page }) => {
  const counts = await stagedFixture(page, { failFirstFull: true });
  await page.goto("/?offline=1");
  await expect(page.locator("#loading-panel")).toBeHidden();
  const before = await page.locator("#portfolio-summary").textContent();
  await page.getByRole("tab", { name: "Value for money" }).click();
  await expect(page.locator("#status-message")).toContainText("Integrity check failed");
  await expect(page.getByRole("tab", { name: "Build order" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#portfolio-summary")).toHaveText(before!);
  await page.getByRole("tab", { name: "Value for money" }).click();
  await expect(page.locator("#pareto-chart svg")).toBeVisible();
  expect(counts).toEqual({ initial: 1, full: 2, canonical: 0 });
});

for (const query of ["view=pareto", "layers=candidates", "candidate=extra"]) {
  test(`loads the full universe for a shared link with ${query}`, async ({ page }) => {
    const counts = await stagedFixture(page);
    await page.goto(`/?offline=1&${query}`);
    await expect(page.locator("#loading-panel")).toBeHidden();
    if (query === "candidate=extra") await expect(page.locator("#candidate-title")).toHaveText("Extra comparison street");
    if (query === "view=pareto") await expect(page.locator("#pareto-chart svg")).toBeVisible();
    expect(counts).toEqual({ initial: query === "candidate=extra" ? 1 : 0, full: 1, canonical: 0 });
  });
}

test("rejects corrupt initial data without downloading a replacement", async ({ page }) => {
  const counts = await stagedFixture(page, { corruptInitial: true });
  await page.goto("/?offline=1");
  await expect(page.locator("#loading-panel")).toContainText("Integrity check failed");
  expect(counts).toEqual({ initial: 1, full: 0, canonical: 0 });
});
