# Evidence library

`library.bib` is the citation source for the method and white paper.
Journal DOI, title, author, year, venue, volume, and pagination metadata were
checked against the DOI landing page, publisher record, Crossref metadata, or
an institutional repository record through 25 August 2026. Reports without a
DOI use their official publisher URL. Verification establishes bibliographic
identity, not study quality or permission to redistribute a local copy.

`evidence-matrix.csv` records what each source can support, its important
limitations, access status, and whether a legally redistributable copy is stored
locally. It is an evidence map, not a quality score or systematic review.

The following corrections are intentional:

- The PCT article is Lovelace et al. (2017), *Journal of Transport and Land
  Use* 10(1), DOI `10.5198/jtlu.2016.862`.
- Liu, Szeto and Long is a 2019 article in *Transportation Research Part E*
  127, DOI `10.1016/j.tre.2019.05.010`.
- Lowry, Furth and Hadden-Loh (2016), DOI
  `10.1016/j.tra.2016.02.003`, is the relevant prioritisation study.
- The 2012 bikeability article authors are Michael B. Lowry, Daniel Callister,
  Maureen Gresham, and Brandon Moore.
- The New Zealand equity records use Bruce Kidd for Jones et al. (2020) and
  Rebekah Thorne for Thorne et al. (2020), matching the publisher metadata.
- Yen's loopless-path algorithm is the 1971 *Management Science* article, DOI
  `10.1287/mnsc.17.11.712`; the path-size-logit lineage includes Ben-Akiva and
  Bierlaire (1999), DOI `10.1007/978-1-4615-5203-1_2`.
- NZTA General Circular 26/01 records the May 2026 changes and applicability of
  MBCM v1.7.5. Discounting remains governed by the separate General Circular
  25/01: a stepped non-commercial schedule and a required 8% sensitivity, not
  the historical constant 4% rate in Auckland's 2022 programme business case.
- No verifiable record was found for the previously noted “Saxe and Miller
  (2021), Counterfactual route-choice analysis for urban cycling”; it is omitted.
- Stats NZ's 2023 Census confidentiality method is the April 2024 report, ISBN
  978-1-99-104974-2. An explicit below-six suppression marker and a numeric
  fixed-random-rounded zero have different analytical intervals. The rule
  applies to each disclosure-controlled field; the bicycle-subset constraint
  and any OD-to-margin universe reconciliation are separate analysis steps.
- The NZDep2023 methodological source is Atkinson et al. (2024), the official
  University of Otago research report dated 31 October 2024. Its CC BY 4.0
  notice applies to the report; the separately downloadable data remains
  rights-pending until the publisher ties terms to that exact dataset.
- Future Connect 2023 is strategic-network context, not a funded-project list;
  its official technical PDF is retained locally but remains marked `Draft` in
  its footer. The final RLTP 2024--2034 is the statutory investment bid, not
  evidence that every listed activity received funding or will be delivered.

## Access policy

- `open/` contains only unmodified article copies with an explicit licence that
  permits sharing; its README records licence evidence and checksums.
- `restricted/` contains citation and acquisition metadata only. Do not commit
  downloaded subscription copies, even when obtained through institutional
  access.
- A free-to-read page is not necessarily licensed for redistribution.
- Credentials are never recorded in this project. An authorised reader signs
  in directly through their institution and keeps any restricted copy outside
  the repository.
