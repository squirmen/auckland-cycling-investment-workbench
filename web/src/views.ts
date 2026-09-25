// Everything drawn in the panel, the link card and the map key. These functions
// only read the model and the manifest; app.ts owns state and events.

import {
  ACCESS_GAIN_NOTE,
  ALIGNED_NOTE,
  APPRAISAL_SCENARIO_NOTE,
  GOALS,
  INCREMENT_NOTE,
  NETWORK_CONTEXT_NOTE,
  NETWORK_ROLES,
  SCENARIO_FIXED_NOTE,
  SCENARIO_PHRASE,
  SCENARIOS,
  amount,
  candidateOnlyNetwork,
  linkName,
  linkWarnings,
  money,
  percent,
  programmeText,
  rationaleText,
  ratio,
  runNote,
} from "./copy";
import { create, requiredElement, svgElement, svgText } from "./dom";
import type { DemandDiagnostics } from "./diagnostics";
import { DEFAULT_JOURNEY_ASSUMPTIONS, journeyEquivalent, journeyPeriodLabel, type JourneyAssumptions } from "./journeys";
import { COLOURS, CRASH_BREAKS, NUMBERED_LINKS } from "./map";
import { candidateLengthKm, connectedGroups, metricFor, type SketchResult } from "./model";
import type { AppState, CandidateFeature, CandidateMetric, Manifest, PortfolioStep, PurposeId, RouteUse } from "./types";

export interface ViewContext {
  journeyAssumptions?: JourneyAssumptions;
  demandDiagnostics?: DemandDiagnostics;
  manifest: Manifest;
  state: AppState;
  byId: Map<string, CandidateFeature>;
  /** Links in the build order that fit the budget. */
  steps: PortfolioStep[];
  /** The whole build order for this goal and scenario. */
  sequence: PortfolioStep[];
  front: () => Set<string>;
  select: (candidateId: string) => void;
  zoom: (candidateId: string) => void;
  focusGroup: (candidateIds: string[]) => void;
  packageEvaluation: (candidateIds: string[]) => RouteUse | undefined;
}

const ACCESS_NOUN: Partial<Record<PurposeId, string>> = {
  school: "school trips",
  everyday: "everyday trips",
  transit: "station trips",
};
const PARETO_POINT_LIMIT = 1_500;
const FRONTIER_ROWS = 40;

/** The figure a goal ranks on: riders, access gain, or for Benefit–cost the ratio. */
export function goalValue(metric: CandidateMetric, purpose: PurposeId): number {
  if (!metric.available) return 0;
  if (purpose === "appraisal") return metric.objectiveValue ?? metric.bcrP50 ?? 0;
  return metric.objectiveValue ?? 0;
}

function goalValueText(metric: CandidateMetric, purpose: PurposeId): string {
  if (purpose === "appraisal") return `benefit–cost ${ratio(goalValue(metric, purpose))}`;
  if (GOALS[purpose].commute) return `+${amount(goalValue(metric, purpose))} usual cycle commuters`;
  return `access gain ${amount(goalValue(metric, purpose))}`;
}

function stepText(step: PortfolioStep, purpose: PurposeId, candidate: CandidateFeature, ctx: ViewContext): string {
  const parts: string[] = [];
  if (purpose === "network" || purpose === "appraisal") parts.push(`+${amount(step.marginalObjective)} usual cycle commuters`);
  else if (purpose === "equity") parts.push(`+${amount(step.marginalObjective)} usual cycle commuters from deprived areas`);
  else parts.push(`access gain ${amount(step.marginalObjective)}`);
  if (purpose === "appraisal") {
    parts.push(`benefit–cost ${ratio(goalValue(metricFor(candidate, ctx.state.scenario, "appraisal"), "appraisal"))}`);
  }
  if (candidate.properties.programmeStatus === "aligned") parts.push("on an AT plan route");
  if (candidate.properties.networkContext) parts.push(NETWORK_ROLES[candidate.properties.networkContext.role]);
  return parts.join(" · ");
}

export function renderGoalPicker(
  root: HTMLElement,
  current: PurposeId,
  available: (purpose: PurposeId) => boolean,
  onPick: (purpose: PurposeId) => void,
  order: readonly PurposeId[],
): void {
  root.replaceChildren(
    ...order.map((purpose) => {
      const button = create("button", { type: "button", className: "chip", role: "radio", text: GOALS[purpose].chip });
      button.setAttribute("aria-checked", String(purpose === current));
      button.dataset.purpose = purpose;
      button.tabIndex = purpose === current ? 0 : -1;
      if (!available(purpose)) {
        button.disabled = true;
        button.title = "Not available in this release";
      }
      button.addEventListener("click", () => onPick(purpose));
      return button;
    }),
  );
}

export function renderNotes(ctx: ViewContext): void {
  const { purpose, scenario } = ctx.state;
  const goal = GOALS[purpose];
  requiredElement("purpose-note").textContent = goal.commute ? goal.note : `${goal.note} ${ACCESS_GAIN_NOTE}`;
  requiredElement("scenario-note").textContent =
    purpose === "appraisal" ? APPRAISAL_SCENARIO_NOTE : goal.commute ? SCENARIOS[scenario].note : SCENARIO_FIXED_NOTE;
}

export function renderHero(root: HTMLElement, ctx: ViewContext): void {
  const { purpose, scenario, budgetNzd } = ctx.state;
  const steps = ctx.steps;
  const last = steps.at(-1);
  if (last && ctx.manifest.networkContext && last.routeUsersAfter !== undefined) {
    renderNetworkHero(root, ctx, last);
    return;
  }
  let figure: string;
  let text: string;
  let sub: string;
  if (!last) {
    const first = ctx.sequence[0];
    figure = "0";
    text = `links fit within ${money(budgetNzd)}.`;
    sub = first
      ? `The first link in the build order costs ${money(first.cumulativeCostNzd)}. Raise the budget to include it.`
      : "There are no links for this goal in this run.";
  } else {
    const links = steps.length === 1 ? "link" : "links";
    const cost = last.cumulativeCostNzd;
    const total = last.cumulativeObjective;
    if (GOALS[purpose].commute) {
      const who = purpose === "equity" ? "more people from deprived areas" : "more people";
      figure = amount(total);
      text = `${who} would cycle to work if the first ${String(steps.length)} ${links} in the build order were built.`;
      sub = `They cost ${money(cost)} of the ${money(budgetNzd)} budget, ${SCENARIO_PHRASE[scenario]}.`;
    } else {
      figure = String(steps.length);
      text = `${links} fit within ${money(budgetNzd)}. Together they give an access gain of ${amount(total)} for ${ACCESS_NOUN[purpose] ?? "these trips"}.`;
      sub = `They cost ${money(cost)} in total.`;
    }
  }
  root.replaceChildren(
    ...(last && GOALS[purpose].commute ? [create("p", { className: "eyebrow", text: "Modelled increase" })] : []),
    create("div", { className: "hero-figure", text: figure }),
    create("p", { className: "hero-text", text }),
    create("p", { className: "hero-sub", text: sub }),
  );
  if (last && GOALS[purpose].commute) {
    const details = create("details", { className: "method-note" });
    details.append(create("summary", { text: "How to read this estimate" }));
    const notes = create("div", { className: "context-note" });
    notes.append(renderJourneyEquivalents(undefined, last.cumulativeObjective, ctx), create("p", { text: INCREMENT_NOTE }));
    if (last.cumulativeObjective >= 1) notes.append(create("p", {
      text: `Build cost per modelled extra commuter: ${money(last.cumulativeCostNzd / last.cumulativeObjective)}. ` +
        "This divides the capital cost by additional commuters; it is not a benefit–cost ratio or a cost per journey.",
    }));
    if (candidateOnlyNetwork(ctx.manifest)) notes.append(create("p", {
      text: "The model tests improvements against up to five retained routes per origin–destination pair. " +
        "It can change the balance between those routes, but cannot discover new routes outside that set. " +
        "A small increase therefore does not measure all the benefits of a connected network.",
    }));
    notes.append(create("p", { text: "School, everyday and station access are reported separately under their own goals." }));
    details.append(notes);
    root.append(details);
  }
  if (candidateOnlyNetwork(ctx.manifest)) root.append(create("p", {
    className: "estimate-scope",
    text: NETWORK_CONTEXT_NOTE,
  }));
}

function outcome(value: number, label: string, note?: string): HTMLElement {
  const block = create("div", { className: "outcome" });
  block.append(create("strong", { text: amount(value) }), create("span", { text: label }));
  if (note) block.append(create("small", { text: note }));
  return block;
}

function renderJourneyEquivalents(users: number | undefined, additional: number, ctx: ViewContext): HTMLElement {
  const assumptions = ctx.journeyAssumptions ?? DEFAULT_JOURNEY_ASSUMPTIONS;
  const period = journeyPeriodLabel(assumptions.period);
  const block = create("section", { className: "journey-equivalents", "aria-label": "Commute journey equivalents" });
  block.append(create("p", { className: "eyebrow", text: `Commute journeys ${period}` }));
  const grid = create("div", { className: "outcome-grid" });
  if (users !== undefined) grid.append(outcome(journeyEquivalent(users, assumptions), "by people using the upgrades"));
  grid.append(outcome(journeyEquivalent(additional, assumptions), "additional journey equivalents"));
  block.append(grid, create("p", { className: "help", text: `Illustrative · ${assumptions.daysPerYear} cycling days/year × ${assumptions.legsPerDay} one-way ${assumptions.legsPerDay === 1 ? "journey" : "journeys"}/day${assumptions.period === "month" ? " ÷ 12 months" : ""}. ${assumptions.legsPerDay === 2 ? "Return routes are assumed, not separately assigned. " : ""}Commuting only; not measured traffic. Change the calendar in “Journeys over time”.` }));
  return block;
}

function renderNetworkHero(root: HTMLElement, ctx: ViewContext, last: PortfolioStep): void {
  const links = ctx.steps.flatMap((step) => ctx.byId.get(step.candidateId) ?? []);
  const km = links.reduce((total, candidate) => total + candidateLengthKm(candidate), 0);
  const figures = create("div", { className: "outcome-grid" });
  figures.append(
    outcome(last.routeUsersAfter ?? 0, "cycle commuters using the upgrades", `Before upgrades: ${amount(last.routeUsersBefore ?? 0)}`),
    outcome(last.cumulativeObjective, "additional cycle commuters", "Above the scenario's starting level"),
  );
  const explanation = create("details", { className: "method-note" });
  explanation.append(create("summary", { text: "How these outcomes are estimated" }));
  const note = create("div", { className: "context-note" });
  note.append(renderJourneyEquivalents(last.routeUsersAfter, last.cumulativeObjective, ctx));
  note.append(create("p", { text: "Route use includes existing and additional commuters allocated to any upgraded link. Each person is counted at most once across the programme, even if their route uses several links." }));
  note.append(create("p", { text: "The additional figure estimates uptake across affected commute markets. Changes in route use also include people changing routes, so they are not the same measure. These are usual commuters, not daily journeys or all-purpose cycling." }));
  note.append(create("p", { text: "Both use the retained route alternatives. New routes outside that set and full-network low-stress OD access are not evaluated here." }));
  if (last.cumulativeObjective >= 1) note.append(create("p", { text: `Capital cost per modelled extra commuter: ${money(last.cumulativeCostNzd / last.cumulativeObjective)}. This is not a cost per journey or a benefit–cost ratio.` }));
  explanation.append(note);
  root.replaceChildren(
    create("p", { className: "eyebrow", text: "Your proposed programme" }),
    create("div", { className: "hero-figure", text: `${km.toFixed(1)} km` }),
    create("p", { className: "hero-text", text: `${String(links.length)} ${links.length === 1 ? "link" : "links"} · ${money(last.cumulativeCostNzd)} of ${money(ctx.state.budgetNzd)}` }),
    figures,
    create("p", { className: "help", text: `Protected-cycleway upgrades, priced for early comparison. Modelled ${SCENARIO_PHRASE[ctx.state.scenario]}; not a forecast.` }),
    explanation,
  );
}

function groupsInBudget(ctx: ViewContext): CandidateFeature[][] {
  return connectedGroups(ctx.steps.flatMap((step) => ctx.byId.get(step.candidateId) ?? []));
}

export function renderNetworkGroups(ctx: ViewContext): void {
  const root = requiredElement("network-groups");
  root.hidden = !ctx.manifest.networkContext || ctx.steps.length === 0;
  if (root.hidden) return;
  const groups = groupsInBudget(ctx);
  const list = create("div", { className: "compact-list" });
  for (const [index, group] of groups.entries()) {
    const ids = group.map((candidate) => candidate.properties.candidateId);
    const cost = group.reduce((total, candidate) => total + metricFor(candidate, ctx.state.scenario, ctx.state.purpose).capitalCostNzd, 0);
    const button = create("button", { type: "button", className: "compact-row group-row" });
    button.append(
      create("strong", { text: `${linkName(group[0]!.properties.name)}${group.length > 1 ? " and nearby links" : ""}` }),
      create("span", { text: `Group ${index + 1} · ${group.length} ${group.length === 1 ? "upgrade" : "upgrades"} · ${money(cost)}` }),
    );
    button.addEventListener("click", () => ctx.focusGroup(ids));
    list.append(button);
  }
  const details = create("details", { className: "network-group-list" });
  details.open = groups.length <= 4;
  details.append(create("summary", { text: `Explore ${String(groups.length)} connected ${groups.length === 1 ? "group" : "groups"}` }), list);
  root.replaceChildren(
    create("p", { className: "programme-connections", text: groups.length > 1 ? `These upgrades form ${groups.length} separate groups, not one continuous route.` : "These upgrades belong to one connected group in the mapped street network." }),
    details,
  );
  details.append(create("p", { className: "help", text: "Groups share junctions or existing low-stress streets. This does not confirm a safe end-to-end route; crossings and travel direction still need checking." }));
}

export function renderBuildList(ctx: ViewContext, filter: string, limit: number): void {
  const { purpose } = ctx.state;
  const items = ctx.steps
    .map((step) => ({ step, candidate: ctx.byId.get(step.candidateId) }))
    .filter((item): item is { step: PortfolioStep; candidate: CandidateFeature } => Boolean(item.candidate));
  const matching = items.filter(({ candidate }) => !filter || [
    linkName(candidate.properties.name),
    programmeText(candidate.properties.programmeStatus),
    candidate.properties.candidateId,
  ].join(" ").toLocaleLowerCase("en-NZ").includes(filter));
  const visible = matching.slice(0, limit);
  const total = ctx.steps.length;
  requiredElement("portfolio-count").textContent = filter
    ? `${String(matching.length)} of ${String(total)}`
    : `${String(total)} ${total === 1 ? "link" : "links"}`;
  requiredElement("candidate-search-status").textContent = matching.length > visible.length
    ? `Showing ${String(visible.length)} of ${String(matching.length)}.`
    : "";
  const search = requiredElement<HTMLInputElement>("candidate-search");
  search.hidden = total < 2 && !filter;
  const list = requiredElement("candidate-list");
  if (!visible.length) {
    list.replaceChildren(create("li", {
      className: "empty-state",
      text: total ? "No link in the build order matches that search." : "No links fit this budget yet.",
    }));
  } else {
    list.replaceChildren(...visible.map(({ step, candidate }) => {
      const id = candidate.properties.candidateId;
      const button = create("button", {
        type: "button",
        className: id === ctx.state.selectedCandidateId ? "rank-row selected" : "rank-row",
        "data-candidate-id": id,
      });
      button.append(
        create("span", { className: step.step <= NUMBERED_LINKS ? "rank" : "rank plain", text: String(step.step) }),
        create("span", { className: "rank-name", text: linkName(candidate.properties.name) }),
        create("span", { className: "rank-meta", text: money(metricFor(candidate, ctx.state.scenario, purpose).capitalCostNzd) }),
        create("span", { className: "rank-detail", text: stepText(step, purpose, candidate, ctx) }),
      );
      button.addEventListener("click", () => ctx.select(id));
      const item = create("li");
      item.append(button);
      return item;
    }));
  }
  const more = requiredElement<HTMLButtonElement>("show-more-button");
  more.hidden = matching.length <= visible.length;
  more.textContent = `Show ${String(Math.min(100, matching.length - visible.length))} more`;
}

export function renderMethodNote(root: HTMLElement, ctx: ViewContext): void {
  const summary = ctx.manifest.summaries[ctx.state.scenario][ctx.state.purpose];
  const paragraphs = [
    GOALS[ctx.state.purpose].order,
    "Links are taken in that order until the next one would go over the budget.",
    `Low-stress means traffic stress ${String(summary.maximumLts)} or lower, on a route no more than ` +
      `${summary.maximumDetourRatio.toFixed(1)} times the shortest. The model could route ${percent(summary.routingCoverage)} of these trips.`,
  ];
  if (summary.odLowStressShare !== null) {
    paragraphs.push(
      `${percent(summary.odLowStressShare)} of weighted trips can be made on low-stress routes ` +
        `(${amount(summary.odLowStressConnectedWeight ?? 0)} of ${amount(summary.odLowStressDenominatorWeight ?? 0)}, counting every trip, including those that could not be routed).`,
    );
  }
  paragraphs.push(...new Set(summary.warnings.map(runNote)));
  const demand = ctx.manifest.demandContext;
  if (demand && GOALS[ctx.state.purpose].commute) {
    paragraphs.push(`Screening capital cost: ${money(demand.capitalCostPerKm)} per km. These provisional costs are not project estimates.`);
    if (demand.routedBaselineUsers !== null && demand.sourceMarginUsers !== null) {
      paragraphs.push(`Baseline check: ${amount(demand.routedBaselineUsers)} usual cycle commuters in the routed OD sample; ${amount(demand.sourceMarginUsers)} in the broader source margins. ${demand.note}`);
    }
    if (demand.internalCoverage !== null && demand.sourceCoverage !== null) {
      paragraphs.push(`Routed coverage is ${percent(demand.internalCoverage)} of the prepared internal market, or ${percent(demand.sourceCoverage)} against the broader source margins. A high internal routing rate does not mean the whole commute market is represented.`);
    }
  }
  const link = create("a", { href: ctx.manifest.methodologyUrl, text: "Read the full method" });
  const last = create("p");
  last.append(link, document.createTextNode("."));
  root.replaceChildren(...paragraphs.map((text) => create("p", { text })), last);
}

export function renderPareto(ctx: ViewContext): void {
  const { scenario, purpose, budgetNzd } = ctx.state;
  const front = ctx.front();
  const chart = requiredElement("pareto-chart");
  const eligible = [...ctx.byId.values()].filter((candidate) => metricFor(candidate, scenario, purpose).available);
  const inBudget = new Set(ctx.steps.map((step) => step.candidateId));
  const hero = requiredElement("pareto-summary");
  if (!eligible.length) {
    hero.replaceChildren(create("p", { className: "hero-text", text: "No link has a value for this goal in this scenario." }));
    chart.replaceChildren();
    requiredElement("pareto-list").replaceChildren();
    requiredElement("pareto-plot-status").textContent = "";
    return;
  }
  const frontier = eligible.filter((candidate) => front.has(candidate.properties.candidateId));
  const frontierInBudget = frontier.filter((candidate) => inBudget.has(candidate.properties.candidateId)).length;
  hero.replaceChildren(
    create("div", { className: "hero-figure", text: String(frontier.length) }),
    create("p", { className: "hero-text", text: "links give the most for their whole-life cost: no other link does more for less." }),
    create("p", {
      className: "hero-sub",
      text: `${String(frontierInBudget)} of them are in the build order within ${money(budgetNzd)}. Click a dot to see the link.`,
    }),
  );
  const label = GOALS[purpose].valueLabel;
  const plotted = plotSample(eligible, (candidate) =>
    front.has(candidate.properties.candidateId) || inBudget.has(candidate.properties.candidateId) ||
    candidate.properties.candidateId === ctx.state.selectedCandidateId);
  requiredElement("pareto-plot-status").textContent = plotted.length < eligible.length
    ? `Showing ${String(plotted.length)} of ${String(eligible.length)} links: every best-value and build-order link, and an even sample of the rest.`
    : `${String(eligible.length)} links.`;
  const width = 620;
  const height = 330;
  const margin = { top: 20, right: 20, bottom: 46, left: 60 };
  const cost = (candidate: CandidateFeature) => metricFor(candidate, scenario, purpose).lifecycleCostNzd;
  const value = (candidate: CandidateFeature) => goalValue(metricFor(candidate, scenario, purpose), purpose);
  const maxCost = Math.max(...eligible.map(cost));
  const maxValue = Math.max(...eligible.map(value), 0.001);
  const x = (v: number) => margin.left + (v / maxCost) * (width - margin.left - margin.right);
  const y = (v: number) => height - margin.bottom - (v / maxValue) * (height - margin.top - margin.bottom);
  const svg = svgElement("svg", {
    viewBox: `0 0 ${String(width)} ${String(height)}`,
    role: "img",
    "aria-label": `Whole-life cost against ${label.toLowerCase()} for each link`,
  });
  for (let tick = 0; tick <= 4; tick += 1) {
    const fraction = tick / 4;
    svg.append(
      svgElement("line", { x1: x(maxCost * fraction), y1: margin.top, x2: x(maxCost * fraction), y2: height - margin.bottom, class: "grid-line" }),
      svgElement("line", { x1: margin.left, y1: y(maxValue * fraction), x2: width - margin.right, y2: y(maxValue * fraction), class: "grid-line" }),
      svgText(x(maxCost * fraction), height - margin.bottom + 18, money(maxCost * fraction), "tick-label"),
      svgText(margin.left - 8, y(maxValue * fraction) + 4, purpose === "appraisal" ? ratio(maxValue * fraction) : amount(maxValue * fraction), "tick-label", "end"),
    );
  }
  svg.append(
    svgText(width / 2, height - 8, "Whole-life cost (NZD, 40 years)", "axis-label"),
    svgText(16, height / 2, label, "axis-label rotated"),
  );
  const line = frontier.slice().sort((a, b) => cost(a) - cost(b)).map((candidate) => `${String(x(cost(candidate)))},${String(y(value(candidate)))}`);
  if (line.length > 1) svg.append(svgElement("polyline", { points: line.join(" "), class: "frontier-line" }));
  const order = (candidate: CandidateFeature) =>
    candidate.properties.candidateId === ctx.state.selectedCandidateId ? 3
      : front.has(candidate.properties.candidateId) ? 2 : inBudget.has(candidate.properties.candidateId) ? 1 : 0;
  for (const candidate of plotted.slice().sort((a, b) => order(a) - order(b))) {
    const id = candidate.properties.candidateId;
    const kind = ["point", "point budget", "point frontier", "point selected"][order(candidate)]!;
    const circle = svgElement("circle", {
      cx: x(cost(candidate)),
      cy: y(value(candidate)),
      r: order(candidate) >= 2 ? 6 : order(candidate) === 1 ? 5 : 3.5,
      class: kind,
      tabindex: order(candidate) ? "0" : "-1",
      role: "button",
      "data-candidate-id": id,
      "aria-label": `${linkName(candidate.properties.name)}: ${money(cost(candidate))}, ${goalValueText(metricFor(candidate, scenario, purpose), purpose)}`,
    });
    circle.append(svgElement("title", { textContent: linkName(candidate.properties.name) }));
    circle.addEventListener("click", () => ctx.select(id));
    circle.addEventListener("keydown", (event) => {
      if (!(event instanceof KeyboardEvent) || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      ctx.select(id);
    });
    svg.append(circle);
  }
  chart.replaceChildren(svg);
  const rows = frontier.slice().sort((a, b) => value(b) - value(a)).slice(0, FRONTIER_ROWS);
  requiredElement("pareto-heading").textContent = frontier.length > FRONTIER_ROWS
    ? `Best-value links, top ${String(FRONTIER_ROWS)} by ${purpose === "appraisal" ? "benefit–cost" : "gain"}`
    : "Best-value links";
  requiredElement("pareto-list").replaceChildren(...rows.map((candidate) => {
    const id = candidate.properties.candidateId;
    const row = create("button", { type: "button", className: "compact-row", "data-candidate-id": id });
    row.append(
      create("strong", { text: linkName(candidate.properties.name) }),
      create("span", { text: `${money(cost(candidate))} · ${goalValueText(metricFor(candidate, scenario, purpose), purpose)}` }),
    );
    row.addEventListener("click", () => ctx.select(id));
    return row;
  }));
}

function plotSample(eligible: CandidateFeature[], keep: (candidate: CandidateFeature) => boolean): CandidateFeature[] {
  if (eligible.length <= PARETO_POINT_LIMIT) return eligible;
  const kept = eligible.filter(keep);
  const rest = eligible.filter((candidate) => !keep(candidate))
    .sort((a, b) => a.properties.candidateId.localeCompare(b.properties.candidateId));
  const room = Math.max(0, PARETO_POINT_LIMIT - kept.length);
  if (room === 0 || rest.length === 0) return kept;
  if (rest.length <= room) return [...kept, ...rest];
  const step = (rest.length - 1) / Math.max(1, room - 1);
  return [...kept, ...Array.from({ length: room }, (_, index) => rest[Math.round(index * step)]!)];
}

export function renderLinkCard(ctx: ViewContext): void {
  const card = requiredElement("link-card");
  const candidate = ctx.state.selectedCandidateId ? ctx.byId.get(ctx.state.selectedCandidateId) : undefined;
  card.hidden = !candidate || ctx.state.activeTab === "connected";
  if (!candidate || card.hidden) return;
  const { scenario, purpose, budgetNzd } = ctx.state;
  const id = candidate.properties.candidateId;
  const metric = metricFor(candidate, scenario, purpose);
  const step = ctx.sequence.find(item => item.candidateId === id);
  const inBudget = ctx.steps.some(item => item.candidateId === id);
  requiredElement("candidate-eyebrow").textContent = step
    ? inBudget ? `Link ${step.step} of ${ctx.steps.length} in the build order` : `Link ${step.step} in the build order, beyond ${money(budgetNzd)}`
    : "Not in this build order";
  requiredElement("candidate-title").textContent = linkName(candidate.properties.name);
  requiredElement("candidate-sub").textContent = `${candidateLengthKm(candidate).toFixed(1)} km · ${programmeText(candidate.properties.programmeStatus)}`;

  const facts = create("dl", { className: "facts" });
  facts.append(create("dt", { text: "Build cost" }), create("dd", { text: money(metric.capitalCostNzd) }),
    create("dt", { text: "Length to upgrade" }), create("dd", { text: `${candidateLengthKm(candidate).toFixed(2)} km` }));
  const body: HTMLElement[] = [facts, create("h3", { text: "What would be built" }),
    create("p", { text: "Protected cycling space along the orange section. This is the treatment priced by the model, not a finished street design." })];
  if (candidate.properties.networkContext) body.push(...connectionDetails(candidate, ctx));
  else body.push(create("p", { className: "help", text: "Connection details are not available for this link." }));

  const usage = candidate.properties.commuteRouteUse?.[scenario];
  const diagnostic = ctx.demandDiagnostics?.scenario === scenario
    ? ctx.demandDiagnostics.candidates.find(row => row.candidateId === id) : undefined;
  const matchedDiagnostic = usage && diagnostic && Math.abs(diagnostic.additionalUsualCommuters - usage.additional) < 1e-7 ? diagnostic : undefined;
  body.push(create("h3", { text: "What the model estimates" }),
    create("p", { className: "card-lead", text: leadSentence(candidate, metric, step, ctx) }),
    create("p", { className: "help estimate-status", text: matchedDiagnostic && matchedDiagnostic.largestOdContributionShare > 0.5
      ? "Preliminary estimate — most of the gain depends on one sampled journey."
      : "Preliminary estimate — not a measured or calibrated forecast." }));

  const evidence = create("details", { className: "method-note", id: "candidate-evidence" });
  evidence.append(create("summary", { text: "How this was estimated" }));
  const notes = create("div", { className: "context-note" });
  notes.append(create("h3", { text: "From street data to an investment estimate" }));
  const steps = create("ol", { className: "model-steps" });
  for (const text of [
    "Map existing streets, cycle facilities, hills and traffic stress.",
    "Test this street upgrade against the sampled journeys and their retained route alternatives.",
    "Estimate the change in route choice and cycling for the chosen scenario.",
    "Recalculate the build order with earlier upgrades in place, so shared benefits are not counted twice.",
  ]) steps.append(create("li", { text }));
  notes.append(steps, create("p", { className: "rationale", text: rationaleText(candidate.properties.rationale) }));
  if (candidate.properties.programmeStatus === "aligned") notes.append(create("p", { text: ALIGNED_NOTE }));
  if (GOALS[purpose].commute) notes.append(create("p", { text: INCREMENT_NOTE }));
  if (usage) {
    notes.append(create("p", { text: `${amount(usage.after)} cycle commuters are assigned to this link after its upgrade, compared with ${amount(usage.before)} before. This includes people changing routes as well as additional cycling.` }));
    notes.append(renderJourneyEquivalents(usage.after, usage.additional, ctx));
  }
  if (matchedDiagnostic) {
    notes.append(create("h3", { text: "Sensitivity to the sampled journeys" }),
      create("p", { text: `${percent(matchedDiagnostic.largestOdContributionShare)} of the gain comes from one weighted journey record, among ${matchedDiagnostic.affectedOdRecords} affected records. The sample contains ${ctx.demandDiagnostics?.commuteRecordsPerStratum} commute record per source origin–destination cell. These are model records, not observed riders.` }));
    const table = create("dl", { className: "facts" });
    for (const sensitivity of matchedDiagnostic.elasticitySensitivity) table.append(create("dt", { text: `Response elasticity ${sensitivity.elasticity}` }), create("dd", { text: `+${amount(sensitivity.additionalUsualCommuters)} commuters` }));
    notes.append(table, create("p", { text: "These response settings have not been locally calibrated. Repeating the analysis with different sampled journeys is still needed." }));
  }
  if (candidate.properties.commuteRouteUse?.baseline.before === 0 && usage && usage.after > 0) notes.append(create("p", { text: "No commuters are assigned here in the census baseline. Suppressed counts and incomplete coverage mean this is not evidence of an unused street." }));
  notes.append(create("h3", { text: "Costs and effects" }));
  const moreFacts = create("dl", { className: "facts" });
  const rows: Array<[string, string]> = [["Whole-life cost, 40 years", money(metric.lifecycleCostNzd)]];
  if (metric.annualBikeKmDelta !== null) rows.push(["Extra km cycled a year", amount(metric.annualBikeKmDelta)]);
  const appraisal = candidate.properties.metrics.commute_8pct.appraisal;
  if (ctx.manifest.capabilities.appraisal !== "withheld" && appraisal.bcrP50 !== null && scenario === "commute_8pct") rows.push(["Indicative benefit–cost ratio", ratio(appraisal.bcrP50)]);
  rows.push(["Best value for its cost", ctx.front().has(id) ? "Yes" : "No"]);
  for (const [label, value] of rows) moreFacts.append(create("dt", { text: label }), create("dd", { text: value }));
  notes.append(moreFacts, create("h3", { text: "Parameter sensitivity" }));
  if (metric.frontierProbability !== null || metric.topKProbability !== null) {
    if (metric.frontierProbability !== null) notes.append(create("p", { text: `Best value for its cost in ${percent(metric.frontierProbability)} of the parameter tests.` }));
    if (metric.topKProbability !== null) notes.append(create("p", { text: `In the top 50 by benefit–cost in ${percent(metric.topKProbability)} of the parameter tests.` }));
    notes.append(create("p", { text: "These 1,000 tests vary costs, response and route-choice settings, but keep the journey sample fixed. The percentages are not forecast confidence." }));
  } else notes.append(create("p", { text: "Parameter tests are available only for the 8% scenario's cycling and benefit–cost goals." }));
  const warnings = linkWarnings(metric.warnings);
  if (warnings.length) {
    const list = create("ul");
    for (const warning of warnings) list.append(create("li", { text: warning }));
    notes.append(list);
  }
  const method = create("a", { href: ctx.manifest.methodologyUrl, text: "Full method and data sources" });
  notes.append(method); evidence.append(notes); body.push(evidence);
  const zoom = create("button", { type: "button", className: "secondary", text: "Zoom to this link" });
  zoom.addEventListener("click", () => ctx.zoom(id)); body.push(zoom);
  requiredElement("candidate-detail").replaceChildren(...body);
}

function connectionDetails(candidate: CandidateFeature, ctx: ViewContext): HTMLElement[] {
  const context = candidate.properties.networkContext!;
  const parts: HTMLElement[] = [create("h3", { text: "How it connects" })];
  parts.push(create("p", { className: "network-role", text: NETWORK_ROLES[context.role] }));
  const endpoints = create("div", { className: "endpoint-list" });
  for (const endpoint of context.endpoints) {
    const row = create("div", { className: "endpoint-row" });
    const label = endpoint.componentId ? "Touches an existing low-stress area" : "No low-stress street at this end";
    row.append(create("span", { className: "endpoint-label", text: endpoint.label }), create("span", { text: label }));
    endpoints.append(row);
  }
  parts.push(endpoints);
  if (!context.endpoints.some(endpoint => endpoint.componentId) && context.componentIds.length) parts.push(create("p", { className: "help", text: "The low-stress connection is part-way along this section, at a blue dot on the map—not at either end." }));
  const direction = context.direction === "mixed"
    ? "Conflicting one-way directions prevent riding this whole chain end to end under the current access rules."
    : context.direction === "both" ? "The candidate chain permits travel in both directions."
    : `The candidate chain permits travel ${context.direction === "forward" ? "A to B" : "B to A"} only.`;
  const connectionNotes = create("details", { className: "method-note" });
  connectionNotes.append(create("summary", { text: "Connection checks" }), create("p", { text: `${direction} Connections are based on shared street junctions, not a checked end-to-end route.` }));
  if (context.componentIds.length > 1) connectionNotes.append(create("p", { text: `Touches ${context.componentIds.length} separate low-stress areas, including contacts along its length.` }));
  const group = groupsInBudget(ctx).find((items) => items.some((item) => item.properties.candidateId === candidate.properties.candidateId));
  if (group && group.length > 1) {
    const ids = group.map((item) => item.properties.candidateId);
    const packageCard = create("section", { className: "package-card", "aria-label": "Connected package" });
    packageCard.append(create("h3", { text: `A package of ${String(group.length)} links` }));
    const cost = group.reduce((total, item) => total + metricFor(item, ctx.state.scenario, ctx.state.purpose).capitalCostNzd, 0);
    packageCard.append(create("p", { text: `${money(cost)} · ${group.reduce((total, item) => total + candidateLengthKm(item), 0).toFixed(1)} km of upgrades connected physically through the current network.` }));
    const evaluation = ctx.packageEvaluation(ids);
    if (evaluation) {
      const grid = create("div", { className: "outcome-grid" });
      grid.append(outcome(evaluation.after, "cycle commuters using the package"), outcome(evaluation.additional, "additional cycle commuters"));
      connectionNotes.append(grid, renderJourneyEquivalents(evaluation.after, evaluation.additional, ctx), create("p", { className: "help", text: "Evaluated together against the scenario baseline. Travellers are counted once. Separate package estimates must not be added together." }));
    }
    const focus = create("button", { type: "button", className: "secondary", text: "Show this package on the map" });
    focus.addEventListener("click", () => ctx.focusGroup(ids));
    packageCard.append(focus);
    parts.push(packageCard);
  }
  parts.push(connectionNotes);
  const neighbours = context.touchingCandidateIds.flatMap((id) => ctx.byId.get(id) ?? []).slice(0, 8);
  if (neighbours.length) {
    const details = create("details", { className: "method-note" });
    details.append(create("summary", { text: `Other candidates touching this corridor (${String(context.touchingCandidateIds.length)})` }));
    for (const neighbour of neighbours) {
      const button = create("button", { type: "button", className: "compact-row", text: linkName(neighbour.properties.name) });
      button.addEventListener("click", () => ctx.select(neighbour.properties.candidateId));
      details.append(button);
    }
    parts.push(details);
  }
  return parts;
}

function leadSentence(
  candidate: CandidateFeature,
  metric: CandidateMetric,
  step: PortfolioStep | undefined,
  ctx: ViewContext,
): string {
  const { purpose } = ctx.state;
  const cost = money(metric.capitalCostNzd);
  if (!metric.available || metric.objectiveValue === null) {
    return purpose === "appraisal"
      ? `No benefit–cost ratio for this link ${SCENARIO_PHRASE[ctx.state.scenario]}. Build cost ${cost}.`
      : `This link has no value for this goal. Build cost ${cost}.`;
  }
  let sentence: string;
  if (purpose === "appraisal") {
    sentence = `Indicative benefit–cost ratio of ${ratio(metric.objectiveValue)}, for a build cost of ${cost}.`;
  } else if (GOALS[purpose].commute) {
    const who = purpose === "equity" ? "people from deprived areas" : "people";
    const riders = metric.additionalCycleUsers ?? metric.objectiveValue;
    sentence = `About ${amount(riders)} additional ${who} cycling to work, for a build cost of ${cost}.`;
  } else {
    sentence = `Access gain of ${amount(metric.objectiveValue)} for ${ACCESS_NOUN[purpose] ?? "these trips"}, for a build cost of ${cost}.`;
  }
  const standalone = purpose === "appraisal" ? metric.additionalCycleUsers ?? 0 : metric.objectiveValue;
  if (step && standalone > 0 && Math.abs(step.marginalObjective - standalone) / standalone > 0.05) {
    sentence += step.marginalObjective < standalone
      ? ` In the build order it adds ${amount(step.marginalObjective)}, because earlier links already help some of the same trips.`
      : ` In the build order it adds ${amount(step.marginalObjective)}, because the combined treatments change the response for some of the same trips.`;
  }
  void candidate;
  return sentence;
}


export const LAYER_LABELS: Record<string, string> = {
  cells: "Where trips start",
  candidates: "Other proposals",
  network: "Streets in the model",
  existing: "Low-stress streets & paths",
  programmes: "AT cycling plans",
  counters: "Cycle counters",
  safety: "Cycle crashes",
  intersections: "Intersections",
};

export function renderLayerControls(root: HTMLElement, manifest: Manifest, visible: Set<string>): void {
  root.replaceChildren(...manifest.layers.map((layer) => {
    const input = create("input", { type: "checkbox", id: `layer-${layer.id}` });
    input.checked = visible.has(layer.id);
    input.dataset.layerId = layer.id;
    const row = create("label", { className: "check-row", htmlFor: input.id });
    const label = layer.id === "network" && (candidateOnlyNetwork(manifest) || manifest.networkContext)
      ? "Modelled street segments"
      : LAYER_LABELS[layer.id] ?? layer.label;
    row.append(input, create("span", { text: label }));
    return row;
  }));
  if (manifest.effectiveNetwork) {
    const context = manifest.effectiveNetwork;
    requiredElement("intersection-source-note").textContent = `${amount(context.matchedSites)} of ${amount(context.inventorySites)} AT sites matched to the street network; ${amount(context.reviewSites)} need review. Connected journeys uses assumed waits, not measured signal timings.`;
  }
}

interface KeyRow {
  swatch: HTMLElement;
  title: string;
  note?: string;
}

export function renderLegend(
  root: HTMLElement,
  ctx: ViewContext,
  demand: { breaks: number[]; empty: boolean },
): void {
  const { state } = ctx;
  const rows: KeyRow[] = [];
  const count = ctx.steps.length;
  if (count) {
    rows.push({
      swatch: pinSwatch(),
      title: `Build order: ${String(count)} ${count === 1 ? "link" : "links"} within ${money(state.budgetNzd)}`,
      note: count > NUMBERED_LINKS ? `The first ${String(NUMBERED_LINKS)} are numbered.` : undefined,
    });
  }
  const selected = state.selectedCandidateId ? ctx.byId.get(state.selectedCandidateId) : undefined;
  if (selected) rows.push({ swatch: lineSwatch(COLOURS.selected, 5), title: `Selected: ${linkName(selected.properties.name)}` });
  if (state.focusedGroupIds.size > 1) rows.push({ swatch: lineSwatch(COLOURS.selected, 4), title: `Focused package: ${String(state.focusedGroupIds.size)} links` });
  if (selected?.properties.networkContext) rows.push({ swatch: dotSwatch(COLOURS.selected), title: "A / B: corridor ends" });
  if (state.visibleLayerIds.has("cells")) {
    rows.push({
      swatch: rampSwatch(COLOURS.demand),
      title: "Where these trips start",
      note: demand.empty ? "No start points for this goal and scenario." : "Lighter to darker: fewer to more.",
    });
  }
  if (state.visibleLayerIds.has("candidates")) {
    rows.push({ swatch: lineSwatch(COLOURS.other, 2), title: `Other links tested (${amount(ctx.byId.size)})` });
  }
  if (state.visibleLayerIds.has("existing")) {
    rows.push({ swatch: lineSwatch(COLOURS.existing, 3), title: "Existing separated lane or shared path" });
    rows.push({ swatch: lineSwatch(COLOURS.quiet, 2), title: "Other existing low-stress street", note: "Modelled traffic stress 1–2. Connections use source junctions." });
    if (selected?.properties.networkContext?.componentIds.length) rows.push({
      swatch: lineSwatch(COLOURS.counter, 3),
      title: "Existing area attached to the selection",
      note: "Blue dots mark shared junctions along the selected corridor.",
    });
  }
  if (state.visibleLayerIds.has("network")) {
    if (candidateOnlyNetwork(ctx.manifest) || ctx.manifest.networkContext) {
      rows.push({
        swatch: lineSwatch(COLOURS.street, 2, true),
        title: "Candidate street segments",
        note: "The existing low-stress network is not included in this layer.",
      });
    } else {
      rows.push({ swatch: lineSwatch(COLOURS.existing, 3), title: "Existing facility or quiet street" });
      rows.push({ swatch: lineSwatch(COLOURS.street, 2, true), title: "Other street in the model" });
    }
  }
  if (state.visibleLayerIds.has("programmes")) {
    rows.push({ swatch: lineSwatch(COLOURS.planned, 4), title: "AT committed or planned project" });
    rows.push({ swatch: lineSwatch(COLOURS.strategic, 3, true), title: "Future Connect route" });
  }
  if (state.visibleLayerIds.has("intersections")) {
    rows.push({ swatch: dotSwatch("#7c3aed"), title: "Matched signal-controlled site", note: "Illustrative delay sensitivity; timings need AT evidence." });
    rows.push({ swatch: dotSwatch("#b45309"), title: "Matched site without recorded signal control" });
    rows.push({ swatch: dotSwatch("#64748b"), title: "Intersection needs review", note: "No delay applied at unresolved sites." });
  }
  if (state.visibleLayerIds.has("counters")) {
    rows.push({
      swatch: dotSwatch(COLOURS.counter),
      title: "Cycle counter, bigger for more bikes a day",
      note: `${String(ctx.manifest.validation.counterCount)} sites, ${ctx.manifest.validation.periodLabel}. ` +
        "They count all cycling, not just commuting, so they are a rough check only.",
    });
  }
  if (state.visibleLayerIds.has("safety")) {
    rows.push({
      swatch: rampSwatch(COLOURS.crashes),
      title: `Crashes involving a bike per 500 m square: 3–${String(CRASH_BREAKS[0] - 1)}, ${String(CRASH_BREAKS[0])}–${String(CRASH_BREAKS[1] - 1)}, ${String(CRASH_BREAKS[1])}+`,
      note: "Squares with fewer than 3 are not shown. Not adjusted for how much cycling happens there.",
    });
  }
  root.replaceChildren(...rows.map((row) => {
    const item = create("div", { className: "key-row" });
    const text = create("div", { className: "key-text" });
    text.append(create("span", { text: row.title }));
    item.append(row.swatch, text);
    return item;
  }));
  const notes = rows.filter(row => row.note);
  if (notes.length) {
    const details = create("details", { className: "key-notes" });
    details.append(create("summary", { text: "Layer details" }));
    for (const row of notes) details.append(create("p", { text: `${row.title}: ${row.note}` }));
    root.append(details);
  }
}

function lineSwatch(colour: string, weight: number, dashed = false): HTMLElement {
  const swatch = create("span", { className: dashed ? "key-line dashed" : "key-line" });
  swatch.style.setProperty("--key-colour", colour);
  swatch.style.setProperty("--key-weight", `${String(weight)}px`);
  return swatch;
}

function pinSwatch(): HTMLElement {
  const swatch = create("span", { className: "key-pin" });
  swatch.style.setProperty("--key-colour", COLOURS.build);
  swatch.append(create("span", { text: "1" }));
  return swatch;
}

function rampSwatch(colours: readonly string[]): HTMLElement {
  const swatch = create("span", { className: "key-ramp" });
  for (const colour of colours) {
    const step = create("i");
    step.style.background = colour;
    swatch.append(step);
  }
  return swatch;
}

function dotSwatch(colour: string): HTMLElement {
  const swatch = create("span", { className: "key-dot" });
  swatch.style.setProperty("--key-colour", colour);
  return swatch;
}

export function renderSketchResult(root: HTMLElement, result: SketchResult | null, error?: string): void {
  if (error) {
    root.replaceChildren(create("p", { className: "error-text", text: error }));
    return;
  }
  if (!result || result.edgeIds.length === 0) {
    root.replaceChildren(create("p", { className: "help", text: "Choose at least two points on the map." }));
    return;
  }
  const list = create("dl", { className: "mini-facts" });
  for (const [term, value] of [
    ["Length", `${result.lengthKm.toFixed(2)} km`],
    ["Rough build cost", money(result.capitalCostNzd)],
  ] as const) {
    list.append(create("dt", { text: term }), create("dd", { text: value }));
  }
  root.replaceChildren(list, create("p", {
    className: "help",
    text: "Length and a rough cost only: riders are not modelled for a drawn link. Download it to run it through the full model.",
  }));
}
