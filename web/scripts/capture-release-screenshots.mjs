import { readFile, unlink } from "node:fs/promises";
import path from "node:path";

import { chromium } from "playwright";

const baseUrl = process.env.CIW_SCREENSHOT_BASE_URL;
const expectedRunId = process.env.CIW_EXPECTED_RUN_ID;
if (!baseUrl || !expectedRunId) {
  throw new Error("CIW_SCREENSHOT_BASE_URL and CIW_EXPECTED_RUN_ID are required");
}

const webRoot = path.resolve(import.meta.dirname, "..");
const registry = JSON.parse(
  await readFile(path.join(webRoot, "screenshot-states.json"), "utf8"),
);
const outputRoot = path.resolve(
  process.env.CIW_SCREENSHOT_OUTPUT_ROOT ??
    path.join(webRoot, "..", "documentation", "screenshots", "full"),
);
const expectedOrigin = new URL(baseUrl).origin;
const selectedNames = new Set(
  (process.env.CIW_SCREENSHOT_NAMES ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const browser = await chromium.launch({ headless: true });

try {
  for (const state of registry.states.filter(
    (item) => selectedNames.size === 0 || selectedNames.has(item.basename),
  )) {
    const context = await browser.newContext({
      deviceScaleFactor: 1,
      viewport: state.viewport,
    });
    const page = await context.newPage();
    const consoleErrors = [];
    const externalRequests = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("request", (request) => {
      if (new URL(request.url()).origin !== expectedOrigin) externalRequests.push(request.url());
    });
    await page.goto(new URL(state.releaseQuery, baseUrl).href, { waitUntil: "load" });
    await page.locator("#app[aria-busy='false']").waitFor({ timeout: 60_000 });
    await page.locator("#run-summary").filter({ hasText: expectedRunId }).waitFor();
    await page.waitForTimeout(600);
    await page.evaluate(() => window.scrollTo(0, 0));
    const status = await page.locator("#status-message").innerText();
    if (status || consoleErrors.length || externalRequests.length) {
      throw new Error(
        `${state.basename} failed: status=${JSON.stringify(status)}, ` +
        `console=${JSON.stringify(consoleErrors)}, external=${JSON.stringify(externalRequests)}`,
      );
    }
    const scrollTarget = state.releaseScrollTarget ?? state.scrollTarget;
    if (scrollTarget) {
      if (state.releaseScrollContainer) {
        await page.locator(state.releaseScrollContainer).evaluate(
          (container, selector) => {
            const target = container.querySelector(selector);
            if (!(target instanceof HTMLElement)) throw new Error(`Scroll target not found: ${selector}`);
            container.scrollTop = Math.max(0, target.offsetTop - 24);
          },
          scrollTarget,
        );
        await page.evaluate(() => window.scrollTo(0, 0));
      } else {
        await page.locator(scrollTarget).scrollIntoViewIfNeeded();
      }
      await page.waitForTimeout(300);
    }

    const outputPath = path.join(outputRoot, `${state.basename}.png`);
    if (state.viewport.width === 390 && state.viewport.height === 844) {
      const nativePath = path.join(outputRoot, `.${state.basename}-native.png`);
      await page.screenshot({ path: nativePath, type: "png" });
      const nativeBase64 = (await readFile(nativePath)).toString("base64");
      const canvasContext = await browser.newContext({
        deviceScaleFactor: 1,
        viewport: { width: 1800, height: 1100 },
      });
      const canvasPage = await canvasContext.newPage();
      await canvasPage.setContent(
        `<style>*{box-sizing:border-box}html,body{width:1800px;height:1100px;margin:0}` +
          `body{display:grid;place-items:center;background:#edf3f2}` +
          `img{width:390px;height:844px;box-shadow:0 18px 50px rgb(20 50 57 / 18%)}</style>` +
          `<img alt="" src="data:image/png;base64,${nativeBase64}">`,
      );
      await canvasPage.locator("img").waitFor();
      await canvasPage.screenshot({ path: outputPath, type: "png" });
      await canvasContext.close();
      await unlink(nativePath);
    } else {
      await page.locator("#app").screenshot({ path: outputPath, type: "png" });
    }
    await context.close();
    process.stdout.write(`${state.basename}\n`);
  }
} finally {
  await browser.close();
}
