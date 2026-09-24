import { amount, money } from "./copy";
import { create, requiredElement } from "./dom";
import type { SpanMap } from "./map";
import { portfolioGeoJson, reportSchema, type ResearchReport, type ResearchRoute, type ResearchSolution } from "./research-data";
import type { Manifest } from "./types";

export const CONNECTED_QUERY_KEYS = ["areaBudget", "method", "journey", "preference", "route", "extent"] as const;

/** Complete-route results share SPAN's map, basemaps and workspace. */
export class ConnectedJourneys {
  private active = false;
  private loading: Promise<void> | undefined;
  private report: ResearchReport | undefined;
  private solution: ResearchSolution | undefined;
  private route: ResearchRoute | undefined;
  private alternativeContext = "";
  private mapExtent: "route" | "package" = "route";
  private budget = requiredElement<HTMLSelectElement>("connected-budget");
  private method = requiredElement<HTMLSelectElement>("connected-method");
  private journey = requiredElement<HTMLSelectElement>("connected-journey");
  private preference = requiredElement<HTMLSelectElement>("connected-preference");
  private alternative = requiredElement<HTMLSelectElement>("connected-alternative");

  constructor(private map: SpanMap, private manifest: Manifest) {}
  get canExport(): boolean { return this.solution !== undefined; }

  setActive(active: boolean): void {
    this.active = active;
    this.map.setConnectedMode(active);
    if (!active) return;
    if (!this.loading) this.loading = this.load();
    else if (this.report) this.restoreQuery();
  }

  private async load(): Promise<void> {
    const status = requiredElement("connected-status");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}data/access-experiment.json`);
      if (!response.ok) throw new Error("Connected-journey results are not available in this release. The other SPAN views are still available.");
      const report = reportSchema.parse(await response.json());
      if (report.runId !== this.manifest.runId || (this.manifest.effectiveNetwork && report.sourceHashes.topology !== this.manifest.effectiveNetwork.topologySha256)) throw new Error("Journey results belong to a different data release and have not been shown. Reload after the site data is updated.");
      this.report = report;
      const budgets = [...new Set(report.solutions.map(s => s.budget))].sort((a, b) => a - b);
      this.budget.replaceChildren(...budgets.map(value => create("option", { value: String(value), text: money(value) })));
      this.budget.value = String(budgets.at(-1));
      for (const option of this.method.options) option.disabled = !report.solutions.some(s => s.method === option.value);
      this.preference.append(...report.assignment.profiles.map(p => create("option", { value: p.id, text: { direct: "Shortest and quickest", balanced: "Some preference for cycle facilities", comfort: "Stronger preference for cycle facilities" }[p.id] ?? p.label })));
      this.journey.replaceChildren(...report.journeys.map(j => create("option", { value: j.name, text: j.name })));
      const funded = report.solutions.find(s => s.budget === Number(this.budget.value) && s.method === this.method.value)?.selected ?? [];
      this.journey.value = report.journeys.filter(j => j.alternatives.some(r => r.projectIds.length > 0 && r.projectIds.every(p => funded.includes(p)))).sort((a, b) => b.weight - a.weight)[0]?.name ?? report.journeys[0]?.name ?? "";
      for (const control of [this.budget, this.method, this.journey, this.preference, this.alternative]) control.addEventListener("change", () => {
        if (control === this.journey || control === this.preference || control === this.alternative) this.mapExtent = "route";
        this.render();
      });
      requiredElement("connected-zoom").addEventListener("click", () => { this.mapExtent = "route"; this.render(); });
      requiredElement("connected-package-map").addEventListener("click", () => { this.mapExtent = this.mapExtent === "package" ? "route" : "package"; this.render(); });
      status.textContent = `${report.sample.selected} sample journeys · ${report.graph.projects} possible upgrades`;
      requiredElement("connected-controls").hidden = false;
      requiredElement("connected-coverage").textContent = `${report.sample.selected} of ${report.sample.eligibleWithinArea} eligible journeys in this area were sampled. ${report.searchComplete ? "All sampled searches finished within their limit." : "Some searches hit their limit; routes may be missing."} This sample does not represent all Auckland travel.`;
      requiredElement("connected-standard").textContent = `Routes must stay at traffic stress ${report.standard.maximum_stress} or below (out of 4), be no more than ${report.standard.maximum_detour} times the shortest legal distance and take no more than ${report.standard.maximum_time_s / 60} minutes.`;
      requiredElement("connected-provenance").textContent = `Data release ${report.runId}; area radius ${report.radiusM / 1000} km. ${report.intersectionContext ? `Assumed waits at ${report.intersectionContext.sitesInCrop} matched intersections (${report.intersectionContext.scenario} case); not measured traffic-light timings.` : "No intersection-delay evidence is included."}`;
      if (this.active) this.restoreQuery();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "Journey results could not be loaded.";
      status.classList.add("error-text");
    }
  }

  private restoreQuery(): void {
    const params = new URLSearchParams(window.location.search);
    this.mapExtent = params.get("extent") === "package" ? "package" : "route";
    for (const [key, control] of [["areaBudget", this.budget], ["method", this.method], ["journey", this.journey], ["preference", this.preference]] as const) {
      const value = params.get(key);
      if (value !== null && [...control.options].some(o => o.value === value && !o.disabled)) control.value = value;
    }
    this.render(params.get("route"));
  }

  private render(requestedRoute: string | null = null): void {
    if (!this.active || !this.report) return;
    const report = this.report;
    const solution = report.solutions.find(s => s.budget === Number(this.budget.value) && s.method === this.method.value);
    this.solution = solution;
    this.route = undefined;
    requiredElement<HTMLButtonElement>("download-button").disabled = !solution;
    if (!solution) {
      requiredElement("connected-status").textContent = "No package was calculated for this combination.";
      for (const id of ["connected-outcomes", "connected-route-detail", "connected-projects", "connected-funded-projects"]) requiredElement(id).replaceChildren();
      requiredElement<HTMLButtonElement>("connected-package-map").disabled = true;
      this.map.showConnectedRoute(report);
      return;
    }
    requiredElement("connected-outcomes").replaceChildren(...([
      [`${solution.served_journeys} / ${report.sample.selected}`, `sample journeys connected (${report.baseline.journeys} before)`],
      [money(solution.capital_cost), `${solution.selected.length} upgrades in the package`],
    ] as const).map(([value, label]) => { const card = create("div"); card.append(create("strong", { text: value }), create("span", { text: label })); return card; }));
    requiredElement("connected-weight").textContent = `With the source population weights, connected journeys represent ${amount(solution.served_weight)} eligible commuters (${amount(report.baseline.weight)} before). These are not forecasts of new cyclists.`;
    const fundedProjects = report.projects.filter(project => solution.selected.includes(project.id));
    if (!fundedProjects.length) this.mapExtent = "route";
    const fundedKm = fundedProjects.reduce((sum, project) => sum + project.lengthM, 0) / 1000;
    const packageButton = requiredElement<HTMLButtonElement>("connected-package-map");
    packageButton.disabled = !fundedProjects.length;
    packageButton.textContent = !fundedProjects.length ? "No upgrades in this budget" : this.mapExtent === "package" ? "Back to the selected journey" : `Show all ${fundedProjects.length} upgrades · ${fundedKm.toFixed(1)} km`;
    packageButton.setAttribute("aria-pressed", String(this.mapExtent === "package"));
    const fundedList = requiredElement("connected-funded-projects");
    fundedList.replaceChildren(...fundedProjects.map((project, index) => {
      const row = create("div", { className: "connected-project" });
      const supportingJourney = report.journeys.find(j => j.alternatives.some(r => r.projectIds.includes(project.id) && r.projectIds.every(id => solution.selected.includes(id))));
      const title = `${index + 1}. ${project.name}`;
      if (supportingJourney) {
        const button = create("button", { type: "button", className: "project-journey-link", text: title });
        button.setAttribute("aria-label", `Inspect a journey using ${project.name}`);
        button.addEventListener("click", () => this.inspectProject(project.id));
        row.append(button);
      } else row.append(create("strong", { text: title }));
      row.append(create("span", { text: `${(project.lengthM / 1000).toFixed(2)} km · ${money(project.cost)}` }));
      return row;
    }));
    if (!fundedProjects.length) fundedList.append(create("p", { text: "This package funds no upgrades." }));
    const j = report.journeys.find(j => j.name === this.journey.value);
    if (!j) { this.map.showConnectedRoute(report); return; }
    const selected = new Set(solution.selected);
    const profileId = this.preference.value === "access" ? "balanced" : this.preference.value;
    const assigned = report.assignment.portfolios.find(p => p.key === solution.assignmentKey)?.profiles.find(p => p.profileId === profileId);
    const baseline = report.assignment.portfolios.find(p => p.selected.length === 0)?.profiles.find(p => p.profileId === profileId);
    const assignedJourney = assigned?.journeys.find(item => item.name === j.name);
    const parameters = report.assignment.profiles.find(p => p.id === profileId);
    requiredElement("connected-assignment-summary").textContent = assigned ? `Of ${amount(report.assignment.totalDemand)} cycle commuters assumed in the 8% scenario, ${amount(assigned.assigned)} can use acceptable routes with this package (${amount(baseline?.assigned ?? 0)} before). ${amount(assigned.unassigned)} have no acceptable route in the set tested. These are not additional cyclists.${assigned.journeys.some(item => !item.choiceSearchComplete) ? " Some searches were incomplete." : ""}` : "Route-choice estimates are not available for this package.";
    requiredElement("connected-preference-assumptions").textContent = parameters ? `${parameters.label}: time × ${parameters.time_weight}; distance penalty ${parameters.distance_s_per_km} seconds/km. Facility penalties (protected, shared, painted, quiet, none): ${parameters.facility_s_per_km.join(", ")} seconds/km. Stress penalties (levels 1–4): ${parameters.stress_s_per_km.join(", ")} seconds/km. These scores are not travel times. Settings are not calibrated to observed choices.` : "The route must meet the traffic-stress, distance and time limits.";
    const context = [this.budget.value, this.method.value, this.journey.value, this.preference.value].join("|");
    const options = this.preference.value === "access" ? j.alternatives : assignedJourney?.alternatives ?? [];
    const previous = context === this.alternativeContext ? Number(this.alternative.value) : Math.max(0, options.findIndex(r => r.projectIds.every(id => selected.has(id))));
    this.alternative.replaceChildren(...options.map((r, index) => create("option", { value: String(index), text: `Route ${index + 1} · ${(r.distanceM / 1000).toFixed(1)} km · ${(r.timeS / 60).toFixed(0)} min` })));
    this.alternative.disabled = !options.length;
    const requested = requestedRoute === null ? previous : Number(requestedRoute);
    this.alternative.value = String(Number.isInteger(requested) && requested >= 0 && requested < options.length ? requested : 0);
    this.alternativeContext = context;
    const route = options[Number(this.alternative.value)];
    this.route = route;
    const detail = requiredElement("connected-route-detail");
    const projects = requiredElement("connected-projects");
    projects.replaceChildren();
    requiredElement<HTMLButtonElement>("connected-zoom").disabled = !route;
    if (!route) {
      const reason = this.preference.value === "access" ? j.stopReason : assignedJourney?.stopReason;
      detail.replaceChildren(create("h2", { text: "No suitable route found" }), create("p", { text: reason === "disconnected" ? "This journey cannot be joined within the area tested. A route outside the area may exist." : reason === "label_limit" ? "The search stopped before every route could be checked." : "No route meets the current limits. Cycling here may still be possible." }));
    } else {
      const missing = route.projectIds.filter(id => !selected.has(id));
      detail.replaceChildren(create("h2", { text: !missing.length ? (route.projectIds.length ? "This package connects the journey" : "Already connected without upgrades") : `${missing.length} ${missing.length === 1 ? "upgrade is" : "upgrades are"} still needed` }), create("p", { className: "route-facts", text: `${(route.distanceM / 1000).toFixed(1)} km · ${(route.timeS / 60).toFixed(0)} minutes` }), create("p", { text: `Follow the whole route from A to B. ${missing.length ? "Red dashed sections still need funding." : route.projectIds.length ? "Orange sections are the upgrades included in this budget." : "This route already meets the model's limits."}` }));
      if (route.intersectionDelayS !== undefined) detail.append(create("p", { className: "help", text: `Includes ${(route.intersectionDelayS / 60).toFixed(1)} minutes of assumed intersection delay.` }));
      if (!route.projectIds.length) projects.append(create("p", { text: "No upgrades needed under the model's limits." }));
      for (const id of route.projectIds) {
        const project = report.projects.find(p => p.id === id);
        if (!project) continue;
        const row = create("p", { className: "connected-project" });
        row.append(create("strong", { text: project.name }), create("span", { text: `${(project.lengthM / 1000).toFixed(2)} km · ${money(project.cost)} · ${selected.has(id) ? "in this budget" : "not in this budget"}` }));
        projects.append(row);
      }
      projects.append(create("p", { className: "help", text: `${money(route.capitalCost)} for all upgrades on this route. Priced as protected cycleways; not a detailed design.` }));
    }
    if (this.mapExtent === "package") {
      this.map.showConnectedPackage(report, solution.selected, id => this.inspectProject(id));
      requiredElement("connected-map-caption").textContent = fundedProjects.length ? `All ${fundedProjects.length} funded upgrades. Numbers match the package list.` : "No upgrades funded in this package.";
    } else {
      this.map.showConnectedRoute(report, route, solution.selected);
      requiredElement("connected-map-caption").textContent = "A → B: whole journey. Dashed orange: rest of the upgrade.";
    }
    requiredElement("connected-route-detail").hidden = this.mapExtent === "package";
    document.querySelectorAll<HTMLElement>('#map-legend-items [data-route-only="true"]').forEach(row => { row.hidden = this.mapExtent === "package"; });
    requiredElement("map").setAttribute("aria-label", this.mapExtent === "package" ? "All funded cycling upgrades in this package" : "Whole journey and required upgrades");
    const mapSubject = this.mapExtent === "package" ? `${fundedProjects.length} funded upgrades` : j.name;
    requiredElement("mobile-map-status").textContent = `${mapSubject} · ${money(solution.capital_cost)} package`;
    requiredElement("view-announcement").textContent = `${mapSubject}: ${solution.served_journeys} sample journeys connected within ${money(solution.budget)}.`;
    const params = new URLSearchParams(window.location.search);
    params.set("extent", this.mapExtent);
    for (const [key, control] of [["areaBudget", this.budget], ["method", this.method], ["journey", this.journey], ["preference", this.preference], ["route", this.alternative]] as const) params.set(key, control.value);
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }

  private inspectProject(projectId: string): void {
    if (!this.report || !this.solution) return;
    const selected = this.solution.selected;
    const supports = (route: ResearchRoute) => route.projectIds.includes(projectId) && route.projectIds.every(id => selected.includes(id));
    const journey = this.report.journeys.find(j => j.alternatives.some(supports));
    if (!journey) return;
    this.journey.value = journey.name; this.preference.value = "access"; this.mapExtent = "route";
    this.render(String(journey.alternatives.findIndex(supports)));
    requiredElement("connected-route-detail").scrollIntoView({ block: "nearest" });
  }

  download(): void {
    if (!this.report || !this.solution) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(portfolioGeoJson(this.report, this.solution, this.route), null, 2)], { type: "application/geo+json" }));
    const link = create("a", { href: url, download: "span-connected-journey.geojson" });
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
