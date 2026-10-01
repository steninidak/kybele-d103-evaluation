#!/usr/bin/env python3
"""
Population benchmark: gold for the species the KYBELE trait pipeline actually processes.

The treatment benchmark shares only 5 of its 126 species with the pipeline's 330 BOLD species,
and neither benchmark contains questions whose answer is that nothing is documented. This
benchmark samples the pipeline's own species and asks all three trait questions for each, so
that the pipeline can be scored on precision, recall and correct abstention where it is used.

Stage 1 (sample):  python3 scripts/make_population_sample.py sample [--n 100] [--seed 2026]
  Draws n of the 330 species (the SEED list of kybele_trophic_harvest.py) at random and writes
  data/population/population_curation.csv: one row per species and trait, with the documents
  that mention the binomial anywhere SIBiLS indexes it (Medline title and abstract, PMC title,
  abstract and full text, Plazi treatment title and text; up to 50 per collection) as candidate
  sources. Curators see no output of the pipeline or of the QA service.

Curation (by specialists, blind to the pipeline's output), per row:
  gold_status           documented | not_documented
  gold_answer           verbatim value(s), alternatives separated by " || " (documented rows)
  gold_guilds           Potapov et al. 2022 guilds, "|"-separated (trophic rows)
  gold_habitat_classes  habitat classes of trait_extraction_v3, "|"-separated (habitat rows)
  docid, gold_context   the source document and the sentence that states the value
  curator, curation_note
  A row is not_documented when none of the candidate documents states the trait for this
  species. Statements about the genus or about Collembola in general do not count.

Stage 2 (build):   python3 scripts/make_population_sample.py build
  Writes data/benchmark_population.csv from the curated rows (gold_answer NOT_DOCUMENTED for
  not_documented rows), in the columns of the other benchmarks. Run it with the runner
  (pipeline and end-to-end configurations; there is no single gold document for doc_*), score it
  with score_traits.py, and score the published pipeline table with score_pipeline_output.py.

Standard library only.
"""

import argparse
import csv
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEARCH_URL = "https://biodiversitypmc.sibils.org/api/search"
UA = "KYBELE-D10.3-evaluation/1.0 (ELIXIR KYBELE project)"
FIELDS = {"medline": ["title", "abstract"], "pmc": ["title", "abstract", "full_text"],
          "plazi": ["treatment_title", "text"]}
QUESTIONS = [("body_size", "What is the body length of {sp}?"), ("habitat", "What is the habitat of {sp}?"),
             ("trophic_guild", "What does {sp} feed on?")]
CURATION = ROOT / "data/population/population_curation.csv"
BENCH = ROOT / "data/benchmark_population.csv"
CUR_FIELDS = ["qid", "taxon", "genus", "question_type", "question", "n_candidate_docs", "candidate_docs",
              "gold_status", "gold_answer", "gold_guilds", "gold_habitat_classes", "docid", "gold_context",
              "curator", "curation_note"]


def species_list():
    src = (ROOT / "scripts/kybele_trophic_harvest.py").read_text(encoding="utf-8")
    seed = json.loads(re.search(r"SEED = json.loads\(r'''(.*?)'''\)", src, re.S).group(1))
    return sorted(seed["species"])


def candidate_docs(binomial, n=50):
    docs = []
    for col, fields in FIELDS.items():
        esq = {"query": {"bool": {"must": [{"multi_match": {"query": binomial, "type": "phrase", "fields": fields}}]}},
               "_source": ["title", "treatment_title", "article-title"]}
        body = urllib.parse.urlencode({"jq": json.dumps(esq)}).encode("utf-8")
        url = SEARCH_URL + "?" + urllib.parse.urlencode({"col": col, "n": n})
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                for h in ((d.get("elastic_output") or {}).get("hits") or {}).get("hits") or []:
                    s = h.get("_source") or {}
                    title = s.get("title") or s.get("treatment_title") or s.get("article-title") or ""
                    docs.append(f"{col}:{h.get('_id')} {re.sub(r'[|;]', ' ', title)[:90]}")
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
    return docs


def sample(n, seed):
    sp = species_list()
    if len(sp) != 330:
        print(f"warning: {len(sp)} species in the SEED list, expected 330", file=sys.stderr)
    chosen = sorted(random.Random(seed).sample(sp, n))
    rows = []
    for i, s in enumerate(chosen, 1):
        docs = candidate_docs(s)
        print(f"  {i:3d}/{n} {s}: {len(docs)} candidate documents", file=sys.stderr)
        for qt, tmpl in QUESTIONS:
            rows.append({"taxon": s, "genus": s.split()[0], "question_type": qt, "question": tmpl.format(sp=s),
                         "n_candidate_docs": len(docs), "candidate_docs": " | ".join(docs)})
        time.sleep(0.3)
    for i, r in enumerate(rows, 1):
        r["qid"] = f"Q{i:03d}"
    CURATION.parent.mkdir(parents=True, exist_ok=True)
    with open(CURATION, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CUR_FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows ({n} species x 3 traits) to {CURATION}", file=sys.stderr)


def build():
    rows = list(csv.DictReader(open(CURATION, encoding="utf-8")))
    out, pending = [], 0
    for r in rows:
        status = (r.get("gold_status") or "").strip().lower()
        if status not in ("documented", "not_documented"):
            pending += 1
            continue
        if status == "documented" and not r["gold_answer"].strip():
            sys.exit(f"{r['qid']}: documented but no gold_answer")
        out.append({"qid": r["qid"], "docid": r["docid"], "taxon": r["taxon"], "taxon_rank": "species",
                    "family": "", "question_type": r["question_type"], "question": r["question"],
                    "gold_answer": r["gold_answer"].strip() if status == "documented" else "NOT_DOCUMENTED",
                    "gold_guilds": r["gold_guilds"], "gold_habitat_classes": r["gold_habitat_classes"],
                    "gold_context": r["gold_context"], "answer_offset": "", "text_length": "",
                    "curation_note": f"{r['curator']}: {r['curation_note']}".strip(": ")})
    with open(BENCH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["qid"])
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} curated items to {BENCH}; {pending} rows still to curate", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["sample", "build"])
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    sample(args.n, args.seed) if args.stage == "sample" else build()


if __name__ == "__main__":
    main()
