// Interface wording. The manifest keeps the technical labels as the record of
// the run; everything a reader sees is phrased here, keyed by the manifest ids.

import type { CandidateFeature, Manifest, PurposeId, ScenarioId } from "./types";

export interface GoalCopy {
  chip: string;
  note: string;
  valueLabel: string;
  unit: string;
  order: string;
  commute: boolean;
}

const PER_DOLLAR =
  "Each step adds the link with the biggest gain per dollar, allowing for the links already in.";

export const ACCESS_GAIN_NOTE =
  "Access gain counts people helped, scaled by how much easier their ride gets: " +
  "100 people whose ride becomes 10% easier count as 10.";

export const INCREMENT_NOTE =
  "This estimates extra usual cycle commuters above the selected scenario's starting level. " +
  "It does not count everyone using the routes, daily journeys, or non-work cycling.";

export const NETWORK_CONTEXT_NOTE =
  "The map's network layer contains candidate streets only. The existing low-stress network " +
  "is not included, so this view cannot show whether these links form a continuous low-stress route.";

export function candidateOnlyNetwork(manifest: Manifest): boolean {
  return !manifest.networkContext && manifest.limitations.some((note) => /browser network contains exact candidate edges/i.test(note));
}

export const NETWORK_ROLES = {
  joins_areas: "Joins low-stress areas",
  within_area: "Alternative within one area",
  extends_area: "Extends a low-stress area",
  separate: "Needs another connection",
} as const;

export const GOALS: Record<PurposeId, GoalCopy> = {
  network: {
    chip: "Cycling to work",
    note: "Modelled extra usual cycle commuters above the selected scenario's starting level.",
    valueLabel: "Extra people cycling to work",
    unit: "extra riders",
    order: "Each step adds the link that brings the most extra riders, allowing for the links already in. Cost only decides what fits.",
    commute: true,
  },
  equity: {
    chip: "Deprived areas",
    note: "Extra people cycling to work who live in the most deprived 30% of areas (NZDep2023 deciles 8–10).",
    valueLabel: "Extra riders from deprived areas",
    unit: "extra riders",
    order: PER_DOLLAR,
    commute: true,
  },
  school: {
    chip: "School trips",
    note: "How much easier it gets to cycle to school, weighted by school rolls.",
    valueLabel: "Access gain for school trips",
    unit: "access gain",
    order: PER_DOLLAR,
    commute: false,
  },
  everyday: {
    chip: "Everyday trips",
    note: "How much easier it gets to cycle to shops, services and other everyday places.",
    valueLabel: "Access gain for everyday trips",
    unit: "access gain",
    order: PER_DOLLAR,
    commute: false,
  },
  transit: {
    chip: "Stations",
    note: "How much easier it gets to cycle to train and ferry stations, main interchanges and the busiest bus stops.",
    valueLabel: "Access gain for station trips",
    unit: "access gain",
    order: PER_DOLLAR,
    commute: false,
  },
  appraisal: {
    chip: "Benefit–cost",
    note: "Indicative benefit–cost ratio over 40 years, from health benefits. For research use, and only for the 8% scenario.",
    valueLabel: "Benefit–cost ratio (indicative)",
    unit: "extra riders",
    order: "Each step adds the link with the most extra riders per dollar, allowing for the links already in. Each link's benefit–cost ratio is then worked out.",
    commute: true,
  },
};

export const SCENARIOS: Record<ScenarioId, { label: string; note: string }> = {
  baseline: {
    label: "Census baseline",
    note: "The model's 2023 Census cycling baseline. Suppressed bicycle counts use a lower-bound estimate.",
  },
  government_target: {
    label: "Government target",
    note: "The government-target scenario from England's Propensity to Cycle Tool, applied to Auckland trips by distance and hilliness.",
  },
  go_dutch: {
    label: "Go Dutch",
    note: "If Aucklanders cycled as often as Dutch people do on trips of the same length and hilliness. From England's Propensity to Cycle Tool.",
  },
  ebike: {
    label: "E-bikes",
    note: "As Go Dutch, with e-bikes making longer and hillier trips easier. From England's Propensity to Cycle Tool.",
  },
  commute_8pct: {
    label: "8% of commutes",
    note: "An 8% commute-cycling sensitivity used to allocate additional demand. A test case, not an Auckland Transport target.",
  },
};

/** Used inside sentences: "…about $180k per extra rider, if 8% of commuters cycled." */
export const SCENARIO_PHRASE: Record<ScenarioId, string> = {
  baseline: "under the census baseline",
  government_target: "under the government-target scenario",
  go_dutch: "under Go Dutch",
  ebike: "under the e-bike scenario",
  commute_8pct: "under the 8% commute sensitivity",
};

export const SCENARIO_FIXED_NOTE =
  "School, everyday and station trips don't change with the scenario.";
export const APPRAISAL_SCENARIO_NOTE =
  "Benefit–cost ratios are only worked out for the 8% scenario.";

/** Caveats that belong to the run or the goal rather than to one link. */
const RUN_LEVEL_WARNINGS = [
  /low-stress connectivity is (reserved|intentionally reserved)/i,
  /scenario-invariant/i,
  /available only for (the declared )?commute_8pct/i,
  /^Distributional subgroup lens/i,
];

const WARNING_TEXT: Record<string, string> = {
  indicative_screening_bcr_not_business_case_bcr:
    "The benefit–cost ratio is a screening figure, not a business-case result.",
  "Indicative screening BCR; it is not a business-case BCR.":
    "The benefit–cost ratio is a screening figure, not a business-case result.",
  provisional_corridor_unit_cost_range:
    "Costs use provisional per-kilometre rates, not a project estimate.",
  fixed_retained_route_choice_set_pending_full_network_reroute_check:
    "Trips keep to their plausible routes; a check that reroutes the whole network is still to come.",
  uncertainty_distributions_require_local_evidence_review:
    "The uncertainty ranges still need checking against local evidence.",
  counter_validation_is_spatial_plausibility_only:
    "Cycle counters are a rough check on where riders are, not a calibration.",
  "No routed commute market intersects this candidate.": "No modelled commutes use this link.",
  "No routed high-deprivation-origin commute market intersects this candidate.":
    "No modelled commutes from deprived areas use this link.",
  "No routed school market intersects this candidate.": "No modelled school trips use this link.",
  "No routed everyday market intersects this candidate.": "No modelled everyday trips use this link.",
  "No routed transit market intersects this candidate.": "No modelled station trips use this link.",
  "Lifecycle cost falls back to capital cost where no appraisable demand response exists.":
    "Whole-life cost equals build cost here, because there was no rider response to value.",
};

export function linkWarnings(warnings: string[]): string[] {
  const shown = warnings
    .filter((warning) => !RUN_LEVEL_WARNINGS.some((pattern) => pattern.test(warning)))
    .map((warning) => WARNING_TEXT[warning] ?? withNewName(warning));
  return [...new Set(shown)];
}

export function runNote(warning: string): string {
  if (/low-stress connectivity is/i.test(warning)) {
    return "Whole-network low-stress connectivity is not part of this release.";
  }
  if (/available only for/i.test(warning)) return APPRAISAL_SCENARIO_NOTE;
  if (/^Distributional subgroup lens/i.test(warning)) {
    return "This goal counts riders by where they live. It is not a measure of equity impact.";
  }
  return withNewName(warning);
}

export function rationaleText(rationale: string): string {
  const level = /LTS (\d)/.exec(rationale)?.[1];
  if (!level || !/high-stress gap/i.test(rationale)) return rationale;
  return (
    "It is a connected stretch of high-stress streets. The most stressful stretch rates " +
    `${level} on the four-level traffic-stress scale today.`
  );
}

export function programmeText(status: CandidateFeature["properties"]["programmeStatus"]): string {
  return {
    unprogrammed: "Not on an AT plan",
    aligned: "Follows an AT plan route",
    funded: "Overlaps funded AT work",
    possible_duplicate: "May repeat AT work",
  }[status];
}

export const ALIGNED_NOTE =
  "At least a quarter of it runs within 20 m of a Future Connect or RLTP route.";

export function linkName(name: string): string {
  return /^Candidate candidate-/.test(name) ? "Unnamed street" : name;
}

export function dataStatusName(dataStatus: Manifest["dataStatus"]): string {
  return {
    synthetic_demo: "Synthetic demo",
    research_snapshot: "Research snapshot",
    validated_release: "Validated release",
  }[dataStatus];
}

/** The project was released under an earlier name; credits name it as SPAN. */
export function withNewName(text: string): string {
  return text
    .replace(/the Auckland Cycling Investment Workbench project/g, "the SPAN project")
    .replace(/Auckland Cycling Investment Workbench/g, "SPAN")
    .replace(/\bCIW\b/g, "SPAN");
}

const integer = new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 0 });

export function money(value: number): string {
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e7) return `$${integer.format(value / 1e6)}M`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `$${integer.format(value / 1e3)}k`;
  return `$${integer.format(value)}`;
}

export function amount(value: number): string {
  if (Math.abs(value) >= 10) return integer.format(value);
  if (value === 0) return "0";
  return value.toFixed(1);
}

export function ratio(value: number): string {
  return value.toFixed(value >= 10 ? 0 : 1);
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function snapshotDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-NZ", { day: "numeric", month: "long", year: "numeric" });
}
