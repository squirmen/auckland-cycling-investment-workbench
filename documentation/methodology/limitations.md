# Limitations and appropriate use

## Appropriate use

The workbench is suitable for:

- finding network gaps worthy of investigation;
- comparing candidate packages under common, visible assumptions;
- testing how a cumulative network programme changes access and connectivity;
- identifying evidence gaps and sensitivity drivers; and
- structuring discussion before detailed planning and appraisal.

It is not suitable on its own for approving expenditure, selecting a final
alignment, forecasting opening-year patronage, satisfying statutory process,
or claiming causal health, safety, emissions, or equity outcomes.

## Demand

- Census journey-to-work data omit education, shopping, care, recreation,
  escort, shift-work, and many multimodal trips.
- Working from home, irregular workplaces, and post-census travel change can
  weaken commute-based spatial patterns.
- Random rounding and suppression create uncertainty that cannot be reversed.
- Suppression affects the total-stated OD field as well as the bicycle subset.
  In the audited internal-Auckland table, 5,441 total-stated cells are
  suppressed and all coincide with bicycle suppression; treating those
  eligible totals as observed zero would remove feasible demand and bias both
  the target denominator and capacity.
- Datafinder table 121988 removes OD rows whose total population is below six
  and includes only people with workplace address available at SA2. Those
  structurally absent pairs have no published cell: they are not numeric zero
  and do not automatically receive a 0–5 interval. Their locations and total
  mass may be unknown, so the internal scenario denominator undercovers all
  commuters and the missing mass cannot be routed or spatially imputed without
  separate evidence.
- The full-origin SA2 transport margin (`VAR_2_786`, published total 874,065)
  and the internal-Auckland journey-to-work OD table (approximately 610,101
  published total trips plus suppressed and structurally omitted cells) do not
  share a demonstrated
  universe. The margin can provide bounded, soft validation only until exact
  categories, geography, direction, exclusions, and disclosure treatment are
  reconciled.
- Outbound and other out-of-scope movements may be absent from an internal OD
  extract; unsnapped and unreachable internal movements also receive no routed
  allocation. They must remain visible in source/route ledgers and coverage
  denominators, not disappear through filtering or margin balancing.
- England-derived PCT coefficients have not, by themselves, established local
  Auckland behavioural validity.
- The 8% commute-cycling share is a configurable modelling sensitivity. TERP's
  adopted 17% target covers cycling and micromobility across all trips, with no
  direct equivalence to the Census commute denominator.
- Scenario uptake is not a prediction and does not include an implementation
  pathway, pricing, parking, service, culture, or land-use response.

## Routing and topology

- OpenStreetMap and agency layers can be incomplete, stale, differently
  classified, or geometrically misaligned.
- The configured LINZ layer 51768 is a contour-interpolated 8 m DEM whose
  publisher describes it as suitable for cartographic visualisation but not
  terrain analysis. It cannot support publication-grade gradient estimates
  without replacement or a documented validation showing fitness for this
  use. Hashing its VRT alone is also insufficient; every referenced raster tile
  must appear in the run manifest.
- Legal access, temporary closures, crossing delay, surface condition,
  lighting, personal security, wayfinding, and perceived comfort may be absent.
- Conservative imputation is transparent but can still systematically
  misclassify stress.
- A shortest generalized-cost path is a simplification of heterogeneous route
  choice; a finite plausible path set remains an approximation.
- Zone representative points and snapping can create artificial access links or
  omit within-zone movement.
- Static topology does not represent construction staging, congestion,
  interactions with pedestrians, or future network change unless supplied as a
  scenario.

## Candidates and sequencing

- Generated corridors are analytical edge sets, not surveyed or designed
  projects. Feasibility, gradients, structures, property, drainage, utilities,
  intersections, consenting, and community priorities require field and design
  work.
- Proximity does not guarantee a facility is an equivalent or accessible
  substitute; duplicate filters require audit.
- Candidate boundaries affect costs and benefits. Splitting or joining segments
  can change rank.
- Continuous response remains a model assumption and cannot distinguish
  rerouting from new cycling without supporting behavioural evidence.
- Named presets and Pareto membership do not choose a programme under fixed
  budgets, indivisibility, staging, geographic balance, dependencies, or
  delivery constraints. Portfolio outcomes also depend on project order.
- Future Connect is a strategic planning network, not an investment-ranking
  tool. Alignment is context, not validation of a candidate score.

The CIW OD low-stress connectivity share is conditional on its OD set, demand
weights, routing coverage, stress threshold, and detour threshold. It is not a
universal city index and cannot be compared with differently constructed
connectivity measures without harmonisation.

## Benefits and costs

- Screening unit rates may omit property, structures, utilities, escalation,
  risk, maintenance, renewals, disruption, and project-specific design.
- Health, carbon, safety, travel-time, and vehicle-operating effects can overlap;
  benefits must follow the applicable appraisal manual to avoid double counting.
- Benefits depend on trip purpose, traveller, distance, counterfactual mode,
  ramp-up, decay, and additionality; average values can conceal distribution.
- An indicative lifecycle ratio is not an approved business-case BCR.
- The current public Auckland research asset withholds appraisal entirely:
  candidate BCR fields are null and the Appraisal lens is disabled until local
  capital, maintenance, renewal, residual, benefit, e-bike, price-base, and
  demand-response inputs pass expert review.
- Monetary parameters and rules change. The exact MBCM version applicable when
  appraisal commences controls any formal claim.

## Equity, safety, and access

- NZDep is a relative area index; missing/withheld values require explicit
  handling, and area deprivation must not be assigned to individuals or read as
  absolute change over time.
- Distributional maps can reveal unequal opportunity but do not establish who
  receives or bears project effects.
- Destination datasets differ in completeness and quality; a missing point is
  not necessarily missing access.
- Recorded crashes understate incidents and are influenced by exposure and
  reporting. Crash clusters do not by themselves estimate treatment effects.
- A commute-led demand score can under-prioritise children, older people,
  disabled riders, caregivers, low-income households, and people not in formal
  employment.

## Validation

- Sparse counters cover selected corridors, count existing users, and may not
  represent low-cycling or candidate areas.
- Spatial matching can associate a counter with the wrong parallel edge.
- Present-day counts cannot directly validate a future target scenario.
- Correlation does not establish unbiased scale or correct intervention effects;
  a global scaling ratio can hide spatial errors.
- Expert face review can identify errors but is subjective and is not a
  substitute for out-of-sample observation.

## Responsible release

Do not publish a map without source and basemap attribution, data licence
review, source dates, configuration, warnings, and a release manifest. Restricted
microdata, credentials, cached tiles, and non-redistributable publications stay
outside version control. Avoid interpreting candidate rankings beyond the
geography, scenario, data vintage, and uncertainty stated in the release.

The current Auckland rights review is deliberately fail-closed. Several
configured inputs have accessible publisher pages but do not yet have an exact
source-to-file chain or dataset-specific redistribution evidence. Dependent
layers remain blocked or omitted as recorded in
[`../audit/public-layer-rights.csv`](../audit/public-layer-rights.csv). Hosted
CARTO tiles are disabled and must not appear in screenshots unless a separate
licence or qualifying grant is documented.
