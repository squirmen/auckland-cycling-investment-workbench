import { z } from "zod";

const hash = z.string().regex(/^[a-f0-9]{64}$/);
const identifiers = z.array(z.string().min(1)).refine(ids => new Set(ids).size === ids.length, "Duplicate project IDs");
const outcome = z.object({ scenarioId: z.string().min(1), networkScenarioHash: hash, projectIds: identifiers, value: z.number().finite().nonnegative() });

// CRANC INTEGRATION BOUNDARY: a future local/server adapter returns this envelope.
// This is not CRANC's native API and v1 does not verify crop/speed/delay equivalence.
export const crancComparisonSchema = z.object({
  schemaVersion: z.literal("span.cranc-access.v1"),
  provider: z.object({ name: z.literal("CRANC"), version: z.string().min(1), attribution: z.string().min(1) }),
  scope: z.object({
    runId: z.string().min(1), baseNetworkHash: hash, originsHash: hash, weightingHash: hash,
    opportunitiesHash: hash, profile: z.enum(["ibc", "eac", "saf"]), profileHash: hash,
    timeLimitS: z.number().int().positive(), reverseFlow: z.literal(false),
    category: z.string().min(1), unit: z.literal("reachable_opportunities_per_origin"),
    aggregation: z.literal("weighted_mean"), crs: z.literal("EPSG:4326"),
    stressTransferValidation: z.object({ status: z.literal("validated_for_auckland"), evidence: z.string().min(1) }),
  }),
  baseline: outcome.extend({ projectIds: identifiers.refine(ids => ids.length === 0, "Baseline must have no proposed projects") }),
  investment: outcome.extend({ crosswalkHash: hash }),
}).superRefine((value, ctx) => {
  if (value.investment.projectIds.length && value.baseline.networkScenarioHash === value.investment.networkScenarioHash) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Changed investment requires a distinct network scenario hash" });
  }
});

export type CrancComparison = z.infer<typeof crancComparisonSchema>;
export type CrancContext = { runId: string; topologyHash: string; originsHash: string; weightingHash: string; selected: string[] };

export function checkCrancScope(comparison: CrancComparison, context: CrancContext): string | null {
  const scope = comparison.scope;
  if (scope.runId !== context.runId || scope.baseNetworkHash !== context.topologyHash) return "CRANC uses a different source network or SPAN run.";
  if (scope.originsHash !== context.originsHash || scope.weightingHash !== context.weightingHash) return "CRANC uses different origins or population weights.";
  if (JSON.stringify([...comparison.investment.projectIds].sort()) !== JSON.stringify([...context.selected].sort())) return "CRANC describes a different investment package. Select the matching package to compare it.";
  return null;
}

export function crancRequest(context: CrancContext): object {
  return {
    schemaVersion: "span.cranc-request.v1", status: "request_only_no_accessibility_results",
    provider: "CRANC · Steve Gehrke and collaborators",
    runId: context.runId, baseNetworkHash: context.topologyHash,
    originsHash: context.originsHash, weightingHash: context.weightingHash,
    baselineProjectIds: [], investmentProjectIds: [...context.selected].sort(),
    supportedProfiles: ["ibc", "eac", "saf"],
    requiredReturnFormat: "span.cranc-access.v1",
    requirements: [
      "Return one attributed profile/time/category comparison per file, on the same opportunity dataset and weighted origins.",
      "Supply distinct network scenario hashes, a project-to-CRANC-edge crosswalk hash, and profile/opportunity versions.",
      "Validate Auckland speed units, stress transfer and crossings with Steve before setting validated_for_auckland.",
      "Native route/isochrone responses alone do not contain opportunity counts or an investment scenario contract.",
      "Version 1 does not verify matching crop, speed or intersection-delay assumptions; agree and version those before a live routing-equivalent integration.",
    ],
  };
}
