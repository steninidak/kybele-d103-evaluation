#!/usr/bin/env python3
"""
Stricter measures for the D10.3 runs, following trait-extraction and LLM-evaluation practice.

1. Numerical error for body size (as for numerical traits in Domazetoski et al. 2025, Applications
   in Plant Sciences). Pass/fail within 2 % hides how far a wrong value is from the truth. For
   every answer that states a value: the relative error of the stated value closest to a gold value,
   the normalised mean absolute error (NMAE = sum |v - g| / sum g), and the share within 2, 10 and
   25 %. Values stated for negative items (nothing documented) are counted separately.

2. Label-level precision and recall for the categorical traits (feeding group, habitat class), as
   per-trait and per-fact precision/recall in Domazetoski et al. 2025 and Keck et al. 2025. The
   per-question measure used elsewhere counts an answer as correct when any of its labels matches,
   so an answer with one right and two wrong labels counts as correct. Here every label given is
   scored: precision = labels given that are in the gold / labels given (labels given for negative
   items count as false); recall = gold labels recovered / gold labels. "microbivore" is expanded to
   fungivore and bacterivore on both sides, as in the scorers. Habitat has no negative items, and its
   gold classes come from the pipeline's classifier until reviewed (see AGENTS.md section 6).

3. Confidence and selective answering (as self-reported confidence is used to prioritise LLM
   assignments in Münch et al. 2026, Genome Biology): accuracy among the values a system gives,
   against the share of all questions (answerable and negative) it gives a value for, when it only
   answers above a confidence level. Three signals, on identical documents:
     - the extractive reader's answer score (a curve);
     - the generative answer's wording: plain, then also hedged (points);
     - agreement: the generative value is kept only when the extractive reader, on the same
       documents, gives an agreeing value (body size within 2 %; overlapping feeding groups).

4. Bootstrap 95 % intervals (2,000 resamples of questions, answerable and negative items resampled
   separately, seed 2026) for the precision and recall of every configuration and output level.

Usage: python3 scripts/rigor_analysis.py [--out results/rigor]
Needs scripts/trait_extraction_v3.py.
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import reader_comparison as rc  # noqa: E402
import score_traits as st  # noqa: E402
import score_trophic as so  # noqa: E402

CONFIGS = ["doc_extractive", "doc_generative", "e2e_sparse_extractive", "e2e_sparse_generative",
           "pipeline_extractive", "pipeline"]
SETTINGS = rc.SETTINGS  # (name, extractive config, generative config)
RUNS = {"traits": {"pipeline": "traits_pipeline", "pipeline_extractive": "traits_pipeline_extractive"},
        "trophic": {"pipeline": "trophic_pipeline", "pipeline_extractive": "trophic_pipeline_extractive"},
        "negatives": {"pipeline_extractive": "negatives_pipeline_extractive"}}
DEFAULT = {"traits": "traits_main", "trophic": "trophic", "negatives": "negatives"}
B = 2000
SEED = 2026


def expand(s):
    s = set(s)
    return s | {"fungivore", "bacterivore"} if "microbivore" in s else s


def runs(bench, cfg):
    path = ROOT / "results" / RUNS[bench].get(cfg, DEFAULT[bench]) / "runs.jsonl"
    latest = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if not r.get("error") and r.get("response") and r["config"] == cfg:
                latest[r["qid"]] = r["response"]
    return latest


def first_answer_score(resp):
    for c in resp.get("collection_results") or []:
        a = (c.get("answers") or [{}])[0]
        if a.get("answer"):
            return a.get("answer_score")
    return None


def plazi_score(resp):
    for c in resp.get("collection_results") or []:
        if c.get("collection") == "plazi":
            return (c.get("answers") or [{}])[0].get("answer_score")
    return None


def best_score(resp):
    s = [(c.get("answers") or [{}])[0].get("answer_score") or 0.0 for c in resp.get("collection_results") or []
         if (c.get("answers") or [{}])[0].get("answer")]
    return max(s) if s else None


def score_of(bench, cfg, resp):
    """The score of the answer that is scored for this configuration (None for generative answers)."""
    if resp is None:
        return None
    if cfg.startswith("pipeline"):
        return first_answer_score(resp) if bench != "trophic" else first_answer_score(resp)
    return best_score(resp) if bench == "trophic" else plazi_score(resp)


def load(cfg):
    """Item records with gold, predicted values or labels, outcome, confidence and wording."""
    bench_t = {b["qid"]: b for b in csv.DictReader(open(ROOT / "data/benchmark_traits.csv", encoding="utf-8"))}
    bench_n = {b["qid"]: b for b in csv.DictReader(open(ROOT / "data/benchmark_negatives.csv", encoding="utf-8"))}
    troph = {r["qid"]: r for r in rc.scored("trophic", cfg)}
    rt, ro, rn = runs("traits", cfg), runs("trophic", cfg), runs("negatives", cfg)
    out = []
    for r in rc.items(cfg):
        s, q, sp, ans = r["set"], r["qid"], r["taxon"], r["answer_text"] or ""
        rec = dict(r, wording=rc.wording(ans))
        if s == "body_size":
            g = st.gold_values(bench_t[q]["gold_answer"])
            rec.update(gold_vals=sorted(g), vals=st.values_mm(ans),
                       stored_vals=st._range_values(st.tx.extract_body_size(ans, sp)["range_mm"]),
                       score=score_of("traits", cfg, rt.get(q)))
        elif s == "body_size_negative":
            rec.update(gold_vals=[], vals=st.values_mm(ans),
                       stored_vals=st._range_values(st.tx.extract_body_size(ans, sp)["range_mm"]),
                       score=score_of("negatives", cfg, rn.get(q)))
        elif s == "habitat":
            rec.update(gold_labels=sorted(st.gold_habitat(q, bench_t[q]["gold_answer"], sp)),
                       labels=sorted(st.habitat_classes(ans, sp)),
                       stored_labels=sorted(st.tx.extract_habitat(ans, sp)["habitats"]),
                       score=score_of("traits", cfg, rt.get(q)))
        elif s == "diet":
            t = troph[q]
            rec.update(gold_labels=sorted(expand(filter(None, t["gold_guilds"].split("|")))),
                       labels=sorted(expand(so.answer_guilds(ans, sp))),
                       stored_labels=sorted(expand(so.pipeline_guilds(ans, sp, t["rank"]))),
                       score=score_of("trophic", cfg, ro.get(q)))
        elif s == "diet_negative":
            rec.update(gold_labels=[], labels=sorted(expand(so.answer_guilds(ans, sp))),
                       stored_labels=sorted(expand(so.pipeline_guilds(ans, sp, "species"))),
                       score=score_of("negatives", cfg, rn.get(q)))
        out.append(rec)
    return out


# ---------------------------------------------------------------------------

def rel_err(vals, gold):
    if not vals or not gold:
        return None
    return min((abs(v - g) / g, v, g) for v in vals for g in gold)


def numeric_error(items, key):
    pos = [r for r in items if r["set"] == "body_size"]
    neg = [r for r in items if r["set"] == "body_size_negative"]
    errs = [rel_err(r[key], r["gold_vals"]) for r in pos]
    errs = [e for e in errs if e is not None]
    if not errs:
        return {"n_answerable": len(pos), "n_with_value": 0}
    re = sorted(e[0] for e in errs)
    nmae = sum(abs(v - g) for _, v, g in errs) / sum(g for _, _, g in errs)
    wrong = [e for e in errs if e[0] > 0.02 + 1e-9]
    nmae_wrong = (sum(abs(v - g) for _, v, g in wrong) / sum(g for _, _, g in wrong)) if wrong else None
    return {"n_answerable": len(pos), "n_with_value": len(errs),
            "within_2pct": round(sum(e <= 0.02 for e in re) / len(re), 3),
            "within_10pct": round(sum(e <= 0.10 for e in re) / len(re), 3),
            "within_25pct": round(sum(e <= 0.25 for e in re) / len(re), 3),
            "median_rel_error": round(re[len(re) // 2], 4), "nmae": round(nmae, 3),
            "n_wrong": len(wrong), "wrong_beyond_25pct": sum(e[0] > 0.25 for e in wrong),
            "nmae_wrong_only": round(nmae_wrong, 3) if nmae_wrong is not None else None,
            "negatives_with_value": sum(bool(r[key]) for r in neg), "n_negatives": len(neg),
            "rel_errors": [round(e, 5) for e in re]}


def label_counts(items, pos_set, neg_set, key):
    """Per item: (labels given, given that are correct, gold labels, gold recovered)."""
    rows = []
    for r in items:
        if r["set"] not in (pos_set, neg_set):
            continue
        pred, gold = set(r[key]), set(r["gold_labels"])
        rows.append((r["set"] == neg_set, len(pred), len(pred & gold), len(gold), len(gold & pred)))
    return rows


def micro(rows):
    given = sum(r[1] for r in rows)
    ok = sum(r[2] for r in rows)
    gold = sum(r[3] for r in rows)
    rec = sum(r[4] for r in rows)
    p = ok / given if given else None
    r_ = rec / gold if gold else None
    f = 2 * p * r_ / (p + r_) if p and r_ else 0.0
    return p, r_, f, given, gold


def boot(rows, fn, rng):
    pos = [r for r in rows if not r[0]]
    neg = [r for r in rows if r[0]]
    stats = []
    for _ in range(B):
        sample = [rng.choice(pos) for _ in pos] + [rng.choice(neg) for _ in neg]
        stats.append(fn(sample))
    out = []
    for i in range(len(stats[0])):
        v = sorted(x[i] for x in stats if x[i] is not None)
        out.append([round(v[int(0.025 * len(v))], 3), round(v[int(0.975 * len(v)) - 1], 3)] if v else None)
    return out


def value_rows(items, key, pos_set="body_size", neg_set="body_size_negative"):
    """Body size as one fact per question: (negative, given, correct, gold=1 for answerable, recovered)."""
    rows = []
    for r in items:
        if r["set"] == pos_set:
            e = rel_err(r[key], r["gold_vals"])
            ok = e is not None and e[0] <= 0.02 + 1e-9
            rows.append((False, int(bool(r[key])), int(ok), 1, int(ok)))
        elif r["set"] == neg_set:
            rows.append((True, int(bool(r[key])), 0, 0, 0))
    return rows


def diet_question_rows(items, key):
    """Diet as one fact per question (correct when any label matches), for the lenient measure."""
    rows = []
    for r in items:
        if r["set"] == "diet":
            ok = bool(set(r[key]) & set(r["gold_labels"]))
            rows.append((False, int(bool(r[key])), int(ok), 1, int(ok)))
        elif r["set"] == "diet_negative":
            rows.append((True, int(bool(r[key])), 0, 0, 0))
    return rows


def selective(items_e, items_g, kind):
    """Accuracy among values given against the share of all questions given a value."""
    if kind == "body":
        pos_s, neg_s = "body_size", "body_size_negative"
        ok = lambda r, key="vals": (rel_err(r[key], r["gold_vals"]) or (9,))[0] <= 0.02 + 1e-9
        has = lambda r, key="vals": bool(r[key])
        agree = lambda a, b: bool(a["vals"]) and bool(b["vals"]) and any(
            abs(x - y) <= 0.02 * max(x, y) for x in a["vals"] for y in b["vals"])
    else:
        pos_s, neg_s = "diet", "diet_negative"
        ok = lambda r, key="labels": bool(set(r[key]) & set(r["gold_labels"]))
        has = lambda r, key="labels": bool(r[key])
        agree = lambda a, b: bool(set(a["labels"]) & set(b["labels"]))
    E = {(r["set"], r["qid"]): r for r in items_e if r["set"] in (pos_s, neg_s)}
    G = {(r["set"], r["qid"]): r for r in items_g if r["set"] in (pos_s, neg_s)}
    keys = sorted(set(E) & set(G))
    n = len(keys)
    n_pos = sum(k[0] == pos_s for k in keys)

    def point(chosen):  # chosen: list of (record, correct?)
        given = len(chosen)
        correct = sum(c for _, c in chosen)
        return {"coverage": round(given / n, 3), "accuracy": round(correct / given, 3) if given else None,
                "recall": round(correct / n_pos, 3), "given": given, "correct": correct}

    out = {"n_questions": n, "n_answerable": n_pos}
    # extractive score curve
    ext = sorted(((E[k].get("score") or 0.0), k) for k in keys if has(E[k]))
    curve = []
    for i in range(len(ext)):
        chosen = [(E[k], k[0] == pos_s and ok(E[k])) for _, k in ext[i:]]
        curve.append({"threshold": round(ext[i][0], 4), **point(chosen)})
    out["extractive_score_curve"] = curve
    out["extractive_all"] = point([(E[k], k[0] == pos_s and ok(E[k])) for k in keys if has(E[k])])
    out["generative_all"] = point([(G[k], k[0] == pos_s and ok(G[k])) for k in keys if has(G[k])])
    out["generative_plain_or_hedged"] = point([(G[k], k[0] == pos_s and ok(G[k])) for k in keys
                                               if has(G[k]) and G[k]["wording"] in ("plain", "hedged")])
    out["generative_plain"] = point([(G[k], k[0] == pos_s and ok(G[k])) for k in keys
                                     if has(G[k]) and G[k]["wording"] == "plain"])
    out["readers_agree"] = point([(G[k], k[0] == pos_s and ok(G[k])) for k in keys
                                  if has(G[k]) and agree(E[k], G[k])])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "results/rigor"))
    args = ap.parse_args()
    rng = random.Random(SEED)
    data = {cfg: load(cfg) for cfg in CONFIGS}
    summary = {"numeric_error": {}, "labels": {}, "body_size_facts": {}, "selective": {}}

    for cfg, items in data.items():
        for level, key in (("answer", "vals"), ("stored", "stored_vals")):
            summary["numeric_error"][f"{cfg} | {level}"] = numeric_error(items, key)
            rows = value_rows(items, key)
            p, r_, f, given, gold = micro(rows)
            ci = boot(rows, lambda s: micro(s)[:3], rng)
            summary["body_size_facts"][f"{cfg} | {level}"] = {
                "precision": round(p, 3) if p is not None else None, "recall": round(r_, 3), "f1": round(f, 3),
                "precision_ci95": ci[0], "recall_ci95": ci[1], "f1_ci95": ci[2], "values_given": given}
        for trait, pos_s, neg_s in (("diet", "diet", "diet_negative"), ("habitat", "habitat", None)):
            for level, key in (("answer", "labels"), ("stored", "stored_labels")):
                rows = label_counts(items, pos_s, neg_s or "__none__", key)
                p, r_, f, given, gold = micro(rows)
                ci = boot(rows, lambda s: micro(s)[:3], rng) if any(r[0] for r in rows) else \
                    boot(rows + [(True, 0, 0, 0, 0)], lambda s: micro(s)[:3], rng)
                lenient = [r for r in items if r["set"] == pos_s]
                lenient_ok = sum(r["answer" if level == "answer" else "stored"] == "correct" for r in lenient)
                summary["labels"][f"{trait} | {cfg} | {level}"] = {
                    "micro_precision": round(p, 3) if p is not None else None, "micro_recall": round(r_, 3),
                    "micro_f1": round(f, 3), "precision_ci95": ci[0], "recall_ci95": ci[1],
                    "labels_given": given, "gold_labels": gold,
                    "per_question_any_overlap": round(lenient_ok / len(lenient), 3)}

    # per-question diet measure with intervals, and the constant "fungi" baseline at both levels
    summary["diet_questions"] = {}
    for cfg, items in data.items():
        for level, key in (("answer", "labels"), ("stored", "stored_labels")):
            rows = diet_question_rows(items, key)
            p, r_, f, given, gold = micro(rows)
            ci = boot(rows, lambda s: micro(s)[:3], rng)
            summary["diet_questions"][f"{cfg} | {level}"] = {
                "precision": round(p, 3) if p is not None else None, "recall": round(r_, 3), "f1": round(f, 3),
                "precision_ci95": ci[0], "recall_ci95": ci[1]}
    summary["fungi_baseline"] = {}
    for gold_kind, cfg in (("per-question gold (gold document)", "doc_generative"),
                           ("taxon gold (end to end, pipeline)", "e2e_sparse_generative")):
        items = [dict(r, labels=["fungivore"]) for r in data[cfg] if r["set"] in ("diet", "diet_negative")]
        lab = micro(label_counts(items, "diet", "diet_negative", "labels"))
        q = micro(diet_question_rows(items, "labels"))
        summary["fungi_baseline"][gold_kind] = {
            "label_precision": round(lab[0], 3), "label_recall": round(lab[1], 3), "label_f1": round(lab[2], 3),
            "question_precision": round(q[0], 3), "question_recall": round(q[1], 3)}

    for setting, ecfg, gcfg in SETTINGS:
        summary["selective"][f"body size | {setting}"] = selective(data[ecfg], data[gcfg], "body")
        summary["selective"][f"diet | {setting}"] = selective(data[ecfg], data[gcfg], "diet")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(summary, open(out / "summary.json", "w"), indent=1)

    print("== body size: numerical error of the closest stated value (answers with a value)")
    for k, v in summary["numeric_error"].items():
        if v.get("n_with_value"):
            print(f"  {k:36} n={v['n_with_value']:2}/{v['n_answerable']} within2%={v['within_2pct']:.2f} "
                  f"within25%={v['within_25pct']:.2f} median={v['median_rel_error']:.3f} NMAE={v['nmae']:.3f} "
                  f"wrong={v['n_wrong']} (>25% off: {v['wrong_beyond_25pct']}, NMAE of wrong {v['nmae_wrong_only']}) "
                  f"negatives given a value={v['negatives_with_value']}/{v['n_negatives']}")
    print("\n== body size as facts (precision includes negative items), bootstrap 95 % CI")
    for k, v in summary["body_size_facts"].items():
        print(f"  {k:36} P={v['precision']} {v['precision_ci95']}  R={v['recall']} {v['recall_ci95']}")
    print("\n== label-level (micro) precision and recall vs per-question 'any overlap'")
    for k, v in summary["labels"].items():
        print(f"  {k:44} P={v['micro_precision']} {v['precision_ci95']}  R={v['micro_recall']} {v['recall_ci95']}  "
              f"F1={v['micro_f1']}  any-overlap={v['per_question_any_overlap']}  labels={v['labels_given']}/{v['gold_labels']}")
    print("\n== diet per question (any label matches; negatives count as false), bootstrap 95 % CI")
    for k, v in summary["diet_questions"].items():
        print(f"  {k:36} P={v['precision']} {v['precision_ci95']}  R={v['recall']} {v['recall_ci95']}")
    print("\n== constant 'fungi' baseline:", summary["fungi_baseline"])
    print("\n== selective answering (accuracy among values given / share of all questions given a value)")
    for k, v in summary["selective"].items():
        pts = {n: (v[n]["accuracy"], v[n]["coverage"], v[n]["recall"]) for n in
               ("extractive_all", "generative_all", "generative_plain_or_hedged", "generative_plain", "readers_agree")}
        print(f"  {k:32} n={v['n_questions']} {pts}")


if __name__ == "__main__":
    main()
