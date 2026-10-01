#!/usr/bin/env python3
"""
Two analyses over the scored runs, on the same items.

1. Is the generative reader more informative than the extractive one?
   Paired comparison on identical documents, in three retrieval settings:
     gold document   doc_extractive        vs doc_generative
     service         e2e_sparse_extractive vs e2e_sparse_generative
     pipeline docs   pipeline_extractive   vs pipeline   (the trait pipeline's phrase search)
   Measures: body size, habitat and diet guild correct; food named; abstaining on negative items;
   and the value trait_extraction_v3 would store from the answer. Exact McNemar tests on the
   discordant pairs. Descriptors: answer length, whether the answer names the species (the
   version 3 extractor binds a value to the species named in the same sentence), denials.

2. Do the curated gold documents and the trait-mining repository improve precision and recall?
   A grid of retrieval (service / pipeline phrase search / curated gold document) x reader x
   output (the answer / the version 3 stored value). Body size and diet pool the answerable
   questions with the negative items: a value is a true positive when it matches the gold and a
   false positive when it is wrong or the question has nothing documented. Precision is also
   given at a share q of unanswerable questions, re-weighting the two item sets:
       P(q) = (1-q)*TP/n_pos / ((1-q)*(TP+FPpos)/n_pos + q*FPneg/n_neg)
   In the pipeline's use, (211 + 40) / 330 = 76 % of diet questions and (264 + 40) / 330 = 92 % of
   body-size questions have no answer (version 3 answers that state no value, plus the 40 species with
   no document), so precision is reported at q = 0.76 and q = 0.92.

3. Generative answers carry no confidence score (the service sets answer_score to None). As a
   proxy, answers are grouped by wording: denies the trait / hedged / plain assertion. The level
   "answer_plain" of the grid keeps only plainly worded generative answers, a second operating
   point that trades recall for precision.

Usage: python3 scripts/reader_comparison.py [--out results/reader_comparison]
Needs scripts/trait_extraction_v3.py.
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import score_traits as st  # noqa: E402
import score_trophic as so  # noqa: E402

SETTINGS = [("gold document", "doc_extractive", "doc_generative"),
            ("service retrieval", "e2e_sparse_extractive", "e2e_sparse_generative"),
            ("pipeline documents", "pipeline_extractive", "pipeline")]
FOLDERS = {  # (benchmark, config) -> results folder
    "traits": {"pipeline": "traits_pipeline", "pipeline_extractive": "traits_pipeline_extractive"},
    "trophic": {"pipeline": "trophic_pipeline", "pipeline_extractive": "trophic_pipeline_extractive"},
    "negatives": {"pipeline_extractive": "negatives_pipeline_extractive"},
}
DEFAULT = {"traits": "traits_main", "trophic": "trophic", "negatives": "negatives"}
HEDGE = re.compile(r"\b(?:however|approximately|about|around|may|might|could|suggest\w*|likely|possibly|"
                   r"probably|appears?|seems?|indicat\w*|presumably|not explicitly|not directly)\b", re.I)


def wilson(k, n):
    return so.wilson(k, n) if n else None


def mcnemar(b, c):
    """Exact two-sided McNemar p-value on b (generative better) and c (extractive better)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def scored(bench, cfg):
    folder = ROOT / "results" / FOLDERS[bench].get(cfg, DEFAULT[bench])
    name = "scored_trophic.csv" if bench == "trophic" else "scored_traits.csv"
    path = folder / name
    if not path.exists():
        return []
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["config"] == cfg]


def items(cfg):
    """Item-level records for one configuration: body size, habitat, diet, negatives."""
    pipe = cfg.startswith("pipeline")
    bench_t = {b["qid"]: b for b in csv.DictReader(open(ROOT / "data/benchmark_traits.csv", encoding="utf-8"))}
    out = []
    for r in scored("traits", cfg):
        if r["trait"] not in ("body_size", "habitat") or r["plazi"] == "unscored":
            continue
        b = bench_t[r["qid"]]
        ans = r["pipeline_answer"] if pipe else r["plazi_answer"]
        outcome = r["pipeline"] if pipe else r["plazi"]
        gc = st.gold_habitat(r["qid"], b["gold_answer"], b["taxon"]) if r["trait"] == "habitat" else None
        stored = st.stored_outcome(ans, r["trait"], b["taxon"], b["gold_answer"], gc)
        out.append({"set": r["trait"], "qid": r["qid"], "taxon": b["taxon"], "answer_text": ans,
                    "answer": outcome, "stored": stored, "food": None, "negative": False})
    for r in scored("trophic", cfg):
        out.append({"set": "diet", "qid": r["qid"], "taxon": r["taxon"], "answer_text": r["answer_text"],
                    "answer": r["answer"], "stored": r["pipeline"], "food": int(r["food_match"]),
                    "negative": False})
    bench_n = {b["qid"]: b for b in csv.DictReader(open(ROOT / "data/benchmark_negatives.csv", encoding="utf-8"))}
    neg_cfg_rows = scored("negatives", cfg)
    for r in neg_cfg_rows:
        b = bench_n[r["qid"]]
        ans = r["pipeline_answer"] if pipe else r["plazi_answer"]
        qt = b["question_type"]
        if qt == "trophic_guild":
            # read like the answerable diet questions: any feeding group the answer states (sentence-level reader)
            # counts as a value given; the stored value is the pipeline's reading of the answer
            given = bool(so.answer_guilds(ans, b["taxon"]))
            stored_given = bool(so.pipeline_guilds(ans, b["taxon"], "species"))
        else:
            given = (r["pipeline"] if pipe else r["plazi"]) == "wrong"
            stored_given = st.negative(st.stored_outcome(ans, qt, b["taxon"], "", None, set())) == "wrong"
        out.append({"set": "body_size_negative" if qt == "body_size" else "diet_negative", "qid": r["qid"],
                    "taxon": b["taxon"], "answer_text": ans, "answer": "wrong" if given else "correct",
                    "stored": "wrong" if stored_given else "correct", "food": None, "negative": True})
    return out


def names_species(text, taxon):
    g, e = taxon.split()[0], taxon.split()[-1]
    return bool(re.search(rf"\b{re.escape(g)}\s+{re.escape(e)}\b|\b{g[0]}\.\s*{re.escape(e)}\b", text or ""))


DENY = re.compile(r"\bno (?:specific |explicit |direct |detailed |clear )?(?:\w+ ){0,2}(?:information|details?|data|"
                  r"mention|description)\b|\bnot (?:explicitly |specifically |directly |clearly )?(?:mentioned|stated|"
                  r"specified|given|provided|available|reported|described|discussed|documented)\b|\bdo(?:es)? not "
                  r"(?:mention|specify|state|provide|describe|contain|include)\b|\bunknown\b|\bnot known\b", re.I)
VALUE = re.compile(r"\d\s*(?:mm|µm|μm)\b|\bfeeds? (?:on|upon)\b|\bfed (?:on|upon)\b|\bdiet (?:consists|includes|"
                   r"comprises)\b|\bgraz\w* on\b|\bpreys? (?:on|upon)\b|\b(?:inhabits|lives in|found in|occurs in)\b", re.I)


def wording(text):
    """denies: says the trait is not stated and states no value; hedged: a value with a qualifier, or a
    denial followed by a value ("not stated; however ..."); plain: a value stated without qualifier."""
    if not (text or "").strip():
        return "empty"
    deny, value = bool(DENY.search(text)), bool(VALUE.search(text))
    if deny and not value:
        return "denies"
    return "hedged" if (deny or HEDGE.search(text)) else "plain"


def rate(rows, key, value="correct"):
    k = sum(r[key] == value for r in rows)
    return {"k": k, "n": len(rows), "rate": round(k / len(rows), 3) if rows else None, "ci95": wilson(k, len(rows))}


def pr(pos, neg, key, qs=(0.5, 0.76, 0.92)):
    tp = sum(r[key] == "correct" for r in pos)
    fp_pos = sum(r[key] == "wrong" for r in pos)
    fp_neg = sum(r[key] == "wrong" for r in neg)
    n_pos, n_neg = len(pos), len(neg)
    out = {"n_pos": n_pos, "n_neg": n_neg, "tp": tp, "fp_wrong": fp_pos, "fp_negative": fp_neg,
           "recall": round(tp / n_pos, 3), "recall_ci95": wilson(tp, n_pos),
           "precision": round(tp / (tp + fp_pos + fp_neg), 3) if tp + fp_pos + fp_neg else None,
           "precision_ci95": wilson(tp, tp + fp_pos + fp_neg) if tp + fp_pos + fp_neg else None}
    p, r = out["precision"], out["recall"]
    out["f1"] = round(2 * p * r / (p + r), 3) if p and r else 0.0
    for q in qs:
        num = (1 - q) * tp / n_pos
        den = (1 - q) * (tp + fp_pos) / n_pos + q * fp_neg / n_neg
        out[f"precision_at_q{q}"] = round(num / den, 3) if den else None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "results/reader_comparison"))
    args = ap.parse_args()
    data = {cfg: items(cfg) for _, e, g in SETTINGS for cfg in (e, g)}
    for cfg, rows in data.items():  # generative answers withheld unless stated plainly
        for r in rows:
            withheld = wording(r["answer_text"]) != "plain"
            r["answer_plain"] = (("correct" if r["negative"] else "no_answer") if withheld else r["answer"])
    summary = {"readers": {}, "precision_recall": {}, "wording": {}}

    # 1. Paired reader comparison.
    measures = [("body size correct", "body_size", "answer"), ("habitat correct", "habitat", "answer"),
                ("diet guild correct", "diet", "answer"), ("food named", "diet", "food"),
                ("no body size given (negative)", "body_size_negative", "answer"),
                ("no diet given (negative)", "diet_negative", "answer"),
                ("body size stored correctly", "body_size", "stored"),
                ("habitat stored correctly", "habitat", "stored"),
                ("diet guild stored correctly", "diet", "stored")]
    for setting, ecfg, gcfg in SETTINGS:
        E = {(r["set"], r["qid"]): r for r in data[ecfg]}
        G = {(r["set"], r["qid"]): r for r in data[gcfg]}
        res = {}
        for label, s, key in measures:
            common = sorted(k for k in E if k[0] == s and k in G)
            if not common:
                continue
            ok = (lambda r: r["food"] == 1) if key == "food" else (lambda r, key=key: r[key] == "correct")
            e_ok = [ok(E[k]) for k in common]
            g_ok = [ok(G[k]) for k in common]
            b = sum(g and not e for e, g in zip(e_ok, g_ok))
            c = sum(e and not g for e, g in zip(e_ok, g_ok))
            n = len(common)
            res[label] = {"n": n, "extractive": round(sum(e_ok) / n, 3), "generative": round(sum(g_ok) / n, 3),
                          "extractive_ci95": wilson(sum(e_ok), n), "generative_ci95": wilson(sum(g_ok), n),
                          "generative_only": b, "extractive_only": c, "mcnemar_p": round(mcnemar(b, c), 4)}
        desc = {}
        for name, cfg in (("extractive", ecfg), ("generative", gcfg)):
            pos = [r for r in data[cfg] if not r["negative"]]
            words = sorted(len((r["answer_text"] or "").split()) for r in pos)
            desc[name] = {"median_words": words[len(words) // 2] if words else None,
                          "names_species": round(sum(names_species(r["answer_text"], r["taxon"]) for r in pos) / len(pos), 3),
                          "denies": round(sum(wording(r["answer_text"]) == "denies" for r in pos) / len(pos), 3)}
        res["descriptors"] = desc
        summary["readers"][setting] = res

    # 2. Precision and recall grid.
    for trait, pos_set, neg_set in (("body size", "body_size", "body_size_negative"), ("diet", "diet", "diet_negative")):
        grid = {}
        for setting, ecfg, gcfg in SETTINGS:
            for reader, cfg in (("extractive", ecfg), ("generative", gcfg)):
                pos = [r for r in data[cfg] if r["set"] == pos_set]
                neg = [r for r in data[cfg] if r["set"] == neg_set]
                if not pos or not neg:
                    continue
                for level in ("answer", "stored") + (("answer_plain",) if reader == "generative" else ()):
                    grid[f"{setting} | {reader} | {level}"] = pr(pos, neg, level)
        summary["precision_recall"][trait] = grid
    hab = {}
    for setting, ecfg, gcfg in SETTINGS:
        for reader, cfg in (("extractive", ecfg), ("generative", gcfg)):
            rows = [r for r in data[cfg] if r["set"] == "habitat"]
            for level in ("answer", "stored"):
                hab[f"{setting} | {reader} | {level}"] = {"recall": rate(rows, level),
                                                          "wrong": rate(rows, level, "wrong")}
    summary["precision_recall"]["habitat (no negative items: recall and wrong values only)"] = hab

    # 3. Generative answers by wording.
    for setting, _, gcfg in SETTINGS:
        tab = defaultdict(lambda: Counter())
        for r in data[gcfg]:
            w = wording(r["answer_text"])
            kind = "negative" if r["negative"] else "answerable"
            tab[(kind, w)]["n"] += 1
            tab[(kind, w)]["correct"] += r["answer"] == "correct"
        summary["wording"][setting] = {f"{k} | {w}": {"n": c["n"], "correct": c["correct"],
                                                      "rate": round(c["correct"] / c["n"], 3)}
                                       for (k, w), c in sorted(tab.items())}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(out / "summary.json", "w"), indent=2)
    with open(out / "items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["config", "set", "qid", "answer", "stored", "food", "wording", "names_species"])
        for cfg, rows in data.items():
            for r in rows:
                w.writerow([cfg, r["set"], r["qid"], r["answer"], r["stored"], r["food"], wording(r["answer_text"]),
                            int(names_species(r["answer_text"], r["taxon"]))])

    for setting, res in summary["readers"].items():
        print(f"\n== {setting}: extractive vs generative")
        for label, m in res.items():
            if label == "descriptors":
                print("   ", m)
                continue
            print(f"  {label:32} n={m['n']:3}  ext {m['extractive']:.2f}  gen {m['generative']:.2f}  "
                  f"gen-only {m['generative_only']:3} ext-only {m['extractive_only']:3}  p={m['mcnemar_p']}")
    for trait, grid in summary["precision_recall"].items():
        if trait.startswith("habitat"):
            continue
        print(f"\n== precision/recall: {trait}")
        for k, v in grid.items():
            print(f"  {k:46} P={v['precision']}  R={v['recall']}  F1={v['f1']}  P@q0.76={v['precision_at_q0.76']}  "
                  f"P@q0.92={v['precision_at_q0.92']}  "
                  f"(TP {v['tp']}, FP wrong {v['fp_wrong']}, FP negative {v['fp_negative']})")
    print("\n== generative answers by wording")
    for setting, tab in summary["wording"].items():
        print(" ", setting, tab)


if __name__ == "__main__":
    main()
