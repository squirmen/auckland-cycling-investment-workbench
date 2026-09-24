import assert from "node:assert/strict";
import { createReadStream } from "node:fs";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";

import { chromium, expect } from "@playwright/test";

const site = path.resolve(import.meta.dirname, "../dist");
const output = path.resolve(import.meta.dirname, "../../build/effective-network/browser");
const manifest = JSON.parse(await readFile(path.join(site, "data/manifest.json"), "utf8"));
const report = JSON.parse(await readFile(path.join(site, "data/access-experiment.json"), "utf8"));
assert.equal(manifest.dataStatus, "research_snapshot");
assert.equal(manifest.runId, report.runId);
assert.equal(manifest.effectiveNetwork.topologySha256, report.sourceHashes.topology);
await mkdir(output, { recursive: true });
const mime = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css",
  ".json": "application/json", ".geojson": "application/geo+json", ".svg": "image/svg+xml",
  ".md": "text/plain", ".png": "image/png" };
// A subdirectory is intentional: both SPAN pages and data must use relative URLs.
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    assert.ok(url.pathname.startsWith("/span-preview/"));
    const pathname = decodeURIComponent(url.pathname.slice("/span-preview/".length));
    const file = path.resolve(site, pathname || "index.html");
    assert.ok(file.startsWith(`${site}${path.sep}`));
    assert.ok((await stat(file)).isFile());
    response.setHeader("Content-Type", mime[path.extname(file)] ?? "application/octet-stream");
    createReadStream(file).pipe(response);
  } catch {
    response.writeHead(404); response.end("Not found");
  }
});
await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", resolve);
});
const base = `http://127.0.0.1:${server.address().port}/span-preview/`;
let browser;
const checks = [];
try {
  browser = await chromium.launch({ headless: true });
  for (const [name, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, acceptDownloads: true });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    await page.goto(`${base}?offline=1&layers=existing,intersections`, { waitUntil: "load" });
    await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false", { timeout: 90000 });
    await expect(page.locator("#controls-panel h1")).toHaveText("SPAN");
    await expect(page.locator("#data-status")).toHaveText("Preliminary estimates");
    await expect(page.locator("#run-summary")).toContainText(manifest.runId);
    await expect(page.locator("#status-message")).not.toHaveClass(/error/);
    await expect(page.locator("#layer-intersections")).toBeChecked();
    await expect(page.locator("#map-legend-items")).toContainText("Matched signal-controlled site");
    await expect(page.locator("#intersection-source-note")).toContainText(`${manifest.effectiveNetwork.matchedSites} of`);
    await page.waitForTimeout(500); // Let Leaflet's fit/pan animation settle before visual QA.
    await page.screenshot({ path: path.join(output, `${name}-explorer.png`) });
    if (name === "desktop") {
      await page.locator("#layers-disclosure > summary").click();
      await page.locator("#layer-intersections").uncheck();
      await expect(page.locator("#map-legend-items")).not.toContainText("Matched signal-controlled site");
      await page.locator("#layer-intersections").check();
      await expect(page.locator("#map-legend-items")).toContainText("Matched signal-controlled site");
      await page.screenshot({ path: path.join(output, "desktop-layers.png") });
      await page.locator("#layers-disclosure > summary").click();
      const markerPoints = await page.evaluate(() => {
        const points = [];
        for (const canvas of document.querySelectorAll(".leaflet-points-pane canvas")) {
          const rect = canvas.getBoundingClientRect();
          const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
          for (let y = 0; y < canvas.height; y += 2) {
            for (let x = 0; x < canvas.width; x += 2) {
              const offset = (y * canvas.width + x) * 4;
              if (pixels[offset] < 110 || pixels[offset] > 170 || pixels[offset + 1] > 120 || pixels[offset + 2] < 200 || pixels[offset + 3] < 150) continue;
              const screenX = rect.x + x * rect.width / canvas.width;
              const screenY = rect.y + y * rect.height / canvas.height;
              if (screenX > 500 && screenX < innerWidth - 250 && screenY > 350 && screenY < innerHeight - 300 && document.elementFromPoint(screenX, screenY) === canvas && !points.some(p => Math.hypot(p.x - screenX, p.y - screenY) < 16)) points.push({ x: screenX, y: screenY });
            }
          }
        }
        return points.slice(0, 30);
      });
      assert.ok(markerPoints.length, "a matched signal marker must be drawn");
      let matchedPopup = false;
      for (const point of markerPoints) {
        await page.mouse.click(point.x, point.y);
        if (await page.locator(".leaflet-popup-content").count()) {
          if ((await page.locator(".leaflet-popup-content").innerText()).includes("Assumed delay:")) { matchedPopup = true; break; }
          await page.keyboard.press("Escape");
        }
      }
      assert.ok(matchedPopup, "a matched intersection popup must show its assumed wait");
      await expect(page.locator(".leaflet-popup-content")).toContainText("Assumed delay:");
      await expect(page.locator(".leaflet-popup-content")).toContainText("Actual phases, bicycle detection and waiting times require AT data");
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(output, "desktop-intersection-popup.png") });
      await page.locator(".leaflet-popup-close-button").click();
      await page.locator("#candidate-search").fill("Grand Drive");
      await page.locator("#candidate-list button").first().click();
      await expect(page.locator("#link-card")).toBeVisible();
      await expect(page.locator("#candidate-title")).not.toBeEmpty();
      await page.waitForTimeout(700);
      await page.screenshot({ path: path.join(output, "desktop-link-details.png") });
    }
    if (name === "desktop") await page.locator("#link-close").click();
    await page.getByRole("tab", { name: "Connected journeys" }).click();
    await expect(page.locator("#connected-controls")).toBeVisible({ timeout: 30000 });
    await expect(page.locator("#connected-provenance")).toContainText(`${report.intersectionContext.sitesInCrop} matched intersections`);
    await page.locator("#connected-package-map").click();
    const packageSelection = report.solutions.find(s => s.budget === Math.max(...report.solutions.map(item => item.budget)) && s.method === "route_packages_milp");
    await expect(page.locator("#map .connected-package-pin")).toHaveCount(packageSelection.selected.length);
    await page.screenshot({ path: path.join(output, `${name}-package.png`) });
    await page.locator("#connected-package-map").click();
    const delayed = report.journeys.find(j => j.alternatives.some(r => r.intersectionDelayS > 0));
    assert.ok(delayed, "the pilot must exercise at least one nonzero delay");
    await page.locator("#connected-journey").selectOption(delayed.name);
    const index = delayed.alternatives.findIndex(r => r.intersectionDelayS > 0);
    await page.locator("#connected-alternative").selectOption(String(index));
    await expect(page.locator("#connected-route-detail")).toContainText("assumed intersection delay");
    await page.waitForTimeout(500);
    const drawnPaths = page.locator('#map .connected-end');
    if (await drawnPaths.count() === 0) {
      process.stdout.write(JSON.stringify(await page.locator("#map").evaluate(el => ({
        viewport: el.getBoundingClientRect().toJSON(), pane: el.querySelector(".leaflet-map-pane")?.getAttribute("style"),
        svg: el.querySelector("svg")?.outerHTML.slice(0, 500), markers: [...el.querySelectorAll(".connected-end")].map(m => m.getAttribute("style")),
      })), null, 2) + "\n");
    }
    await expect(drawnPaths.first()).toBeVisible();
    const endpoints = await drawnPaths.evaluateAll(markers => markers.map(m => m.getBoundingClientRect().toJSON()));
    assert.ok(Math.hypot(endpoints[0].x - endpoints[1].x, endpoints[0].y - endpoints[1].y) > 60, "route must be legible at the fitted zoom");
    await page.screenshot({ path: path.join(output, `${name}-connected.png`) });
    const download = page.waitForEvent("download");
    await page.locator("#download-button").click();
    const exported = await download;
    const json = JSON.parse(await readFile(await exported.path(), "utf8"));
    assert.equal(json.type, "FeatureCollection");
    assert.ok(json.features.length > 0);
    assert.ok(json.span.inspectedRouteIntersectionDelayS > 0);
    assert.equal(json.span.intersectionContext.scenario, "default");
    await page.getByText("Route preferences", { exact: true }).click();
    await page.locator("#connected-preference").selectOption(report.assignment.profiles[0].id);
    await expect(page.locator("#connected-assignment-summary")).toContainText("not additional cyclists");
    const notes = await context.request.get(`${base}documentation/effective-network.md`);
    assert.ok(notes.ok());
    const comparisonResponse = await context.request.get(`${base}data/delay-comparison.json`);
    assert.ok(comparisonResponse.ok());
    const comparison = await comparisonResponse.json();
    assert.equal(comparison.runId, manifest.runId);
    assert.deepEqual(errors, [], `${name}: runtime or HTTP errors`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: horizontal overflow`);
    checks.push({ viewport: name, branding: true, intersections: true, researchDelay: true,
      export: true, relativeAssets: true, errors });
    await context.close();
  }
  await writeFile(path.join(output, "checks.json"), JSON.stringify({ runId: manifest.runId, checks }, null, 2));
  process.stdout.write(JSON.stringify({ runId: manifest.runId, checks, screenshots: output }, null, 2) + "\n");
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
