#!/usr/bin/env python3
"""
Write the habitat gold-class review sheet, data/curation/traits/habitat_gold_classes.csv.

The gold habitat classes of the treatment benchmark are, except for four set by hand
(MANUAL_HABITAT in score_traits.py), produced by running the trait pipeline's own classifier
(trait_extraction_v3.extract_habitat) on the gold span. The same classifier then reads the
answers, so its mistakes can agree on both sides. This sheet lets a reviewer set the classes
independently: fill reviewed_classes ("|"-separated classes of trait_extraction_v3, or "none"
when the gold names no class), and score_traits.py uses them instead of the classifier's.

Re-running keeps the reviewer columns of rows already in the sheet.

Usage: python3 scripts/make_habitat_review.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_traits as st  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/curation/traits/habitat_gold_classes.csv"
FIELDS = ["qid", "taxon", "gold_answer", "classifier_classes", "manual_classes", "all_classes",
          "reviewed_classes", "reviewer", "note"]


def main():
    keep = {}
    if OUT.exists():
        keep = {r["qid"]: r for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    classes = sorted(set(st.tx.HABITAT_KEYWORDS) if hasattr(st.tx, "HABITAT_KEYWORDS") else set())
    rows = []
    for b in csv.DictReader(open(ROOT / "data/benchmark_traits.csv", encoding="utf-8")):
        if b["question_type"] != "habitat":
            continue
        clf = set()
        for alt in b["gold_answer"].split("||"):
            clf |= st.habitat_classes(alt.strip(), b["taxon"])
        prev = keep.get(b["qid"], {})
        rows.append({"qid": b["qid"], "taxon": b["taxon"], "gold_answer": b["gold_answer"],
                     "classifier_classes": "|".join(sorted(clf)),
                     "manual_classes": "|".join(sorted(st.MANUAL_HABITAT.get(b["qid"], set()))),
                     "all_classes": "|".join(classes),
                     "reviewed_classes": prev.get("reviewed_classes", ""), "reviewer": prev.get("reviewer", ""),
                     "note": prev.get("note", "")})
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} habitat rows to {OUT}")


if __name__ == "__main__":
    main()
