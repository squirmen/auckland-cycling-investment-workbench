import { afterEach, expect, it, vi } from "vitest";
import { sha256Hex } from "./data";
import { loadJourneyReport } from "./research-data";
import { journeyReportDescriptorSchema, type Manifest } from "./types";

const hash = "a".repeat(64);
const report = {
  schemaVersion: "1.0.0", status: "local_research_pilot", runId: "test",
  centre: [174, -36], radiusM: 4000, seed: 1, elapsedS: 1, searchComplete: true,
  graph: { nodes: 2, directedArcs: 1, projects: 0 },
  sample: { selected: 0, eligibleWithinArea: 0, weightedDemand: 0, citywideRepresentative: false },
  standard: { maximum_stress: 2, maximum_detour: 1.5, maximum_time_s: 1800 },
  sourceHashes: { topology: hash, odLedger: hash, candidateLedger: hash, scenarioOdLedger: hash, origins: hash, originWeights: hash },
  implementationHash: hash, experimentScriptHash: hash,
  baseline: { weight: 0, journeys: 0 }, solutions: [], journeys: [], projects: [],
  ridershipForecast: null, limitations: [],
  assignment: { status: "fixed_demand_illustrative_preferences", scenarioId: "test", totalDemand: 0, profiles: [], portfolios: [] },
};
afterEach(() => vi.unstubAllGlobals());

async function serve(value: object = report) {
  const body = JSON.stringify(value);
  const sha256 = await sha256Hex(new TextEncoder().encode(body).buffer);
  const fetch = vi.fn().mockResolvedValue(new Response(body));
  vi.stubGlobal("fetch", fetch);
  const manifest = {
    runId: "test", effectiveNetwork: { topologySha256: hash },
    journeyReport: { url: "./data/access-experiment.json", sha256, runId: "test", topologySha256: hash },
  } as Manifest;
  return { manifest, fetch };
}

it("accepts only matching report bytes and release scope", async () => {
  const { manifest, fetch } = await serve();
  expect((await loadJourneyReport(manifest)).runId).toBe("test");
  expect(fetch).toHaveBeenCalledWith("./data/access-experiment.json", { credentials: "same-origin", cache: "no-cache" });
});

it("rejects corrupted bytes even when the report is valid JSON with the same run", async () => {
  const { manifest, fetch } = await serve();
  fetch.mockResolvedValue(new Response(JSON.stringify({ ...report, radiusM: 8000 })));
  await expect(loadJourneyReport(manifest)).rejects.toThrow("Integrity check failed");
});

it("does not fetch an unbound or mismatched report", async () => {
  const { manifest, fetch } = await serve();
  await expect(loadJourneyReport({ ...manifest, journeyReport: undefined })).rejects.toThrow("not available");
  await expect(loadJourneyReport({ ...manifest, runId: "different" })).rejects.toThrow("different data release");
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["run", "topology"])("rejects a correctly hashed report with the wrong %s", async field => {
  const wrong = field === "run" ? { ...report, runId: "wrong" } : { ...report, sourceHashes: { ...report.sourceHashes, topology: "b".repeat(64) } };
  const { manifest } = await serve(wrong);
  await expect(loadJourneyReport(manifest)).rejects.toThrow("different data release");
});

it("keeps missing report errors understandable", async () => {
  const { manifest, fetch } = await serve();
  fetch.mockResolvedValue(new Response("", { status: 404 }));
  await expect(loadJourneyReport(manifest)).rejects.toThrow("not available in this release");
});

it.each(["https://example.test/report.json", "../private.json", "./data/%2e%2e/report.json"])("rejects unsafe report URL %s", url => {
  expect(journeyReportDescriptorSchema.safeParse({ url, sha256: hash, runId: "test", topologySha256: hash }).success).toBe(false);
});
