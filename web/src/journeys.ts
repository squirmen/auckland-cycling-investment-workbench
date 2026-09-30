/** A transparent calendar conversion, separate from the demand model. */
export type JourneyPeriod = "year" | "month" | "day";
export interface JourneyAssumptions {
  period: JourneyPeriod;
  daysPerYear: number;
  legsPerDay: number;
}

// Matches this release's declared appraisal calendar (configs/auckland.yml).
// These are display assumptions, not observations of commuting frequency.
export const DEFAULT_JOURNEY_ASSUMPTIONS: JourneyAssumptions = {
  period: "year", daysPerYear: 220, legsPerDay: 2,
};

export function journeyAssumptionsFromQuery(params: URLSearchParams): JourneyAssumptions {
  const period = params.get("journeys");
  const days = Number(params.get("cyclingDays"));
  const legs = Number(params.get("journeyLegs"));
  return {
    period: period === "month" || period === "day" ? period : "year",
    daysPerYear: params.has("cyclingDays") && Number.isInteger(days) && days >= 0 && days <= 366 ? days : 220,
    legsPerDay: legs === 1 || legs === 2 ? legs : 2,
  };
}

export function journeysPerPerson(assumptions: JourneyAssumptions): number {
  const { period, daysPerYear, legsPerDay } = assumptions;
  if (!Number.isInteger(daysPerYear) || daysPerYear < 0 || daysPerYear > 366 || ![1, 2].includes(legsPerDay)) {
    throw new Error("Invalid commuting calendar");
  }
  if (period === "day") return daysPerYear === 0 ? 0 : legsPerDay;
  return daysPerYear * legsPerDay / (period === "month" ? 12 : 1);
}

export function journeyEquivalent(people: number, assumptions: JourneyAssumptions): number {
  if (!Number.isFinite(people) || people < 0) throw new Error("People must be finite and non-negative");
  return people * journeysPerPerson(assumptions);
}

export function journeyPeriodLabel(period: JourneyPeriod): string {
  return period === "year" ? "per year" : period === "month" ? "per average month" : "per cycling commute day";
}
