import { expect, it } from "vitest";
import { journeyStatus } from "./connected";

const route = (projectIds: string[]) => ({ projectIds, distanceM: 100, timeS: 30, capitalCost: 0, existingCyclewayM: 0, segments: [] });
const journey = (alternatives: ReturnType<typeof route>[]) => ({ name: "Journey", weight: 1, searchComplete: true, stopReason: "exhausted", shortestLegalDistanceM: 100, alternatives });

it("sorts sample journeys by what a package does for them", () => {
  const funded = new Set(["P", "Q"]);
  expect(journeyStatus(journey([]), funded)).toEqual({ status: "none", missing: 0 });
  expect(journeyStatus(journey([route(["X"]), route([])]), funded)).toEqual({ status: "already", missing: 0 });
  expect(journeyStatus(journey([route(["P", "X"]), route(["P", "Q"])]), funded)).toEqual({ status: "package", missing: 0 });
  // The closest route decides how many more upgrades are needed.
  expect(journeyStatus(journey([route(["X", "Y", "Z"]), route(["P", "X"])]), funded)).toEqual({ status: "needs", missing: 1 });
  expect(journeyStatus(journey([route(["P"])]), new Set())).toEqual({ status: "needs", missing: 1 });
});
