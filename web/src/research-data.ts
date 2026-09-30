import { z } from "zod";
import { fetchVerifiedJson } from "./data";
import { journeyReportDescriptorSchema, type Manifest } from "./types";

const point = z.tuple([z.number(), z.number()]);
export const routeSchema = z.object({ projectIds: z.array(z.string()), distanceM: z.number().positive(), timeS: z.number().positive(), intersectionDelayS: z.number().nonnegative().optional(), capitalCost: z.number().nonnegative(), existingCyclewayM: z.number().nonnegative(), segments: z.array(z.object({ projectId: z.string().nullable(), existingCycleway: z.boolean(), coordinates: z.array(point).min(2) })) });
export const reportSchema = z.object({
  schemaVersion: z.literal("1.0.0"), status: z.literal("local_research_pilot"), runId: z.string(), centre: point, radiusM: z.number().positive(), seed: z.number(), elapsedS: z.number(), searchComplete: z.boolean(),
  graph: z.object({ nodes: z.number(), directedArcs: z.number(), projects: z.number() }),
  intersectionContext: z.object({ scenario: z.enum(["low", "default", "high"]), matchedSitesCitywide: z.number().int().nonnegative(), sitesInCrop: z.number().int().nonnegative(), directedMovementsInCrop: z.number().int().nonnegative(), evidenceSha256: z.string(), note: z.string() }).nullable().optional(),
  sample: z.object({ selected: z.number(), eligibleWithinArea: z.number(), weightedDemand: z.number(), citywideRepresentative: z.literal(false) }),
  standard: z.object({ maximum_stress: z.number(), maximum_detour: z.number(), maximum_time_s: z.number() }),
  sourceHashes: z.object({ topology: z.string(), odLedger: z.string(), candidateLedger: z.string(), scenarioOdLedger: z.string(), origins: z.string(), originWeights: z.string() }),
  implementationHash: z.string(),
  experimentScriptHash: z.string(),
  baseline: z.object({ weight: z.number().nonnegative(), journeys: z.number().int().nonnegative() }),
  solutions: z.array(z.object({ budget: z.number(), method: z.string(), selected: z.array(z.string()), capital_cost: z.number(), served_weight: z.number(), served_journeys: z.number(), optimal_within_columns: z.boolean(), assignmentKey: z.string() })),
  journeys: z.array(z.object({ name: z.string(), weight: z.number(), searchComplete: z.boolean(), stopReason: z.string(), shortestLegalDistanceM: z.number().nullable(), alternatives: z.array(routeSchema) })),
  projects: z.array(z.object({ id: z.string(), name: z.string(), cost: z.number(), lengthM: z.number(), coordinates: z.array(point).min(2) })),
  ridershipForecast: z.null(), limitations: z.array(z.string()),
  assignment: z.object({
    status: z.literal("fixed_demand_illustrative_preferences"), scenarioId: z.string(), totalDemand: z.number().nonnegative(),
    profiles: z.array(z.object({ id: z.string(), label: z.string(), time_weight: z.number(), distance_s_per_km: z.number(), facility_s_per_km: z.array(z.number()), stress_s_per_km: z.array(z.number()), coefficient_status: z.literal("illustrative_unfitted") })),
    portfolios: z.array(z.object({ key: z.string(), selected: z.array(z.string()), profiles: z.array(z.object({ profileId: z.string(), assigned: z.number().nonnegative(), unassigned: z.number().nonnegative(), journeys: z.array(z.object({ name: z.string(), demand: z.number().nonnegative(), assigned: z.number().nonnegative(), unassigned: z.number().nonnegative(), searchOptimal: z.boolean(), choiceSearchComplete: z.boolean(), stopReason: z.string(), alternatives: z.array(routeSchema.extend({ generalizedCostS: z.number(), probability: z.number().min(0).max(1), flow: z.number().nonnegative(), pathSize: z.number().positive().max(1) })) })) })) })),
  }),
});


export type ResearchReport = z.infer<typeof reportSchema>;
export type ResearchRoute = z.infer<typeof routeSchema>;
export type ResearchSolution = ResearchReport["solutions"][number];

export async function loadJourneyReport(manifest: Manifest): Promise<ResearchReport> {
  if (!manifest.journeyReport) throw new Error("Connected-journey results are not available in this release. The other SPAN views are still available.");
  const descriptor = journeyReportDescriptorSchema.parse(manifest.journeyReport);
  const mismatch = "Journey results belong to a different data release and have not been shown. Reload after the site data is updated.";
  if (descriptor.runId !== manifest.runId || (manifest.effectiveNetwork && descriptor.topologySha256 !== manifest.effectiveNetwork.topologySha256)) throw new Error(mismatch);
  let raw: unknown;
  try {
    raw = await fetchVerifiedJson(descriptor.url, descriptor.sha256);
  } catch (error) {
    if (error instanceof Error && error.message.includes("HTTP 404")) throw new Error("Connected-journey results are not available in this release. The other SPAN views are still available.");
    throw error;
  }
  const report = reportSchema.parse(raw);
  if (report.runId !== manifest.runId || report.sourceHashes.topology !== descriptor.topologySha256) throw new Error(mismatch);
  return report;
}

export function portfolioGeoJson(report: ResearchReport, solution: ResearchSolution, route?: ResearchRoute, reportSha256?: string): object {
  const features: object[] = report.projects.filter(p => solution.selected.includes(p.id)).map(p => ({
    type: "Feature", properties: { role: "proposed_project", id: p.id, name: p.name, capitalCostNzd: p.cost, lengthM: p.lengthM, treatment: "protected_lane", costStatus: "provisional" }, geometry: { type: "LineString", coordinates: p.coordinates },
  }));
  for (const [index, segment] of (route?.segments ?? []).entries()) features.push({
    type: "Feature", properties: { role: "inspected_route_segment", sequence: index, projectId: segment.projectId, existingCycleway: segment.existingCycleway, projectFunded: segment.projectId ? solution.selected.includes(segment.projectId) : null }, geometry: { type: "LineString", coordinates: segment.coordinates },
  });
  return {
    type: "FeatureCollection", features, reportSha256: reportSha256 ?? null,
    span: { schemaVersion: "span.planner-export.v1", runId: report.runId, sourceHashes: report.sourceHashes, implementationHash: report.implementationHash, experimentScriptHash: report.experimentScriptHash, standard: report.standard, sample: report.sample, budgetNzd: solution.budget, method: solution.method, selectedProjectIds: solution.selected, capitalCostNzd: solution.capital_cost, eligibleAccessWeight: solution.served_weight, baselineEligibleAccessWeight: report.baseline.weight, additionalEligibleAccessWeight: solution.served_weight - report.baseline.weight, additionalCyclists: null, intersectionContext: report.intersectionContext ?? null, inspectedRouteTimeS: route?.timeS ?? null, inspectedRouteIntersectionDelayS: route?.intersectionDelayS ?? null, status: "research_screening_not_design_or_calibrated_forecast", limitations: report.limitations },
  };
}
