import { z } from "zod";
import { candidateFeatureSchema, candidateMetricSchema, candidatePropertiesSchema, purposeIds, scenarioIds, type CandidateFeature } from "./types";

export const COMPACT_CANDIDATE_FORMAT = "span-candidates-v1";
// The explicit field order belongs to this format version; never derive it from input.
const fields = ["additionalCycleUsers", "annualBikeKmDelta", "available", "bcrP5", "bcrP50", "bcrP95", "capitalCostNzd", "frontierProbability", "lifecycleCostNzd", "meanRank", "objectiveUnit", "objectiveValue", "odLowStressShareDelta", "routeCoverage", "topKProbability", "warnings"] as const;
if (JSON.stringify(fields) !== JSON.stringify(Object.keys(candidateMetricSchema.shape).sort())) {
  throw new Error("Candidate metric schema changed: update the compact format before publishing");
}
const index = z.number().int().nonnegative();
const purposes = z.object({ network: index, equity: index, school: index, everyday: index, transit: index, appraisal: index }).strict();
const scenarios = z.object({ baseline: purposes, government_target: purposes, go_dutch: purposes, ebike: purposes, commute_8pct: purposes }).strict();
const indexedFeature = candidateFeatureSchema.extend({ properties: candidatePropertiesSchema.extend({ metrics: scenarios }) });
const compactSchema = z.object({
  format: z.literal(COMPACT_CANDIDATE_FORMAT),
  metrics: z.array(z.array(z.unknown()).length(fields.length)),
  features: z.array(z.unknown()),
}).strict();
export type CompactCandidates = { format: typeof COMPACT_CANDIDATE_FORMAT; metrics: unknown[][]; features: z.infer<typeof indexedFeature>[] };

/** Build-time encoding of validated values. No rounding, geometry changes or scenario removal. */
export function encodeCompactCandidates(features: unknown[]): CompactCandidates {
  const metrics: unknown[][] = [];
  const lookup = new Map<string, number>();
  const indexed = features.map(raw => {
    const feature = candidateFeatureSchema.parse(raw);
    const references = Object.fromEntries(scenarioIds.map(scenario => [scenario,
      Object.fromEntries(purposeIds.map(purpose => {
        const metric = feature.properties.metrics[scenario][purpose];
        const row = fields.map(field => metric[field]);
        const key = JSON.stringify(row);
        let ref = lookup.get(key);
        if (ref === undefined) { ref = metrics.length; lookup.set(key, ref); metrics.push(row); }
        return [purpose, ref];
      })),
    ])) as z.infer<typeof scenarios>;
    return { ...feature, properties: { ...feature.properties, metrics: references } };
  });
  return { format: COMPACT_CANDIDATE_FORMAT, metrics, features: indexed };
}

/** Validate each distinct metric once; shared validated metrics are immutable. */
export function decodeCompactCandidates(raw: unknown): CandidateFeature[] {
  const packed = compactSchema.parse(raw);
  const metrics = packed.metrics.map(row => {
    const metric = candidateMetricSchema.parse(Object.fromEntries(fields.map((field, i) => [field, row[i]])));
    Object.freeze(metric.warnings);
    return Object.freeze(metric);
  });
  return packed.features.map(rawFeature => {
    const feature = indexedFeature.parse(rawFeature);
    const decoded = Object.fromEntries(scenarioIds.map(scenario => [scenario,
      Object.fromEntries(purposeIds.map(purpose => {
        const ref = feature.properties.metrics[scenario][purpose];
        const metric = metrics[ref];
        if (!metric) throw new Error("Compact candidate metric reference is out of range");
        return [purpose, metric];
      })),
    ])) as CandidateFeature["properties"]["metrics"];
    return { ...feature, properties: { ...feature.properties, metrics: decoded } };
  });
}
