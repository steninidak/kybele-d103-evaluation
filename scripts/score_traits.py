"""
Trait-level scoring for the KYBELE D10.3 benchmark.

Scores each QA answer the way the KYBELE trait pipeline reads it, instead of by string overlap:
  body size      numeric value in mm: correct if any stated value equals a gold value (within 2 %)
  habitat        habitat classes (13-class scheme of the trait-mining pipeline, trait_extraction_v3):
                 correct if the answer's classes overlap the gold classes
  trophic guild  guilds (Potapov et al. 2022 scheme via trait_extraction_v3) against gold guilds

Outcomes per answer: correct, wrong (a value/class that does not match), no_answer (the answer
states no usable value, e.g. "not mentioned"), and for habitat also geography (only a place).

Which answer is scored:
  the five service configurations  the Plazi collection's answer (every gold treatment is in Plazi)
  the pipeline configuration        the answer the trait pipeline keeps: the first non-empty answer
                                    in the order the service returns the collections
                                    (collembola_species_traits.query_qa_docrefs)
For the pipeline configuration the scorer also reports "stored": the PRIMARY value that
trait_extraction_v3 would write to the trait table (extract_body_size, extract_habitat,
extract_trophic), i.e. what the pipeline records, not only what the answer says.

Negative items (gold_answer NOT_DOCUMENTED, data/benchmark_negatives.csv) are scored as correct
when no value is given (or stored) and wrong when one is. They are summarised under
"<trait>_negative" and kept out of "all".

Gold habitat classes come from the benchmark's own gold_habitat_classes column when it has one
(population benchmark), else from the reviewed_classes column of
data/curation/traits/habitat_gold_classes.csv where a reviewer has filled it, else from
MANUAL_HABITAT, else from the classifier run on the gold span.

Usage: python3 score_traits.py benchmark_traits.csv runs.jsonl out_dir
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    import trait_extraction_v3 as tx  # noqa: E402  (from github.com/ecsltae/collembola-trait-mining)
except ImportError:
    print("score_traits.py needs trait_extraction_v3.py from github.com/ecsltae/collembola-trait-mining,\n"
          "which is not distributed with this repository. Fetch it into scripts/ with:\n"
          "  curl -L -o scripts/trait_extraction_v3.py https://raw.githubusercontent.com/ecsltae/"
          "collembola-trait-mining/1d5b5b62ab8fa6c13e5097701affdbba442c8764/scripts/trait_extraction_v3.py",
          file=sys.stderr)
    sys.exit(1)

# Gold habitat classes the keyword classifier misses (vocabulary gaps), assigned by hand.
MANUAL_HABITAT = {"K025": {"leaf_litter"}, "K093": {"synanthropic"}, "K123": {"leaf_litter"}, "K215": {"cave"}}
NOT_DOCUMENTED = "NOT_DOCUMENTED"
REVIEWED_HABITAT_PATH = Path(__file__).resolve().parent.parent / "data/curation/traits/habitat_gold_classes.csv"


def load_reviewed_habitat(path=REVIEWED_HABITAT_PATH):
    if not path.exists():
        return {}
    # "none" means the gold names no habitat class: the item is then not scored.
    return {r["qid"]: set(filter(None, r["reviewed_classes"].split("|"))) - {"none"}
            for r in csv.DictReader(open(path, encoding="utf-8")) if r.get("reviewed_classes", "").strip()}


REVIEWED_HABITAT = load_reviewed_habitat()
# Gold guilds for the trophic items (Potapov et al. 2022 scheme). [TBC: confirm with the reviewers]
GOLD_GUILDS = {"K235": {"detritivore"}, "K236": {"fungivore"}, "K237": {"fungivore", "detritivore"},
               "K238": {"detritivore", "omnivore"}, "K244": {"fungivore"}, "K247": {"fungivore"},
               "K248": {"detritivore", "fungivore"}}

UNIT = r"(mm|millimet(?:er|re)s?|µm|μm|um|micromet(?:er|re)s?|microns?)"
NUM = r"(\d+(?:[.,]\d+)?)"
VAL = re.compile(NUM + r"(?:\s*(?:–|-|to)\s*" + NUM + r")?\s*" + UNIT + r"\b", re.I)
DENIAL = re.compile(r"not (?:explicitly |specifically )?(?:mentioned|stated|specified|given|provided|available|reported)"
                    r"|no (?:specific |explicit |direct )?(?:mention|information|data)|does not (?:mention|specify|state|provide)",
                    re.I)
COUNTRY_OR_PLACE = re.compile(r"\b[A-Z][a-zà-ž]{2,}(?:\s+[A-Z][a-zà-ž]{2,})*\b")


def _num(s, unit):
    s = s.strip()
    if "," in s:
        head, tail = s.split(",", 1)
        s = head + tail if (unit.lower().startswith(("µ", "μ", "u", "micro")) and len(tail) == 3) else head + "." + tail
    return float(s)


def values_mm(text):
    out = []
    for m in VAL.finditer(text or ""):
        unit = m.group(3).lower()
        f = 0.001 if unit.startswith(("µ", "μ", "um", "micro")) else 1.0
        for g in (m.group(1), m.group(2)):
            if g:
                try:
                    out.append(round(_num(g, unit) * f, 4))
                except ValueError:
                    pass
    return out


def gold_values(gold):
    vals = []
    for alt in gold.split("||"):
        vals += values_mm(alt)
        if not values_mm(alt):  # bare numbers such as "3.0" are in mm in this benchmark
            vals += [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", alt)]
    return set(vals)


def score_body(answer, gold):
    got = values_mm(answer)
    if not got:
        return "no_answer"
    gv = gold_values(gold)
    return "correct" if any(abs(v - g) <= 0.02 * g + 1e-9 for v in got for g in gv) else "wrong"


def habitat_classes(text, species):
    h = tx.extract_habitat(text or "", species)
    return set(h["habitats"]) | set(h["habitats_indirect"])


def gold_habitat(qid, gold, species):
    if qid in REVIEWED_HABITAT:
        return REVIEWED_HABITAT[qid]
    if qid in MANUAL_HABITAT:
        return MANUAL_HABITAT[qid]
    cls = set()
    for alt in gold.split("||"):
        cls |= habitat_classes(alt.strip(), species)
    return cls


def score_habitat(answer, gold_cls, species):
    if not (answer or "").strip() or DENIAL.search(answer):
        return "no_answer"
    cls = habitat_classes(answer, species)
    if cls:
        return "correct" if cls & gold_cls else "wrong"
    return "geography" if COUNTRY_OR_PLACE.search(answer) else "no_answer"


def score_trophic(answer, species, gold_guilds):
    if not (answer or "").strip() or DENIAL.search(answer):
        return "no_answer"
    r = tx.extract_trophic(answer, species)
    got = set(r.get("guilds") or []) | set(r.get("guilds_indirect") or [])
    if "microbivore" in got:          # microbial feeding covers the fungal and bacterial guilds
        got |= {"fungivore", "bacterivore"}
    if "microbivore" in gold_guilds:
        gold_guilds = gold_guilds | {"fungivore", "bacterivore"}
    if not got:
        return "no_answer"
    return "correct" if got & gold_guilds else "wrong"


def food_match(answer, gold):
    """A gold food item (any alternative) appears in the answer."""
    norm = lambda s: " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())
    a = norm(answer)
    return int(any(norm(g) and norm(g) in a for g in gold.split("||")))


def is_server_error(resp):
    return not resp.get("collection_results") and not resp.get("model") and resp.get("pipeline_time") is None


def pipeline_answer(resp):
    """(answer, collection): the first non-empty answer in the order the service returns the
    collections, as collembola_species_traits.query_qa_docrefs keeps it."""
    for c in resp.get("collection_results") or []:
        a = (c.get("answers") or [{}])[0].get("answer") or ""
        if a:
            return a, c.get("collection") or ""
    return "", ""


def _range_values(r):
    vals = []
    for x in re.split(r"[-–]", r or ""):
        try:
            vals.append(float(x))
        except ValueError:
            pass
    return vals


def stored_outcome(answer, qt, species, gold, gold_cls=None, gold_guilds=None):
    """Outcome of the PRIMARY value trait_extraction_v3 would store from the answer."""
    if qt == "body_size":
        vals = _range_values(tx.extract_body_size(answer or "", species)["range_mm"])
        if not vals:
            return "no_answer"
        gv = gold_values(gold)
        return "correct" if any(abs(v - g) <= 0.02 * g for v in vals for g in gv) else "wrong"
    if qt == "habitat":
        got = set(tx.extract_habitat(answer or "", species)["habitats"])
        return "no_answer" if not got else ("correct" if got & (gold_cls or set()) else "wrong")
    got = set(tx.extract_trophic(answer or "", species)["guilds"])
    if "microbivore" in got:
        got |= {"fungivore", "bacterivore"}
    gg = set(gold_guilds or set())
    if "microbivore" in gg:
        gg |= {"fungivore", "bacterivore"}
    return "no_answer" if not got else ("correct" if got & gg else "wrong")


def negative(outcome):
    """A negative item is answered correctly when no value is given."""
    return outcome if outcome == "unscored" else ("correct" if outcome in ("no_answer", "geography") else "wrong")


def primary(r):
    return r["pipeline"] if r["config"].startswith("pipeline") else r["plazi"]


def answers(resp):
    """Return (plazi answer, top-ranked answer, top collection, plazi doc ids)."""
    cols = sorted(resp.get("collection_results") or [], key=lambda c: c.get("rank", 99))
    plazi = top = top_col = ""
    ids = []
    for c in cols:
        a = (c.get("answers") or [{}])[0].get("answer") or ""
        if not top_col and (c.get("answers") or []):
            top, top_col = a, c.get("collection")
        if c.get("collection") == "plazi":
            plazi = a
            for ans in c.get("answers") or []:
                ids += [d.get("docid") for d in ans.get("docs") or []]
    return plazi, top, top_col, ids


def main(bench_path, runs_path, out_dir="."):
    bench = {r["qid"]: r for r in csv.DictReader(open(bench_path, encoding="utf-8"))}
    latest = {}
    for line in open(runs_path, encoding="utf-8"):
        if not line.strip():
            continue
        run = json.loads(line)
        if run["qid"] not in bench or run.get("error") or (
                not run.get("no_docs") and is_server_error(run.get("response") or {})):
            continue
        latest[(run["qid"], run["config"])] = run

    # Gold guilds: per item for gold-document runs; the union over the species for end-to-end runs.
    item_guilds, species_guilds = {}, defaultdict(set)
    for qid, b in bench.items():
        g = set(filter(None, (b.get("gold_guilds") or "").split("|"))) or GOLD_GUILDS.get(qid, set())
        item_guilds[qid] = g
        species_guilds[b["taxon"]] |= g

    rows = []
    for (qid, cfg), run in sorted(latest.items()):
        b = bench[qid]
        sp, qt, gold = b["taxon"], b["question_type"], b["gold_answer"]
        neg = gold == NOT_DOCUMENTED
        plazi, top, top_col, ids = answers(run["response"])
        rec = {"qid": qid, "config": cfg, "trait": qt + ("_negative" if neg else ""), "family": b["family"],
               "answer_offset": int(b["answer_offset"]) if b.get("answer_offset") else -1, "gold": gold,
               "plazi_answer": plazi, "top_collection": top_col,
               "gold_retrieved": int(b["docid"] in ids), "wall_s": run.get("wall_s")}
        gc = gg = None
        if qt == "habitat" and not neg:
            own = set(filter(None, (b.get("gold_habitat_classes") or "").split("|")))
            gc = own or gold_habitat(qid, gold, sp)
        if qt == "trophic_guild":
            gg = item_guilds[qid] if cfg.startswith("doc") else species_guilds[sp]
        answers_to_score = [("plazi", plazi), ("top", top)]
        if cfg.startswith("pipeline"):
            pa, pcol = pipeline_answer(run["response"])
            rec.update(pipeline_answer=pa, pipeline_collection=pcol, pipeline_path=run.get("pipeline_path", ""),
                       n_pipeline_docs=len(run.get("pipeline_ids") or []), no_docs=int(bool(run.get("no_docs"))),
                       gold_in_pipeline_ids=int(bool(run.get("gold_in_pipeline_ids"))))
            answers_to_score.append(("pipeline", pa))
        for pref, ans in answers_to_score:
            if qt == "body_size":
                rec[pref] = score_body(ans, "" if neg else gold)
            elif qt == "habitat":
                rec[pref] = score_habitat(ans, gc, sp) if gc else "unscored"
            else:
                rec[pref] = score_trophic(ans, sp, gg)
                rec[pref + "_food"] = 0 if neg else food_match(ans, gold)
            if neg:
                rec[pref] = negative(rec[pref])
        if cfg.startswith("pipeline"):
            st = stored_outcome(rec["pipeline_answer"], qt, sp, "" if neg else gold, gc, gg)
            rec["stored"] = negative(st) if neg else ("unscored" if qt == "habitat" and not gc else st)
        rows.append(rec)

    out = Path(out_dir)
    with open(out / "scored_traits.csv", "w", newline="", encoding="utf-8") as f:
        fields = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)

    summ = defaultdict(dict)
    for cfg in sorted({r["config"] for r in rows}):
        for trait in ("body_size", "habitat", "trophic_guild", "all",
                      "body_size_negative", "habitat_negative", "trophic_guild_negative"):
            rs = [r for r in rows if r["config"] == cfg and r["plazi"] != "unscored"
                  and (r["trait"] == trait or (trait == "all" and not r["trait"].endswith("_negative")))]
            if not rs:
                continue
            c = Counter(primary(r) for r in rs)
            n = len(rs)
            s = {"n": n, **{k: round(c[k] / n, 3) for k in ("correct", "wrong", "no_answer", "geography")},
                 "top_correct": round(sum(r["top"] == "correct" for r in rs) / n, 3),
                 "gold_retrieved": round(sum(r["gold_retrieved"] for r in rs) / n, 3),
                 "top_is_plazi": round(sum(r["top_collection"] == "plazi" for r in rs) / n, 3),
                 "mean_wall_s": round(sum(r["wall_s"] or 0 for r in rs) / n, 2)}
            for lo, hi, lab in ((0, 1500, "offset<=1500"), (1501, 10 ** 9, "offset>1500")):
                sub = [r for r in rs if lo <= r["answer_offset"] <= hi]
                if sub:
                    s[lab] = {"n": len(sub), "correct": round(sum(primary(r) == "correct" for r in sub) / len(sub), 3)}
            if cfg.startswith("pipeline"):
                ss = [r for r in rs if r["stored"] != "unscored"]
                cs = Counter(r["stored"] for r in ss)
                s["stored"] = {"n": len(ss), **{k: round(cs[k] / len(ss), 3) for k in ("correct", "wrong", "no_answer")}}
                s["gold_in_pipeline_ids"] = round(sum(r["gold_in_pipeline_ids"] for r in rs) / n, 3)
                s["no_docs"] = round(sum(r["no_docs"] for r in rs) / n, 3)
                s["pipeline_collection"] = dict(sorted(Counter(r["pipeline_collection"] or "none" for r in rs).items()))
            summ[cfg][trait] = s
    json.dump(summ, open(out / "summary_traits.json", "w"), indent=2)
    for cfg, d in summ.items():
        for trait, s in d.items():
            print(f"{cfg:22} {trait:13} n={s['n']:3} correct={s['correct']:.2f} wrong={s['wrong']:.2f} "
                  f"no_answer={s['no_answer']:.2f} geo={s['geography']:.2f} top_correct={s['top_correct']:.2f} "
                  f"gold_ret={s['gold_retrieved']:.2f} plazi_top={s['top_is_plazi']:.2f} t={s['mean_wall_s']}"
                  + "".join(f"  [{k}: n={v['n']} {v['correct']:.2f}]" for k, v in s.items() if k.startswith("offset")))


if __name__ == "__main__":
    main(*sys.argv[1:])
