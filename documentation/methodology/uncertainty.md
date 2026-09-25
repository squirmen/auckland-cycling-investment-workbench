# Uncertainty framework

SPAN avoids compressing all uncertainty into one interval. Each source
has a different interpretation and mitigation.

| Class | Examples | Principal treatment | What remains outside it |
| --- | --- | --- | --- |
| Measurement | random-rounded/suppressed eligible-total and bicycle-subset census counts, structurally omitted OD rows and unlocated workplaces, counter error, incomplete attributes | joint feasible cell bounds, source-coverage ledger, quality flags, alternative supported bounds | unknown location/mass for structurally absent demand, undisclosed publisher processing, and systematic bias |
| Parameter | PCT coefficients, stress multipliers, elasticity, costs, values, discount rate | documented distributions/ranges and global sensitivity | omitted mechanisms |
| Structural | trip-purpose restriction, one best path versus path set, induced-demand model, static land use | competing model specifications | unknowable future system change |
| Spatial | geography aggregation, centroid/snap choice, topology errors, MAUP | alternative zones/snaps, audit samples, topology warnings | all positional and boundary uncertainty |
| Scenario | target share, implementation year, programme interactions | clearly named scenarios, never probability claims without basis | political and delivery uncertainty |
| Computational | finite simulation draws, tie handling, numerical tolerance | fixed seeds, convergence checks, deterministic ties | software defects, addressed separately by tests |

## Confidentiality-bound scenarios

The lower, point, and upper interpretations of disclosure-controlled counts are
run end to end. Eligible-total and bicycle-subset values are selected or drawn
jointly so bicycle never exceeds total stated. The resulting range is not a
frequentist confidence interval; it answers how results change across declared
interpretations compatible with the published table. Spatial correlation
introduced by disclosure control may remain. The full-origin SA2 margin is not
used to close or rescale the internal OD table unless an exact universe
reconciliation has been demonstrated; otherwise its uncertainty comparison is
reported as a soft validation diagnostic.
Structurally absent table-121988 rows are not sampled as if they were explicit
suppressed cells. When no compatible publisher total bounds their mass, that
coverage gap remains outside the numerical ensemble and is reported as an
unresolved structural limitation.

## Parameter uncertainty

Use a reproducible seeded Latin-hypercube design over declared marginal
distributions or bounded ranges. Preserve
logical dependencies: for example, higher capital unit cost should propagate to
renewal cost, and values with a shared price base should use the same update
factor.

For each outcome report:

- median and central 90% interval across parameter draws;
- probability of crossing policy-relevant thresholds, with threshold source;
- rank acceptability or top-k inclusion frequency rather than only mean rank;
- partial rank correlation or another global sensitivity diagnostic; and
- the assumed parameter distributions and correlations.

The default design has 1,000 draws and seed 20260301. Convergence is checked
against additional draws and seeds. These are parameter/scenario ensembles
unless the distributions have empirical probability meaning.

## Structural scenarios

At minimum, compare:

1. one least-generalized-cost path versus a plausible path set;
2. observed commute demand only versus broader trip-purpose demand where data
   support it;
3. target-constrained allocation under multiple PCT priors;
4. lower and higher continuous response elasticities;
5. low-stress definitions and detour thresholds;
6. cumulative re-routing versus static candidate cover sets; and
7. lifecycle appraisal with alternative ramp-up, asset life, and residual
   value.

Results that reverse across plausible structures are model-dependent and must
be described as such.

## Spatial robustness

Assess sensitivity to OD representative points, snap thresholds, network
vintage, route alternatives, and analysis geography. Publish the number and
demand share of unsnapped or unreachable pairs. Maps use uncertainty hatching
or separately labelled evidence components where exact-looking colours would
imply unsupported spatial precision.

## Decision communication

Every candidate card and table should separate:

- central conditional estimate;
- interval or sensitivity range and its type;
- input-data completeness;
- routing coverage;
- frontier and rank stability;
- parameter-sensitivity span;
- structural warnings; and
- the run and scenario to which the evidence applies.

Avoid decimal precision beyond the underlying evidence. A screening BCR near a
decision threshold is not decisive when construction costs and behavioural
response are weakly evidenced.
