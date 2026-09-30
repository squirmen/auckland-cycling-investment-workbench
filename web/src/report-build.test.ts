// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { manifestWithJourneyReport } from "../report-integrity";

const temporary: string[] = [];
afterEach(() => { for (const path of temporary.splice(0)) rmSync(path, { recursive: true, force: true }); });
const hash = "a".repeat(64);
function fixture() {
  const directory = mkdtempSync(join(tmpdir(), "span-report-test-"));
  temporary.push(directory);
  writeFileSync(join(directory, "manifest.json"), JSON.stringify({
    runId: "test", preservedField: 123, effectiveNetwork: { topologySha256: hash },
    journeyReport: { sha256: "obsolete" },
  }));
  return directory;
}

it("binds exact bytes and preserves the source manifest and model results", () => {
  const directory = fixture();
  const before = readFileSync(join(directory, "manifest.json"), "utf8");
  const body = JSON.stringify({ runId: "test", sourceHashes: { topology: hash } }) + "\n";
  writeFileSync(join(directory, "access-experiment.json"), body);
  expect(JSON.parse(manifestWithJourneyReport(directory))).toMatchObject({
    preservedField: 123,
    journeyReport: { url: "./data/access-experiment.json", runId: "test", topologySha256: hash, sha256: createHash("sha256").update(body).digest("hex") },
  });
  expect(readFileSync(join(directory, "manifest.json"), "utf8")).toBe(before);
  expect(readFileSync(join(directory, "access-experiment.json"), "utf8")).toBe(body);
});

it("omits stale descriptors when no report is bundled", () => {
  expect(JSON.parse(manifestWithJourneyReport(fixture()))).not.toHaveProperty("journeyReport");
});

it.each(["run", "topology"])("refuses a report with mismatched %s", field => {
  const directory = fixture();
  writeFileSync(join(directory, "access-experiment.json"), JSON.stringify({
    runId: field === "run" ? "wrong" : "test",
    sourceHashes: { topology: field === "topology" ? "b".repeat(64) : hash },
  }));
  expect(() => manifestWithJourneyReport(directory)).toThrow("does not match");
});
