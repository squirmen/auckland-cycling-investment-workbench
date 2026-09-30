import { describe, expect, it } from "vitest";
import { matchingDiagnostics } from "./diagnostics";
import type { Manifest } from "./types";

describe("optional OD audit provenance", () => {
  const manifest = { runId: "run-a", layers: [{ id: "candidates", sha256: "a".repeat(64) }] } as Manifest;
  const report = { runId: "run-a", scenario: "commute_8pct", candidateLayerSha256: "a".repeat(64), status: "exploratory_sensitivity_not_confidence_interval", commuteRecordsPerStratum: 1, candidates: [] };
  it("only attaches diagnostics to their exact run and candidate data", () => {
    expect(matchingDiagnostics(report, manifest)).toBeDefined();
    expect(matchingDiagnostics({ ...report, runId: "run-b" }, manifest)).toBeUndefined();
    expect(matchingDiagnostics({ ...report, candidateLayerSha256: "b".repeat(64) }, manifest)).toBeUndefined();
  });
  it("treats missing or malformed audit data as unavailable", () => {
    expect(matchingDiagnostics(null, manifest)).toBeUndefined();
    expect(matchingDiagnostics({ ...report, candidates: [{ largestOdContributionShare: 2 }] }, manifest)).toBeUndefined();
  });
});
