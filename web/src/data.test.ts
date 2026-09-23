import { describe, expect, it } from "vitest";

import { sha256Hex } from "./data";
import { layerSchema, manifestSchema, purposeIds, scenarioIds } from "./types";

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
