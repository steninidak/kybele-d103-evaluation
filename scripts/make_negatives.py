#!/usr/bin/env python3
"""
Build the negative items of the D10.3 treatment benchmark: questions whose correct answer is
that the trait is not documented (gold_answer NOT_DOCUMENTED).

The benchmarks otherwise hold only answerable questions, so they measure how often the system
finds a stated value but never how often it asserts a value that no source supports. In the
trait-mining run most species have no documented diet (211 of the 290 version 3 diet
answers state no diet at all, and 264 of 290 body-size answers no size), so abstaining correctly is the common case in practice.

Pool: the treatments of data/sampling_frame.csv that belong to a Collembola family query, are
titled with their own binomial, have at least 1,500 characters of text, and whose species and
treatment are not already in data/benchmark_traits.csv.

A treatment gives a negative item for a trait when
  1. its own text has no statement of the trait (BODY_SIZE or DIET below), and
  2. no document returned by the trait pipeline's phrase search for the binomial (Medline and PMC
     title, abstract and keywords, Plazi treatment text; 20 hits per collection) states it either,
     so the trait is undocumented in everything the pipeline could read.
Both rules err towards rejecting a candidate. Items were drawn with a fixed seed in rotation
across families, one question per treatment, alternating the two traits.

Habitat has no negative items: nearly every treatment gives a collecting substrate in its
material-examined section, so an automatic "no habitat" rule would not be trustworthy.

The rules are automatic. The items are flagged for the specialist spot-check.

Usage: python3 scripts/make_negatives.py [--per-trait 30] [--seed 2026]
Writes data/benchmark_negatives.csv and data/curation/negatives/negatives_log.csv; caches the
treatment texts in runs/negatives_cache.jsonl (git-ignored). Standard library only.
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_URL = "https://biodiversitypmc.sibils.org/api/search"
FETCH_URL = "https://biodiversitypmc.sibils.org/api/fetch"
UA = "KYBELE-D10.3-evaluation/1.0 (ELIXIR KYBELE project)"
FIELDS_BY_COL = {  # the trait pipeline's phrase-search fields (collembola_species_traits.COL_FIELDS)
    "medline": ["title", "abstract", "keywords"],
    "pmc": ["title", "abstract", "keywords"],
    "plazi": ["treatment_title", "text", "title"],
}

# Any statement of body size: a length heading or phrase, a value in mm, or a length-like
# phrase with a value of 300 µm or more nearby.
BODY_SIZE = re.compile(
    r"\bbody\s+(?:length|size)|\blength\s+of\s+(?:the\s+)?body|\btotal\s+length|\bbody\s+\w+\s+length"
    r"|\bSize\b|\d\s*(?:mm|millimet)", re.I)
BODY_UM = re.compile(r"(?:length|long|size)[^.]{0,80}?(\d{3,5})\s*(?:µm|μm|um)\b|(\d{3,5})\s*(?:µm|μm|um)\s+long", re.I)
# The diet cues of the trophic harvest (kybele_trophic_harvest.DIET).
DIET = re.compile(
    r"\b(?:feed(?:s|ing)?|fed|diet(?:s|ary)?|gut contents?|consum(?:e|es|ed|ing|ption)|graz(?:e|es|ed|ing)|"
    r"ingest(?:s|ed|ing|ion)?|mycophag\w*|fungivor\w*|bacterivor\w*|microbivor\w*|algivor\w*|detritivor\w*|"
    r"herbivor\w*|phytophag\w*|saprophag\w*|predator\w*|predat(?:e|es|ed|ing|ion)|prey(?:s|ed)? (?:on|upon)|"
    r"food (?:source|preference|choice|item|web)s?|trophic (?:level|position|niche|group|guild)s?|"
    r"stable isotope|δ15N|δ13C|palatab\w*|nutrition\w*)\b", re.I)
TRAITS = {
    "body_size": ("What is the body length of {sp}?",
                  lambda t: bool(BODY_SIZE.search(t)) or any(int(a or b) >= 300 for a, b in BODY_UM.findall(t))),
    "trophic_guild": ("What does {sp} feed on?", lambda t: bool(DIET.search(t))),
}


def http_json(url, data=None, timeout=90):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def fetch_text(docid):
    d = http_json(FETCH_URL + "?" + urllib.parse.urlencode({"ids": docid, "col": "plazi"}))
    arts = d.get("sibils_article_set") or []
    return ((arts[0].get("document") or {}).get("text") or "") if arts else ""


def texts_under(src):
    out = []
    for k, v in (src or {}).items():
        if isinstance(v, str) and k in ("title", "abstract", "keywords", "text", "treatment_title", "article-title"):
            out.append(v)
        elif isinstance(v, list) and k == "keywords":
            out += [x for x in v if isinstance(x, str)]
    return " ".join(out)


def phrase_docs(binomial, n=20):
    """(collection, docid, text) for every document the pipeline's phrase search returns."""
    docs = []
    for col, fields in FIELDS_BY_COL.items():
        esq = {"query": {"bool": {"must": [{"multi_match": {"query": binomial, "type": "phrase", "fields": fields}}]}}}
        d = http_json(SEARCH_URL + "?" + urllib.parse.urlencode({"col": col, "n": n}),
                      data=urllib.parse.urlencode({"jq": json.dumps(esq)}).encode("utf-8"), timeout=60)
        for h in ((d.get("elastic_output") or {}).get("hits") or {}).get("hits") or []:
            docs.append((col, str(h.get("_id")), texts_under(h.get("_source"))))
    return docs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-trait", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    bench = list(csv.DictReader(open(os.path.join(ROOT, "data/benchmark_traits.csv"), encoding="utf-8")))
    used_sp = {b["taxon"].lower() for b in bench}
    used_doc = {b["docid"] for b in bench}
    frame = list(csv.DictReader(open(os.path.join(ROOT, "data/sampling_frame.csv"), encoding="utf-8")))
    pool = [r for r in frame
            if r["family"] and r["query"] == r["family"] and int(r["text_length"] or 0) >= 1500
            and r["treatment_title"].startswith(r["species"]) and len(r["species"].split()) == 2
            and r["species"].lower() not in used_sp and r["docid"] not in used_doc]
    seen, uniq = set(), []
    for r in sorted(pool, key=lambda r: r["docid"]):
        if r["species"].lower() not in seen:
            seen.add(r["species"].lower())
            uniq.append(r)
    rnd = random.Random(args.seed)
    rnd.shuffle(uniq)
    by_fam = defaultdict(list)
    for r in uniq:
        by_fam[r["family"]].append(r)
    fams = sorted(by_fam, key=lambda f: (-len(by_fam[f]), f))
    order = []
    while any(by_fam.values()):
        for f in fams:
            if by_fam[f]:
                order.append(by_fam[f].pop(0))
    print(f"{len(order)} eligible treatments in {len(fams)} families", file=sys.stderr)

    cache_path = os.path.join(ROOT, "runs/negatives_cache.jsonl")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    cache = {}
    if os.path.exists(cache_path):
        for line in open(cache_path, encoding="utf-8"):
            c = json.loads(line)
            cache[c["docid"]] = c

    items, log_rows = [], []
    count = {t: 0 for t in TRAITS}
    turn = 0
    for r in order:
        if all(count[t] >= args.per_trait for t in TRAITS):
            break
        if r["docid"] not in cache:
            try:
                c = {"docid": r["docid"], "text": fetch_text(r["docid"]), "docs": phrase_docs(r["species"])}
            except Exception as e:
                print(f"  {r['docid']} {r['species']}: {e}", file=sys.stderr)
                continue
            cache[r["docid"]] = c
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
            time.sleep(0.3)
        c = cache[r["docid"]]
        text, docs = c["text"], c["docs"]
        rec = {"docid": r["docid"], "species": r["species"], "family": r["family"], "text_length": len(text),
               "n_docs_with_binomial": len(docs),
               "collections": "|".join(sorted({d[0] for d in docs}))}
        ok = {}
        for t, (_, stated) in TRAITS.items():
            in_text = stated(text)
            in_docs = [d[1] for d in docs if d[1] != r["docid"] and stated(d[2])]
            ok[t] = len(text) >= 1500 and not in_text and not in_docs
            rec[f"{t}_in_treatment"] = int(in_text)
            rec[f"{t}_in_other_docs"] = "|".join(in_docs)
        # Alternate the traits so that neither takes all the treatments that qualify for both.
        prefs = list(TRAITS)[turn % 2:] + list(TRAITS)[:turn % 2]
        chosen = next((t for t in prefs if ok[t] and count[t] < args.per_trait), "")
        rec["chosen"] = chosen
        log_rows.append(rec)
        if not chosen:
            continue
        turn += 1
        count[chosen] += 1
        items.append({
            "docid": r["docid"], "taxon": r["species"], "family": r["family"], "question_type": chosen,
            "question": TRAITS[chosen][0].format(sp=r["species"]), "gold_answer": "NOT_DOCUMENTED",
            "gold_guilds": "", "gold_context": "", "answer_offset": "", "text_length": len(text),
            "treatment_title": r["treatment_title"], "article_title": r["article_title"], "doi": r["doi"],
            "treatment_uri": r["treatment_uri"], "n_docs_with_binomial": len(docs),
            "curation_note": "automatic rule (make_negatives.py); pending specialist review"})
    items.sort(key=lambda x: (x["question_type"], x["taxon"]))
    for i, it in enumerate(items, 1):
        it["qid"] = f"N{i:03d}"
    fields = ["qid", "docid", "taxon", "family", "question_type", "question", "gold_answer", "gold_guilds",
              "gold_context", "answer_offset", "text_length", "treatment_title", "article_title", "doi",
              "treatment_uri", "n_docs_with_binomial", "curation_note"]
    with open(os.path.join(ROOT, "data/benchmark_negatives.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(items)
    os.makedirs(os.path.join(ROOT, "data/curation/negatives"), exist_ok=True)
    with open(os.path.join(ROOT, "data/curation/negatives/negatives_log.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()))
        w.writeheader()
        w.writerows(log_rows)
    print(f"wrote {len(items)} negative items ({count}); {len(log_rows)} treatments checked", file=sys.stderr)


if __name__ == "__main__":
    main()
