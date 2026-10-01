#!/usr/bin/env python3
"""
Attribute the errors of each configuration to a layer of the KYBELE system, on the same items.

  retrieval   the gold document reaches the reader (gold_retrieved; for the pipeline
              configuration, the gold document is among the IDs its phrase search passed on)
  reading     the scored answer is correct, given that the gold document was or was not there
  selection   pipeline configuration only: how the answer the pipeline keeps (the first non-empty
              answer in collection order) compares with two other rules on the same response:
              the highest answer_score, and the first answer that does not deny the trait
  extraction  the value the pipeline stores is correct, given that the answer was correct

It also reports the trophic "guild of the answer" measure with the pipeline's own vocabulary as
well as with the extended vocabulary, since the extension was built by looking at the gold
answers (a sensitivity check for that choice).

Reads the scored files written by score_traits.py and score_trophic.py, and the runs.jsonl of
pipeline runs. Needs scripts/trait_extraction_v3.py.

Usage:
  python3 scripts/attribution.py --out results/attribution \\
      --traits results/traits_main results/traits_pipeline \\
      --trophic results/trophic results/trophic_pipeline
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_traits as st  # noqa: E402
import score_trophic as so  # noqa: E402


def rate(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": so.wilson(k, n) if n else None}


def chain(rows, answer_key, stored_key=None):
    """rows: dicts with gold_retrieved (0/1), answer outcome, optionally stored outcome."""
    n = len(rows)
    ret = [r for r in rows if int(r["gold_retrieved"])]
    nret = [r for r in rows if not int(r["gold_retrieved"])]
    ok = lambda r, k: r[k] == "correct"
    out = {"n": n,
           "gold_retrieved": rate(len(ret), n),
           "answer_correct": rate(sum(ok(r, answer_key) for r in rows), n),
           "answer_correct|retrieved": rate(sum(ok(r, answer_key) for r in ret), len(ret)),
           "answer_correct|not_retrieved": rate(sum(ok(r, answer_key) for r in nret), len(nret))}
    if stored_key:
        good = [r for r in rows if ok(r, answer_key)]
        out["stored_correct"] = rate(sum(ok(r, stored_key) for r in rows), n)
        out["stored_correct|answer_correct"] = rate(sum(ok(r, stored_key) for r in good), len(good))
        out["stored_wrong"] = rate(sum(r[stored_key] == "wrong" for r in rows), n)
    return out


def load_runs(path):
    latest = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if not r.get("error"):
                latest[(r["qid"], r["config"])] = r
    return latest


def selection_rules(resp, denial):
    """Answer under three selection rules on one response."""
    cols = resp.get("collection_results") or []
    firsts = [((c.get("answers") or [{}])[0].get("answer") or "", (c.get("answers") or [{}])[0].get("answer_score") or 0.0)
              for c in cols]
    firsts = [(a, s) for a, s in firsts if a]
    first = firsts[0][0] if firsts else ""
    best = max(firsts, key=lambda x: x[1])[0] if firsts else ""
    nondeny = next((a for a, _ in firsts if not denial.search(a)), first)
    return {"pipeline_first": first, "highest_score": best, "first_not_denying": nondeny}


def traits_selection(bench, runs):
    out = defaultdict(Counter)
    n = 0
    for (qid, cfg), run in runs.items():
        if cfg != "pipeline" or qid not in bench:
            continue
        b = bench[qid]
        qt, sp, gold = b["question_type"], b["taxon"], b["gold_answer"]
        if gold == st.NOT_DOCUMENTED or qt == "trophic_guild":
            continue
        gc = st.gold_habitat(qid, gold, sp) if qt == "habitat" else None
        if qt == "habitat" and not gc:
            continue
        n += 1
        for rule, ans in selection_rules(run.get("response") or {}, st.DENIAL).items():
            a = st.score_body(ans, gold) if qt == "body_size" else st.score_habitat(ans, gc, sp)
            out[rule]["answer_correct"] += a == "correct"
            out[rule]["stored_correct"] += st.stored_outcome(ans, qt, sp, gold, gc) == "correct"
    return {rule: {k: rate(v, n) for k, v in c.items()} for rule, c in out.items()}


def trophic_selection(bench, runs):
    item_g, taxon_g = {}, defaultdict(set)
    for q, b in bench.items():
        item_g[q] = set(filter(None, b["gold_guilds"].split("|")))
        taxon_g[b["taxon"]] |= item_g[q]
    out = defaultdict(Counter)
    n = 0
    for (qid, cfg), run in runs.items():
        if cfg != "pipeline" or qid not in bench or bench[qid].get("taxon_rank") == "genus":
            continue
        b = bench[qid]
        n += 1
        for rule, ans in selection_rules(run.get("response") or {}, so.DENIAL).items():
            out[rule]["answer_correct"] += so.answer_outcome(ans, b["taxon"], taxon_g[b["taxon"]]) == "correct"
            out[rule]["stored_correct"] += so.pipeline_outcome(ans, b["taxon"], taxon_g[b["taxon"]]) == "correct"
            out[rule]["food_named"] += so.food_match(ans, b["gold_answer"])
    return {rule: {k: rate(v, n) for k, v in c.items()} for rule, c in out.items()}


def base_vocab_answer(rows):
    """Guild of the answer with the pipeline's own vocabulary, sentence by sentence."""
    saved = so._EXT
    so._EXT = so._BASE
    try:
        k = sum(so.answer_outcome(r["answer_text"], r["taxon"], set(filter(None, r["gold_guilds"].split("|")))) == "correct"
                for r in rows)
    finally:
        so._EXT = saved
    return rate(k, len(rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traits", nargs="*", default=[])
    ap.add_argument("--trophic", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    result = {"traits": {}, "trophic": {}}

    tbench = {r["qid"]: r for r in csv.DictReader(open(root / "data/benchmark_traits.csv", encoding="utf-8"))}
    for folder in args.traits:
        rows = list(csv.DictReader(open(Path(folder) / "scored_traits.csv", encoding="utf-8")))
        for cfg in sorted({r["config"] for r in rows}):
            rs = [r for r in rows if r["config"] == cfg and r["plazi"] != "unscored" and not r["trait"].endswith("_negative")]
            key = "pipeline" if cfg == "pipeline" else "plazi"
            if cfg == "pipeline":  # retrieval = the gold document reached the reader
                rs = [{**r, "gold_retrieved": r["gold_in_pipeline_ids"]} for r in rs]
            result["traits"][f"{Path(folder).name}/{cfg}"] = chain(rs, key, "stored" if cfg == "pipeline" else None)
        runs = load_runs(Path(folder) / "runs.jsonl")
        if any(c == "pipeline" for _, c in runs):
            result["traits"][f"{Path(folder).name}/pipeline/selection_rules"] = traits_selection(tbench, runs)

    obench = {r["qid"]: r for r in csv.DictReader(open(root / "data/benchmark_trophic.csv", encoding="utf-8"))}
    for folder in args.trophic:
        rows = list(csv.DictReader(open(Path(folder) / "scored_trophic.csv", encoding="utf-8")))
        for cfg in sorted({r["config"] for r in rows}):
            rs = [r for r in rows if r["config"] == cfg]
            generative = "generative" in cfg or cfg == "pipeline"
            c = chain(rs, "answer", "pipeline" if generative else None)
            c["answer_correct_base_vocabulary"] = base_vocab_answer(rs)
            c["food_named"] = rate(sum(int(r["food_match"]) for r in rs), len(rs))
            result["trophic"][f"{Path(folder).name}/{cfg}"] = c
        runs = load_runs(Path(folder) / "runs.jsonl")
        if any(c == "pipeline" for _, c in runs):
            result["trophic"][f"{Path(folder).name}/pipeline/selection_rules(species)"] = trophic_selection(obench, runs)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(out / "attribution.json", "w"), indent=2)
    for bench, d in result.items():
        for name, c in d.items():
            if "selection_rules" in name:
                for rule, v in c.items():
                    print(f"{bench:7} {name:52} {rule:18} " + "  ".join(f"{k}={x['rate']:.2f}" for k, x in v.items()))
                continue
            line = (f"{bench:7} {name:52} n={c['n']:3} retrieved={c['gold_retrieved']['rate']:.2f} "
                    f"answer={c['answer_correct']['rate']:.2f} "
                    f"answer|ret={c['answer_correct|retrieved']['rate'] if c['answer_correct|retrieved']['n'] else float('nan'):.2f} "
                    f"answer|not={c['answer_correct|not_retrieved']['rate'] if c['answer_correct|not_retrieved']['n'] else float('nan'):.2f}")
            if "stored_correct" in c:
                line += (f" stored={c['stored_correct']['rate']:.2f} "
                         f"stored|answer_ok={c['stored_correct|answer_correct']['rate'] or 0:.2f}")
            if "answer_correct_base_vocabulary" in c:
                line += f" answer(base vocab)={c['answer_correct_base_vocabulary']['rate']:.2f} food={c['food_named']['rate']:.2f}"
            print(line)


if __name__ == "__main__":
    main()
