import { afterEach, describe, expect, it, vi } from "vitest";

import { candidateFeatures, fetchVerifiedJson, loadLayer, setRetryDelayMs, sha256Hex } from "./data";
import { candidateFeatureSchema, layerSchema, manifestSchema, purposeIds, scenarioIds, type CandidateFeature, type Manifest } from "./types";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); setRetryDelayMs(1500); });

it("tries again after a dropped connection or a busy server, then checks the bytes", async () => {
  setRetryDelayMs(0);
  const body = JSON.stringify({ ok: true });
  const sha256 = await sha256Hex(new TextEncoder().encode(body).buffer);
  const dropped = new Response(new ReadableStream({ start(controller) { controller.error(new Error("reset")); } }));
  const fetchMock = vi.fn()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(dropped)
    .mockResolvedValueOnce(new Response(body));
  vi.stubGlobal("fetch", fetchMock);
  await expect(fetchVerifiedJson("./data/file.json", sha256)).resolves.toEqual({ ok: true });
  expect(fetchMock).toHaveBeenCalledTimes(3);

  fetchMock.mockReset().mockResolvedValue(new Response("busy", { status: 503 }));
  await expect(fetchVerifiedJson("./data/file.json", sha256)).rejects.toThrow("HTTP 503");
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("does not repeat a request that cannot succeed", async () => {
  setRetryDelayMs(0);
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("missing", { status: 404 })));
  vi.stubGlobal("fetch", fetchMock);
  await expect(fetchVerifiedJson("./data/file.json")).rejects.toThrow("HTTP 404");
  expect(fetchMock).toHaveBeenCalledTimes(1);

  fetchMock.mockClear().mockImplementation(() => Promise.resolve(new Response("{}")));
  await expect(fetchVerifiedJson("./data/file.json", "a".repeat(64))).rejects.toThrow("Integrity check failed");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("reports how much of a file of known size has arrived", async () => {
  const body = JSON.stringify({ rows: "x".repeat(4000) });
  const bytes = new TextEncoder().encode(body);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, 1000));
      controller.enqueue(bytes.slice(1000));
      controller.close();
    },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream)));
  const shares: number[] = [];
  const sha256 = await sha256Hex(bytes.buffer);
  await expect(fetchVerifiedJson("./data/file.json", sha256, (share) => shares.push(share), bytes.byteLength)).resolves.toEqual(JSON.parse(body));
  expect(shares).toEqual([1000 / bytes.byteLength, 1]);
});

it("validates candidate records once when loading, then reuses the validated collection", async () => {
  const feature = { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] }, properties: {} };
  const parsed = { ...feature, properties: { candidateId: "validated" } } as CandidateFeature;
  const parse = vi.spyOn(candidateFeatureSchema, "parse").mockReturnValue(parsed);
  const body = JSON.stringify({ type: "FeatureCollection", features: [feature] });
  const sha256 = await sha256Hex(new TextEncoder().encode(body).buffer);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
  const manifest = { layers: [{ id: "candidates", label: "Candidates", url: "./data/candidates.geojson", sha256, defaultVisible: true, optional: false, licence: "Test" }] } as Manifest;
  const collection = await loadLayer(manifest, "candidates");
  const first = candidateFeatures({ candidates: collection });
  expect(first[0]).toBe(parsed);
  expect(candidateFeatures({ candidates: collection })).toBe(first);
  expect(parse).toHaveBeenCalledTimes(1);
});

function completeByScenario<T>(value: T): Record<(typeof scenarioIds)[number], Record<(typeof purposeIds)[number], T>> {
  return Object.fromEntries(
    scenarioIds.map((scenario) => [scenario, Object.fromEntries(purposeIds.map((purpose) => [purpose, structuredClone(value)]))]),
  ) as Record<(typeof scenarioIds)[number], Record<(typeof purposeIds)[number], T>>;
}

function completeSummaries(
  value: Record<string, unknown>,
): Record<(typeof scenarioIds)[number], Record<(typeof purposeIds)[number], Record<string, unknown>>> {
  return Object.fromEntries(
    scenarioIds.map((scenario) => [
      scenario,
      Object.fromEntries(
        purposeIds.map((purpose) => [purpose, { ...structuredClone(value), purpose }]),
      ),
    ]),
  ) as unknown as Record<
    (typeof scenarioIds)[number],
    Record<(typeof purposeIds)[number], Record<string, unknown>>
  >;
}

describe("web data integrity", () => {
  it("calculates a standard SHA-256 digest", async () => {
    const bytes = new TextEncoder().encode("abc");
    await expect(sha256Hex(bytes.buffer)).resolves.toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("requires every scenario and purpose in a manifest", () => {
    const summary = {
      activityValue: 100,
      activityUnit: "modelled daily trips",
      odLowStressShare: 0.2,
      odLowStressConnectedWeight: 20,
      odLowStressDenominatorWeight: 100,
      routingCoverage: 0.9,
      maximumLts: 2,
      maximumDetourRatio: 1.5,
      candidateCount: 2,
      validationCoverage: null,
      warnings: [],
    };
    const valid = {
      schemaVersion: "2.0.0",
      modelVersion: "1.0.0",
      configSha256: "a".repeat(64),
      runId: "fixture",
      generatedAtUtc: "2026-08-16T00:00:00Z",
      title: "Fixture",
      dataStatus: "synthetic_demo",
      dataStatusLabel: "Synthetic demonstration",
      defaultScenario: "baseline",
      defaultPurpose: "network",
      defaultBudgetNzd: 1_000_000,
      maxBudgetNzd: 5_000_000,
      scenarios: scenarioIds.map((id) => ({ id, label: id, description: id })),
      purposes: purposeIds.map((id) => ({ id, label: id, description: id, objectiveLabel: id })),
      summaries: completeSummaries(summary),
      portfolios: completeByScenario([]),
      validation: {
        periodLabel: "Synthetic fixture; no calendar period",
        counterCount: 2,
        matchedCount: 2,
        coverage: 1,
        purposeAlignment: "Synthetic daily cycling counts",
        status: "synthetic_fixture",
      },
      capabilities: {
        equity: "available",
        appraisal: "research_only",
        sketchEvaluation: "requires_pipeline_evaluation",
      },
      limitations: ["Fixture only"],
      layers: [],
      attribution: ["Fixture"],
      methodologyUrl: "./documentation/methodology.md",
    };
    expect(manifestSchema.parse(valid).runId).toBe("fixture");
    const incomplete = structuredClone(valid) as Record<string, unknown> & { summaries: Record<string, unknown> };
    delete incomplete.summaries.ebike;
    expect(() => manifestSchema.parse(incomplete)).toThrow();
    const misordered = structuredClone(valid);
    [misordered.scenarios[0], misordered.scenarios[1]] = [
      misordered.scenarios[1]!,
      misordered.scenarios[0]!,
    ];
    expect(() => manifestSchema.parse(misordered)).toThrow(/stable order/);
    const externalMethodology = structuredClone(valid);
    externalMethodology.methodologyUrl = "https://example.test/methodology";
    expect(() => manifestSchema.parse(externalMethodology)).toThrow(/Layer URLs/);
    const impossibleValidation = structuredClone(valid);
    impossibleValidation.validation.matchedCount = 3;
    expect(() => manifestSchema.parse(impossibleValidation)).toThrow(/Matched counter count/);
  });

  it("rejects external and parent-traversing layer URLs", () => {
    const layer = {
      id: "network",
      label: "Network",
      url: "./data/network.geojson",
      sha256: "a".repeat(64),
      defaultVisible: true,
      optional: false,
      licence: "Fixture",
    };
    expect(layerSchema.parse(layer).url).toBe("./data/network.geojson");
    expect(() => layerSchema.parse({ ...layer, url: "https://example.test/network.json" })).toThrow();
    expect(() => layerSchema.parse({ ...layer, url: "../private/network.json" })).toThrow();
    expect(() => layerSchema.parse({ ...layer, url: "./data/%2e%2e/private.json" })).toThrow();
  });
});
