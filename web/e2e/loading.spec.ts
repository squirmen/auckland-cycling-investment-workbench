import { expect, test, type Page } from "@playwright/test";

async function ready(page: Page): Promise<void> {
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false", { timeout: 15000 });
  await expect(page.locator("#candidate-list button").first()).toBeAttached();
}

test("shows the build order before a slow context layer arrives", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested = 0;
  await page.route("**/data/cells.geojson", async route => { requested++; await gate; await route.fallback(); });
  await page.goto("/?offline=1");
  await ready(page);
  await expect(page.locator("#layer-cells")).toBeChecked();
  expect(requested).toBe(1);
  const loaded = page.waitForResponse(response => response.url().endsWith("/data/cells.geojson"));
  release();
  await loaded;
  await expect(page.locator("#status-message")).not.toHaveClass(/error/);
  await expect(page.locator("#layer-cells")).toBeChecked();
});

test("keeps the build order when a context layer cannot be loaded", async ({ page }) => {
  await page.route("**/data/cells.geojson", route => route.fulfill({ status: 404, body: "missing" }));
  await page.goto("/?offline=1");
  await ready(page);
  await expect(page.locator("#status-message")).toContainText("HTTP 404");
  await expect(page.locator("#status-message")).toHaveClass(/error/);
  await expect(page.locator("#layer-cells")).not.toBeChecked();
  await expect(page.locator("#map-legend-items")).toContainText("Build order");
});

test("recovers from a dropped connection without asking", async ({ page }) => {
  let calls = 0;
  await page.route("**/data/manifest.json", route => (++calls === 1 ? route.abort("connectionreset") : route.fallback()));
  await page.goto("/?offline=1");
  await ready(page);
  expect(calls).toBe(2);
  await expect(page.locator("#loading-panel")).toBeHidden();
});

test("offers another try when the data cannot be loaded", async ({ page }) => {
  await page.route("**/data/manifest.json", route => route.fulfill({ status: 404, body: "missing" }));
  await page.goto("/?offline=1");
  await expect(page.locator("#loading-panel")).toContainText("The data could not be loaded");
  await expect(page.locator("#loading-panel")).toContainText("HTTP 404");
  await page.unroute("**/data/manifest.json");
  await page.getByRole("button", { name: "Try again" }).click();
  await ready(page);
  await expect(page.locator("#loading-panel")).toBeHidden();
});

test("fits the map to the printed page and puts it back afterwards", async ({ page }) => {
  await page.goto("/?offline=1");
  await ready(page);
  await page.evaluate(() => {
    window.print = () => { document.body.dataset.printedWhilePrinting = String(document.body.classList.contains("printing")); };
  });
  const before = await page.locator("#map").boundingBox();
  await page.locator("#print-button").click();
  await expect(page.locator("body")).toHaveAttribute("data-printed-while-printing", "true");
  await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
  await expect(page.locator("body")).not.toHaveClass(/printing/);
  expect(await page.locator("#map").boundingBox()).toEqual(before);
  await page.emulateMedia({ media: "print" });
  await expect(page.locator("#map-legend")).toHaveCSS("position", "static");
  await expect(page.locator(".map-tools")).toBeHidden();
  await expect(page.locator("#print-button")).toBeHidden();
});

test("list rows keep their height inside a scrolling list", async ({ page }) => {
  await page.goto("/?offline=1&view=pareto");
  await ready(page);
  await expect(page.locator("#pareto-list .compact-row").first()).toHaveCSS("flex-shrink", "0");
});

test("gives the map its box even when the stylesheet is missing", async ({ page }) => {
  // Safari can run the script before the stylesheet arrives. The map's box comes from the page itself.
  await page.route("**/assets/*.css", route => route.abort());
  await page.goto("/?offline=1");
  await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false", { timeout: 20000 });
  const box = await page.evaluate(() => {
    const map = document.getElementById("map")!;
    return { height: map.clientHeight, width: map.clientWidth, viewport: [window.innerWidth, window.innerHeight], inlinePosition: map.style.position };
  });
  expect([box.width, box.height]).toEqual(box.viewport);
  expect(box.inlinePosition).toBe("");
});
