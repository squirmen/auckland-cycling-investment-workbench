import "./style.css";

import { candidateFeatures, loadDefaultLayers, loadLayer, loadManifest } from "./data";
import { WorkbenchMap } from "./map";
import {
  compactNumber,
  formatCost,
  formatPercent,
  metricFor,
  objectiveValue,
  paretoFront,
  portfolioAtBudget,
  portfolioGeoJson,
  purposeBenefit,
  type SketchResult,
} from "./model";
import type {
  AppState,
  CandidateFeature,
  CandidateMetric,
  LoadedLayers,
  Manifest,
  PortfolioStep,
  PurposeId,
  ScenarioId,
  SummaryMetric,
} from "./types";

const app = requiredElement("app");
const statusMessage = requiredElement("status-message");
const loadingPanel = requiredElement("loading-panel");
const PORTFOLIO_PAGE_SIZE = 100;
const PARETO_POINT_LIMIT = 1_500;
let manifest: Manifest;
let layers: LoadedLayers;
let candidates: CandidateFeature[] = [];
let currentSketch: SketchResult | null = null;
let desiredSketchNodeIds: string[] = [];
let candidateFilter = "";
let candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
let statusTimer: number | undefined;
let budgetRenderTimer: number | undefined;
const paretoCache = new Map<string, Set<string>>();
let state: AppState;

const mapController = new WorkbenchMap(requiredElement("map"), {
  onCandidateSelected: (candidateId) => selectCandidate(candidateId),
  onSketchChanged: (result, error) => renderSketch(result, error),
});

void initialise();

async function initialise(): Promise<void> {
  try {
    manifest = await loadManifest();
    layers = await loadDefaultLayers(manifest);
    candidates = candidateFeatures(layers);
    paretoCache.clear();
    state = initialState(manifest);
    populateControls();
    await applyQueryState(false);
    bindEvents();
    mapController.setLayers(layers);
    mapController.setSketchNodes(desiredSketchNodeIds);
    renderAll();
    loadingPanel.hidden = true;
    app.setAttribute("aria-busy", "false");
  } catch (error) {
    app.setAttribute("aria-busy", "false");
    const message = error instanceof Error ? error.message : "The verified model run could not be loaded.";
    statusMessage.textContent = message;
    statusMessage.classList.add("error");
    loadingPanel.classList.add("error");
    loadingPanel.replaceChildren(
      create("strong", { text: "The model run could not be loaded" }),
      create("span", { text: message }),
      create("span", { text: "Check that the verified web-data bundle is present, then reload this page." }),
    );
  }
}

function initialState(data: Manifest): AppState {
  return {
    scenario: data.defaultScenario,
    purpose: data.defaultPurpose,
    budgetNzd: data.defaultBudgetNzd,
    selectedCandidateId: null,
    visibleLayerIds: new Set(data.layers.filter((layer) => layer.defaultVisible).map((layer) => layer.id)),
    portfolioIds: new Set(),
    activeTab: "portfolio",
    sketching: false,
  };
}

function populateControls(): void {
  requiredElement<HTMLDetailsElement>("map-legend").open =
    !window.matchMedia("(max-width: 520px)").matches;
  const scenarioSelect = requiredElement<HTMLSelectElement>("scenario-select");
  const purposeSelect = requiredElement<HTMLSelectElement>("purpose-select");
  replaceChildren(
    scenarioSelect,
    manifest.scenarios.map((scenario) => option(scenario.id, scenario.label)),
  );
  replaceChildren(
    purposeSelect,
    manifest.purposes.map((purpose) => purposeOption(purpose.id, purpose.label)),
  );
  scenarioSelect.value = state.scenario;
  purposeSelect.value = state.purpose;

  const budget = requiredElement<HTMLInputElement>("budget-slider");
  const budgetStepMillions = budgetStep(manifest.maxBudgetNzd);
  budget.step = String(budgetStepMillions);
  budget.max = queryNumber(manifest.maxBudgetNzd / 1_000_000);
  budget.value = String(state.budgetNzd / 1_000_000);
  requiredElement("budget-maximum").textContent = formatCost(manifest.maxBudgetNzd);

  const controls = requiredElement("layer-controls");
  replaceChildren(
    controls,
    manifest.layers.map((layer) => {
      const input = create("input", { type: "checkbox", id: `layer-${layer.id}` });
      input.checked = state.visibleLayerIds.has(layer.id);
      input.dataset.layerId = layer.id;
      const row = create("label", { className: "check-row", htmlFor: input.id });
      row.append(input, create("span", { text: layer.label }));
      return row;
    }),
  );
}

function bindEvents(): void {
  requiredElement<HTMLSelectElement>("scenario-select").addEventListener("change", (event) => {
    state.scenario = (event.currentTarget as HTMLSelectElement).value as ScenarioId;
    state.selectedCandidateId = null;
    candidateFilter = "";
    candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
    requiredElement<HTMLInputElement>("candidate-search").value = "";
    renderAll();
  });
  requiredElement<HTMLSelectElement>("purpose-select").addEventListener("change", (event) => {
    state.purpose = (event.currentTarget as HTMLSelectElement).value as PurposeId;
    state.selectedCandidateId = null;
    candidateFilter = "";
    candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
    requiredElement<HTMLInputElement>("candidate-search").value = "";
    renderAll();
  });
  requiredElement<HTMLInputElement>("budget-slider").addEventListener("input", (event) => {
    state.budgetNzd = Math.min(
      Number((event.currentTarget as HTMLInputElement).value) * 1_000_000,
      manifest.maxBudgetNzd,
    );
    candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
    requiredElement("budget-output").textContent = formatCost(state.budgetNzd);
    (event.currentTarget as HTMLInputElement).setAttribute(
      "aria-valuetext",
      formatCost(state.budgetNzd),
    );
    if (budgetRenderTimer !== undefined) window.clearTimeout(budgetRenderTimer);
    budgetRenderTimer = window.setTimeout(() => renderAll(), 120);
  });
  requiredElement<HTMLInputElement>("candidate-search").addEventListener("input", (event) => {
    candidateFilter = (event.currentTarget as HTMLInputElement).value
      .trim()
      .toLocaleLowerCase("en-NZ");
    candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
    renderPortfolio();
  });
  requiredElement("show-more-button").addEventListener("click", () => {
    candidateDisplayLimit += PORTFOLIO_PAGE_SIZE;
    renderPortfolio();
  });
  requiredElement("layer-controls").addEventListener("change", (event) => void handleLayerToggle(event));
  requiredElement("sketch-toggle").addEventListener("click", () => {
    state.sketching = !state.sketching;
    renderSketchControls();
    mapController.update(state);
  });
  requiredElement("sketch-clear").addEventListener("click", () => mapController.clearSketch());
  requiredElement("download-button").addEventListener("click", downloadPortfolio);
  requiredElement("share-button").addEventListener("click", () => void copyViewLink());
  requiredElement("reset-button").addEventListener("click", () => void resetView());
  requiredElement("print-button").addEventListener("click", () => window.print());
  document.querySelectorAll<HTMLButtonElement>("button.tab").forEach((button) => {
    button.addEventListener("click", () => {
      activateTab(button.dataset.tab as AppState["activeTab"]);
    });
    button.addEventListener("keydown", handleTabKeydown);
  });
  window.addEventListener("popstate", () => void applyQueryState());
}

async function handleLayerToggle(event: Event): Promise<void> {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.dataset.layerId) return;
  const layerId = input.dataset.layerId;
  if (input.checked) {
    state.visibleLayerIds.add(layerId);
    if (!layers[layerId as keyof LoadedLayers]) {
      setStatus(`Loading ${layerId}…`);
      try {
        layers[layerId as keyof LoadedLayers] = await loadLayer(manifest, layerId);
        candidates = candidateFeatures(layers);
        paretoCache.clear();
        mapController.setLayers(layers);
        setStatus("");
      } catch (error) {
        state.visibleLayerIds.delete(layerId);
        input.checked = false;
        setStatus(error instanceof Error ? error.message : `Unable to load ${layerId}`, true);
      }
    }
  } else {
    state.visibleLayerIds.delete(layerId);
  }
  renderOverlayContext();
  mapController.update(state);
  syncQueryState();
}

function renderAll(): void {
  const scenario = manifest.scenarios.find((item) => item.id === state.scenario)!;
  const purpose = manifest.purposes.find((item) => item.id === state.purpose)!;
  requiredElement("scenario-note").textContent = scenario.description;
  requiredElement("purpose-note").textContent = `${purpose.description} Objective: ${purpose.objectiveLabel}.`;
  const summary = currentSummary();
  const context = summary.odLowStressShare === null
    ? `CIW OD low-stress connectivity is not yet available for this run. Routing coverage ${formatPercent(summary.routingCoverage)}.`
    : `CIW OD low-stress connectivity · ${purpose.label} purpose · ` +
      `${formatDemand(summary.odLowStressConnectedWeight ?? 0)} connected of complete denominator ` +
      `${formatDemand(summary.odLowStressDenominatorWeight ?? 0)} weighted activity · ` +
      `LTS ≤ ${summary.maximumLts} · detour ≤ ${summary.maximumDetourRatio.toFixed(1)} · ` +
      `routing coverage ${formatPercent(summary.routingCoverage)}.`;
  requiredElement("connectivity-context").textContent = [context, ...summary.warnings].join(" ");
  requiredElement("data-status").textContent = dataStatusName(manifest.dataStatus);
  requiredElement("data-status").className = `data-status ${manifest.dataStatus}`;
  requiredElement("run-summary").textContent = `Run ${manifest.runId} · model ${manifest.modelVersion}`;
  requiredElement("map-provenance-text").textContent =
    `${manifest.dataStatusLabel} · run ${manifest.runId} · ${manifest.attribution.join(" · ")}`;
  requiredElement("mobile-map-status").textContent =
    `${dataStatusName(manifest.dataStatus)} · ${scenario.label} · ${purpose.label} · ${manifest.runId}`;
  requiredElement<HTMLAnchorElement>("methodology-link").href = manifest.methodologyUrl;
  requiredElement("budget-output").textContent = formatCost(state.budgetNzd);
  requiredElement<HTMLInputElement>("budget-slider").setAttribute(
    "aria-valuetext",
    formatCost(state.budgetNzd),
  );
  requiredElement("attribution").textContent = manifest.attribution.join(" · ");
  renderKpis();
  renderPortfolio();
  if (state.activeTab === "pareto") renderPareto();
  if (state.activeTab === "evidence") renderCandidateDetail();
  renderTabs();
  renderSketchControls();
  renderLegend();
  renderOverlayContext();
  mapController.update(state);
  syncQueryState();
  requiredElement("view-announcement").textContent =
    `${scenario.label}, ${purpose.label} lens, ${formatCost(state.budgetNzd)} budget. ` +
    `${selectedPortfolio().length} ${selectedPortfolio().length === 1 ? "project" : "projects"} in the portfolio.`;
}

function renderKpis(): void {
  const summary = currentSummary();
  const cards: Array<[string, string, string]> = [
    [
      compactNumber.format(summary.activityValue),
      summary.activityUnit,
      "Scenario activity represented by this planning lens.",
    ],
    [
      summary.odLowStressShare === null ? "—" : formatPercent(summary.odLowStressShare),
      "low-stress OD share",
      "Demand-weighted share connected at the stated stress and detour thresholds.",
    ],
    [
      formatPercent(summary.routingCoverage),
      "routing coverage",
      "Share of eligible weighted activity represented by successful routes.",
    ],
    [String(summary.candidateCount), "screened corridors", "Candidate corridors evaluated in this run."],
  ];
  replaceChildren(
    requiredElement("headline-kpis"),
    cards.map(([value, label, explanation]) => {
      const card = create("div", { className: "kpi", title: explanation });
      card.append(create("strong", { text: value }), create("span", { text: label }));
      return card;
    }),
  );
}

function selectedPortfolio(): PortfolioStep[] {
  return portfolioAtBudget(manifest, state.scenario, state.purpose, state.budgetNzd);
}

function renderPortfolio(): void {
  const steps = selectedPortfolio();
  const selectedIds = new Set(steps.map((step) => step.candidateId));
  state.portfolioIds = selectedIds;
  const selectedItems = steps
    .map((step) => ({
      step,
      candidate: candidates.find((candidate) => candidate.properties.candidateId === step.candidateId),
    }))
    .filter((item): item is { step: PortfolioStep; candidate: CandidateFeature } =>
      Boolean(item.candidate)
    );
  const matchingItems = selectedItems.filter(({ candidate }) => {
    if (!candidateFilter) return true;
    const haystack = [
      candidate.properties.name,
      candidate.properties.facilityType,
      programmeLabel(candidate.properties.programmeStatus),
      candidate.properties.candidateId,
    ]
      .join(" ")
      .toLocaleLowerCase("en-NZ");
    return haystack.includes(candidateFilter);
  });
  const visibleItems = matchingItems.slice(0, candidateDisplayLimit);
  requiredElement("portfolio-count").textContent = candidateFilter
    ? `${matchingItems.length} of ${steps.length}`
    : `${steps.length} ${steps.length === 1 ? "project" : "projects"}`;
  requiredElement("candidate-search-status").textContent = matchingItems.length > visibleItems.length
    ? `Showing ${visibleItems.length} of ${matchingItems.length} matches; search covers the complete ${steps.length}-project portfolio.`
    : `${matchingItems.length} of ${steps.length} portfolio projects shown.`;
  const finalStep = steps.at(-1);
  const summaryCards: Array<[string, string]> = [
    [formatCost(finalStep?.cumulativeCostNzd ?? 0), "capital screen"],
    [
      formatMetricValue(finalStep?.cumulativeObjective ?? 0, finalStep?.objectiveUnit ?? "modelled activity"),
      finalStep?.objectiveUnit ?? "modelled objective",
    ],
  ];
  replaceChildren(
    requiredElement("portfolio-summary"),
    summaryCards.map(([value, label]) => {
      const card = create("div");
      card.append(create("strong", { text: value }), create("span", { text: label }));
      return card;
    }),
  );
  const list = requiredElement("candidate-list");
  if (visibleItems.length) {
    replaceChildren(list, visibleItems.map(({ candidate, step }) => candidateRow(candidate, step)));
  } else {
    replaceChildren(
      list,
      [create("li", {
        className: "empty-state",
        text: steps.length
          ? "No portfolio corridors match this search."
          : "No projects fit this budget. Increase the budget to begin a portfolio.",
      })],
    );
  }
  const search = requiredElement<HTMLInputElement>("candidate-search");
  search.disabled = steps.length === 0;
  const showMore = requiredElement<HTMLButtonElement>("show-more-button");
  showMore.hidden = matchingItems.length <= visibleItems.length;
  showMore.textContent = `Show ${Math.min(PORTFOLIO_PAGE_SIZE, matchingItems.length - visibleItems.length)} more`;
  requiredElement<HTMLButtonElement>("download-button").disabled =
    steps.length === 0 && currentSketch === null;
  if (!state.selectedCandidateId && selectedItems.length) {
    state.selectedCandidateId = selectedItems[0]!.candidate.properties.candidateId;
  }
}

function candidateRow(candidate: CandidateFeature, step: PortfolioStep): HTMLElement {
  const metric = metricFor(candidate, state.scenario, state.purpose);
  const button = create("button", {
    type: "button",
    className: candidate.properties.candidateId === state.selectedCandidateId ? "candidate-button selected" : "candidate-button",
    "data-candidate-id": candidate.properties.candidateId,
  });
  button.addEventListener("click", () => selectCandidate(candidate.properties.candidateId));
  const heading = create("div", { className: "candidate-heading" });
  heading.append(
    create("span", { className: "rank", text: String(step.step) }),
    create("strong", { text: candidate.properties.name }),
    create("span", { className: `status ${candidate.properties.programmeStatus}`, text: programmeLabel(candidate.properties.programmeStatus) }),
  );
  const metrics = create("div", { className: "candidate-metrics" });
  const metricPairs = [
    metricPair("Capital screen", formatCost(metric.capitalCostNzd)),
    metricPair(
      "Objective",
      `${formatMetricValue(metric.objectiveValue ?? 0, metric.objectiveUnit)} ${metric.objectiveUnit}`,
    ),
    metricPair("Marginal", formatMetricValue(step.marginalObjective, step.objectiveUnit)),
  ];
  if (manifest.capabilities.appraisal !== "withheld") {
    metricPairs.splice(2, 0, metricPair("Indicative BCR", formatBcr(metric)));
  }
  metrics.append(...metricPairs);
  button.append(heading, metrics);
  const item = create("li");
  item.append(button);
  return item;
}

function renderPareto(): void {
  const front = currentParetoFront();
  const chart = requiredElement("pareto-chart");
  chart.replaceChildren();
  const eligibleCandidates = candidates.filter((candidate) =>
    metricFor(candidate, state.scenario, state.purpose).available
  );
  if (!eligibleCandidates.length) {
    chart.append(create("p", {
      className: "help",
      text: "This purpose is not available for the selected run.",
    }));
    requiredElement("pareto-list").replaceChildren();
    requiredElement("pareto-plot-status").textContent = "No eligible corridors are available for this view.";
    return;
  }
  const benefitLabel = manifest.purposes.find(
    (item) => item.id === state.purpose,
  )!.objectiveLabel;
  const objectiveUnit = metricFor(
    eligibleCandidates[0]!,
    state.scenario,
    state.purpose,
  ).objectiveUnit;
  const plotCandidates = paretoPlotCandidates(eligibleCandidates, front);
  const frontierCount = eligibleCandidates.filter((candidate) =>
    front.has(candidate.properties.candidateId)
  ).length;
  requiredElement("pareto-plot-status").textContent =
    plotCandidates.length < eligibleCandidates.length
      ? `Showing all ${frontierCount} frontier corridors and a deterministic visual sample of ` +
        `${plotCandidates.length - frontierCount} of ${eligibleCandidates.length - frontierCount} other corridors. ` +
        `Frontier calculations use all ${eligibleCandidates.length} eligible corridors.`
      : `Showing all ${eligibleCandidates.length} eligible corridors; ${frontierCount} are on the frontier.`;
  requiredElement("pareto-description").textContent =
    `Frontier projects are not dominated on lifecycle cost and ${benefitLabel.toLowerCase()}.`;
  requiredElement("pareto-heading").textContent = `Cost and ${benefitLabel.toLowerCase()}`;
  const width = 620;
  const height = 330;
  const margin = { top: 22, right: 22, bottom: 48, left: 62 };
  const maxCost = Math.max(
    ...eligibleCandidates.map(
      (candidate) => metricFor(candidate, state.scenario, state.purpose).lifecycleCostNzd,
    ),
  );
  const maxBenefit = Math.max(
    ...eligibleCandidates.map((candidate) =>
      purposeBenefit(metricFor(candidate, state.scenario, state.purpose), state.purpose),
    ),
    0.001,
  );
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `Candidate lifecycle cost versus ${benefitLabel.toLowerCase()}`,
  });
  const x = (value: number) => margin.left + (value / maxCost) * (width - margin.left - margin.right);
  const y = (value: number) =>
    height - margin.bottom - (value / maxBenefit) * (height - margin.top - margin.bottom);
  for (let tick = 0; tick <= 4; tick += 1) {
    const fraction = tick / 4;
    const xPosition = x(maxCost * fraction);
    const yPosition = y(maxBenefit * fraction);
    svg.append(
      svgElement("line", {
        x1: xPosition,
        y1: margin.top,
        x2: xPosition,
        y2: height - margin.bottom,
        class: "grid-line",
      }),
      svgElement("line", {
        x1: margin.left,
        y1: yPosition,
        x2: width - margin.right,
        y2: yPosition,
        class: "grid-line",
      }),
      svgText(xPosition, height - margin.bottom + 18, axisCost(maxCost * fraction), "tick-label"),
      svgText(
        margin.left - 8,
        yPosition + 4,
        formatMetricValue(maxBenefit * fraction, objectiveUnit),
        "tick-label end",
      ),
    );
  }
  svg.append(
    svgElement("line", { x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom, class: "axis" }),
    svgElement("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: height - margin.bottom, class: "axis" }),
    svgText(width / 2, height - 10, "Lifecycle cost screen (NZD)", "axis-label"),
    svgText(16, height / 2, benefitLabel, "axis-label rotated"),
  );
  for (const candidate of plotCandidates) {
    const metric = metricFor(candidate, state.scenario, state.purpose);
    const benefit = purposeBenefit(metric, state.purpose);
    const circle = svgElement("circle", {
      cx: x(metric.lifecycleCostNzd),
      cy: y(benefit),
      r: front.has(candidate.properties.candidateId) ? 7 : 4.5,
      class: front.has(candidate.properties.candidateId) ? "point frontier" : "point",
      tabindex: "0",
      role: "button",
      "data-candidate-id": candidate.properties.candidateId,
      "aria-label": `${candidate.properties.name}, ${formatCost(metric.lifecycleCostNzd)}, ${benefitLabel.toLowerCase()} ${formatMetricValue(benefit, metric.objectiveUnit)}`,
    });
    circle.append(svgElement("title", { textContent: candidate.properties.name }));
    circle.addEventListener("click", () => selectCandidate(candidate.properties.candidateId));
    circle.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectCandidate(candidate.properties.candidateId);
      }
    });
    svg.append(circle);
  }
  chart.append(svg);
  const frontCandidates = eligibleCandidates
    .filter((candidate) => front.has(candidate.properties.candidateId))
    .sort((a, b) => objectiveValue(metricFor(b, state.scenario, state.purpose), state.purpose) - objectiveValue(metricFor(a, state.scenario, state.purpose), state.purpose));
  replaceChildren(
    requiredElement("pareto-list"),
    frontCandidates.map((candidate) => {
      const metric = metricFor(candidate, state.scenario, state.purpose);
      const benefit = purposeBenefit(metric, state.purpose);
      const row = create("button", {
        type: "button",
        className: "compact-row",
        "data-candidate-id": candidate.properties.candidateId,
      });
      row.append(
        create("strong", { text: candidate.properties.name }),
        create("span", {
          text: `${formatCost(metric.lifecycleCostNzd)} · ${formatMetricValue(benefit, metric.objectiveUnit)}`,
        }),
      );
      row.addEventListener("click", () => selectCandidate(candidate.properties.candidateId));
      return row;
    }),
  );
}

function currentParetoFront(): Set<string> {
  const key = `${manifest.runId}|${state.scenario}|${state.purpose}|${candidates.length}`;
  const cached = paretoCache.get(key);
  if (cached) return cached;
  const front = paretoFront(candidates, state.scenario, state.purpose);
  paretoCache.set(key, front);
  return front;
}

function paretoPlotCandidates(
  eligible: CandidateFeature[],
  front: Set<string>,
): CandidateFeature[] {
  if (eligible.length <= PARETO_POINT_LIMIT) return eligible;
  const frontierCandidates = eligible.filter((candidate) =>
    front.has(candidate.properties.candidateId)
  );
  const otherCandidates = eligible
    .filter((candidate) => !front.has(candidate.properties.candidateId))
    .sort((left, right) =>
      left.properties.candidateId.localeCompare(right.properties.candidateId)
    );
  const capacity = Math.max(0, PARETO_POINT_LIMIT - frontierCandidates.length);
  if (capacity === 0) return frontierCandidates;
  if (otherCandidates.length <= capacity) return [...frontierCandidates, ...otherCandidates];
  if (capacity === 1) return [...frontierCandidates, otherCandidates[0]!];
  const sampled = Array.from({ length: capacity }, (_, index) =>
    otherCandidates[Math.round(index * (otherCandidates.length - 1) / (capacity - 1))]!
  );
  return [...frontierCandidates, ...sampled];
}

function selectCandidate(candidateId: string): void {
  state.selectedCandidateId = candidateId;
  state.activeTab = "evidence";
  renderAll();
}

function renderCandidateDetail(): void {
  const candidate = candidates.find((item) => item.properties.candidateId === state.selectedCandidateId);
  const title = requiredElement("candidate-title");
  const detail = requiredElement("candidate-detail");
  if (!candidate) {
    title.textContent = "Choose a corridor";
    detail.replaceChildren(create("p", { className: "help", text: "Select a portfolio row, map corridor, or trade-off point." }));
    return;
  }
  const metric = metricFor(candidate, state.scenario, state.purpose);
  const purposeDefinition = manifest.purposes.find((item) => item.id === state.purpose)!;
  const frontier = currentParetoFront();
  title.textContent = candidate.properties.name;
  const facts = create("dl", { className: "facts" });
  const factRows: Array<[string, string]> = [
    ["Facility", candidate.properties.facilityType],
    ["Programme", programmeLabel(candidate.properties.programmeStatus)],
    ["Capital cost screen", formatCost(metric.capitalCostNzd)],
    ["Lifecycle cost screen", formatCost(metric.lifecycleCostNzd)],
    [purposeDefinition.objectiveLabel, metric.available
      ? `${formatMetricValue(metric.objectiveValue ?? 0, metric.objectiveUnit)} ${metric.objectiveUnit}`
      : "Not available"],
    ["Additional commute cyclists", optionalNumber(metric.additionalCycleUsers)],
    ["Annual cycling distance", optionalNumber(metric.annualBikeKmDelta, " km")],
    ["CIW OD low-stress share", metric.odLowStressShareDelta === null
      ? "Not available"
      : `+${formatPercent(metric.odLowStressShareDelta, 2)}`],
    [manifest.capabilities.appraisal === "withheld" ? "Appraisal status" : "Indicative BCR", formatBcr(metric)],
    ["Pareto frontier", frontier.has(candidate.properties.candidateId) ? "Member" : "Not a member"],
    ["Exact network edges", String(candidate.properties.edgeIds.length)],
  ];
  for (const [term, value] of factRows) {
    facts.append(create("dt", { text: term }), create("dd", { text: value }));
  }
  const evidence = create("div", { className: "evidence-bars" });
  evidence.append(
    evidenceBar("Routed demand coverage", metric.routeCoverage),
    evidenceBar("Top-k inclusion", metric.topKProbability),
    evidenceBar("Pareto-frontier stability", metric.frontierProbability),
  );
  const warnings = create("ul", { className: "warning-list" });
  for (const warning of metric.warnings) warnings.append(create("li", { text: warning }));
  detail.replaceChildren(
    create("p", { className: "rationale", text: candidate.properties.rationale }),
    facts,
    create("h3", { text: "Evidence profile" }),
    evidence,
    create("p", {
      className: "help",
      text: `Mean uncertainty rank: ${metric.meanRank?.toFixed(1) ?? "not available"}. Values are conditional scenario screens, not causal forecasts.`,
    }),
    warnings,
  );
}

function evidenceBar(label: string, value: number | null): HTMLElement {
  const wrapper = create("div", { className: "evidence-row" });
  const header = create("div");
  header.append(
    create("span", { text: label }),
    create("strong", { text: value === null ? "Not available" : formatPercent(value, 0) }),
  );
  if (value === null) {
    wrapper.append(header);
    return wrapper;
  }
  const track = create("div", {
    className: "bar-track",
    role: "progressbar",
    "aria-label": label,
    "aria-valuemin": "0",
    "aria-valuemax": "100",
    "aria-valuenow": String(Math.round(value * 100)),
  });
  const fill = create("span", { className: "bar-fill" });
  fill.style.width = `${Math.round(value * 100)}%`;
  track.append(fill);
  wrapper.append(header, track);
  return wrapper;
}

function renderTabs(): void {
  document.querySelectorAll<HTMLButtonElement>("button.tab").forEach((button) => {
    const active = button.dataset.tab === state.activeTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  for (const id of ["portfolio", "pareto", "evidence"] as const) {
    const panel = requiredElement(`tab-${id}`);
    panel.classList.toggle("hidden", state.activeTab !== id);
    panel.hidden = state.activeTab !== id;
  }
}

function activateTab(tab: AppState["activeTab"], focus = false): void {
  state.activeTab = tab;
  renderTabs();
  if (tab === "pareto") renderPareto();
  if (tab === "evidence") renderCandidateDetail();
  syncQueryState();
  if (focus) {
    document.querySelector<HTMLButtonElement>(`button.tab[data-tab="${tab}"]`)?.focus();
  }
}

function handleTabKeydown(event: KeyboardEvent): void {
  const tabs = ["portfolio", "pareto", "evidence"] as const;
  const current = tabs.indexOf(state.activeTab);
  let next = current;
  if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
  else if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = tabs.length - 1;
  else return;
  event.preventDefault();
  activateTab(tabs[next]!, true);
}

function renderSketchControls(): void {
  const button = requiredElement<HTMLButtonElement>("sketch-toggle");
  const unavailable = manifest.capabilities.sketchEvaluation === "unavailable";
  button.disabled = unavailable;
  requiredElement("sketch-help").textContent = unavailable
    ? "Corridor sketch evaluation is unavailable for this run."
    : manifest.capabilities.sketchEvaluation === "same_pipeline"
      ? "Select points to route and evaluate a corridor through the same model pipeline."
      : "Select points on exported edges, then export the exact edge IDs for canonical pipeline evaluation.";
  button.textContent = state.sketching ? "Finish sketch" : "Start sketch";
  button.setAttribute("aria-pressed", String(state.sketching));
  document.body.classList.toggle("sketching", state.sketching);
  if (state.sketching) requiredElement<HTMLDetailsElement>("sketch-disclosure").open = true;
}

function renderSketch(result: SketchResult | null, error?: string): void {
  currentSketch = result;
  requiredElement<HTMLButtonElement>("download-button").disabled =
    selectedPortfolio().length === 0 && currentSketch === null;
  if (result) requiredElement<HTMLDetailsElement>("sketch-disclosure").open = true;
  desiredSketchNodeIds = result?.nodeIds ?? [];
  const panel = requiredElement("sketch-result");
  if (error) {
    panel.replaceChildren(create("p", { className: "error-text", text: error }));
    syncQueryState();
    return;
  }
  if (!result || result.edgeIds.length === 0) {
    panel.replaceChildren(create("p", { className: "help", text: "Choose at least two map points." }));
    syncQueryState();
    return;
  }
  const list = create("dl", { className: "mini-facts" });
  const sketchRows: Array<[string, string]> = [
    ["Length", `${result.lengthKm.toFixed(2)} km`],
    ["Capital screen", formatCost(result.capitalCostNzd)],
    ["Edge commute-activity attribute", compactNumber.format(result.dailyTripsDelta)],
  ];
  if (result.odLowStressShareDelta > 0) {
    sketchRows.push([
      "Edge connectivity attribute sum",
      formatPercent(result.odLowStressShareDelta, 2),
    ]);
  }
  for (const [label, value] of sketchRows) {
    list.append(create("dt", { text: label }), create("dd", { text: value }));
  }
  panel.replaceChildren(
    list,
    create("p", {
      className: "help",
      text:
        "Browser display sums exported edge attributes only; it is not a counterfactual, appraisal, " +
        "or uncertainty result. Export the exact edge IDs for canonical pipeline evaluation.",
    }),
  );
  syncQueryState();
}

function renderLegend(): void {
  const legend = requiredElement("map-legend-items");
  const items: Array<[string, string]> = [
    ["#08766c", "Higher purpose potential"],
    ["#007f73", "Existing protected network"],
    ["#0f5c6e", "Screened candidate"],
    ["#ea580c", "Selected or sketched corridor"],
    ["#a855f7", "Planned/funded programme"],
  ];
  replaceChildren(
    legend,
    items.map(([colour, label]) => {
      const row = create("div");
      const swatch = create("span", { className: "legend-swatch" });
      swatch.style.backgroundColor = colour;
      row.append(swatch, create("span", { text: label }));
      return row;
    }),
  );
}

function renderOverlayContext(): void {
  const panel = requiredElement("overlay-context");
  const notes: HTMLElement[] = [];
  if (state.visibleLayerIds.has("programmes")) {
    const programmeFeatures = layers.programmes?.features ?? [];
    const fundedCount = programmeFeatures.filter(
      (feature) => feature.properties.status === "funded",
    ).length;
    notes.push(
      create("p", {
        text:
          `Programmes · ${fundedCount} funded of ${programmeFeatures.length} shown` +
          (manifest.dataStatus === "synthetic_demo" ? " · synthetic fixture." : "."),
      }),
    );
  }
  if (state.visibleLayerIds.has("counters")) {
    const validation = manifest.validation;
    notes.push(
      create("p", {
        text:
          `Validation · ${validation.matchedCount}/${validation.counterCount} counter sites matched ` +
          `(${formatPercent(validation.coverage)}) · ${validation.periodLabel} · ` +
          `${validation.purposeAlignment}.`,
      }),
    );
  }
  replaceChildren(panel, notes);
  panel.hidden = notes.length === 0;
  if (notes.length) requiredElement<HTMLDetailsElement>("layers-disclosure").open = true;
}

async function copyViewLink(): Promise<void> {
  syncQueryState();
  try {
    await navigator.clipboard.writeText(window.location.href);
    setStatus("Shareable view link copied.");
  } catch {
    setStatus("The link is ready in the address bar; copy it from there.");
  }
}

async function resetView(): Promise<void> {
  window.history.replaceState(null, "", window.location.pathname);
  candidateFilter = "";
  requiredElement<HTMLInputElement>("candidate-search").value = "";
  currentSketch = null;
  await applyQueryState();
  setStatus("View reset to the published defaults.");
}

function downloadPortfolio(): void {
  const ids = new Set(selectedPortfolio().map((step) => step.candidateId));
  const collection = portfolioGeoJson(candidates, ids);
  for (const feature of collection.features) {
    const rawCandidateId = feature.properties.candidate_id;
    const candidateId =
      typeof rawCandidateId === "string" || typeof rawCandidateId === "number"
        ? String(rawCandidateId)
        : "";
    const candidate = candidates.find((item) => item.properties.candidateId === candidateId);
    if (!candidate) continue;
    const metric = metricFor(candidate, state.scenario, state.purpose);
    Object.assign(feature.properties, {
      scenario: state.scenario,
      purpose: state.purpose,
      capital_cost_nzd: metric.capitalCostNzd,
      lifecycle_cost_nzd: metric.lifecycleCostNzd,
      objective_value: metric.objectiveValue,
      objective_unit: metric.objectiveUnit,
      additional_cycle_users: metric.additionalCycleUsers,
      annual_cycle_km: metric.annualBikeKmDelta,
      od_low_stress_share_delta: metric.odLowStressShareDelta,
      indicative_bcr_p5: manifest.capabilities.appraisal === "withheld" ? null : metric.bcrP5,
      indicative_bcr_p50: manifest.capabilities.appraisal === "withheld" ? null : metric.bcrP50,
      indicative_bcr_p95: manifest.capabilities.appraisal === "withheld" ? null : metric.bcrP95,
    });
  }
  if (currentSketch) {
    collection.features.push({
      type: "Feature",
      geometry: { type: "MultiLineString", coordinates: currentSketch.coordinates },
      properties: {
        candidate_id: "user-sketch",
        name: "User corridor sketch",
        scenario: state.scenario,
        purpose: state.purpose,
        ordered_edge_ids: currentSketch.edgeIds,
        unique_edge_ids: currentSketch.uniqueEdgeIds,
        source_run_id: manifest.runId,
        model_version: manifest.modelVersion,
        config_sha256: manifest.configSha256,
        evaluation_status: "requires_pipeline_evaluation",
        preliminary_edge_capital_cost_nzd: currentSketch.capitalCostNzd,
        preliminary_edge_daily_trips_potential: currentSketch.dailyTripsDelta,
        preliminary_edge_od_low_stress_share_potential_sum: currentSketch.odLowStressShareDelta,
      },
    });
  }
  const exportCollection = {
    ...collection,
    ciw_export: {
      schema_version: manifest.schemaVersion,
      run_id: manifest.runId,
      model_version: manifest.modelVersion,
      config_sha256: manifest.configSha256,
      data_status: manifest.dataStatus,
      scenario: state.scenario,
      purpose: state.purpose,
      budget_nzd: state.budgetNzd,
      methodology_url: manifest.methodologyUrl,
      generated_at_utc: new Date().toISOString(),
    },
  };
  const blob = new Blob([JSON.stringify(exportCollection, null, 2)], {
    type: "application/geo+json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `ciw-${state.scenario}-${state.purpose}-${queryNumber(state.budgetNzd / 1_000_000)}m.geojson`;
  link.hidden = true;
  document.body.append(link);
  link.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 0);
}

async function applyQueryState(render = true): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  candidateFilter = "";
  candidateDisplayLimit = PORTFOLIO_PAGE_SIZE;
  state.scenario = manifest.defaultScenario;
  state.purpose = manifest.defaultPurpose;
  state.budgetNzd = manifest.defaultBudgetNzd;
  state.selectedCandidateId = null;
  state.activeTab = "portfolio";
  state.portfolioIds = new Set();
  state.sketching = false;
  state.visibleLayerIds = new Set(
    manifest.layers.filter((layer) => layer.defaultVisible).map((layer) => layer.id),
  );
  desiredSketchNodeIds = [];

  const scenario = params.get("scenario");
  const purpose = params.get("purpose");
  const tab = params.get("view");
  if (isScenarioId(scenario)) state.scenario = scenario;
  if (isPurposeId(purpose) && isPurposeAvailable(purpose)) state.purpose = purpose;
  if (isTab(tab)) state.activeTab = tab;
  if (params.has("budget")) {
    const budget = Number(params.get("budget"));
    if (Number.isFinite(budget) && budget >= 0) {
      state.budgetNzd = Math.min(budget * 1_000_000, manifest.maxBudgetNzd);
    }
  }
  if (params.has("layers")) {
    const validLayerIds = new Set(manifest.layers.map((layer) => layer.id));
    state.visibleLayerIds = new Set(
      (params.get("layers") ?? "")
        .split(",")
        .map((value) => value.trim())
        .filter((value) => validLayerIds.has(value as Manifest["layers"][number]["id"])),
    );
  }
  desiredSketchNodeIds = (params.get("sketch") ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .slice(0, 20);

  await ensureVisibleLayersLoaded();
  const candidate = params.get("candidate");
  if (candidate && candidates.some((item) => item.properties.candidateId === candidate)) {
    state.selectedCandidateId = candidate;
  }
  syncControlsFromState();
  if (render) {
    mapController.setLayers(layers);
    mapController.setSketchNodes(desiredSketchNodeIds);
    renderAll();
  }
}

async function ensureVisibleLayersLoaded(): Promise<void> {
  for (const layer of manifest.layers) {
    if (!state.visibleLayerIds.has(layer.id) || layers[layer.id as keyof LoadedLayers]) continue;
    try {
      layers[layer.id as keyof LoadedLayers] = await loadLayer(manifest, layer.id);
    } catch (error) {
      if (!layer.optional) throw error;
      state.visibleLayerIds.delete(layer.id);
      setStatus(
        error instanceof Error ? error.message : `The optional ${layer.label} layer is unavailable.`,
        true,
      );
    }
  }
  candidates = candidateFeatures(layers);
  paretoCache.clear();
}

function syncControlsFromState(): void {
  requiredElement<HTMLSelectElement>("scenario-select").value = state.scenario;
  requiredElement<HTMLSelectElement>("purpose-select").value = state.purpose;
  requiredElement<HTMLInputElement>("budget-slider").value = String(state.budgetNzd / 1_000_000);
  requiredElement<HTMLInputElement>("candidate-search").value = candidateFilter;
  for (const layer of manifest.layers) {
    requiredElement<HTMLInputElement>(`layer-${layer.id}`).checked = state.visibleLayerIds.has(layer.id);
  }
}

function syncQueryState(): void {
  const params = new URLSearchParams();
  params.set("scenario", state.scenario);
  params.set("purpose", state.purpose);
  params.set("view", state.activeTab);
  params.set("budget", queryNumber(state.budgetNzd / 1_000_000));
  // The public v1 runtime is deliberately basemap-free. An online tile provider
  // must not be enabled until its access and attribution terms are configured.
  params.set("offline", "1");
  const layerIds = manifest.layers
    .map((layer) => layer.id)
    .filter((layerId) => state.visibleLayerIds.has(layerId));
  params.set("layers", layerIds.join(","));
  if (state.selectedCandidateId) params.set("candidate", state.selectedCandidateId);
  if (desiredSketchNodeIds.length >= 2) params.set("sketch", desiredSketchNodeIds.join(","));
  const next = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState(null, "", next);
}

function setStatus(message: string, error = false): void {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer);
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", error);
  if (message && !error) {
    statusTimer = window.setTimeout(() => {
      statusMessage.textContent = "";
    }, 3500);
  }
}

function dataStatusName(dataStatus: Manifest["dataStatus"]): string {
  return {
    synthetic_demo: "Synthetic demo",
    research_snapshot: "Research snapshot",
    validated_release: "Validated release",
  }[dataStatus];
}

function programmeLabel(status: CandidateFeature["properties"]["programmeStatus"]): string {
  return {
    unprogrammed: "Unprogrammed",
    aligned: "Strategic alignment",
    funded: "Funded overlap",
    possible_duplicate: "Check overlap",
  }[status];
}

function currentSummary(): SummaryMetric {
  return manifest.summaries[state.scenario][state.purpose];
}

function isScenarioId(value: string | null): value is ScenarioId {
  return value !== null && manifest.scenarios.some((item) => item.id === value);
}

function isPurposeId(value: string | null): value is PurposeId {
  return value !== null && manifest.purposes.some((item) => item.id === value);
}

function isPurposeAvailable(value: PurposeId): boolean {
  if (value === "equity") return manifest.capabilities.equity === "available";
  if (value === "appraisal") return manifest.capabilities.appraisal !== "withheld";
  return true;
}

function isTab(value: string | null): value is AppState["activeTab"] {
  return value === "portfolio" || value === "pareto" || value === "evidence";
}

function budgetStep(maxBudgetNzd: number): number {
  if (maxBudgetNzd <= 10_000_000) return 0.1;
  if (maxBudgetNzd <= 50_000_000) return 1;
  return 5;
}

function queryNumber(value: number): string {
  return String(Number(value.toFixed(3)));
}

function formatDemand(value: number): string {
  return new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 1 }).format(value);
}

function axisCost(value: number): string {
  return `$${compactNumber.format(value)}`;
}

function formatMetricValue(value: number, unit: string): string {
  if (unit.toLowerCase().includes("share")) return formatPercent(value, 2);
  if (unit.toLowerCase().includes("bcr") || unit.toLowerCase().includes("ratio")) {
    return value.toFixed(2);
  }
  return compactNumber.format(value);
}

function optionalNumber(value: number | null, suffix = ""): string {
  return value === null ? "Not available" : `${compactNumber.format(value)}${suffix}`;
}

function formatBcr(metric: CandidateMetric): string {
  if (manifest.capabilities.appraisal === "withheld") {
    return "withheld — release inputs unresolved";
  }
  if (metric.bcrP5 === null || metric.bcrP50 === null || metric.bcrP95 === null) {
    return "not available";
  }
  return `${metric.bcrP50.toFixed(2)} (${metric.bcrP5.toFixed(2)}–${metric.bcrP95.toFixed(2)})`;
}

function metricPair(label: string, value: string): HTMLElement {
  const pair = create("span", { className: "metric-pair" });
  pair.append(create("small", { text: label }), create("span", { text: value }));
  return pair;
}

function requiredElement<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Required interface element is missing: ${id}`);
  return element as T;
}

function create<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string> & { text?: string; className?: string } = {},
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") element.textContent = value;
    else if (key === "className") element.className = value;
    else if (key === "htmlFor" && element instanceof HTMLLabelElement) element.htmlFor = value;
    else element.setAttribute(key, value);
  }
  return element;
}

function option(value: string, label: string): HTMLOptionElement {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function purposeOption(value: PurposeId, label: string): HTMLOptionElement {
  const item = option(value, label);
  if (!isPurposeAvailable(value)) {
    item.disabled = true;
    item.textContent = `${label} — withheld`;
  }
  return item;
}

function replaceChildren(parent: Element, children: Node[]): void {
  parent.replaceChildren(...children);
}

function svgElement(tag: string, attributes: Record<string, string | number>): SVGElement {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "textContent") element.textContent = String(value);
    else element.setAttribute(key, String(value));
  }
  return element;
}

function svgText(x: number, y: number, text: string, className: string): SVGElement {
  return svgElement("text", { x, y, class: className, "text-anchor": "middle", textContent: text });
}
