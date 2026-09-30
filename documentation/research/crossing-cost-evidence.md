# Crossing costs: evidence needed for SPAN

Checked 26 September 2026. No crossing unit prices have been substituted into
the public model. The existing fixed short-link allowances are sensitivity
tests, not construction estimates.

## What is publicly available

NZTA's [SM014 cost-estimation resource page](https://www.nzta.govt.nz/resources/cost-estimation-manual)
lists the May 2025 manual, an elemental costing database and escalation-factor
workbooks. These provide a route to structured, dated estimates rather than
one universal cost per crossing. The listing was accessible through the search
index; the workbooks and full manual were not reviewed in this pass.

NZTA's [8 May 2025 OIA response, reference 18075](https://nzta.govt.nz/assets/About-us/docs/oia-2025/oia-18075-response-letter.pdf)
identifies an indicative Cycle Facilities ROC Estimation Tool and says its last
update was in 2020, without subsequent inflation or escalation. The response's
indexed text was checked. Direct PDF retrieval/rendering was blocked, so the
attachment's tables, footnotes and component totals have **not** been validated
or imported. The release date must not be mistaken for the price base year.

AT's [February 2024 board digest](https://at.govt.nz/about-us/news-events/media-centre/2024-media-releases/decision-digest-february-2024-auckland-transport-board-meeting)
describes different crossing treatments and a pre-cast example, not a standard
tariff. Its [2 February statement](https://at.govt.nz/about-us/news-events/media-centre/2024-media-releases/statement-on-safety-measures-and-raised-crossings)
describes combining safety work with maintenance and utilities. This matters:
the incremental cost within a corridor contract cannot simply be compared with
the total cost of a standalone crossing project.

## What must be matched before a cost enters the model

For each intervention, retain:

- A physical asset/project ID and the directed crossing movements it treats.
  Several short street chains meeting at a junction are not several crossings.
- The treatment and scope: refuge, zebra, raised platform, signals, junction
  conversion or other works; distinguish pedestrian from rideable cycle provision.
- Quantities, dimensions, street class and the applicable design requirements.
- Price date, currency, GST treatment, estimate stage and whether the figure is
  forecast, tendered or an actual outturn.
- Separate construction, lighting, drainage, utilities, traffic management,
  design, consenting, land, contingency and escalation components. Record
  exclusions explicitly and avoid counting shared works twice.
- Low/base/high assumptions and their basis. Do not label arbitrary multipliers
  as confidence intervals or a published range as an engineering estimate.
- The source document, version, permission to publish and reviewer/sign-off.
- Residual crossing stress, delay and permitted movements after construction.
  Funding a street upgrade must not silently remove an untreated crossing.

Until those mappings exist, use costs only as clearly labelled exploratory
cases. Do not automatically assign an old ROC row or an average project cost
to every `diagnostic-short:` chain.

## Targeted request for an AT contact

Draft only; not sent:

> We're developing SPAN to compare complete cycling investment packages. Could
> you point us to a shareable schedule or anonymised sample of recent crossing
> and short-connection projects? Ideally it would distinguish treatment type,
> standalone versus corridor delivery, estimate/tender/outturn cost, price year,
> GST, included works and exclusions. Component costs for lighting, drainage,
> utilities, traffic management, design and contingency would help us avoid
> misleading per-crossing averages. We would also need treatment geometry or
> movement coverage to avoid charging several times for one junction. Public
> documentation or de-identified cost ranges would be useful; please identify
> any restrictions on reuse or publication.

This is separate from the signal-timing request: actual timing plans and observed
waits address journey delay, not construction cost.
