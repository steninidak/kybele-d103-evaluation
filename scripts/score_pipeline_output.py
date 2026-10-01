#!/usr/bin/env python3
"""
Score the published output of the KYBELE trait-mining pipeline (layer 2) against the D10.3 gold.

The runner's pipeline configuration replays the pipeline's request path live. This script does
the complementary, offline check: it takes the version 3 trait table the pipeline published
(github.com/ecsltae/collembola-trait-mining at PIPELINE_COMMIT; only version 3 is evaluated) and
compares it, species by species, with the independently curated gold of this repository.

  trophic   species level: collembola_species_traits_v3.csv (trophic_guild, the primary column)
            against the union of the gold guilds of the species in data/benchmark_trophic.csv;
            genus level: results/collembola_trophic_guilds.csv (trophic_guilds), the pipeline's
            genus table, against the gold guilds of the genus questions.
  body size body_size_mm against the gold values of data/benchmark_traits.csv (few species
            overlap; reported for completeness).
  habitat   habitat against the gold classes (same caveat).

Outcomes per species: correct (a stored value matches the gold), wrong (values stored, none
matches), abstained (nothing stored). For trophic guilds also "unsupported": at least one stored
guild is not among the gold guilds. Gold guilds come from the benchmark's documents only, so a
stored guild supported by another document counts against the pipeline: wrong and unsupported
rates are upper bounds.

Retrieval: whether any of the species' gold documents is among the pipeline's recorded sources
(trophic_sources), i.e. whether the pipeline's phrase search reached the evidence at all.

Species whose trophic guild was adjudicated in review_adjudication_2026-09.csv are reported
separately: version 3's rules were written in response to that review, so only the other species
are an independent test of version 3.

Usage:
  python3 scripts/score_pipeline_output.py --fetch           # download the pinned tables to external/
  python3 scripts/score_pipeline_output.py [--tables external] [--out results/pipeline_output]
Needs scripts/trait_extraction_v3.py (habitat classes of the gold spans), like score_traits.py.
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PIPELINE_COMMIT = "1d5b5b62ab8fa6c13e5097701affdbba442c8764"
RAW = f"https://raw.githubusercontent.com/ecsltae/collembola-trait-mining/{PIPELINE_COMMIT}/"
TABLES = {
    "v3": "collembola_species_traits_v3.csv",
    "genus": "results/collembola_trophic_guilds.csv",
    "review": "review_adjudication_2026-09.csv",
}


def fetch(dest):
    dest.mkdir(parents=True, exist_ok=True)
    for name in TABLES.values():
        target = dest / Path(name).name
        with urllib.request.urlopen(RAW + name, timeout=120) as r:
            target.write_bytes(r.read())
        print(f"fetched {name} -> {target}")


def split(s):
    return set(x for x in (s or "").split("|") if x and x != "unknown")


def expand(g):
    return g | {"fungivore", "bacterivore"} if "microbivore" in g else g


def guild_outcome(stored, gold):
    if not stored:
        return "abstained", 0
    gold_x = expand(gold) | ({"microbivore"} if gold & {"fungivore", "bacterivore"} else set())
    unsupported = int(any(g not in gold_x for g in stored))
    return ("correct" if expand(stored) & expand(gold) else "wrong"), unsupported


def sources(s):
    return {x.split("(")[0] for x in (s or "").split("|") if x}


def summarise(rows, with_unsupported=False):
    n = len(rows)
    if not n:
        return {"n": 0}
    c = Counter(r["outcome"] for r in rows)
    s = {"n": n, **{k: round(c[k] / n, 3) for k in ("correct", "wrong", "abstained")},
         "counts": {k: c[k] for k in ("correct", "wrong", "abstained")}}
    stored = [r for r in rows if r["outcome"] != "abstained"]
    if stored:
        s["precision_when_stored"] = round(sum(r["outcome"] == "correct" for r in stored) / len(stored), 3)
    if with_unsupported and stored:
        s["unsupported_when_stored"] = round(sum(r["unsupported"] for r in stored) / len(stored), 3)
    if rows and "gold_doc_in_sources" in rows[0]:
        s["gold_doc_in_sources"] = round(sum(r["gold_doc_in_sources"] for r in rows) / n, 3)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--tables", default=str(ROOT / "external"))
    ap.add_argument("--out", default=str(ROOT / "results/pipeline_output"))
    args = ap.parse_args()
    tdir = Path(args.tables)
    if args.fetch:
        fetch(tdir)
        return
    missing = [n for n in TABLES.values() if not (tdir / Path(n).name).exists()]
    if missing:
        sys.exit(f"missing {', '.join(missing)} in {tdir}; run with --fetch first")
    import score_traits as st  # noqa: E402  (needs trait_extraction_v3.py)

    load = lambda name: list(csv.DictReader(open(tdir / Path(TABLES[name]).name, encoding="utf-8")))
    v3 = {r["species"]: r for r in load("v3")}
    genus_tab = {r["genus"]: r for r in load("genus")}
    reviewed = {r["species"] for r in load("review") if r["trait"] == "trophic_guild"}

    trophic = list(csv.DictReader(open(ROOT / "data/benchmark_trophic.csv", encoding="utf-8")))
    gold_g, gold_docs, qids = defaultdict(set), defaultdict(set), defaultdict(list)
    for b in trophic:
        key = (b["taxon_rank"], b["taxon"])
        gold_g[key] |= split(b["gold_guilds"])
        gold_docs[key].add(b["docid"])
        qids[key].append(b["qid"])

    rows = []
    for (rank, taxon), gold in sorted(gold_g.items()):
        if rank == "species":
            if taxon in v3:
                t = v3[taxon]
                out, uns = guild_outcome(split(t["trophic_guild"]), gold)
                rows.append({"trait": "trophic_guild", "rank": rank, "taxon": taxon, "version": "v3",
                             "qids": "|".join(qids[(rank, taxon)]), "gold": "|".join(sorted(gold)),
                             "stored": "|".join(sorted(split(t["trophic_guild"]))),
                             "stored_indirect": "|".join(sorted(split(t.get("trophic_guild_indirect", "")))),
                             "outcome": out, "unsupported": uns,
                             "gold_doc_in_sources": int(bool(gold_docs[(rank, taxon)] & sources(t["trophic_sources"]))),
                             "in_expert_review": int(taxon in reviewed)})
        elif taxon in genus_tab:
            t = genus_tab[taxon]
            out, uns = guild_outcome(split(t["trophic_guilds"]), gold)
            rows.append({"trait": "trophic_guild", "rank": rank, "taxon": taxon, "version": "genus_batch",
                         "qids": "|".join(qids[(rank, taxon)]), "gold": "|".join(sorted(gold)),
                         "stored": "|".join(sorted(split(t["trophic_guilds"]))), "stored_indirect": "",
                         "outcome": out, "unsupported": uns,
                         "gold_doc_in_sources": int(bool(gold_docs[(rank, taxon)] & sources(t["qa_source_docids"]))),
                         "in_expert_review": 0})

    traits = list(csv.DictReader(open(ROOT / "data/benchmark_traits.csv", encoding="utf-8")))
    for b in traits:
        sp, qt = b["taxon"], b["question_type"]
        if qt not in ("body_size", "habitat"):
            continue
        if sp in v3:
            t = v3[sp]
            if qt == "body_size":
                stored = st._range_values(t["body_size_mm"])
                gv = st.gold_values(b["gold_answer"])
                out = "abstained" if not stored else (
                    "correct" if any(abs(v - g) <= 0.02 * g for v in stored for g in gv) else "wrong")
                shown = "|".join(str(v) for v in stored)
                src = t["body_size_sources"]
            else:
                gc = st.gold_habitat(b["qid"], b["gold_answer"], sp)
                stored = split(t["habitat"])
                out = "abstained" if not stored else ("correct" if stored & gc else "wrong")
                shown = "|".join(sorted(stored))
                src = t["habitat_sources"]
            rows.append({"trait": qt, "rank": "species", "taxon": sp, "version": "v3", "qids": b["qid"],
                         "gold": b["gold_answer"], "stored": shown, "stored_indirect": "",
                         "outcome": out, "unsupported": "", "gold_doc_in_sources": int(b["docid"] in sources(src)),
                         "in_expert_review": ""})

    # Population benchmark (make_population_sample.py): every curated species x trait, including
    # the rows whose gold is NOT_DOCUMENTED, where storing nothing is the correct outcome.
    pop_path = ROOT / "data/benchmark_population.csv"
    pop = list(csv.DictReader(open(pop_path, encoding="utf-8"))) if pop_path.exists() else []
    for b in pop:
        sp, qt, gold = b["taxon"], b["question_type"], b["gold_answer"]
        neg = gold == st.NOT_DOCUMENTED
        if sp in v3:
            t = v3[sp]
            if qt == "body_size":
                vals = st._range_values(t["body_size_mm"])
                shown = "|".join(str(v) for v in vals)
                hit = (not neg) and any(abs(v - g) <= 0.02 * g for v in vals for g in st.gold_values(gold))
                src = t["body_size_sources"]
            elif qt == "habitat":
                vals = split(t["habitat"])
                shown = "|".join(sorted(vals))
                gc = split(b.get("gold_habitat_classes")) or (set() if neg else st.gold_habitat(b["qid"], gold, sp))
                hit = bool(vals & gc)
                src = t["habitat_sources"]
            else:
                vals = split(t["trophic_guild"])
                shown = "|".join(sorted(vals))
                hit = bool(expand(vals) & expand(split(b["gold_guilds"])))
                src = t["trophic_sources"]
            outcome = ("correct" if not vals else "wrong") if neg else ("abstained" if not vals else ("correct" if hit else "wrong"))
            rows.append({"trait": f"population/{qt}" + ("_negative" if neg else ""), "rank": "species", "taxon": sp,
                         "version": "v3", "qids": b["qid"], "gold": gold, "stored": shown, "stored_indirect": "",
                         "outcome": outcome, "unsupported": "",
                         "gold_doc_in_sources": int(bool(b["docid"]) and b["docid"] in sources(src)),
                         "in_expert_review": ""})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scored_pipeline_output.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summ = {"pipeline_commit": PIPELINE_COMMIT}
    for ver in ("v3", "genus_batch"):
        rs = [r for r in rows if r["trait"] == "trophic_guild" and r["version"] == ver]
        if not rs:
            continue
        summ[f"trophic_guild/{ver}"] = {"all": summarise(rs, True)}
        if ver != "genus_batch":
            summ[f"trophic_guild/{ver}"]["not_in_expert_review"] = summarise([r for r in rs if not r["in_expert_review"]], True)
            summ[f"trophic_guild/{ver}"]["in_expert_review"] = summarise([r for r in rs if r["in_expert_review"]], True)
    for trait in ["body_size", "habitat"] + sorted({r["trait"] for r in rows if r["trait"].startswith("population/")}):
        rs = [r for r in rows if r["trait"] == trait]
        if rs:
            summ[f"{trait}/v3"] = {"all": summarise(rs)}
    json.dump(summ, open(out / "summary_pipeline_output.json", "w"), indent=2)
    for k, v in summ.items():
        if k == "pipeline_commit":
            continue
        for sub, s in v.items():
            if s.get("n"):
                print(f"{k:24} {sub:22} n={s['n']:3} correct={s['correct']:.2f} wrong={s['wrong']:.2f} "
                      f"abstained={s['abstained']:.2f} gold_doc_in_sources={s.get('gold_doc_in_sources', 0):.2f}"
                      + (f" unsupported|stored={s['unsupported_when_stored']:.2f}" if "unsupported_when_stored" in s else ""))


if __name__ == "__main__":
    main()
