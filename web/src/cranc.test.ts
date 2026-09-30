import { describe, expect, it } from "vitest";
import { checkCrancScope, crancComparisonSchema, crancRequest } from "./cranc";

const hash = "a".repeat(64);
const context = { runId: "run-test", topologyHash: hash, originsHash: hash, weightingHash: hash, selected: ["P"] };
const example = () => ({
  schemaVersion: "span.cranc-access.v1",
  provider: { name: "CRANC", version: "test", attribution: "Steve Gehrke and collaborators · synthetic test only" },
  scope: { runId: "run-test", baseNetworkHash: hash, originsHash: hash, weightingHash: hash, opportunitiesHash: hash, profile: "ibc", profileHash: hash, timeLimitS: 900, reverseFlow: false, category: "jobs", unit: "reachable_opportunities_per_origin", aggregation: "weighted_mean", crs: "EPSG:4326", stressTransferValidation: { status: "validated_for_auckland", evidence: "Synthetic test, not a real validation" } },
  baseline: { scenarioId: "baseline", networkScenarioHash: hash, projectIds: [], value: 10 },
  investment: { scenarioId: "test-investment", networkScenarioHash: "b".repeat(64), projectIds: ["P"], value: 20, crosswalkHash: hash },
});

describe("attributed CRANC comparison boundary", () => {
  it("accepts matched aggregate results and preserves attribution", () => {
    const value = crancComparisonSchema.parse(example());
    expect(checkCrancScope(value, context)).toBeNull();
    expect(value.provider.attribution).toContain("Steve Gehrke");
  });
  it("rejects different network, origins, weights and portfolio", () => {
    const value = crancComparisonSchema.parse(example());
    for (const patch of [{ topologyHash: "b".repeat(64) }, { originsHash: "b".repeat(64) }, { weightingHash: "b".repeat(64) }, { selected: ["Q"] }]) {
      expect(checkCrancScope(value, { ...context, ...patch })).not.toBeNull();
    }
  });
  it("does not turn unavailable values or native isochrones into zero access", () => {
    for (const value of [null, { polygons: [] }, { ...example(), investment: { ...example().investment, value: null } }]) {
      expect(crancComparisonSchema.safeParse(value).success).toBe(false);
    }
  });
  it("requires transfer evidence, unique projects, correct units and changed network", () => {
    const ex = example();
    for (const value of [
      { ...ex, scope: { ...ex.scope, stressTransferValidation: null } },
      { ...ex, scope: { ...ex.scope, unit: "cyclists" } },
      { ...ex, scope: { ...ex.scope, reverseFlow: true } },
      { ...ex, investment: { ...ex.investment, projectIds: ["P", "P"] } },
      { ...ex, investment: { ...ex.investment, networkScenarioHash: hash } },
    ]) expect(crancComparisonSchema.safeParse(value).success).toBe(false);
  });
  it("exports a request without fabricated results or raw OD locations", () => {
    const request = crancRequest(context);
    expect(JSON.stringify(request)).not.toContain('"value":');
    expect(request).toMatchObject({ status: "request_only_no_accessibility_results", investmentProjectIds: ["P"] });
    expect(crancComparisonSchema.safeParse(request).success).toBe(false);
  });
});
