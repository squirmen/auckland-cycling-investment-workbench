import { z } from "zod";

export const scenarioIds = [
  "baseline",
  "government_target",
  "go_dutch",
  "ebike",
  "commute_8pct",
] as const;
export const purposeIds = ["network", "equity", "school", "everyday", "transit", "appraisal"] as const;

export type ScenarioId = (typeof scenarioIds)[number];
export type PurposeId = (typeof purposeIds)[number];

export const scenarioSchema = z.object({
  id: z.enum(scenarioIds),
  label: z.string().min(1),
  description: z.string().min(1),
});

export const purposeSchema = z.object({
  id: z.enum(purposeIds),
  label: z.string().min(1),
  description: z.string().min(1),
  objectiveLabel: z.string().min(1),
});

const localAssetUrlSchema = z.string().min(1).refine(
  (value) => {
    if (
      value.startsWith("/") ||
      value.includes("\\") ||
      value.includes("%") ||
      value.includes("?") ||
      value.includes("#") ||
      /^[a-z][a-z0-9+.-]*:/i.test(value)
    ) {
      return false;
    }
    return !value.split("/").includes("..");
  },
  { message: "Layer URLs must be same-origin relative paths without parent traversal" },
);

const localMethodologyUrlSchema = localAssetUrlSchema.refine(
  (value) => /^\.\/documentation\/[A-Za-z0-9._-]+\.md$/.test(value),
  { message: "The methodology URL must name a bundled Markdown file" },
);

export const layerSchema = z.object({
  id: z.enum(["cells", "network", "candidates", "programmes", "counters", "safety", "existing", "intersections"]),
  label: z.string().min(1),
  url: localAssetUrlSchema,
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  defaultVisible: z.boolean(),
  optional: z.boolean().default(false),
  licence: z.string().min(1),
});

export const summaryMetricSchema = z.object({
  purpose: z.enum(purposeIds),
  activityValue: z.number().nonnegative(),
  activityUnit: z.string().min(1),
  odLowStressShare: z.number().min(0).max(1).nullable(),
  odLowStressConnectedWeight: z.number().nonnegative().nullable(),
  odLowStressDenominatorWeight: z.number().nonnegative().nullable(),
  routingCoverage: z.number().min(0).max(1),
  maximumLts: z.number().int().min(1).max(4),
  maximumDetourRatio: z.number().min(1),
  candidateCount: z.number().int().nonnegative(),
  validationCoverage: z.number().min(0).max(1).nullable(),
  warnings: z.array(z.string().min(1)),
}).refine((value) => (
  value.odLowStressConnectedWeight === null ||
  value.odLowStressDenominatorWeight === null ||
  value.odLowStressConnectedWeight <= value.odLowStressDenominatorWeight
), {
  message: "Connected demand cannot exceed the complete eligible denominator",
});

export type SummaryMetric = z.infer<typeof summaryMetricSchema>;

export const candidateMetricSchema = z.object({
  available: z.boolean(),
  capitalCostNzd: z.number().positive(),
  lifecycleCostNzd: z.number().positive(),
  objectiveValue: z.number().nonnegative().nullable(),
  objectiveUnit: z.string().min(1),
  additionalCycleUsers: z.number().nonnegative().nullable(),
  annualBikeKmDelta: z.number().nonnegative().nullable(),
  odLowStressShareDelta: z.number().min(0).max(1).nullable(),
  bcrP5: z.number().nonnegative().nullable(),
  bcrP50: z.number().nonnegative().nullable(),
  bcrP95: z.number().nonnegative().nullable(),
  routeCoverage: z.number().min(0).max(1),
  meanRank: z.number().positive().nullable(),
  topKProbability: z.number().min(0).max(1).nullable(),
  frontierProbability: z.number().min(0).max(1).nullable(),
  warnings: z.array(z.string().min(1)),
});

export type CandidateMetric = z.infer<typeof candidateMetricSchema>;

const metricByPurposeSchema = z.object({
  network: candidateMetricSchema,
  equity: candidateMetricSchema,
  school: candidateMetricSchema,
  everyday: candidateMetricSchema,
  transit: candidateMetricSchema,
  appraisal: candidateMetricSchema,
});
const metricByScenarioSchema = z.object({
  baseline: metricByPurposeSchema,
  government_target: metricByPurposeSchema,
  go_dutch: metricByPurposeSchema,
  ebike: metricByPurposeSchema,
  commute_8pct: metricByPurposeSchema,
});

export const routeUseSchema = z.object({
  before: z.number().finite().nonnegative(),
  after: z.number().finite().nonnegative(),
  additional: z.number().finite().nonnegative(),
});
export type RouteUse = z.infer<typeof routeUseSchema>;

export const candidateNetworkContextSchema = z.object({
  role: z.enum(["joins_areas", "within_area", "extends_area", "separate"]),
  lengthKm: z.number().finite().nonnegative(),
  direction: z.enum(["both", "forward", "reverse", "mixed"]),
  componentIds: z.array(z.string().min(1)),
  contacts: z.array(z.object({
    nodeId: z.string().min(1),
    componentId: z.string().min(1),
    coordinates: z.tuple([z.number().finite(), z.number().finite()]),
  })).optional(),
  existingKm: z.number().finite().nonnegative(),
  touchingCandidateIds: z.array(z.string().min(1)),
  endpoints: z.array(z.object({
    label: z.enum(["A", "B"]),
    nodeId: z.string().min(1),
    coordinates: z.tuple([z.number().finite(), z.number().finite()]),
    componentId: z.string().nullable(),
    existingKm: z.number().finite().nonnegative(),
    touchingCandidateIds: z.array(z.string().min(1)),
  })).length(2),
});

export const candidatePropertiesSchema = z.object({
  candidateId: z.string().min(1),
  name: z.string().min(1),
  purposeOrigins: z.array(z.enum(purposeIds)).min(1),
  edgeIds: z.array(z.string().min(1)).min(1),
  facilityType: z.string().min(1),
  programmeStatus: z.enum(["unprogrammed", "aligned", "funded", "possible_duplicate"]),
  rationale: z.string().min(1),
  metrics: metricByScenarioSchema,
  networkContext: candidateNetworkContextSchema.optional(),
  commuteRouteUse: z.object({
    baseline: routeUseSchema,
    government_target: routeUseSchema,
    go_dutch: routeUseSchema,
    ebike: routeUseSchema,
    commute_8pct: routeUseSchema,
  }).optional(),
});

export type CandidateProperties = z.infer<typeof candidatePropertiesSchema>;

const positionSchema = z.tuple([z.number().finite(), z.number().finite()]);
const candidateGeometrySchema = z.union([
  z.object({ type: z.literal("LineString"), coordinates: z.array(positionSchema).min(2) }),
  z.object({
    type: z.literal("MultiLineString"),
    coordinates: z.array(z.array(positionSchema).min(2)).min(1),
  }),
]);

export const featureSchema = z.object({
  type: z.literal("Feature"),
  id: z.union([z.string(), z.number()]).optional(),
  geometry: z.object({
    type: z.string(),
    coordinates: z.unknown(),
  }),
  properties: z.record(z.unknown()),
});

export const featureCollectionSchema = z.object({
  type: z.literal("FeatureCollection"),
  features: z.array(featureSchema),
});

export const candidateFeatureSchema = featureSchema.extend({
  geometry: candidateGeometrySchema,
  properties: candidatePropertiesSchema,
});

export type GenericFeature = z.infer<typeof featureSchema>;
export type GenericFeatureCollection = z.infer<typeof featureCollectionSchema>;

export type CandidateFeature = z.infer<typeof candidateFeatureSchema>;

export const portfolioStepSchema = z.object({
  candidateId: z.string().min(1),
  step: z.number().int().positive(),
  cumulativeCostNzd: z.number().nonnegative(),
  marginalObjective: z.number().nonnegative(),
  cumulativeObjective: z.number().nonnegative(),
  objectiveUnit: z.string().min(1),
  paretoMember: z.boolean(),
  routeUsersBefore: z.number().finite().nonnegative().optional(),
  routeUsersAfter: z.number().finite().nonnegative().optional(),
});

const portfolioPurposeSchema = z.object({
  network: z.array(portfolioStepSchema),
  equity: z.array(portfolioStepSchema),
  school: z.array(portfolioStepSchema),
  everyday: z.array(portfolioStepSchema),
  transit: z.array(portfolioStepSchema),
  appraisal: z.array(portfolioStepSchema),
});
const portfoliosSchema = z.object({
  baseline: portfolioPurposeSchema,
  government_target: portfolioPurposeSchema,
  go_dutch: portfolioPurposeSchema,
  ebike: portfolioPurposeSchema,
  commute_8pct: portfolioPurposeSchema,
});

const summaryPurposeSchema = z.object({
  network: summaryMetricSchema,
  equity: summaryMetricSchema,
  school: summaryMetricSchema,
  everyday: summaryMetricSchema,
  transit: summaryMetricSchema,
  appraisal: summaryMetricSchema,
}).superRefine((summaries, context) => {
  for (const purpose of purposeIds) {
    if (summaries[purpose].purpose !== purpose) {
      context.addIssue({
        code: "custom",
        path: [purpose, "purpose"],
        message: `Summary purpose must match its ${purpose} manifest key`,
      });
    }
  }
});
const summariesSchema = z.object({
  baseline: summaryPurposeSchema,
  government_target: summaryPurposeSchema,
  go_dutch: summaryPurposeSchema,
  ebike: summaryPurposeSchema,
  commute_8pct: summaryPurposeSchema,
});

const validationSchema = z.object({
  periodLabel: z.string().min(1),
  counterCount: z.number().int().nonnegative(),
  matchedCount: z.number().int().nonnegative(),
  coverage: z.number().min(0).max(1),
  purposeAlignment: z.string().min(1),
  status: z.string().min(1),
}).refine((value) => value.matchedCount <= value.counterCount, {
  message: "Matched counter count cannot exceed the complete counter count",
});

export const manifestSchema = z.object({
  schemaVersion: z.literal("2.0.0"),
  modelVersion: z.string().min(1),
  configSha256: z.string().regex(/^[a-f0-9]{64}$/),
  runId: z.string().min(1),
  generatedAtUtc: z.string().datetime(),
  title: z.string().min(1),
  dataStatus: z.enum(["synthetic_demo", "research_snapshot", "validated_release"]),
  dataStatusLabel: z.string().min(1),
  defaultScenario: z.enum(scenarioIds),
  defaultPurpose: z.enum(purposeIds),
  defaultBudgetNzd: z.number().nonnegative(),
  maxBudgetNzd: z.number().positive(),
  scenarios: z.array(scenarioSchema).length(scenarioIds.length),
  purposes: z.array(purposeSchema).length(purposeIds.length),
  summaries: summariesSchema,
  portfolios: portfoliosSchema,
  validation: validationSchema,
  capabilities: z.object({
    equity: z.enum(["available", "rights_blocked", "unavailable"]),
    appraisal: z.enum(["reviewed", "research_only", "withheld"]),
    sketchEvaluation: z.enum(["same_pipeline", "requires_pipeline_evaluation", "unavailable"]),
  }),
  limitations: z.array(z.string().min(1)),
  layers: z.array(layerSchema),
  attribution: z.array(z.string().min(1)),
  methodologyUrl: localMethodologyUrlSchema,
  effectiveNetwork: z.object({
    version: z.string(), method: z.literal("unambiguous_at_grade_source_junctions"),
    status: z.literal("screening_sensitivity"), runId: z.string(),
    inventorySites: z.number().int().nonnegative(), matchedSites: z.number().int().nonnegative(),
    reviewSites: z.number().int().nonnegative(), directedMovements: z.number().int().nonnegative(),
    topologySha256: z.string().regex(/^[a-f0-9]{64}$/),
    inventorySha256: z.string().regex(/^[a-f0-9]{64}$/), note: z.string(),
  }).optional(),
  networkContext: z.object({
    version: z.string(),
    method: z.literal("weak_components_exact_source_nodes"),
    maximumLts: z.number().int().min(1).max(4),
    displaySimplificationM: z.number().nonnegative(),
    edgeCount: z.number().int().nonnegative(),
    componentCount: z.number().int().nonnegative(),
    lengthKm: z.number().nonnegative(),
    note: z.string(),
    routeUseNote: z.string(),
    sourceFiles: z.record(z.string().regex(/^[a-f0-9]{64}$/)),
    implementationSha256: z.string().regex(/^[a-f0-9]{64}$/),
    packages: z.array(routeUseSchema.extend({
      scenario: z.enum(scenarioIds),
      candidateIds: z.array(z.string().min(1)).min(1),
    })),
  }).optional(),
  demandContext: z.object({
    routedBaselineUsers: z.number().nonnegative().nullable(),
    sourceMarginUsers: z.number().nonnegative().nullable(),
    routedEligible: z.number().nonnegative().nullable(),
    internalEligible: z.number().nonnegative().nullable(),
    sourceEligible: z.number().nonnegative().nullable(),
    internalCoverage: z.number().nonnegative().nullable(),
    sourceCoverage: z.number().nonnegative().nullable(),
    capitalCostPerKm: z.number().positive(),
    note: z.string(),
  }).optional(),
}).superRefine((value, context) => {
  if (!value.scenarios.every((scenario, index) => scenario.id === scenarioIds[index])) {
    context.addIssue({
      code: "custom",
      path: ["scenarios"],
      message: `Scenarios must appear once in stable order: ${scenarioIds.join(", ")}`,
    });
  }
  if (!value.purposes.every((purpose, index) => purpose.id === purposeIds[index])) {
    context.addIssue({
      code: "custom",
      path: ["purposes"],
      message: `Purposes must appear once in stable order: ${purposeIds.join(", ")}`,
    });
  }
  if (value.defaultBudgetNzd > value.maxBudgetNzd) {
    context.addIssue({
      code: "custom",
      path: ["defaultBudgetNzd"],
      message: "Default budget cannot exceed the maximum budget",
    });
  }
});

export type Manifest = z.infer<typeof manifestSchema>;
export type PortfolioStep = z.infer<typeof portfolioStepSchema>;

export interface LoadedLayers {
  intersections?: GenericFeatureCollection;
  existing?: GenericFeatureCollection;
  cells?: GenericFeatureCollection;
  network?: GenericFeatureCollection;
  candidates?: GenericFeatureCollection;
  programmes?: GenericFeatureCollection;
  counters?: GenericFeatureCollection;
  safety?: GenericFeatureCollection;
}

export interface AppState {
  scenario: ScenarioId;
  purpose: PurposeId;
  budgetNzd: number;
  selectedCandidateId: string | null;
  visibleLayerIds: Set<string>;
  portfolioIds: Set<string>;
  activeTab: "portfolio" | "pareto";
  sketching: boolean;
  focusedGroupIds: Set<string>;
}
