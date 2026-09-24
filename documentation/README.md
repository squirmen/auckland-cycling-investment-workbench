# Documentation map

This directory separates the public method, release evidence, white-paper
planning material, equations, references, and visual record.

Current SPAN additions:

- [Priorities and acceptance criteria](roadmap.md)
- [Fresh routing, four-area checks and reliability fixes](audit/span-follow-up-progress-2026-09-24.md)
- [Source-cell influence audit and next sampling work](audit/span-source-cell-influence-2026-09-24.md)
- [Effective-network beta and server handoff](research/span-effective-network.md)
- [SPAN interface and TEAM reuse review](audit/span-interface-and-team-review-2026-09-24.md)
- [CRANC entry points and adapter checklist](research/cranc-integration.md#where-to-connect-cranc)
- [24 September improvement review](audit/span-improvement-review-2026-09-24.md)
- [Complete-route experiment](research/span-access-first-experiment.md)
- [Research methodology review](research/methodology-review-2026-09.md)

```text
documentation/
├── audit/
│   ├── audit-resolution-matrix.md
│   ├── auckland-real-stage-evidence.md
│   ├── container-reproduction.md
│   ├── pct-provenance-review.md
│   ├── public-layer-rights.csv
│   ├── release-dossier.md
│   ├── release-readiness.md
│   ├── run-manifest-evidence.md
│   ├── test-evidence.md
│   └── ui-ux-review.md
├── equations/
│   ├── README.md
│   ├── notation.tex
│   ├── confidentiality.tex
│   ├── pct-uptake.tex
│   ├── target-allocation.tex
│   ├── purpose-demand.tex
│   ├── routing-impedance.tex
│   ├── counterfactual.tex
│   ├── equity.tex
│   ├── economics.tex
│   ├── connectivity.tex
│   ├── uncertainty.tex
│   └── validation.tex
├── methodology/
│   ├── methodology.md
│   ├── data-dictionary.md
│   ├── parameters.md
│   ├── validation.md
│   ├── uncertainty.md
│   └── limitations.md
├── references/
│   ├── README.md
│   ├── library.bib
│   ├── evidence-matrix.csv
│   ├── open/
│   │   └── README.md
│   └── restricted/
│       ├── README.md
│       └── manifest.csv
├── screenshots/
│   ├── README.md
│   ├── manifest.csv
│   ├── full/
│   ├── web/
│   └── thumbnails/
└── white-paper/
    ├── outline.md
    ├── claims-evidence-matrix.md
    ├── figures-and-tables.md
    ├── journal-mapping.md
    └── limitations.md
```

The methodology documents are normative for interpretation. The white-paper
files are editorial plans, not results. The Auckland research snapshot
`run-313e0277521633d3` underpins the public SPAN research beta; commit
`0937175` was deployed to [span.tfwelch.com](https://span.tfwelch.com) on
24 September 2026. Public availability does not make its derived values
decision-ready or its uptake estimates calibrated. New audit outputs are
repository evidence, not changes to that deployed model.
Release and validation gates are recorded in
[`audit/release-readiness.md`](audit/release-readiness.md); a checked box there
requires repository evidence, not an intention to complete the item later.
The authoritative public-data include, omit, and block decisions are in
[`audit/public-layer-rights.csv`](audit/public-layer-rights.csv); configuration
labels alone do not clear a layer for publication.
