# TODO

Open work on the KYBELE D10.3 evaluation, as of 30 September 2026. Context, rules and history
are in [AGENTS.md](AGENTS.md). Tick items off in the same commit that does the work, and add
new items where they belong.

Owners: **Coord** = the coordinator (Stelios Ninidakis); **SIB** = the SIB team behind the QA
service (Patrick Ruch); **TM** = the trait-mining team (collembola-trait-mining); **Spec** = a
Collembola specialist, still to be named.

## 1. Publish this repository

- [ ] **Coord:** Create the GitHub repository (proposed name `kybele-d103-evaluation`; personal
  account or organisation to be decided) and push `main`.
- [ ] **Coord:** Connect the repository to Zenodo (GitHub integration), then publish release
  `v1.0.0` to get a DOI.
- [ ] Put the DOI and repository URL into `CITATION.cff` (`doi`, `repository-code`), the README
  ("Zenodo DOI: [TBC]") and the D10.3 document (sections 2.5 and References).
- [ ] **Coord:** Complete the authors, affiliations and ORCIDs in `CITATION.cff`. Only the two
  leads are listed now, with no affiliations.
- [ ] **Coord:** Confirm the licences (code MIT, data CC BY 4.0) or change `LICENSE`,
  `LICENSE-DATA` and `CITATION.cff`.
- [ ] **TM:** Add a licence to collembola-trait-mining. Then `trait_extraction_v3.py` can be
  vendored here, instead of downloaded, with its commit noted.
- [ ] **Coord:** Settle the official project name: the D10.3 document says "through Large Language
  Model Extraction", this repository says "through LLM Extraction".

## 2. Close the D10.3 document

The deliverable text is kept by the coordinator. Its remaining `[TBC]` placeholders:

- [ ] **Coord:** Correct every statement that the trait pipeline uses `e2e_sparse_generative`
  (sections 3.2, 4.1, 4.3, 7). Only its genus batch does; the species pipeline runs its own phrase
  search and passes the documents through `doc_refs`. Report the `pipeline` configuration as the
  pipeline's result (README, "The trait pipeline (L2)") and keep the service configurations as
  diagnostics of L1.
- [ ] **Coord:** Add the layer view (L1 service, L2 pipeline, L3 evaluation), the published-table
  check (v3 stores a guild for 4 of 21 held-out species) and the answer-selection finding to
  sections 4–6, with P18–P21 below.
- [ ] **Coord:** Limitations: the treatment benchmark shares 5 species with the pipeline's 330;
  habitat gold classes come from the pipeline's classifier until reviewed; the trophic
  vocabulary extension was built on the gold (report the base-vocabulary figures beside it).

- [ ] **Coord:** Document information: lead beneficiary; authors (names, ORCID, affiliations);
  contractual due date; submission date. The version is still "0.1 draft".
- [ ] **Spec:** Section 2.3, specialist spot-check. Send `spotcheck/KYBELE_D10.3_specialist_spotcheck.xlsx`
  and collect the verdicts, then report the name, the number of items checked and the agreement
  (the Summary sheet computes it). Save the filled workbook as
  `spotcheck/KYBELE_D10.3_specialist_spotcheck_filled.xlsx`.
- [ ] **SIB:** Section 3.1, confirm that BioMoQA-RAG commit `13abd69` (19 August 2026) is the
  version deployed on qa.sibils.org.
- [ ] **SIB:** Section 5.2, confirm the passage window the generative model receives (assumed about
  600 characters chosen by a keyword window).
- [x] ~~**TM:** Section 4.2, reconcile the flagged body sizes: 14 of 27 in the adjudication file
  against 15 (56 %) in the repository summary.~~ Not needed: D10.3 now reports only version 3, so
  version 2 error rates are no longer given (1 October 2026).
- [ ] **Coord:** Section 6.2, the target date for every planned action P1–P17. Also the owner of
  P6–P17, now shown as "[Node]".
- [ ] **Coord:** Section 7, the remaining WP10 deliverables and milestones this work feeds into,
  and the registries to use (bio.tools, ELIXIR).
- [ ] **Coord:** References: GitHub URL and Zenodo DOI of this repository, links to the
  HuggingFace and Zenodo models, and the ELIXIR and LifeWatch ERIC service URLs.
- [ ] Before submission, remove the note "Placeholders in square brackets marked TBC…" at the
  top of the document.

## 3. Benchmarks

- [ ] **Spec:** Curate the population benchmark (`data/population/population_curation.csv`,
  100 species x 3 traits), blind to the pipeline's output, then run
  `make_population_sample.py build`, the runner (`--configs pipeline,e2e_sparse_generative`) and
  `score_pipeline_output.py`. About 2–3 specialist days.
- [ ] **Spec:** Review the negative items (`data/benchmark_negatives.csv`) and the habitat gold
  classes (`reviewed_classes` in `data/curation/traits/habitat_gold_classes.csv`). Then re-score
  and report how many habitat outcomes change.
- [ ] **Spec:** Have two people score the 25 spot-check items independently and report their
  agreement (Cohen's kappa), so the gold has a measured reliability.
- [ ] **TM + Spec:** Expert review of values the v3 rules were not written for: all primary
  trophic guilds and body sizes of v3 outside the 56 adjudicated pairs, and a random 40 habitat
  values. This gives v3's precision on new data.
- [ ] **Spec (optional):** Spot-check the trophic benchmark too, about 20 questions (16 species,
  4 genus level). Extend `scripts/make_spotcheck.py` with a second sheet for this, using the same
  seed.
- [ ] **TM:** Confirm the gold guilds of the 7 trophic questions in the treatment benchmark
  (K235–K248). They are set in `GOLD_GUILDS` in `scripts/score_traits.py` and marked TBC there.
- [ ] Decide on the 4 habitat questions that cannot be scored (K053, K203, K205, K225). Either
  add classes to the habitat vocabulary (see P9) or give them manual gold classes in
  `MANUAL_HABITAT`.
- [ ] Trophic gold completeness: for the questions counted wrong, check whether another sentence
  of the gold document supports the answer (for example Tomocerus minor, P079). If so, add that
  guild to the gold with a note, rebuild and re-score.
- [ ] Oligochaeta: build the same two benchmarks once its resources are ready. Reuse the scripts
  and the curation rules in AGENTS.md section 5.

## 4. Planned actions (D10.3 section 6.2)

Each action is tied to a measured failure. To check an action, re-run the benchmarks and compare
with the "measured" column (see section 5 below).

| # | Owner | Action | Measured before |
|---|---|---|---|
| P1 | SIB | Fix the dense-retrieval generative failure and return an error instead of an empty answer | 102 of 126 trait requests failed, 22 of 102 trophic requests; 0 of 69 succeed when BM25 finds nothing in one collection (fallback to the unfiltered dense index); `/qa/multi` swallows the exception |
| P2 | SIB | For taxon-specific trait questions, rank the Plazi answer first, or rank collections by answer confidence | PMC answer ranked first for 94 of 126 questions |
| P3 | SIB | Enforce the full binomial in every retrieval path, including the keyword fallback, and drop passages whose subject is another taxon | All 20 wrong end-to-end body sizes came from other documents |
| P4 | SIB | Instruct the generative model to quote the stated value, and choose its passage by treatment section rather than keyword overlap | "Not stated" in 43 % of answers; in 14 of 25 body-size cases the value was in the returned passage |
| P5 | SIB | Pass the relevant treatment section to the extractive reader, not the first ~1,500 characters | Body size found 96 % of the time before 1,500 characters, 33 % after |
| P6 | TM | Apply the version 3 habitat rule (an ecological descriptor, not a place) to QA answers, or constrain the reader against place names | Places given as habitats in 38 % of gold-document extractive answers |
| P7 | TM | Ask again against the source text whenever a value rests only on the generated answer, and check each claim against the cited passage | Answers that overstate their source; 14 open expert-review cases |
| P8 | TM | Mine body size, type locality and habitat directly from the structure of Plazi treatments | Body size under-recovered from treatments |
| P9 | TM | Extend the habitat classes (decomposing leaves, anthropized, plant debris, bat guano in a cave's dark zone) and align guilds and classes with the M10.1 vocabularies | 8 of 59 gold habitats not classified automatically |
| P10 | TM | Score literature-mined habitat for all 330 species against BOLD's field-recorded habitat | No habitat error rate today |
| P11 | TM | Ask the reviewers how many habitat values they checked | The 13 habitat failures have no denominator |
| P12 | TM | Run the treatment benchmark, the trophic benchmark and the 56-pair test set on every model, prompt or rule change | Regressions |
| P13 | TM | Finalise container images, sizing and monitoring for joint deployment on ELIXIR and LifeWatch ERIC | Availability |
| P14 | TM | Extend the trophic keywords of `trait_extraction_v3` with litter, roots, carcasses, invertebrates and named fungi and bacteria (through a taxonomy lookup, not a fixed list) | Gold guild recognised in 73 of 102 gold answers; a perfect answer recorded correctly 71 % of the time |
| P15 | TM | Apply the "not stated" rule per sentence, so that a closing caveat does not demote an explicit diet statement | Correct guild lost in 10 of 81 species answers given the source (12 of 67 dense) |
| P16 | TM | Genus classifier: remove "collembola", "mite" and "arthropod" from the predator keywords, and read the answer sentence by sentence | Unstated predator guild added to 5 of 21 genus answers |
| P17 | TM | Report trophic-guild accuracy against a constant "fungi" answer and on non-fungal taxa, and track the named food, not only the guild | A constant "fungi" answer scores 63–75 % on guild |
| P18 | TM | Keep the first answer that does not deny the trait (or read every collection's answer), not the first non-empty one | Stored value correct 46 → 59 of 115 traits, 37 → 44 of 81 species diets when simulated on the same responses |
| P19 | SIB | Under `doc_refs`, order collections by the relevance of their answers, not alphabetically (`sorted()` in `api_server.py`) | Medline listed first whenever present; its "not stated" displaced the treatment's value |
| P20 | TM | Phrase search in PMC full text, not only title, abstract and keywords | Gold diet document reached the reader for 40 % of species questions |
| P21 | TM | Track recall, not only removed errors: score each pipeline version on species outside the expert review and on the population benchmark | v3 stores a guild for 4 of 21 held-out species with a documented diet, against 7 of 10 reviewed ones |
| P22 | TM | Choose the reader per trait: the extractive reader for body size on the pipeline's documents, the generative reader for diet and habitat | Body size on the pipeline's documents: extractive 100 % precision, 62 % recall; generative stored 38 % recall |
| P23 | SIB | Return a confidence for generative answers (token log-probabilities, or a flag for hedged answers), and the passage the model read | `answer_score` is `None` for generative answers; hedged answers are right 76–82 %, plain ones 91–98 % |
| P24 | TM | Store a diet only when both readers agree on the same documents, and send disagreements for review | Agreement: 97–100 % precision at 28–71 % recall; generative alone 91–95 % per question, 58–62 % per label |

- [ ] P1 · [ ] P2 · [ ] P3 · [ ] P4 · [ ] P5 · [ ] P6 · [ ] P7 · [ ] P8 · [ ] P9 · [ ] P10 ·
  [ ] P11 · [ ] P12 · [ ] P13 · [ ] P14 · [ ] P15 · [ ] P16 · [ ] P17 · [ ] P18 · [ ] P19 ·
  [ ] P20 · [ ] P21 · [ ] P22 · [ ] P23 · [ ] P24

The scorer here already works around P15 and P16 for its "guild of the answer" measure. The
"guild recorded by the pipeline" measure deliberately keeps the pipeline's behaviour, so it will
show when P14–P16 land.

## 5. Re-evaluation after a change (P12)

1. Note what changed (service commit, model, prompt, extractor commit, pipeline commit). Run
   `python3 scripts/check_pipeline_sync.py` (add `--commit` for a new pipeline commit) and update
   the copied logic if it fails.
2. Run all benchmarks into new folders with runner v6 (all six configurations, including
   `pipeline`; the negative items too):
   ```bash
   python3 scripts/bench_to_candidates.py data/benchmark_traits.csv  runs/traits_YYYYMMDD/candidates.csv
   python3 scripts/bench_to_candidates.py data/benchmark_trophic.csv runs/trophic_YYYYMMDD/candidates.csv
   python3 scripts/kybele_d103_eval.py --out runs/traits_YYYYMMDD
   python3 scripts/kybele_d103_eval.py --out runs/trophic_YYYYMMDD
   python3 scripts/bench_to_candidates.py data/benchmark_negatives.csv runs/negatives_YYYYMMDD/candidates.csv
   python3 scripts/kybele_d103_eval.py --out runs/negatives_YYYYMMDD
   ```
3. Re-run the same command until the log says every run has a valid answer, or only
   deterministic server errors remain.
4. Score each run with `score.py`, then with `score_traits.py` or `score_trophic.py`, into the run
   folder. Move the folder to `results/` with its log.
5. Re-run `score_pipeline_output.py` on the new pipeline tables and `attribution.py` on the new
   folders.
6. Add a row to the README results tables, and a line to the decision log in AGENTS.md.

## 6. Code hygiene

- [ ] Add a GitHub Actions workflow that compiles the scripts and runs the reproduction check of
  AGENTS.md section 4. It needs `trait_extraction_v3.py`, which can be fetched at the pinned commit.
- [ ] Replace the "upload this file to the chat" messages in `kybele_d103_eval.py`,
  `kybele_trophic_harvest.py` and `kybele_trophic_genus.py` with neutral wording. Update the
  harvester docstring, which describes only two of its query stages.
- [ ] Merge the trophic items of `score_traits.py` into `score_trophic.py`, so that trophic
  scoring has one definition. Re-score the treatment benchmark and note any change.
- [ ] Make `data/curation/traits/build2.py` path-independent, or mark it clearly as a record only.
- [ ] Give the runner a `--limit` option for quick tests.
- [ ] Add `check_pipeline_sync.py` to the CI workflow, so drift in collembola-trait-mining fails
  the build.
