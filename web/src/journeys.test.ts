import { describe, expect, it } from "vitest";
import { DEFAULT_JOURNEY_ASSUMPTIONS as calendar, journeyAssumptionsFromQuery, journeyEquivalent } from "./journeys";

describe("people and journey units", () => {
  it("uses unrounded people and a declared commuting calendar", () => {
    const people = 54.476310952448614;
    expect(journeyEquivalent(people, calendar)).toBeCloseTo(23969.5768190774);
    expect(journeyEquivalent(people, { ...calendar, period: "month" }) * 12).toBeCloseTo(journeyEquivalent(people, calendar));
    expect(journeyEquivalent(people, { ...calendar, period: "day" })).toBeCloseTo(people * 2);
    expect(journeyEquivalent(people, { ...calendar, daysPerYear: 100, legsPerDay: 1 })).toBeCloseTo(people * 100);
  });
  it("preserves zero and rejects impossible values", () => {
    expect(journeyEquivalent(0, calendar)).toBe(0);
    expect(journeyEquivalent(54, { ...calendar, daysPerYear: 0 })).toBe(0);
    expect(journeyEquivalent(54, { ...calendar, daysPerYear: 0, period: "day" })).toBe(0);
    expect(() => journeyEquivalent(NaN, calendar)).toThrow();
    expect(() => journeyEquivalent(-1, calendar)).toThrow();
    expect(() => journeyEquivalent(54, { ...calendar, daysPerYear: 400 })).toThrow();
  });
  it("restores shareable assumptions and safely handles malformed URLs", () => {
    expect(journeyAssumptionsFromQuery(new URLSearchParams())).toEqual(calendar);
    expect(journeyAssumptionsFromQuery(new URLSearchParams("journeys=month&cyclingDays=160&journeyLegs=1"))).toEqual({ period: "month", daysPerYear: 160, legsPerDay: 1 });
    expect(journeyAssumptionsFromQuery(new URLSearchParams("journeys=decade&cyclingDays=-7&journeyLegs=NaN"))).toEqual(calendar);
  });
});
