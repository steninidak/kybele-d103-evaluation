"""
Trophic-guild scoring for the KYBELE D10.3 trophic benchmark.

Reads each QA response the way the KYBELE trait pipeline does (the answer with the highest
answer_score across collections, as in collembola_trophic_batch.py) and scores it three ways:

  pipeline   what the trait pipeline would record. Species questions: the PRIMARY guilds of
             trait_extraction_v3.extract_trophic (its own vocabulary). The extractor demotes every
             guild to 'indirect' when any sentence of the answer says something is not stated
             (e.g. "no mention of other food sources"), so correct answers with such a closing
             caveat get no primary guild. Genus questions: infer_guilds() of
             collembola_trophic_batch.py (keyword match over the whole answer), reproduced below.
  answer     how right the QA answer itself is: guilds read sentence by sentence (sentences that
             say the diet is not stated are skipped; predator is dropped when the taxon is the
             prey), with the extractor's vocabulary extended by terms it misses (litter, roots,
             fungal and bacterial genus names, invertebrates ...)
  food match a gold food item (any alternative) appears verbatim in the answer (strict)

Outcomes: correct (guilds overlap the gold guilds), wrong (guilds found, none matches), no_answer.
Gold guilds are per question for the gold-document configurations and the union over the
taxon's questions for end-to-end configurations. Because most springtails are fungivores, the
script also scores two constant answers ("fungi"; "fungi and decaying plant litter") as baselines.

The scored answer is the one the pipeline keeps: the highest answer_score across collections
(genus batch, collembola_trophic_batch.parse_biomoqa_response) for the five service
configurations and for genus questions of the pipeline configuration; for species questions of
the pipeline configuration, the first non-empty answer in the order the service returns the
collections (collembola_species_traits.query_qa_docrefs). For the pipeline configuration,
gold_retrieved means the gold document was among the documents the pipeline's phrase search
passed to the reader.

Usage: python3 score_trophic.py benchmark_trophic.csv runs.jsonl out_dir
"""

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    import trait_extraction_v3 as tx  # noqa: E402  (github.com/ecsltae/collembola-trait-mining)
except ImportError:
    sys.exit("trait_extraction_v3.py is missing: see the README for the pinned download command.")

# Terms trait_extraction_v3 misses (found by running it on the gold answers). Scorer-side only.
EXTRA = {
    "detritivore": [r"\blitter\b", r"\bdebris\b", r"scaveng", r"carcass", r"\bdung\b", r"faec", r"\bfeces\b", r"fertili[sz]er",
                    r"compost", r"saprophag", r"dead organic"],
    "herbivore": [r"\broots?\b", r"\bseedlings?\b", r"macrophyte", r"\bplant (?:particles|material|tissue|sap|matter)",
                  r"\bleaves\b", r"\b(?:wheat|maize|crop) plants?\b", r"\bpepino\b", r"\bSolanum\b", r"\bherbivor", r"phytophag"],
    "fungivore": [r"\bFusarium\b", r"\bTrichoderma\b", r"\bT\. virens\b", r"\bCladosporium\b", r"\bC\. cladosporioides\b",
                  r"\bAspergillus\b", r"\bA\. nidulans\b", r"\bPenicillium\b", r"\bMortierella\b", r"\bUmbelopsis\b",
                  r"\bU\. isabellina\b", r"\bAlternaria\b", r"\bPhanerochaete\b", r"\bAgrocybe\b", r"\bZymoseptoria\b",
                  r"\bZ\. tritici\b", r"\bRhizoctonia\b", r"\bBotrytis\b", r"\bMucor\b", r"\bVerticillium\b",
                  r"\bBeauveria\b", r"\bMetarhizium\b", r"\bLaccaria\b", r"\bPiloderma\b", r"\bPaxillus\b",
                  r"\bGlomus\b", r"\bRhizophagus\b", r"\bAMF\b", r"conidia", r"slime mou?ld", r"myxomycete",
                  r"\bPhysarum\b", r"\bP\. polycephalum\b", r"\bfungivor", r"\bmolds?\b"],
    "bacterivore": [r"\bStreptomyces\b", r"actinobacteri", r"actinomycete"],
    "predator": [r"invertebrates", r"\bmites?\b", r"\binsect eggs\b", r"carnivor", r"first order predator",
                 r"trophic level III"],
    "algivore": [r"\bPleurococcus\b", r"\bDesmococcus\b", r"phycophag"],
    "microbivore": [r"\bmicrobial\b"],
    "omnivore": [r"variety of food", r"wide range of food"],
}
DENIAL = re.compile(r"not (?:explicitly |specifically |directly )?(?:mentioned|stated|specified|given|provided|available|"
                    r"reported|described|discussed)|no (?:specific |explicit |direct )?(?:mention|information|data)|"
                    r"does not (?:mention|specify|state|provide|describe)", re.I)

_BASE = {g: list(p) for g, p in tx._GUILD_PAT.items()}
_EXT = {g: _BASE.get(g, []) + [re.compile(k, re.I) for k in EXTRA.get(g, [])] for g in set(_BASE) | set(EXTRA)}


def guilds(text, taxon, extended, split=False):
    tx._GUILD_PAT = _EXT if extended else _BASE
    try:
        r = tx.extract_trophic(text or "", taxon)
    finally:
        tx._GUILD_PAT = _BASE
    prim, ind = set(r.get("guilds") or []), set(r.get("guilds_indirect") or [])
    for g in (prim, ind):
        if "microbivore" in g:
            g |= {"fungivore", "bacterivore"}
    return (prim, ind) if split else prim | ind


def expand(gold):
    return gold | {"fungivore", "bacterivore"} if "microbivore" in gold else gold


# Genus-level classifier of the trait pipeline (collembola_trophic_batch.py, GUILD_KEYWORDS + infer_guilds).
GENUS_KEYWORDS = {
    "fungivore": ["fung", "hyphae", "hypha", "mycelium", "mycorrhiz", "spore", "yeast", "mold", "mould", "mushroom",
                  "oomycete", "ergosterol"],
    "bacterivore": ["bacteri", "microorganism", "microbe", "microbial community", "prokaryote", "archaea"],
    "algivore": ["alga", "algae", "diatom", "cyanobacteri", "microalga", "biofilm", "green alga", "lichen photobiont"],
    "herbivore": ["plant root", "root hair", "pollen", "seed", "leaf litter fungi", "moss", "lichen", "liverwort",
                  "bryophyte", "epiphyte", "plant tissue", "vascular plant"],
    "predator": ["prey", "predat", "hunt", "capture", "nematode", "mite", "collembola", "arthropod", "protozoa",
                 "tardigrade", "enchytraeid", "parasite"],
    "detritivore": ["detritus", "decompos", "organic matter", "litter", "humus", "soil organic", "carrion", "dead plant",
                    "dead wood"],
    "omnivore": ["omnivore", "generalist", "opportunistic", "various food", "mixed diet", "multiple food source"],
}


def infer_guilds_genus(text):
    low = (text or "").lower()
    matched = [g for g, kws in GENUS_KEYWORDS.items() if any(re.search(k, low, re.I) for k in kws)]
    if len(matched) >= 3 and "omnivore" not in matched:
        matched = ["omnivore"] + matched
    return set(matched)


def pipeline_guilds(answer, taxon, rank):
    if rank == "genus":
        return infer_guilds_genus(answer)
    prim, _ = guilds(answer, taxon, False, split=True)
    return prim


def pipeline_outcome(answer, taxon, gold, rank="species"):
    """What the trait pipeline records (see the module docstring)."""
    if not (answer or "").strip():
        return "no_answer"
    got = pipeline_guilds(answer, taxon, rank)
    if "microbivore" in got:
        got = got | {"fungivore", "bacterivore"}
    if not got:
        return "no_answer"
    return "correct" if got & expand(gold) else "wrong"


def answer_guilds(answer, taxon):
    """Guilds stated in the answer, read sentence by sentence with the extended vocabulary."""
    got = set()
    tx._GUILD_PAT = _EXT
    try:
        for sent in tx.sentences(answer or ""):
            c = tx.classify(sent, taxon)
            if c.get("absence") and not re.search(r"\bfeed|\bfed\b|consum|diet consists|graz", sent, re.I):
                continue
            g = set(tx._guilds_in(sent))
            if c.get("prey_of"):
                g.discard("predator")
            got |= g
    finally:
        tx._GUILD_PAT = _BASE
    if "microbivore" in got:
        got |= {"fungivore", "bacterivore"}
    return got


def answer_outcome(answer, taxon, gold):
    if not (answer or "").strip():
        return "no_answer"
    got = answer_guilds(answer, taxon)
    if not got:
        return "no_answer"
    return "correct" if got & expand(gold) else "wrong"


def norm(s):
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def food_match(answer, gold):
    a = norm(answer)
    return int(any(norm(g) and norm(g) in a for g in gold.split("||")))


def is_server_error(resp):
    return not resp.get("collection_results") and not resp.get("model") and resp.get("pipeline_time") is None


def pipeline_answer(resp):
    """Highest answer_score across collections, as in collembola_trophic_batch.parse_biomoqa_response."""
    best, best_score, best_col, ids = "", -1.0, "", set()
    for cr in resp.get("collection_results") or []:
        answers = cr.get("answers") or []
        for a in answers:
            for d in a.get("docs") or []:
                if d.get("docid"):
                    ids.add(str(d["docid"]))
        if not answers:
            continue
        text = answers[0].get("answer") or ""
        score = answers[0].get("answer_score") or 0.0
        if text and score > best_score:
            best, best_score, best_col = text, score, cr.get("collection", "")
    return best, best_col, ids


def first_answer(resp):
    """First non-empty answer in the order the collections are returned, with all doc ids."""
    best, col, ids = "", "", set()
    for cr in resp.get("collection_results") or []:
        answers = cr.get("answers") or []
        for a in answers:
            for d in a.get("docs") or []:
                if d.get("docid"):
                    ids.add(str(d["docid"]))
        text = (answers[0].get("answer") or "") if answers else ""
        if text and not best:
            best, col = text, cr.get("collection", "")
    return best, col, ids


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


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

    item_g, taxon_g = {}, defaultdict(set)
    for qid, b in bench.items():
        item_g[qid] = set(filter(None, b["gold_guilds"].split("|")))
        taxon_g[b["taxon"]] |= item_g[qid]

    rows = []
    for (qid, cfg), run in sorted(latest.items()):
        b = bench[qid]
        species_path = cfg.startswith("pipeline") and b.get("taxon_rank", "species") == "species"
        ans, col, ids = (first_answer if species_path else pipeline_answer)(run["response"])
        gold_g = item_g[qid] if cfg.startswith("doc") else taxon_g[b["taxon"]]
        rows.append({"qid": qid, "config": cfg, "taxon": b["taxon"], "rank": b.get("taxon_rank", "species"),
                     "nonfungal": int(not (gold_g & {"fungivore", "microbivore"})),
                     "evidence": b["evidence"], "hedged": int(b["hedged"]), "collection": b["collection"],
                     "gold_guilds": "|".join(sorted(gold_g)), "gold_answer": b["gold_answer"],
                     "answer_text": ans, "answer_collection": col,
                     "guilds_pipeline": "|".join(sorted(pipeline_guilds(ans, b["taxon"], b.get("taxon_rank", "species")))),
                     "guilds_answer": "|".join(sorted(answer_guilds(ans, b["taxon"]))),
                     "pipeline": pipeline_outcome(ans, b["taxon"], gold_g, b.get("taxon_rank", "species")),
                     "answer": answer_outcome(ans, b["taxon"], gold_g),
                     "food_match": food_match(ans, b["gold_answer"]),
                     "gold_retrieved": int(bool(run.get("gold_in_pipeline_ids"))) if species_path
                     else int(str(b["docid"]) in ids),
                     "doc_ref_hit_gold": run.get("doc_ref_hit_gold"), "wall_s": run.get("wall_s")})
        if cfg.startswith("pipeline"):
            rows[-1].update(no_docs=int(bool(run.get("no_docs"))), n_pipeline_docs=len(run.get("pipeline_ids") or []))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scored_trophic.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), restval="")
        w.writeheader()
        w.writerows(rows)

    def summarise(rs):
        n = len(rs)
        s = {"n": n}
        for mode in ("pipeline", "answer"):
            c = Counter(r[mode] for r in rs)
            s[mode] = {k: round(c[k] / n, 3) for k in ("correct", "wrong", "no_answer")}
            s[mode]["correct_ci95"] = wilson(c["correct"], n)
        s["food_match"] = round(sum(r["food_match"] for r in rs) / n, 3)
        s["gold_retrieved"] = round(sum(r["gold_retrieved"] for r in rs) / n, 3)
        s["mean_wall_s"] = round(sum(r["wall_s"] or 0 for r in rs) / n, 2)
        if rs[0]["config"].startswith("pipeline"):
            s["no_docs"] = round(sum(r["no_docs"] for r in rs) / n, 3)
            s["answer_collection"] = dict(sorted(Counter(r["answer_collection"] or "none" for r in rs).items()))
        return s

    summ = {}
    for base in ("fungi", "fungi and decaying plant litter"):
        for kind in ("doc", "e2e"):
            k = sum(answer_outcome(f"{b['taxon']} feeds on {base}.", b["taxon"],
                                   item_g[q] if kind == "doc" else taxon_g[b["taxon"]]) == "correct"
                    for q, b in bench.items())
            summ.setdefault("baselines", {})[f"constant '{base}' ({kind} gold)"] = round(k / len(bench), 3)
    for cfg in sorted({r["config"] for r in rows}):
        rs = [r for r in rows if r["config"] == cfg]
        summ[cfg] = {"all": summarise(rs)}
        for key, vals in (("rank", ("species", "genus")), ("hedged", (0, 1)),
                          ("evidence", ("lab", "literature", "isotope", "gut", "field")),
                          ("collection", ("pmc", "medline", "plazi")), ("nonfungal", (1,))):
            for v in vals:
                sub = [r for r in rs if r[key] == v]
                if sub:
                    summ[cfg][f"{key}={v}"] = summarise(sub)
    json.dump(summ, open(out / "summary_trophic.json", "w"), indent=2)
    print("baselines:", summ["baselines"])
    for cfg, d in summ.items():
        if cfg == "baselines":
            continue
        s = d["all"]
        nf = d.get("nonfungal=1", {})
        print(f"{cfg:22} n={s['n']:3}  pipeline correct={s['pipeline']['correct']:.2f} no_ans={s['pipeline']['no_answer']:.2f} | "
              f"answer correct={s['answer']['correct']:.2f} {s['answer']['correct_ci95']} wrong={s['answer']['wrong']:.2f} "
              f"no_answer={s['answer']['no_answer']:.2f} | food={s['food_match']:.2f} | gold_ret={s['gold_retrieved']:.2f}"
              + (f" | non-fungal n={nf['n']} answer correct={nf['answer']['correct']:.2f}" if nf else ""))


if __name__ == "__main__":
    main(*sys.argv[1:])
