# PCT implementation provenance review

Review date: 2026-08-29

Decision owner: project maintainer

Scope: `src/cycling_investment_workbench/demand.py`, its tests, equations, and
the PCT-related function in the legacy CDI workspace

## Decision

The standalone implementation may remain under the project MIT software
licence, subject to preserving the citations and notices listed below. The
review found an independently structured Python implementation of a published
mathematical model; it did not find copied R or application source from the
AGPL PCT website or the GPL-3 `pct` package.

This is a project provenance decision, not legal advice. It must be revisited
if PCT application/package source is copied into the repository, if a generated
file embeds that source, or if the implementation is replaced from a third-party
codebase.

## Sources reviewed

- Lovelace, Goodman, Aldred, Berkoff, Abbas, and Woodcock (2017), “The
  Propensity to Cycle Tool,” *Journal of Transport and Land Use*, 10(1),
  505–528, <https://doi.org/10.5198/jtlu.2016.862>.
- PCT 2020 manual equations and coefficient tables, as identified in the
  project bibliography and equation register.
- Official PCT project description and licence statement:
  <https://www.pct.bike/about.html> (AGPL application; reviewed 2026-08-20).
- Official `pct` package function reference and displayed coefficients:
  <https://itsleeds.github.io/pct/reference/uptake_pct_govtarget.html>
  (reviewed 2026-08-20).
- Current `pct` package implementation used only for behaviour and provenance
  comparison:
  <https://github.com/ITSLeeds/pct/blob/master/R/uptake.R>
  (GPL-3 package; reviewed 2026-08-20).
- Legacy local CDI function `src/nz_pt_access/cli.py::pct_uptake`, inspected to
  establish the standalone project’s development boundary.

## What is carried from the published method

The following are methodological facts or mathematical content recorded with
attribution:

- the logistic functional form;
- distance, square-root distance, squared distance, centred gradient, and the
  two distance–gradient interactions;
- the published 2020 Government Target, Go Dutch, and e-bike coefficients;
- percentage-gradient and kilometre units; and
- the 30 km upper distance cap used by the maintained reference implementation.

The public documentation must continue to describe these as PCT scenarios
developed for England, not calibrated predictions for Auckland. The separate
8% commute sensitivity is a CIW policy sensitivity and is not a PCT or Auckland
Transport forecast.

## Independent implementation findings

The standalone code differs materially in structure and behaviour from the R
package and from the legacy CDI helper:

- coefficients are immutable typed records rather than R function defaults or
  an array held in a scenario dictionary;
- the predictor, stable logistic transform, scenario allocation, confidentiality
  intervals, and capped target allocation are separate tested functions;
- input units are explicit and validated rather than inferred from vector
  means;
- the distance cap is an explicit parameter with a tested default;
- scenario allocation is bounded by eligible demand and cannot fall below the
  declared observed point estimate; and
- reference-vector and cap tests exercise the published equation independently.

A source comparison found no copied comments, documentation blocks, function
names, control flow, package calls, error text, or data structures. Identical
numeric coefficients and ordinary algebraic operations are necessary to
implement the cited model and are not treated as evidence of copied software.

## Required release conditions

- Retain the Lovelace et al. citation in the software documentation,
  bibliography, equation register, and citation metadata.
- Retain acknowledgement that the official PCT application is AGPL and the
  `pct` package is GPL-3; do not imply that those licences cover CIW datasets.
- Do not vendor PCT application/package source or generated derivatives without
  a new licence review.
- Keep reference-vector tests for all three 2020 scenarios and the 30 km cap.
- Record routed distance and hilliness units in every released run schema.
- Re-run a textual and dependency provenance scan before each public tag.

## Current pre-tag scan

The 29 August 2026 source-state scan recorded these SHA-256 values:

- `demand.py`: `eb9c4b0a5465ac50fa1539fd7167626cb9d7672a3a497378f8ed3095f123cce8`;
- `test_demand.py`: `7a9ef908427ccb3ef1166a30e6fa8ef6a46fc68f29d1cd97f1c30a6ac3feb103`;
- legacy CDI `cli.py`: `84b19630856c38c5c19b4477ec169d09ce8973fb6edb20e9fef6864a8cf24b2c`.

The locked dependency tree and public source contained no `pct`, R, or `rpy2`
dependency or import. A whitespace- and number-normalised line comparison of
the standalone PCT section with the legacy helper returned a SequenceMatcher
ratio of 0.014085 and no exact block longer than one punctuation-only line.
The broader non-comment file comparison returned 0.009940 and the same
one-line maximum. This is reproducible technical provenance evidence, not a
legal determination. It closes the source-similarity check for this exact
source state and must be repeated if the implementation changes before a tag.

## Licence boundary

The MIT licence covers original CIW source only. Third-party packages retain
their own licences, input datasets retain their provider terms, and the
published PCT method remains credited to its authors. Container components and
data attributions are recorded separately in `NOTICE.md`, `DATA_LICENSES.md`,
and the public-layer rights register.
