import { expect, test } from "@playwright/test";

// These run in WebKit, the engine Safari uses, as well as in Chrome. WebKit can run the page's
// script before the stylesheet is applied. On 1 October 2026 that left the live map at zero
// height in Safari while every Chrome check passed.
for (const delayMs of [0, 1500]) {
  test(`draws the map when the stylesheet arrives ${delayMs ? "late" : "on time"}`, async ({ page }) => {
    if (delayMs) {
      await page.route("**/assets/*.css", async route => {
        await new Promise(resolve => setTimeout(resolve, delayMs));
        await route.continue();
      });
    }
    await page.goto("/?offline=1");
    await expect(page.locator("#app")).toHaveAttribute("aria-busy", "false", { timeout: 20000 });
    const box = await page.evaluate(() => {
      const map = document.getElementById("map")!;
      return { size: [map.clientWidth, map.clientHeight], viewport: [window.innerWidth, window.innerHeight], inlinePosition: map.style.position };
    });
    expect(box.size).toEqual(box.viewport);
    expect(box.inlinePosition).toBe("");
    const pin = await page.locator("#map .rank-pin").first().boundingBox();
    expect(pin).not.toBeNull();
    expect(pin!.y).toBeGreaterThan(0);
    expect(pin!.y).toBeLessThan(box.viewport[1]!);
  });
}
