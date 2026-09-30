import { z } from "zod";
import type { Manifest } from "./types";

const diagnosticSchema = z.object({
  candidateId: z.string(),
  affectedOdRecords: z.number().int().positive(),
  additionalUsualCommuters: z.number().nonnegative(),
  largestOdContributionShare: z.number().min(0).max(1),
  topThreeOdContributionShare: z.number().min(0).max(1),
  elasticitySensitivity: z.array(z.object({
    elasticity: z.number().positive(), additionalUsualCommuters: z.number().nonnegative(),
  })).length(3),
});
const reportSchema = z.object({
  runId: z.string(), scenario: z.literal("commute_8pct"),
  candidateLayerSha256: z.string().regex(/^[a-f0-9]{64}$/),
  status: z.literal("exploratory_sensitivity_not_confidence_interval"),
  commuteRecordsPerStratum: z.number().int().positive(),
  candidates: z.array(diagnosticSchema),
});
export type DemandDiagnostics = z.infer<typeof reportSchema>;

export function matchingDiagnostics(value: unknown, manifest: Manifest): DemandDiagnostics | undefined {
  const result = reportSchema.safeParse(value);
  if (!result.success) return undefined;
  const report = result.data;
  return report.runId === manifest.runId && report.candidateLayerSha256 === manifest.layers.find(l => l.id === "candidates")?.sha256
    ? report : undefined;
}

export async function loadDemandDiagnostics(manifest: Manifest): Promise<DemandDiagnostics | undefined> {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}data/ridership-diagnostics.json`);
    return response.ok ? matchingDiagnostics(await response.json(), manifest) : undefined;
  } catch {
    return undefined; // Older releases have no optional OD audit.
  }
}
