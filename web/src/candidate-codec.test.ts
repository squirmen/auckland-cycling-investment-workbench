// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { manifestWithCompactCandidates } from "../candidate-build";
import { decodeCompactCandidates, encodeCompactCandidates } from "./candidate-codec";
import { candidateFeatures, loadLayer } from "./data";
import { candidateFeatureSchema, compactCandidatesDescriptorSchema, purposeIds, scenarioIds, type CandidateFeature, type Manifest } from "./types";

function feature(): CandidateFeature {
  const metric = { available: true, capitalCostNzd: 1234.56789, lifecycleCostNzd: 1400,
    objectiveValue: 0, objectiveUnit: "usual commuters", additionalCycleUsers: 0,
    annualBikeKmDelta: 0, odLowStressShareDelta: null, bcrP5: null, bcrP50: null, bcrP95: null,
    routeCoverage: 0.83, meanRank: 1, topKProbability: null, frontierProbability: null,
    warnings: ["Tāmaki Makaurau: provisional"] };
  return { type: "Feature", id: "A", geometry: { type: "LineString", coordinates: [[174.75123456, -36.80123456], [174.75, -36.81]] },
    properties: { candidateId: "A", name: "Test", purposeOrigins: ["network"], edgeIds: ["e"],
      facilityType: "protected_lane", programmeStatus: "unprogrammed", rationale: "test",
      metrics: Object.fromEntries(scenarioIds.map(s => [s, Object.fromEntries(purposeIds.map(p => [p, structuredClone(metric)]))])) as CandidateFeature["properties"]["metrics"] } };
}

const temporary: string[] = [];
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); for (const path of temporary.splice(0)) rmSync(path, { recursive: true, force: true }); });
const digest = (body: string) => createHash("sha256").update(body).digest("hex");
function buildFixture() {
  const directory = mkdtempSync(join(tmpdir(), "span-compact-test-"));
  temporary.push(directory);
  const source = JSON.stringify({ type: "FeatureCollection", features: [feature()] });
  writeFileSync(join(directory, "candidates.geojson"), source);
  const manifest = { retained: "provenance", layers: [{ id: "candidates", label: "Candidates", url: "./data/candidates.geojson", sha256: digest(source), defaultVisible: true, optional: false, licence: "test", sourceIds: ["preserved"] }] };
  return { directory, source, manifest };
}

it("round-trips every validated value, preserving null, zero, precision and geometry", () => {
  const original = feature();
  original.properties.metrics.ebike.appraisal.objectiveValue = 12.3456789012345;
  const packed = encodeCompactCandidates([original]);
  expect(packed.metrics).toHaveLength(2);
  const result = decodeCompactCandidates(JSON.parse(JSON.stringify(packed)));
  expect(result).toEqual([candidateFeatureSchema.parse(original)]);
  expect(result[0]!.properties.metrics.baseline.network).toBe(result[0]!.properties.metrics.baseline.equity);
  expect(Object.isFrozen(result[0]!.properties.metrics.baseline.network)).toBe(true);
  expect(Object.isFrozen(result[0]!.properties.metrics.baseline.network.warnings)).toBe(true);
});

it.each([-1, 0.5, 500])("rejects invalid metric reference %s", ref => {
  const packed = encodeCompactCandidates([feature()]);
  packed.features[0]!.properties.metrics.baseline.network = ref;
  expect(() => decodeCompactCandidates(packed)).toThrow();
});

it("rejects wrong format, incomplete metric rows and invalid geometry", () => {
  const packed = encodeCompactCandidates([feature()]);
  expect(() => decodeCompactCandidates({ ...packed, format: "unknown" })).toThrow();
  expect(() => decodeCompactCandidates({ ...packed, metrics: [[]] })).toThrow();
  packed.features[0]!.geometry = { type: "LineString", coordinates: [] };
  expect(() => decodeCompactCandidates(packed)).toThrow();
});

it("validates metric values even when the shape is correct", () => {
  const packed = encodeCompactCandidates([feature()]);
  packed.metrics[0]![6] = -1;
  expect(() => decodeCompactCandidates(packed)).toThrow();
});

it("builds a source-bound representation without modifying canonical GeoJSON or provenance", () => {
  const { directory, source, manifest } = buildFixture();
  const result = JSON.parse(manifestWithCompactCandidates(directory, JSON.stringify(manifest))) as Manifest;
  const bytes = readFileSync(join(directory, "candidates.compact.json"), "utf8");
  expect(result.compactCandidates).toMatchObject({ sourceSha256: digest(source), sha256: digest(bytes), featureCount: 1 });
  expect(readFileSync(join(directory, "candidates.geojson"), "utf8")).toBe(source);
  expect(result.layers).toEqual(manifest.layers);
  expect(result).toMatchObject({ retained: "provenance" });
  expect(decodeCompactCandidates(JSON.parse(bytes))).toEqual([feature()]);
});

it("refuses a changed canonical source and removes stale descriptors if absent", () => {
  const { directory, manifest } = buildFixture();
  writeFileSync(join(directory, "candidates.geojson"), "{}");
  expect(() => manifestWithCompactCandidates(directory, JSON.stringify(manifest))).toThrow(/checksum/);
  expect(JSON.parse(manifestWithCompactCandidates(directory, JSON.stringify({ layers: [], compactCandidates: {} })))).not.toHaveProperty("compactCandidates");
});

it("loads the verified compact payload without fetching canonical data or validating it twice", async () => {
  const { directory, manifest } = buildFixture();
  const built = JSON.parse(manifestWithCompactCandidates(directory, JSON.stringify(manifest))) as Manifest;
  const bytes = readFileSync(join(directory, "candidates.compact.json"), "utf8");
  const fetchMock = vi.fn().mockResolvedValue(new Response(bytes)); vi.stubGlobal("fetch", fetchMock);
  const layer = await loadLayer(built, "candidates");
  const candidates = candidateFeatures({ candidates: layer });
  expect(candidates).toEqual([feature()]);
  expect(candidateFeatures({ candidates: layer })).toBe(candidates);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0]![0]).toBe("./data/candidates.compact.json");
});

it.each(["source", "bytes", "count"])("fails closed for a mismatched compact %s", async failure => {
  const { directory, manifest } = buildFixture();
  const built = JSON.parse(manifestWithCompactCandidates(directory, JSON.stringify(manifest))) as Manifest;
  let bytes = readFileSync(join(directory, "candidates.compact.json"), "utf8");
  if (failure === "source") built.compactCandidates!.sourceSha256 = "a".repeat(64);
  if (failure === "bytes") bytes += " ";
  if (failure === "count") built.compactCandidates!.featureCount = 9;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(bytes)));
  await expect(loadLayer(built, "candidates")).rejects.toThrow();
});

it("rejects remote compact URLs", () => {
  expect(() => compactCandidatesDescriptorSchema.parse({ format: "span-candidates-v1", url: "https://external.test/data", sha256: "a".repeat(64), sourceSha256: "b".repeat(64), featureCount: 1 })).toThrow();
});
