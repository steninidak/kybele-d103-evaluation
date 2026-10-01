#!/usr/bin/env python3
"""
Convert data/benchmark_traits.csv or data/benchmark_trophic.csv into the candidates.csv that
kybele_d103_eval.py reads.

The runner expects the column names it writes itself (species instead of taxon, plus
candidate_answer and curation) and a gold_answer column, which marks the file as curated.
candidate_answer is set to the first gold alternative and curation is left empty; neither
is used by the runner or the scorers.

Usage: python3 scripts/bench_to_candidates.py data/benchmark_traits.csv kybele_d103/candidates.csv
       python3 scripts/bench_to_candidates.py data/benchmark_trophic.csv kybele_trophic_eval/candidates.csv
"""

import csv
import os
import sys

FIELDS = ["qid", "docid", "species", "treatment_title", "family", "article_title", "doi",
          "treatment_uri", "question_type", "question", "candidate_answer", "gold_context",
          "answer_offset", "text_length", "gold_answer", "curation", "curation_note", "taxon_rank"]


def main(bench_path, out_path):
    rows = list(csv.DictReader(open(bench_path, encoding="utf-8")))
    out = []
    for r in rows:
        c = {k: r.get(k, "") for k in FIELDS}
        c["species"] = r["taxon"]
        c["taxon_rank"] = r.get("taxon_rank") or "species"  # the pipeline configuration asks genera differently
        c["treatment_title"] = r.get("treatment_title") or r.get("source_title", "")  # fallback doc_ref
        c["article_title"] = r.get("article_title") or r.get("source_title", "")
        c["candidate_answer"] = r["gold_answer"].split("||")[0].strip()
        out.append(c)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} questions to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
