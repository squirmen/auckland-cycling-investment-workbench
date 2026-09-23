# Documentation map

This directory separates the public method, release evidence, white-paper
planning material, equations, references, and visual record.

Current SPAN additions:

- [Effective-network beta and server handoff](research/span-effective-network.md)
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
files are editorial plans, not results. A complete local Auckland research
snapshot now exists as run `run-313e0277521633d3`, but its derived values are
not decision-ready or publicly released. An Auckland value becomes publishable
only when it is traced to the exact tagged release manifest, cleared asset, and
completed validation and manual-audit evidence.
Current gate status is recorded in
[`audit/release-readiness.md`](audit/release-readiness.md); a checked box there
requires repository evidence, not an intention to complete the item later.
The authoritative public-data include, omit, and block decisions are in
[`audit/public-layer-rights.csv`](audit/public-layer-rights.csv); configuration
labels alone do not clear a layer for publication.
