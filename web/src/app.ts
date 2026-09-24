import "./style.css";
import { ConnectedJourneys, CONNECTED_QUERY_KEYS } from "./connected";

import { GOALS, SCENARIOS, dataStatusName, money, snapshotDate, withNewName } from "./copy";
import { candidateFeatures, loadDefaultLayers, loadLayer, loadManifest } from "./data";
import { create, requiredElement } from "./dom";
import { loadDemandDiagnostics, type DemandDiagnostics } from "./diagnostics";
import { DEFAULT_JOURNEY_ASSUMPTIONS, journeyAssumptionsFromQuery } from "./journeys";
import { BASEMAP_IDS, SpanMap, type BasemapId, type MapPadding } from "./map";
import { connectedGroups, metricFor, packageKey, paretoFront, portfolioAtBudget, portfolioGeoJson, type SketchResult } from "./model";
import { purposeIds, type AppState, type CandidateFeature, type LoadedLayers, type Manifest, type PortfolioStep, type PurposeId, type ScenarioId } from "./types";
import {
  renderBuildList,
  renderGoalPicker,
  renderHero,
  renderLayerControls,
  renderLegend,
  renderLinkCard,
  renderMethodNote,
  renderNotes,
  renderNetworkGroups,
  renderPareto,
  renderSketchResult,
  type ViewContext,
} from "./views";

const PAGE_SIZE = 100;
const app = requiredElement("app");
const statusMessage = requiredElement("status-message");
const loadingPanel = requiredElement("loading-panel");
const panelToggle = requiredElement<HTMLButtonElement>("panel-toggle");
let manifest: Manifest;
let layers: LoadedLayers;
let candidates: CandidateFeature[] = [];
let byId = new Map<string, CandidateFeature>();
let currentSketch: SketchResult | null = null;
let desiredSketchNodeIds: string[] = [];
let filter = "";
let limit = PAGE_SIZE;
let statusTimer: number | undefined;
let budgetTimer: number | undefined;
const paretoCache = new Map<string, Set<string>>();
let state: AppState;
let ready = false;
let connected: ConnectedJourneys;
let journeyAssumptions = { ...DEFAULT_JOURNEY_ASSUMPTIONS };
let demandDiagnostics: DemandDiagnostics | undefined;
const offlineMode = new URLSearchParams(window.location.search).get("offline") === "1";

const mapController = new SpanMap(requiredElement("map"), {
  onCandidateSelected: (candidateId) => selectCandidate(candidateId, false),
  onSketchChanged: (result, error) => onSketch(result, error),
  onBasemapChanged: () => {
    renderBasemapControls();
    if (ready) syncQueryState();
  },
}, {
  allowHostedBasemaps: !offlineMode,
  initialBasemap: offlineMode ? "analysis" : basemapId(new URLSearchParams(window.location.search).get("basemap")) ?? "light",
  padding: mapPadding,
});

setPanelOpen(true);
void initialise();

async function initialise(): Promise<void> {
  try {
    manifest = await loadManifest();
    layers = await loadDefaultLayers(manifest);
    setCandidates();
    state = initialState(manifest);
    connected = new ConnectedJourneys(mapController, manifest);
    ready = true;
    populateControls();
    await applyQueryState(false);
    bindEvents();
    mapController.setData(layers, candidates);
    mapController.setSketchNodes(desiredSketchNodeIds);
    renderAll();
    loadingPanel.hidden = true;
    app.setAttribute("aria-busy", "false");
    void loadDemandDiagnostics(manifest).then((diagnostics) => {
      demandDiagnostics = diagnostics;
      renderLinkCard(context());
    });
  } catch (error) {
    app.setAttribute("aria-busy", "false");
    const message = error instanceof Error ? error.message : "The data could not be loaded.";
    statusMessage.textContent = message;
    statusMessage.classList.add("error");
    loadingPanel.classList.add("error");
    loadingPanel.replaceChildren(
      create("strong", { text: "The data could not be loaded" }),
      create("span", { text: message }),
      create("span", { text: "Check that the data folder is present, then reload the page." }),
    );
  }
}

function setCandidates(): void {
  candidates = candidateFeatures(layers);
  byId = new Map(candidates.map((candidate) => [candidate.properties.candidateId, candidate]));
  paretoCache.clear();
}

function defaultLayers(data: Manifest): Set<string> {
  // The other 12,000-odd links are off to start with, so the build order reads clearly.
  return new Set(data.layers.filter((layer) => layer.defaultVisible && layer.id !== "candidates").map((layer) => layer.id));
}

function initialState(data: Manifest): AppState {
  return {
    scenario: data.defaultScenario,
    purpose: data.defaultPurpose,
    budgetNzd: data.defaultBudgetNzd,
    selectedCandidateId: null,
    visibleLayerIds: defaultLayers(data),
    portfolioIds: new Set(),
    activeTab: "portfolio",
    sketching: false,
    focusedGroupIds: new Set(),
  };
}

function populateControls(): void {
  requiredElement<HTMLDetailsElement>("map-legend").open = !window.matchMedia("(max-width: 760px)").matches;
  const scenarioSelect = requiredElement<HTMLSelectElement>("scenario-select");
  scenarioSelect.replaceChildren(...manifest.scenarios.map((scenario) => {
    const item = create("option", { value: scenario.id, text: SCENARIOS[scenario.id].label });
    return item;
  }));
  const budget = requiredElement<HTMLInputElement>("budget-slider");
  budget.step = String(budgetStep(manifest.maxBudgetNzd));
  budget.max = queryNumber(manifest.maxBudgetNzd / 1_000_000);
  requiredElement("budget-maximum").textContent = money(manifest.maxBudgetNzd);
  renderLayerControls(requiredElement("layer-controls"), manifest, state.visibleLayerIds);
  renderBasemapControls();
}

function bindEvents(): void {
  requiredElement("journey-controls").addEventListener("change", () => {
    const days = requiredElement<HTMLInputElement>("journey-days");
    if (!days.reportValidity() || days.value === "") return;
    journeyAssumptions = journeyAssumptionsFromQuery(new URLSearchParams({
      journeys: requiredElement<HTMLSelectElement>("journey-period").value,
      cyclingDays: days.value,
      journeyLegs: requiredElement<HTMLSelectElement>("journey-legs").value,
    }));
    renderAll();
  });
  requiredElement<HTMLSelectElement>("scenario-select").addEventListener("change", (event) => {
    state.scenario = (event.currentTarget as HTMLSelectElement).value as ScenarioId;
    resetList();
    renderAll();
    mapController.fitBuildOrder();
  });
  requiredElement("purpose-picker").addEventListener("keydown", handleGoalKeydown);
  requiredElement<HTMLInputElement>("budget-slider").addEventListener("input", (event) => {
    const input = event.currentTarget as HTMLInputElement;
    state.budgetNzd = Math.min(Number(input.value) * 1_000_000, manifest.maxBudgetNzd);
    limit = PAGE_SIZE;
    requiredElement("budget-output").textContent = money(state.budgetNzd);
    input.setAttribute("aria-valuetext", money(state.budgetNzd));
    if (budgetTimer !== undefined) window.clearTimeout(budgetTimer);
    budgetTimer = window.setTimeout(() => renderAll(), 120);
  });
  requiredElement<HTMLInputElement>("candidate-search").addEventListener("input", (event) => {
    filter = (event.currentTarget as HTMLInputElement).value.trim().toLocaleLowerCase("en-NZ");
    limit = PAGE_SIZE;
    renderBuildList(context(), filter, limit);
  });
  requiredElement("show-more-button").addEventListener("click", () => {
    limit += PAGE_SIZE;
    renderBuildList(context(), filter, limit);
  });
  requiredElement("layer-controls").addEventListener("change", (event) => void handleLayerToggle(event));
  requiredElement("sketch-toggle").addEventListener("click", () => void toggleSketch());
  requiredElement("sketch-clear").addEventListener("click", () => mapController.clearSketch());
  requiredElement("download-button").addEventListener("click", downloadBuildOrder);
  requiredElement("share-button").addEventListener("click", () => void copyViewLink());
  requiredElement("reset-button").addEventListener("click", () => void resetView());
  requiredElement("print-button").addEventListener("click", () => window.print());
  requiredElement("programme-zoom").addEventListener("click", () => mapController.fitBuildOrder());
  requiredElement("link-close").addEventListener("click", closeCard);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !state.selectedCandidateId) return;
    if (requiredElement<HTMLDialogElement>("map-info-dialog").open) return;
    if (event.target instanceof HTMLInputElement && event.target.type === "search" && event.target.value) return;
    closeCard();
  });
  requiredElement("basemap-switcher").addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest<HTMLButtonElement>("button[data-basemap]");
    const selected = basemapId(button?.dataset.basemap ?? null);
    if (button && selected && !button.disabled) mapController.setBasemap(selected);
  });
  bindAboutDialog();
  panelToggle.addEventListener("click", () => setPanelOpen(document.body.dataset.panel === "collapsed"));
  document.querySelectorAll<HTMLButtonElement>("button.tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab as AppState["activeTab"]));
    button.addEventListener("keydown", handleTabKeydown);
  });
  window.addEventListener("popstate", () => void applyQueryState());
}

function resetList(): void {
  filter = "";
  limit = PAGE_SIZE;
  requiredElement<HTMLInputElement>("candidate-search").value = "";
}

function setPurpose(purpose: PurposeId): void {
  if (purpose === state.purpose || !isPurposeAvailable(purpose)) return;
  state.purpose = purpose;
  if (purpose === "appraisal" && state.scenario !== "commute_8pct") {
    state.scenario = "commute_8pct";
    setStatus("Benefit–cost ratios are only worked out for the 8% scenario, so the scenario has changed to 8% of commutes.");
  }
  resetList();
  renderAll();
  mapController.fitBuildOrder();
}

function handleGoalKeydown(event: KeyboardEvent): void {
  const order = purposeIds.filter(isPurposeAvailable);
  const current = order.indexOf(state.purpose);
  let next = current;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (current + 1) % order.length;
  else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (current - 1 + order.length) % order.length;
  else return;
  event.preventDefault();
  setPurpose(order[next]!);
  document.querySelector<HTMLButtonElement>(`#purpose-picker [data-purpose="${order[next]!}"]`)?.focus();
}

async function handleLayerToggle(event: Event): Promise<void> {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || !input.dataset.layerId) return;
  const layerId = input.dataset.layerId;
  if (input.checked) {
    state.visibleLayerIds.add(layerId);
    if (!layers[layerId as keyof LoadedLayers]) {
      setStatus(layerId === "network" ? "Loading the street network. This is a large file." : "Loading…");
      try {
        layers[layerId as keyof LoadedLayers] = await loadLayer(manifest, layerId);
        mapController.setData(layers, candidates);
        setStatus("");
      } catch (error) {
        state.visibleLayerIds.delete(layerId);
        input.checked = false;
        setStatus(error instanceof Error ? error.message : "That layer could not be loaded.", true);
      }
    }
  } else {
    state.visibleLayerIds.delete(layerId);
  }
  renderAll();
}

async function ensureNetwork(): Promise<void> {
  if (layers.network) return;
  setStatus("Loading the street network. This is a large file.");
  layers.network = await loadLayer(manifest, "network");
  mapController.setData(layers, candidates);
  setStatus("");
}

function selectedSteps(): PortfolioStep[] {
  return portfolioAtBudget(manifest, state.scenario, state.purpose, state.budgetNzd);
}

function context(steps = selectedSteps()): ViewContext {
  return {
    journeyAssumptions,
    demandDiagnostics,
    manifest,
    state,
    byId,
    steps,
    sequence: manifest.portfolios[state.scenario][state.purpose],
    front: currentFront,
    select: (candidateId) => selectCandidate(candidateId, true),
    zoom: (candidateId) => mapController.focusCandidate(candidateId),
    focusGroup: (ids) => {
      state.selectedCandidateId = ids.includes(state.selectedCandidateId ?? "") ? state.selectedCandidateId : ids[0] ?? null;
      state.focusedGroupIds = new Set(ids);
      renderAll();
      window.requestAnimationFrame(() => mapController.focusCandidates(ids));
    },
    packageEvaluation: (ids) => {
      const key = packageKey(ids);
      return manifest.networkContext?.packages.find((item) => item.scenario === state.scenario && packageKey(item.candidateIds) === key);
    },
  };
}

function renderAll(): void {
  requiredElement("journey-controls").hidden = !GOALS[state.purpose].commute;
  const steps = selectedSteps();
  state.portfolioIds = new Set(steps.map((step) => step.candidateId));
  if (state.focusedGroupIds.size) {
    const groups = connectedGroups(steps.flatMap((step) => byId.get(step.candidateId) ?? []));
    const group = groups.find((items) => items.some((item) => item.properties.candidateId === state.selectedCandidateId));
    state.focusedGroupIds = new Set(group?.map((item) => item.properties.candidateId) ?? []);
  }
  const ctx = context(steps);
  const goal = GOALS[state.purpose];
  renderGoalPicker(requiredElement("purpose-picker"), state.purpose, isPurposeAvailable, setPurpose, purposeIds);
  renderNotes(ctx);
  const scenarioSelect = requiredElement<HTMLSelectElement>("scenario-select");
  scenarioSelect.value = state.scenario;
  scenarioSelect.disabled = !goal.commute || state.purpose === "appraisal";
  requiredElement("budget-output").textContent = money(state.budgetNzd);
  requiredElement<HTMLInputElement>("budget-slider").setAttribute("aria-valuetext", money(state.budgetNzd));
  requiredElement("lede").textContent = "Compare cycling upgrades: what to build, what they connect and what they could change.";
  renderHero(requiredElement("portfolio-summary"), ctx);
  renderNetworkGroups(ctx);
  renderBuildList(ctx, filter, limit);
  renderMethodNote(requiredElement("connectivity-context"), ctx);
  if (state.activeTab === "pareto") renderPareto(ctx);
  renderLinkCard(ctx);
  document.body.dataset.card = state.selectedCandidateId && byId.has(state.selectedCandidateId) ? "open" : "closed";
  mapController.update(state, steps);
  renderLegend(requiredElement("map-legend-items"), ctx, {
    breaks: mapController.demandBreaks,
    empty: mapController.demandEmpty,
  });
  renderSketchControls();
  renderFooter(steps);
  requiredElement<HTMLButtonElement>("download-button").disabled = steps.length === 0 && currentSketch === null;
  syncQueryState();
  requiredElement("view-announcement").textContent =
    `${goal.chip}, ${SCENARIOS[state.scenario].label}, ${money(state.budgetNzd)} budget: ` +
    `${String(steps.length)} ${steps.length === 1 ? "link" : "links"} in the build order.`;
  renderTabs();
}

function renderFooter(steps: PortfolioStep[]): void {
  const status = requiredElement("data-status");
  status.textContent = dataStatusName(manifest.dataStatus);
  status.className = `data-status ${manifest.dataStatus}`;
  requiredElement("run-summary").textContent = `Data of ${snapshotDate(manifest.generatedAtUtc)} · ${manifest.runId}`;
  requiredElement("map-provenance-text").textContent =
    `${withNewName(manifest.dataStatusLabel)}. Run ${manifest.runId}, model ${manifest.modelVersion}.`;
  requiredElement("attribution").replaceChildren(
    ...manifest.attribution.map((line) => create("li", { text: withNewName(line) })),
  );
  requiredElement<HTMLAnchorElement>("methodology-link").href = manifest.methodologyUrl;
  const last = steps.at(-1);
  requiredElement("mobile-map-status").textContent = last
    ? `${GOALS[state.purpose].chip} · ${String(steps.length)} links · ${money(last.cumulativeCostNzd)}`
    : `${GOALS[state.purpose].chip} · no links within ${money(state.budgetNzd)}`;
}

function currentFront(): Set<string> {
  const key = `${state.scenario}|${state.purpose}`;
  const cached = paretoCache.get(key);
  if (cached) return cached;
  const front = paretoFront(candidates, state.scenario, state.purpose);
  paretoCache.set(key, front);
  return front;
}

function selectCandidate(candidateId: string, focusMap: boolean): void {
  if (!byId.has(candidateId)) return;
  state.selectedCandidateId = candidateId;
  state.focusedGroupIds.clear();
  renderAll();
  if (focusMap) window.requestAnimationFrame(() => mapController.focusCandidate(candidateId));
}

function closeCard(): void {
  const id = state.selectedCandidateId;
  state.selectedCandidateId = null;
  state.focusedGroupIds.clear();
  renderAll();
  if (id) document.querySelector<HTMLButtonElement>(`#candidate-list [data-candidate-id="${CSS.escape(id)}"]`)?.focus();
}

function renderTabs(): void {
  document.querySelectorAll<HTMLButtonElement>("button.tab").forEach((button) => {
    const active = button.dataset.tab === state.activeTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  for (const id of ["portfolio", "pareto", "connected"] as const) requiredElement(`tab-${id}`).hidden = state.activeTab !== id;
  const journeyView = state.activeTab === "connected";
  requiredElement("map").setAttribute("aria-label", journeyView ? "Whole journey and required upgrades" : "Map of candidate cycling links in Auckland");
  for (const id of ["ranking-controls", "sketch-disclosure", "layers-disclosure"]) requiredElement(id).hidden = journeyView;
  if (journeyView) {
    requiredElement("link-card").hidden = true;
    document.body.dataset.card = "closed";
    requiredElement("lede").textContent = "Which upgrades are needed to make a whole journey work?";
    const key = requiredElement("map-legend-items");
    key.replaceChildren(...[["#ea580c", "Funded upgrade"], ["#b42318", "Unfunded gap (red dashes)"], ["#1f7a4d", "Existing cycleway / path"], ["#9aa5ab", "Other usable street"]].map(([colour, label], index) => {
      const row = create("p", { className: "connected-key", "data-route-only": String(index > 0) });
      const swatch = create("i"); swatch.style.backgroundColor = colour!;
      row.append(swatch, document.createTextNode(label!)); return row;
    }), create("p", { id: "connected-map-caption", className: "help", text: "A → B: whole journey. Dashed orange: rest of the upgrade." }));
  }
  const download = requiredElement<HTMLButtonElement>("download-button");
  download.textContent = journeyView ? "Download package and route (GeoJSON)" : "Download build order (GeoJSON)";
  if (journeyView) download.disabled = !connected.canExport;
  connected.setActive(journeyView);
}

function activateTab(tab: AppState["activeTab"], focus = false): void {
  state.activeTab = tab;
  if (tab === "connected") state.sketching = false;
  renderAll();
  if (focus) document.querySelector<HTMLButtonElement>(`button.tab[data-tab="${tab}"]`)?.focus();
}

function handleTabKeydown(event: KeyboardEvent): void {
  const tabs = ["portfolio", "pareto", "connected"] as const;
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

async function toggleSketch(): Promise<void> {
  if (!state.sketching) {
    try {
      await ensureNetwork();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The street network could not be loaded.", true);
      return;
    }
  }
  state.sketching = !state.sketching;
  renderSketchControls();
  mapController.update(state, selectedSteps());
}

function renderSketchControls(): void {
  const button = requiredElement<HTMLButtonElement>("sketch-toggle");
  const capability = manifest.capabilities.sketchEvaluation;
  button.disabled = capability === "unavailable";
  requiredElement("sketch-help").textContent = capability === "unavailable"
    ? "Drawing is not available for this run."
    : capability === "same_pipeline"
      ? "Click points on the map. SPAN joins them along the street network and runs the result through the model."
      : "Click points on the map. SPAN joins them along the street network and gives the length and a rough cost.";
  button.textContent = state.sketching ? "Finish drawing" : "Start drawing";
  button.setAttribute("aria-pressed", String(state.sketching));
  document.body.classList.toggle("sketching", state.sketching);
  if (state.sketching) requiredElement<HTMLDetailsElement>("sketch-disclosure").open = true;
}

function onSketch(result: SketchResult | null, error?: string): void {
  currentSketch = result;
  desiredSketchNodeIds = result?.nodeIds ?? [];
  renderSketchResult(requiredElement("sketch-result"), result, error);
  if (result) requiredElement<HTMLDetailsElement>("sketch-disclosure").open = true;
  if (!ready) return;
  requiredElement<HTMLButtonElement>("download-button").disabled = selectedSteps().length === 0 && result === null;
  syncQueryState();
}

async function copyViewLink(): Promise<void> {
  syncQueryState();
  try {
    await navigator.clipboard.writeText(window.location.href);
    setStatus("Link to this view copied.");
  } catch {
    setStatus("Copy the link from the address bar.");
  }
}

async function resetView(): Promise<void> {
  window.history.replaceState(null, "", window.location.pathname);
  currentSketch = null;
  resetList();
  await applyQueryState();
  mapController.fitBuildOrder();
  setStatus("Reset to the starting view.");
}

function downloadBuildOrder(): void {
  if (state.activeTab === "connected") { connected.download(); return; }
  const collection = portfolioGeoJson(candidates, new Set(selectedSteps().map((step) => step.candidateId)));
  const rank = new Map(selectedSteps().map((step) => [step.candidateId, step]));
  for (const feature of collection.features) {
    const id = String(feature.properties.candidate_id);
    const candidate = byId.get(id);
    if (!candidate) continue;
    const metric = metricFor(candidate, state.scenario, state.purpose);
    const withheld = manifest.capabilities.appraisal === "withheld";
    Object.assign(feature.properties, {
      build_order: rank.get(id)?.step ?? null,
      marginal_objective: rank.get(id)?.marginalObjective ?? null,
      scenario: state.scenario,
      purpose: state.purpose,
      capital_cost_nzd: metric.capitalCostNzd,
      lifecycle_cost_nzd: metric.lifecycleCostNzd,
      objective_value: metric.objectiveValue,
      objective_unit: metric.objectiveUnit,
      additional_cycle_users: metric.additionalCycleUsers,
      annual_cycle_km: metric.annualBikeKmDelta,
      od_low_stress_share_delta: metric.odLowStressShareDelta,
      indicative_bcr_p5: withheld ? null : metric.bcrP5,
      indicative_bcr_p50: withheld ? null : metric.bcrP50,
      indicative_bcr_p95: withheld ? null : metric.bcrP95,
    });
  }
  if (currentSketch) {
    collection.features.push({
      type: "Feature",
      geometry: { type: "MultiLineString", coordinates: currentSketch.coordinates },
      properties: {
        candidate_id: "user-sketch",
        name: "Drawn link",
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
  const exported = {
    ...collection,
    span_export: {
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
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(exported, null, 2)], { type: "application/geo+json" }));
  link.download = `span-${state.scenario}-${state.purpose}-${queryNumber(state.budgetNzd / 1_000_000)}m.geojson`;
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
  journeyAssumptions = journeyAssumptionsFromQuery(params);
  requiredElement<HTMLSelectElement>("journey-period").value = journeyAssumptions.period;
  requiredElement<HTMLInputElement>("journey-days").value = String(journeyAssumptions.daysPerYear);
  requiredElement<HTMLSelectElement>("journey-legs").value = String(journeyAssumptions.legsPerDay);
  resetList();
  Object.assign(state, initialState(manifest));
  desiredSketchNodeIds = [];
  mapController.setBasemap(offlineMode ? "analysis" : basemapId(params.get("basemap")) ?? "light", false);
  renderBasemapControls();
  const scenario = params.get("scenario");
  const purpose = params.get("purpose");
  const tab = params.get("view");
  if (isScenarioId(scenario)) state.scenario = scenario;
  if (isPurposeId(purpose) && isPurposeAvailable(purpose)) state.purpose = purpose;
  if (state.purpose === "appraisal") state.scenario = "commute_8pct";
  if (tab === "portfolio" || tab === "pareto" || tab === "connected") state.activeTab = tab;
  if (params.has("budget")) {
    const budget = Number(params.get("budget"));
    if (Number.isFinite(budget) && budget >= 0) state.budgetNzd = Math.min(budget * 1_000_000, manifest.maxBudgetNzd);
  }
  if (params.has("layers")) {
    const valid = new Set<string>(manifest.layers.map((layer) => layer.id));
    state.visibleLayerIds = new Set((params.get("layers") ?? "").split(",").map((value) => value.trim()).filter((value) => valid.has(value)));
  }
  desiredSketchNodeIds = (params.get("sketch") ?? "").split(",").map((value) => value.trim()).filter(Boolean).slice(0, 20);
  await ensureVisibleLayersLoaded();
  if (desiredSketchNodeIds.length >= 2) {
    try {
      await ensureNetwork();
    } catch (error) {
      desiredSketchNodeIds = [];
      setStatus(error instanceof Error ? error.message : "The street network could not be loaded.", true);
    }
  }
  const candidate = params.get("candidate");
  if (candidate && byId.has(candidate)) state.selectedCandidateId = candidate;
  syncControlsFromState();
  if (render) {
    mapController.setData(layers, candidates);
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
      setStatus(error instanceof Error ? error.message : "A map layer could not be loaded.", true);
    }
  }
  setCandidates();
}

function syncControlsFromState(): void {
  requiredElement<HTMLSelectElement>("scenario-select").value = state.scenario;
  requiredElement<HTMLInputElement>("budget-slider").value = String(state.budgetNzd / 1_000_000);
  requiredElement<HTMLInputElement>("candidate-search").value = filter;
  for (const layer of manifest.layers) {
    requiredElement<HTMLInputElement>(`layer-${layer.id}`).checked = state.visibleLayerIds.has(layer.id);
  }
}

function syncQueryState(): void {
  const params = new URLSearchParams();
  const previous = new URLSearchParams(window.location.search);
  for (const key of CONNECTED_QUERY_KEYS) { const value = previous.get(key); if (value !== null) params.set(key, value); }
  params.set("journeys", journeyAssumptions.period);
  params.set("cyclingDays", String(journeyAssumptions.daysPerYear));
  params.set("journeyLegs", String(journeyAssumptions.legsPerDay));
  params.set("scenario", state.scenario);
  params.set("purpose", state.purpose);
  params.set("view", state.activeTab);
  params.set("budget", queryNumber(state.budgetNzd / 1_000_000));
  if (offlineMode) params.set("offline", "1");
  else params.set("basemap", mapController.activeBasemap);
  params.set("layers", manifest.layers.map((layer) => layer.id).filter((id) => state.visibleLayerIds.has(id)).join(","));
  if (state.selectedCandidateId) params.set("candidate", state.selectedCandidateId);
  if (desiredSketchNodeIds.length >= 2) params.set("sketch", desiredSketchNodeIds.join(","));
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

function renderBasemapControls(): void {
  document.querySelectorAll<HTMLButtonElement>("button[data-basemap]").forEach((button) => {
    const id = basemapId(button.dataset.basemap ?? null);
    const active = id === mapController.activeBasemap;
    const unavailable = offlineMode && id !== "analysis";
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.disabled = unavailable;
    if (unavailable) button.title = "Background maps are off in the offline view.";
    else button.removeAttribute("title");
  });
}

/** Room the map keeps clear for the panel and the link card when it fits or flies. */
function mapPadding(): MapPadding {
  const panel = requiredElement("controls-panel").getBoundingClientRect();
  const card = requiredElement("link-card");
  if (window.matchMedia("(max-width: 760px)").matches) {
    const sheet = card.hidden ? panel : card.getBoundingClientRect();
    return { topLeft: [24, 72], bottomRight: [24, Math.max(24, Math.round(window.innerHeight - sheet.top) + 16)] };
  }
  const cardWidth = card.hidden ? 0 : card.getBoundingClientRect().width;
  return { topLeft: [Math.round(panel.right) + 24, 72], bottomRight: [cardWidth ? Math.round(cardWidth) + 48 : 72, 48] };
}

function setPanelOpen(open: boolean): void {
  document.body.dataset.panel = open ? "open" : "collapsed";
  panelToggle.setAttribute("aria-expanded", String(open));
  panelToggle.setAttribute("aria-label", open ? "Hide controls" : "Show controls");
}

function bindAboutDialog(): void {
  const button = requiredElement<HTMLButtonElement>("map-info-button");
  const dialog = requiredElement<HTMLDialogElement>("map-info-dialog");
  const closeButton = requiredElement<HTMLButtonElement>("map-info-close");
  button.addEventListener("click", () => {
    button.setAttribute("aria-expanded", "true");
    dialog.showModal();
    closeButton.focus();
  });
  closeButton.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
      dialog.close();
    }
  });
  dialog.addEventListener("close", () => {
    button.setAttribute("aria-expanded", "false");
    button.focus();
  });
}

function setStatus(message: string, error = false): void {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer);
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", error);
  if (message && !error) statusTimer = window.setTimeout(() => (statusMessage.textContent = ""), 4000);
}

function basemapId(value: string | null): BasemapId | null {
  return BASEMAP_IDS.find((candidate) => candidate === value) ?? null;
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

function budgetStep(maxBudgetNzd: number): number {
  if (maxBudgetNzd <= 10_000_000) return 0.1;
  if (maxBudgetNzd <= 50_000_000) return 1;
  return 5;
}

function queryNumber(value: number): string {
  return String(Number(value.toFixed(3)));
}
