import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { encodeCompactCandidates } from "../src/candidate-codec";

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
