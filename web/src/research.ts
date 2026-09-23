import "leaflet/dist/leaflet.css";
import "./style.css";
import "./research.css";
import L from "leaflet";
import { amount, money } from "./copy";
import { create, requiredElement } from "./dom";
import { portfolioGeoJson, reportSchema, type ResearchRoute, type ResearchSolution } from "./research-data";
import { checkCrancScope, crancComparisonSchema, crancRequest, type CrancComparison } from "./cranc";


void initialise();
async function initialise(): Promise<void> {
  const status = requiredElement("research-status");
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}data/access-experiment.json`);
    if (!response.ok) throw new Error("Run the access experiment to generate this local pilot.");
    const report = reportSchema.parse(await response.json());
    const budget = requiredElement<HTMLSelectElement>("research-budget");
    const method = requiredElement<HTMLSelectElement>("research-method");
    const journey = requiredElement<HTMLSelectElement>("research-journey");
    const preference = requiredElement<HTMLSelectElement>("research-preference");
    const alternative = requiredElement<HTMLSelectElement>("research-alternative");
    preference.append(...report.assignment.profiles.map(p => create("option", { value: p.id, text: p.label })));
    let activeSolution: ResearchSolution;
    let activeRoute: ResearchRoute | undefined;
    let activeComparison: CrancComparison | null = null;
    let alternativeContext = "";
    function comparisonContext() {
      return { runId: report.runId, topologyHash: report.sourceHashes.topology, originsHash: report.sourceHashes.origins, weightingHash: report.sourceHashes.originWeights, selected: activeSolution.selected };
    }
    function renderCranc(): void {
      const target = requiredElement("cranc-status");
      if (!activeComparison) { target.textContent = "No CRANC comparison loaded. Missing results are unavailable, not zero."; return; }
      const mismatch = checkCrancScope(activeComparison, comparisonContext());
      if (mismatch) { target.textContent = mismatch; return; }
      const result = activeComparison;
      const gain = result.investment.value - result.baseline.value;
      target.textContent = `${result.scope.profile.toUpperCase()} · ${result.scope.timeLimitS / 60} minutes · ${result.scope.category}: ${amount(result.baseline.value)} → ${amount(result.investment.value)} reachable opportunities per origin (weighted mean; change ${gain >= 0 ? "+" : ""}${amount(gain)}). ${result.provider.attribution} · ${result.provider.version}. Imported provider result; SPAN has checked source and package scope, not independently verified the measurement or matching crop, speed and intersection-delay assumptions.`;
    }
    const budgets = [...new Set(report.solutions.map(s => s.budget))].sort((a, b) => a - b);
    budget.replaceChildren(...budgets.map(value => create("option", { value: String(value), text: money(value) })));
    budget.value = String(budgets.at(-1));
    journey.replaceChildren(...report.journeys.map(j => create("option", { value: j.name, text: `${j.name} · ${amount(j.weight)} weighted commuters${j.alternatives.length ? " · route found" : " · no feasible route found"}` })));
    const initialProjects = report.solutions.find(s => s.budget === Number(budget.value) && s.method === method.value)?.selected ?? [];
    journey.value = report.journeys.filter(j => j.alternatives.some(r => r.projectIds.every(p => initialProjects.includes(p)))).sort((a, b) => b.weight - a.weight)[0]?.name ?? report.journeys[0]?.name ?? "";
    // Rapid route changes must not retain an earlier in-flight zoom target.
    const map = L.map(requiredElement("research-map"), { attributionControl: false, zoomAnimation: false }).setView([report.centre[1], report.centre[0]], 13);
    L.control.scale({ imperial: false }).addTo(map);
    const lines = L.featureGroup().addTo(map);
    function render(): void {
      const solution = report.solutions.find(s => s.budget === Number(budget.value) && s.method === method.value);
      if (!solution) throw new Error("No recorded result for this selection");
      activeSolution = solution;
      activeRoute = undefined;
      renderCranc();
      requiredElement("research-outcomes").replaceChildren(...([
        [amount(solution.served_weight), `eligible commute weight with a feasible route · +${amount(solution.served_weight - report.baseline.weight)} over baseline`],
        [String(solution.served_journeys), `of ${report.sample.selected} sampled journeys enabled`],
        [money(solution.capital_cost), `${solution.selected.length} projects funded`],
      ] as const).map(([value, label]) => {
        const card = create("div"); card.append(create("strong", { text: value }), create("span", { text: label })); return card;
      }));
      const j = report.journeys.find(j => j.name === journey.value);
      if (!j) return;
      const selected = new Set(solution.selected);
      const profileId = preference.value === "access" ? "balanced" : preference.value;
      const assigned = report.assignment.portfolios.find(p => p.key === solution.assignmentKey)?.profiles.find(p => p.profileId === profileId);
      const baseline = report.assignment.portfolios.find(p => p.selected.length === 0)?.profiles.find(p => p.profileId === profileId);
      const assignedJourney = assigned?.journeys.find(item => item.name === j.name);
      const parameters = report.assignment.profiles.find(p => p.id === profileId);
      requiredElement("research-assignment-summary").textContent = assigned ? `Fixed 8% scenario demand: ${amount(report.assignment.totalDemand)} usual cycle commuters in these source records. ${amount(baseline?.assigned ?? 0)} assigned to acceptable routes before → ${amount(assigned.assigned)} with this package; ${amount(assigned.unassigned)} remain unassigned under these constraints. These are existing scenario totals, not additional cyclists. Each preference case uses the same demand; do not add cases together.${assigned.journeys.some(item => !item.choiceSearchComplete) ? " Some preference searches reached their limit; allocation is provisional." : ""}` : "Assignment is unavailable for this package.";
      requiredElement("research-preference-assumptions").textContent = parameters ? `${parameters.label}: physical time × ${parameters.time_weight}; distance penalty ${parameters.distance_s_per_km} equivalent seconds/km. Facility penalties (protected, shared, painted, quiet street, no facility): ${parameters.facility_s_per_km.join(", ")} seconds/km. LTS 1–4 penalties: ${parameters.stress_s_per_km.join(", ")} seconds/km. Hard route limits still apply. Route-choice scale: 0.005 per equivalent second; path-size coefficient: 1. These values are unfitted.` : "";
      const context = [budget.value, method.value, journey.value, preference.value].join("|");
      const options = preference.value === "access" ? j.alternatives : assignedJourney?.alternatives ?? [];
      const previousIndex = context === alternativeContext ? Number(alternative.value) : Math.max(0, options.findIndex(r => r.projectIds.every(id => selected.has(id))));
      alternative.replaceChildren(...options.map((r, index) => create("option", { value: String(index), text: `Route ${index + 1} · ${(r.distanceM / 1000).toFixed(2)} km · ${(r.timeS / 60).toFixed(1)} min` })));
      alternative.disabled = options.length === 0;
      alternative.value = String(Math.min(previousIndex, options.length - 1));
      alternativeContext = context;
      const route = options[Number(alternative.value)];
      activeRoute = route;
      const detail = requiredElement("research-route-detail");
      const projects = requiredElement("research-projects");
      lines.clearLayers(); projects.replaceChildren();
      if (!route) {
        const reason = preference.value === "access" ? j.stopReason : assignedJourney?.stopReason;
        detail.replaceChildren(create("h2", { text: "No feasible route found" }), create("p", { text: reason === "disconnected" ? "The endpoints are disconnected in the cropped directed graph. Routes outside the crop have not been searched." : reason === "label_limit" ? "The search reached its label limit. Feasibility has not been resolved." : "No route was found under the current investment and declared stress, detour and time limits. This does not establish that cycling here is impossible." }));
        map.setView([report.centre[1], report.centre[0]], 13, { animate: false }); return;
      }
      const funded = route.projectIds.every(id => selected.has(id));
      detail.replaceChildren(create("h2", { text: funded ? "Complete under this investment" : "Required package is not fully funded" }), create("p", { text: `${(route.distanceM / 1000).toFixed(2)} km · ${(route.timeS / 60).toFixed(1)} minutes · ${(route.distanceM / (j.shortestLegalDistanceM ?? route.distanceM)).toFixed(2)}× shortest legal distance` }), create("p", { text: `${route.projectIds.length} required upgrades, costing ${money(route.capitalCost)} together. ${amount(route.existingCyclewayM)} m uses an existing cycleway or shared path.` }));
      if (route.intersectionDelayS !== undefined && report.intersectionContext) {
        detail.append(create("p", { text: `Time includes ${(route.intersectionDelayS / 60).toFixed(1)} minutes of assumed intersection delay (${report.intersectionContext.scenario} sensitivity). These are illustrative waits, not measured signal operation.` }));
      }
      if (preference.value !== "access") {
        const assignmentRoute = assignedJourney?.alternatives[Number(alternative.value)];
        if (assignmentRoute) detail.append(create("p", { text: `${amount(assignmentRoute.flow)} of ${amount(assignedJourney.demand)} fixed scenario commuters assigned here (${(assignmentRoute.probability * 100).toFixed(1)}%). Preference cost: ${(assignmentRoute.generalizedCostS / 60).toFixed(1)} equivalent minutes; this is not travel time.${assignedJourney.choiceSearchComplete ? "" : " Choice-set search was truncated."}` }));
      }
      for (const id of route.projectIds) {
        const project = report.projects.find(p => p.id === id);
        if (!project) throw new Error("Route project is missing from the report");
        const item = create("p", { className: "research-project" });
        item.append(create("strong", { text: project.name }), create("span", { text: `${(project.lengthM / 1000).toFixed(2)} km · ${money(project.cost)} · ${selected.has(id) ? "funded" : "not funded"}` }));
        projects.append(item);
        L.polyline(project.coordinates.map(p => [p[1], p[0]]), { color: "#cd641e", weight: 3, dashArray: "5 5", opacity: 0.5 }).addTo(lines);
      }
      for (const segment of route.segments) L.polyline(segment.coordinates.map(p => [p[1], p[0]]), { color: segment.projectId ? "#cd641e" : segment.existingCycleway ? "#167b64" : "#718994", weight: 6, opacity: 1 }).addTo(lines);
      const ends = [route.segments[0]?.coordinates[0], route.segments.at(-1)?.coordinates.at(-1)];
      ends.forEach((p, i) => { if (p) L.marker([p[1], p[0]], { icon: L.divIcon({ className: "research-end", html: i === 0 ? "A" : "B", iconSize: [26, 26] }) }).addTo(lines); });
      map.fitBounds(lines.getBounds(), { padding: [30, 30], maxZoom: 16, animate: false });
    }
    for (const control of [budget, method, journey, preference, alternative]) control.addEventListener("change", render);
    requiredElement("research-export").addEventListener("click", () => downloadJson("span-investment-package.geojson", portfolioGeoJson(report, activeSolution, activeRoute)));
    requiredElement("cranc-request").addEventListener("click", () => downloadJson("span-cranc-request.json", crancRequest(comparisonContext())));
    async function importCranc(event: Event): Promise<void> {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;
      activeComparison = null;
      try {
        if (file.size > 1_000_000) throw new Error("Use an aggregate comparison JSON smaller than 1 MB.");
        const parsed = crancComparisonSchema.safeParse(JSON.parse(await file.text()));
        if (!parsed.success) throw new Error(`The CRANC return contract was not met: ${parsed.error.issues.map(i => `${i.path.join(".")}: ${i.message}`).slice(0, 3).join("; ")}`);
        activeComparison = parsed.data;
        renderCranc();
      } catch (error) { requiredElement("cranc-status").textContent = error instanceof Error ? error.message : "The comparison could not be read."; }
    }
    requiredElement<HTMLInputElement>("cranc-import").addEventListener("change", event => { void importCranc(event); });
    status.textContent = `${report.graph.directedArcs.toLocaleString()} directed street arcs · ${report.graph.projects} eligible projects · ${report.sample.selected} of ${report.sample.eligibleWithinArea} local OD records sampled. ${report.searchComplete ? "All sampled route searches completed." : "Some route searches were truncated."}`;
    if (report.intersectionContext) status.textContent += ` Includes ${report.intersectionContext.scenario} delay assumptions at ${report.intersectionContext.sitesInCrop} matched intersections in this crop; these are not observed signal timings.`;
    requiredElement("research-limitations").replaceChildren(...report.limitations.map(text => create("li", { text })));
    requiredElement("research-provenance").textContent = `Source ${report.runId}; ${report.radiusM / 1000} km crop; sample seed ${report.seed}. LTS ≤ ${report.standard.maximum_stress}, detour ≤ ${report.standard.maximum_detour}×, time ≤ ${report.standard.maximum_time_s / 60} minutes. Solver optimality covers the generated routes only. Budgets are independent optimisations, not a cumulative build order.`;
    render();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "The experiment could not be loaded.";
  }
}

function downloadJson(name: string, value: object): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = create("a", { href: url, download: name });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
