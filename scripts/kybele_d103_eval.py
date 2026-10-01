#!/usr/bin/env python3
"""
KYBELE D10.3 evaluation runner (Collembola taxonomic treatments)
=================================================================

Sends a set of questions about Collembola treatments to the SIBiLS biomedical/biodiversity
QA service and records the raw responses. All output goes to the --out folder (default
kybele_d103); every stage is resumable, so re-run the same command after an interruption.

  1. Questions. If the --out folder contains a curated candidates.csv (with a gold_answer
     column), its questions are used as they are; when there is no treatments.jsonl next to
     it, no Plazi sampling is done at all. Without a candidates.csv the runner samples
     Collembola treatments from the SIBiLS Plazi collection (28 family queries plus 6 generic
     queries; cached in treatments.jsonl) and builds one candidate factoid question per
     treatment with a candidate answer taken verbatim from the text, written to
     candidates.csv. An uncurated candidates.csv (no gold_answer column) stops the run so that
     it can be curated first.
  2. QA. Sends every question to the QA API (POST {base}/qa/multi, default base
     https://qa.sibils.org/api, falling back to https://qa.dev.sibils.org/api if the first
     does not answer; override with --qa-base) in six configurations (CONFIGS; choose a
     subset with --configs):
        doc_extractive          gold treatment supplied via doc_refs, extractive reader
        doc_generative          gold treatment supplied via doc_refs, generative model
        e2e_sparse_extractive   sparse (BM25) retrieval, extractive reader
        e2e_sparse_generative   sparse retrieval, generative model (the API default)
        e2e_dense_generative    dense retrieval, generative model
        pipeline                the request path of the KYBELE trait-mining pipeline
                                (github.com/ecsltae/collembola-trait-mining, PIPELINE_COMMIT):
                                species: phrase search for the binomial in Medline, PMC and
                                Plazi (6 hits each, trait terms as a should-clause), then
                                POST {base}/qa, generative, with those IDs as doc_refs; no
                                document means no answer, as in the pipeline. Genus: POST
                                {base}/qa, generative, sparse retrieval, as its genus batch.
        pipeline_extractive     the same request path with the extractive reader, for a paired
                                comparison of the two readers on the pipeline's own documents
                                (not part of the pipeline; run it with --configs)
     One JSON line per (question, configuration) is appended to runs.jsonl; failed requests
     and empty server responses are retried on the next run.
  3. Packaging. Writes <out>_results.zip (treatments.jsonl if present, candidates.csv,
     runs.jsonl, log.txt) in the current directory.

Score the runs with score.py (string metrics) and score_traits.py (trait-level outcomes).

Requirements: Python 3.8+ (standard library only; nothing to install).

Usage:
    python3 kybele_d103_eval.py --probe                     # connectivity check only
    python3 kybele_d103_eval.py --out kybele_d103           # full run, resumable
    python3 kybele_d103_eval.py --out kybele_d103 --workers 2 --qa-base https://qa.sibils.org/api
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

SEARCH_URL = "https://biodiversitypmc.sibils.org/api/search"
FETCH_URL = "https://biodiversitypmc.sibils.org/api/fetch"
QA_BASES = ["https://qa.sibils.org/api", "https://qa.dev.sibils.org/api"]
UA = "KYBELE-D10.3-evaluation/1.0 (ELIXIR KYBELE project)"

# Collembola families used to spread the sample across the group.
FAMILIES = [
    "Hypogastruridae", "Neanuridae", "Onychiuridae", "Tullbergiidae", "Odontellidae",
    "Brachystomellidae", "Poduridae", "Isotomidae", "Entomobryidae", "Orchesellidae",
    "Lepidocyrtidae", "Paronellidae", "Cyphoderidae", "Tomoceridae", "Oncopoduridae",
    "Isotogastruridae", "Sminthuridae", "Katiannidae", "Dicyrtomidae", "Bourletiellidae",
    "Sminthurididae", "Arrhopalitidae", "Neelidae", "Mackenziellidae", "Spinothecidae",
    "Actaletidae", "Coenaletidae", "Protentomobryidae",
]
GENERIC_QUERIES = [
    "Collembola new species", "Collembola sp. nov.", "Collembola redescription",
    "springtail new species", "Collembola Europe new species", "Collembola cave",
]
COLLEMBOLA_WORDS = ["collembola", "springtail"] + [f.lower() for f in FAMILIES]

BAD_EPITHETS = {"sp", "spp", "cf", "aff", "gen", "nov", "n", "var", "subsp", "ssp", "indet",
                "group", "complex", "et", "and", "in", "de", "del", "von", "van", "sensu"}

QUESTION_TYPES = [
    ("type_locality", "What is the type locality of {sp}?",
     r"\b[Tt]ype[- ]locality\s*[.:—–-]?\s*([^.;]{8,180})"),
    ("habitat", "What is the habitat of {sp}?",
     r"\b(?:Habitat(?: and ecology)?|Ecology)\s*[.:—–-]\s*([^.]{8,180})"),
    ("body_length", "What is the body length of {sp}?",
     r"\b(?:[Bb]ody length|[Ll]ength of (?:the )?body|[Tt]otal length)\b[^.;]{0,40}?"
     r"(\d+(?:[.,]\d+)?(?:\s*[–-]\s*\d+(?:[.,]\d+)?)?\s*(?:mm|µm|μm|um)\b)"),
    ("distribution", "What is the known distribution of {sp}?",
     r"\b(?:Distribution|Geographical distribution|Known distribution)\s*[.:—–-]\s*([^.]{4,180})"),
    ("holotype_depository", "Where is the holotype of {sp} deposited?",
     r"\b[Hh]olotype\b[^.]{0,250}?\b(?:deposited|housed|kept|preserved)\s+(?:in|at)\s+(?:the\s+)?([^.;()]{4,140})"),
    ("etymology", "What does the name of {sp} refer to?",
     r"\bEtymology\s*[.:—–-]\s*([^.]{5,200})"),
]
QUESTION_TYPES = [(t, q, re.compile(p)) for t, q, p in QUESTION_TYPES]
TYPE_ORDER = [t for t, _, _ in QUESTION_TYPES]

CONFIGS = [
    ("doc_extractive", {"mode": "extractive"}),
    ("doc_generative", {"mode": "generative"}),
    ("e2e_sparse_extractive", {"mode": "extractive", "retrieval": "sparse"}),
    ("e2e_sparse_generative", {"mode": "generative", "retrieval": "sparse"}),  # API default; the pipeline's genus batch
    ("e2e_dense_generative", {"mode": "generative", "retrieval": "dense"}),
    ("pipeline", {"mode": "generative"}),  # the trait-mining pipeline's own request path, see run_pipeline()
    ("pipeline_extractive", {"mode": "extractive"}),  # the same documents, read by the extractive reader
]

# The trait-mining pipeline reproduced by the "pipeline" configuration. The constants below are
# copied from scripts/collembola_species_traits.py (phrase_search_ids, query_qa_docrefs) and
# scripts/collembola_trophic_batch.py (query_biomoqa) at this commit; check_pipeline_sync.py
# compares them with the upstream file.
PIPELINE_COMMIT = "1d5b5b62ab8fa6c13e5097701affdbba442c8764"
PIPELINE_TRAIT_TERMS = {
    "trophic": "feed diet food prey feeding fungi bacteria algae detritus",
    "size":    "body length size mm millimetre measurement",
    "habitat": "habitat soil litter moss cave forest inhabits found lives",
}
PIPELINE_COL_FIELDS = {
    "medline": ["title", "abstract", "keywords"],
    "pmc":     ["title", "abstract", "keywords"],
    "plazi":   ["treatment_title", "text", "title"],
}
PIPELINE_N = 6
PIPELINE_TRAIT_KEY = {"body_size": "size", "habitat": "habitat", "trophic_guild": "trophic"}

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def log(msg, logf=None):
    line = time.strftime("%H:%M:%S ") + msg
    with _print_lock:
        print(line, flush=True)
        if logf:
            with open(logf, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def http_json(url, params=None, payload=None, timeout=120, retries=2):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read()[:300].decode("utf-8", "replace")
            except Exception:
                detail = ""
            last = f"HTTP {e.code} {detail}"
            if e.code in (400, 401, 403, 404, 405, 422):
                break
        except Exception as e:  # timeouts, connection resets, bad JSON
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(last or "request failed")


def ws(text):
    return re.sub(r"\s+", " ", text or "").strip()


def trim_answer(s):
    return ws(s).strip(" .;:,")


# ---------------------------------------------------------------------------
# Stage 1: sample treatments
# ---------------------------------------------------------------------------

def search_plazi(q, n):
    d = http_json(SEARCH_URL, {"q": q, "col": "plazi", "n": n}, timeout=120)
    if d.get("success") is False:
        raise RuntimeError(d.get("error") or "search failed")
    return ((d.get("elastic_output") or {}).get("hits") or {}).get("hits") or []


def hit_to_doc(hit, query, family):
    s = hit.get("_source") or {}
    return {
        "docid": s.get("docid") or hit.get("_id"),
        "treatment_title": s.get("treatment_title") or "",
        "taxon_field": s.get("nomenclature-taxon-name") or "",
        "article_title": s.get("article-title") or "",
        "doi": s.get("zenodo-doi") or s.get("publication-doi") or "",
        "treatment_uri": s.get("treatment-bank-uri") or "",
        "text": s.get("text") or "",
        "query": query,
        "family": family,
        "search_score": hit.get("_score"),
    }


def _strings_under(obj, keys=("text", "full_text", "body", "content", "sentence")):
    found = []
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k.lower() in keys:
                    found.append(v)
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(o, list):
            stack.extend(reversed(o))
    return found


def fetch_text(docid):
    try:
        d = http_json(FETCH_URL, {"ids": docid, "col": "plazi"}, timeout=90, retries=1)
    except Exception:
        return ""
    parts = _strings_under(d)
    if not parts:
        return ""
    longest = max(parts, key=len)
    if len(longest) >= 500:
        return longest
    return " ".join(parts)


def is_collembola(doc):
    if doc["family"]:
        return True
    blob = (doc["article_title"] + " " + doc["treatment_title"] + " " + doc["text"][:3000]).lower()
    return any(w in blob for w in COLLEMBOLA_WORDS)


def species_name(doc):
    for cand in (doc.get("taxon_field"), doc.get("treatment_title")):
        cand = re.sub(r"[†*×]", "", cand or "").strip()
        m = re.match(r"^([A-Z][a-z]+)\s+(?:\(([A-Z][a-z]+)\)\s+)?([a-z][a-z\-]+)\b\.?(?:\s+([a-z][a-z\-]{2,})\b)?", cand)
        if m and m.group(3) not in BAD_EPITHETS:
            name = f"{m.group(1)} {m.group(3)}"
            if m.group(4) and m.group(4) not in BAD_EPITHETS:
                name += " " + m.group(4)
            return name
    return None


def stage_sample(out, per_query, logf):
    path = os.path.join(out, "treatments.jsonl")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        docs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        log(f"[1/3] Reusing {len(docs)} sampled treatments from {path}", logf)
        return docs
    log("[1/3] Searching the SIBiLS Plazi collection for Collembola treatments ...", logf)
    by_id = {}
    queries = [(f"{fam}", fam) for fam in FAMILIES] + [(q, "") for q in GENERIC_QUERIES]
    for i, (q, fam) in enumerate(queries, 1):
        try:
            hits = search_plazi(q, per_query)
        except Exception as e:
            try:
                hits = search_plazi(q, min(per_query, 20))
            except Exception:
                log(f"      search '{q}' failed: {e}", logf)
                continue
        new = 0
        for h in hits:
            d = hit_to_doc(h, q, fam)
            if d["docid"] and d["docid"] not in by_id:
                by_id[d["docid"]] = d
                new += 1
        log(f"      ({i}/{len(queries)}) '{q}': {len(hits)} hits, {new} new", logf)
        time.sleep(0.5)
    docs = [d for d in by_id.values() if is_collembola(d) and species_name(d)]
    missing = [d for d in docs if len(d["text"]) < 300]
    if missing:
        log(f"      fetching full text for {min(len(missing), 400)} treatments with no text in search results ...", logf)
        for d in missing[:400]:
            t = fetch_text(d["docid"])
            if len(t) > len(d["text"]):
                d["text"] = t
            time.sleep(0.3)
    docs = [d for d in docs if len(d["text"]) >= 300]
    if not docs:
        log("      no usable treatments found", logf)
        return docs
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    log(f"      kept {len(docs)} species-level Collembola treatments with text", logf)
    return docs


# ---------------------------------------------------------------------------
# Stage 2: candidate questions
# ---------------------------------------------------------------------------

def facts_for(doc, sp):
    text = ws(doc["text"])
    facts = []
    for qtype, tmpl, rx in QUESTION_TYPES:
        m = rx.search(text)
        if not m:
            continue
        ans = trim_answer(m.group(1))
        if qtype != "body_length" and not re.search(r"[A-Za-zÀ-ɏ]{3}", ans):
            continue
        s, e = m.start(1), m.end(1)
        facts.append({
            "question_type": qtype,
            "question": tmpl.format(sp=sp),
            "candidate_answer": ans,
            "gold_context": text[max(0, s - 300): min(len(text), e + 300)],
            "answer_offset": s,
            "text_length": len(text),
        })
    return facts


def stage_questions(out, docs, target, seed, logf):
    path = os.path.join(out, "candidates.csv")
    if os.path.exists(path) and os.path.getsize(path) > 200:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        if rows and "gold_answer" not in rows[0]:
            log("[2/3] STOP: kybele_d103/candidates.csv is the uncurated version. Replace it with the curated "
                "candidates.csv from the chat (139 questions) and run the command again.", logf)
            sys.exit(2)
        log(f"[2/3] Reusing {len(rows)} candidate questions from {path}", logf)
        return rows
    rnd = random.Random(seed)
    groups = defaultdict(list)
    seen_species = set()
    shuffled = docs[:]
    rnd.shuffle(shuffled)
    for d in shuffled:
        sp = species_name(d)
        if not sp or sp.lower() in seen_species:
            continue
        facts = facts_for(d, sp)
        if not facts:
            continue
        seen_species.add(sp.lower())
        groups[d["family"] or "other"].append((d, sp, facts))
    fams = sorted(groups, key=lambda k: -len(groups[k]))
    type_counts = Counter()
    rows = []
    while len(rows) < target and any(groups[f] for f in fams):
        for f in fams:
            if len(rows) >= target:
                break
            if not groups[f]:
                continue
            d, sp, facts = groups[f].pop()
            facts.sort(key=lambda x: (type_counts[x["question_type"]], TYPE_ORDER.index(x["question_type"])))
            fx = facts[0]
            type_counts[fx["question_type"]] += 1
            rows.append({
                "qid": f"K{len(rows) + 1:03d}",
                "docid": d["docid"],
                "species": sp,
                "treatment_title": d["treatment_title"],
                "family": d["family"],
                "article_title": d["article_title"],
                "doi": d["doi"],
                "treatment_uri": d["treatment_uri"],
                **fx,
            })
    fields = ["qid", "docid", "species", "treatment_title", "family", "article_title", "doi",
              "treatment_uri", "question_type", "question", "candidate_answer", "gold_context",
              "answer_offset", "text_length"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    log(f"[2/3] Built {len(rows)} candidate questions: {dict(type_counts)}", logf)
    return rows


# ---------------------------------------------------------------------------
# Stage 3: query the QA system
# ---------------------------------------------------------------------------

def trim_response(resp, max_text=4000):
    out = {k: resp.get(k) for k in ("question", "mode_used", "ndocs_retrieved", "model",
                                     "pipeline_time", "unresolved_refs", "_qa_base")}
    cols = []
    for c in resp.get("collection_results") or []:
        answers = []
        for a in (c.get("answers") or [])[:3]:
            docs = [{
                "docid": d.get("docid"),
                "doc_source": d.get("doc_source"),
                "doc_retrieval_score": d.get("doc_retrieval_score"),
                "snippet_start": d.get("snippet_start"),
                "snippet_end": d.get("snippet_end"),
                "doc_text": (d.get("doc_text") or "")[:max_text],
            } for d in (a.get("docs") or [])[:8]]
            answers.append({"answer": a.get("answer"), "answer_score": a.get("answer_score"), "docs": docs})
        dbg = c.get("debug_info")
        cols.append({
            "collection": c.get("collection"),
            "rank": c.get("rank"),
            "answers": answers,
            "debug_info": json.dumps(dbg, ensure_ascii=False)[:6000] if dbg else None,
        })
    out["collection_results"] = cols
    return out


def response_docids(resp):
    ids = set()
    for c in resp.get("collection_results") or []:
        for a in c.get("answers") or []:
            for d in a.get("docs") or []:
                if d.get("docid"):
                    ids.add(str(d["docid"]))
    return ids


def find_qa_base(logf):
    for base in QA_BASES:
        try:
            h = http_json(base + "/health", timeout=30, retries=1)
            if isinstance(h, dict) and h.get("status"):
                log(f"      QA service found at {base} (ready={h.get('ready')}, config={h.get('config')})", logf)
                return base
        except Exception as e:
            log(f"      {base}/health: {e}", logf)
    for base in QA_BASES:
        try:
            r = http_json(base + "/qa/multi", payload={"question": "What is Folsomia candida?",
                                                       "mode": "extractive", "retrieval": "sparse"},
                          timeout=180, retries=0)
            if "collection_results" in r:
                log(f"      QA service answering at {base}", logf)
                return base
        except Exception as e:
            log(f"      {base}/qa/multi: {e}", logf)
    return None


def load_done(path):
    done = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not r.get("error") and (r.get("no_docs") or not is_server_error(r.get("response") or {})):
                    done[(r["qid"], r["config"])] = r
    return done


def append_run(path, rec):
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def is_server_error(resp):
    """/qa/multi swallows internal exceptions and returns an empty result with no model name."""
    return (not resp.get("collection_results") and not resp.get("model")
            and resp.get("pipeline_time") is None)


def ask(base, payload, attempts=2, endpoint="/qa/multi"):
    last = None
    for i in range(attempts):
        t0 = time.time()
        resp = http_json(base + endpoint, payload=payload, timeout=300, retries=2)
        wall = round(time.time() - t0, 2)
        if not is_server_error(resp):
            resp["_qa_base"] = base
            return resp, wall
        last = "service returned an empty result with no model (internal error on the server)"
        time.sleep(5)
    raise RuntimeError(last)


def run_doc_pair(base, row, runs_path, done, logf, names=None):
    """doc_extractive first to find a doc_ref that resolves to the gold treatment, then doc_generative."""
    gold = str(row["docid"])
    ref_used = None
    need = [c for c, _ in CONFIGS[:2] if (row["qid"], c) not in done and (not names or c in names)]
    if not need:
        return 0
    prev = done.get((row["qid"], "doc_extractive"))
    candidates = [prev["doc_ref"]] if prev and prev.get("doc_ref") else [gold, row["treatment_title"], row["species"]]
    n = 0
    for cfg, params in CONFIGS[:2]:
        if (row["qid"], cfg) in done or cfg not in need:
            continue
        tried = candidates if ref_used is None else [ref_used]
        rec = None
        for ref in tried:
            if not ref:
                continue
            payload = {"question": row["question"], "doc_refs": [ref], "debug": True, **params}
            try:
                resp, wall = ask(base, payload)
            except Exception as e:
                rec = {"qid": row["qid"], "config": cfg, "doc_ref": ref, "error": str(e), "wall_s": None}
                continue
            hit = gold in response_docids(resp)
            rec = {"qid": row["qid"], "config": cfg, "doc_ref": ref, "doc_ref_hit_gold": hit,
                   "wall_s": wall, "response": trim_response(resp), "error": ""}
            if hit:
                ref_used = ref
                break
        if rec is None:
            rec = {"qid": row["qid"], "config": cfg, "doc_ref": None, "error": "no usable doc_ref", "wall_s": None}
        append_run(runs_path, rec)
        n += 1
        log(f"      {row['qid']} {cfg:22s} {'ERROR ' + rec['error'][:60] if rec.get('error') else ('gold' if rec.get('doc_ref_hit_gold') else 'other doc')}"
            f" {rec.get('wall_s') or ''}", logf)
    return n


def run_e2e(base, row, cfg, params, runs_path, logf):
    payload = {"question": row["question"], "debug": True, **params}
    try:
        resp, wall = ask(base, payload)
        rec = {"qid": row["qid"], "config": cfg, "wall_s": wall, "response": trim_response(resp), "error": ""}
        status = f"ok {wall}s"
    except Exception as e:
        rec = {"qid": row["qid"], "config": cfg, "wall_s": None, "error": str(e)}
        status = "ERROR " + str(e)[:80]
    append_run(runs_path, rec)
    log(f"      {row['qid']} {cfg:22s} {status}", logf)
    return 1


def phrase_search_ids(binomial, trait_key, n=PIPELINE_N):
    """Document IDs that contain the full binomial as a phrase, ranked by trait relevance, across
    Medline, PMC and Plazi (collembola_species_traits.phrase_search_ids). A failed collection is
    reported instead of skipped, so that a network error is not mistaken for an empty result."""
    ids, failed = [], []
    for col, fields in PIPELINE_COL_FIELDS.items():
        esq = {"query": {"bool": {
            "must": [{"multi_match": {"query": binomial, "type": "phrase", "fields": fields}}],
            "should": [{"multi_match": {"query": PIPELINE_TRAIT_TERMS[trait_key], "fields": fields}}],
        }}}
        url = SEARCH_URL + "?" + urllib.parse.urlencode({"col": col, "n": n})
        body = urllib.parse.urlencode({"jq": json.dumps(esq)}).encode("utf-8")
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={
                    "User-Agent": UA, "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                for h in ((d.get("elastic_output") or {}).get("hits") or {}).get("hits") or []:
                    if h.get("_id"):
                        ids.append(str(h["_id"]))
                break
            except Exception:
                if attempt == 2:
                    failed.append(col)
                else:
                    time.sleep(5 * (attempt + 1))
    return list(dict.fromkeys(ids)), failed


def run_pipeline(base, row, runs_path, logf, cfg="pipeline"):
    """The trait-mining pipeline's request path (see CONFIGS and the module docstring)."""
    mode = dict(CONFIGS)[cfg]["mode"]
    rank = row.get("taxon_rank") or "species"
    rec = {"qid": row["qid"], "config": cfg, "taxon_rank": rank, "wall_s": None, "error": ""}
    try:
        if rank == "genus":
            payload = {"question": row["question"], "mode": mode, "retrieval": "sparse"}
            resp, wall = ask(base, payload, endpoint="/qa")
            rec.update(pipeline_path="genus_batch", wall_s=wall, response=trim_response(resp))
            status = f"ok {wall}s"
        else:
            trait_key = PIPELINE_TRAIT_KEY[row["question_type"]]
            t0 = time.time()
            ids, failed = phrase_search_ids(row["species"], trait_key)
            if failed:
                raise RuntimeError("phrase search failed for " + ",".join(failed))
            rec.update(pipeline_path="species_phrase_docrefs", pipeline_ids=ids,
                       gold_in_pipeline_ids=str(row["docid"]) in ids)
            if not ids:
                # The pipeline leaves the trait blank when no document contains the binomial.
                rec.update(no_docs=True, wall_s=round(time.time() - t0, 2),
                           response={"collection_results": [], "model": None, "pipeline_time": None})
                status = "no document contains the binomial"
            else:
                payload = {"question": row["question"], "mode": mode, "doc_refs": ids}
                resp, wall = ask(base, payload, endpoint="/qa")
                rec.update(wall_s=round(time.time() - t0, 2), response=trim_response(resp))
                status = f"ok {rec['wall_s']}s, {len(ids)} docs" + (", gold among them" if rec["gold_in_pipeline_ids"] else "")
    except Exception as e:
        rec["error"] = str(e)
        status = "ERROR " + str(e)[:80]
    append_run(runs_path, rec)
    log(f"      {row['qid']} {cfg:22s} {status}", logf)
    return 1


def stage_qa(out, rows, workers, logf, configs=None):
    runs_path = os.path.join(out, "runs.jsonl")
    log("[3/3] Querying the QA system ...", logf)
    base = find_qa_base(logf)
    if not base:
        log("      Could not reach the QA service at qa.sibils.org. Check your connection or VPN and re-run.", logf)
        return False
    active = [(c, p) for c, p in CONFIGS if not configs or c in configs]
    names = [c for c, _ in active]
    log(f"      configurations: {', '.join(names)}", logf)
    done = load_done(runs_path)
    total = len(rows) * len(active)
    have = sum(1 for row in rows for cfg, _ in active if (row["qid"], cfg) in done)
    log(f"      {have} of {total} runs already done; {total - have} to go "
        f"(roughly {max(1, (total - have) * 4 // max(1, workers) // 60)} min)", logf)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = []
        if "doc_extractive" in names or "doc_generative" in names:
            for row in rows:
                futs.append(ex.submit(run_doc_pair, base, row, runs_path, done, logf, names))
        for cfg, params in active:               # one configuration at a time, in list order
            if cfg.startswith("doc_"):
                continue
            for row in rows:
                if (row["qid"], cfg) not in done:
                    fn = run_pipeline if cfg.startswith("pipeline") else run_e2e
                    args = (base, row, runs_path, logf, cfg) if cfg.startswith("pipeline") else (base, row, cfg, params, runs_path, logf)
                    futs.append(ex.submit(fn, *args))
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as e:
                log(f"      worker error: {e}", logf)
            if i % 20 == 0:
                log(f"      progress: {i}/{len(futs)} tasks, {round((time.time() - t0) / 60, 1)} min elapsed", logf)
    done = load_done(runs_path)
    ok = sum(1 for row in rows for cfg, _ in active if (row["qid"], cfg) in done)
    missing = total - ok
    log(f"      finished: {ok} of {total} runs have a valid answer"
        + (f"; {missing} still failing (re-run the same command to retry them)" if missing else ""), logf)
    return True


def make_zip(out, logf):
    zpath = os.path.abspath(f"{os.path.basename(os.path.normpath(out))}_results.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("treatments.jsonl", "candidates.csv", "runs.jsonl", "log.txt"):
            p = os.path.join(out, name)
            if os.path.exists(p):
                z.write(p, arcname=name)
    size = os.path.getsize(zpath) / 1e6
    log(f"Done. Upload this file to the chat: {zpath} ({size:.1f} MB)", logf)


def probe(logf):
    log("Probe: SIBiLS Plazi search ...", logf)
    try:
        hits = search_plazi("Isotomidae", 3)
        log(f"      {len(hits)} hits; first _source fields: {sorted((hits[0].get('_source') or {}).keys()) if hits else '-'}", logf)
        if hits:
            d = hit_to_doc(hits[0], "Isotomidae", "Isotomidae")
            log(f"      first: {d['treatment_title'][:80]!r}, text length {len(d['text'])}, species {species_name(d)!r}", logf)
    except Exception as e:
        log(f"      search failed: {e}", logf)
    log("Probe: QA service ...", logf)
    base = find_qa_base(logf)
    if base:
        try:
            resp, wall = ask(base, {"question": "What is the habitat of Folsomia candida?",
                                    "mode": "extractive", "retrieval": "sparse"})
            cols = [(c.get("collection"), (c.get("answers") or [{}])[0].get("answer")) for c in resp.get("collection_results") or []]
            log(f"      answered in {wall}s: {cols}", logf)
        except Exception as e:
            log(f"      QA call failed: {e}", logf)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=150, help="number of candidate questions (default 150; >100 survive curation)")
    ap.add_argument("--workers", type=int, default=1, help="parallel requests to the QA service (default 1)")
    ap.add_argument("--per-query", type=int, default=100, help="Plazi search hits per query (default 100)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="kybele_d103")
    ap.add_argument("--probe", action="store_true", help="connectivity check only")
    ap.add_argument("--qa-base", default=None, help="QA API base URL (default: https://qa.sibils.org/api)")
    ap.add_argument("--configs", default="", help="comma-separated configurations to run "
                    "(default: the five service configurations and pipeline)")
    args = ap.parse_args()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()] or [c for c, _ in CONFIGS if c != "pipeline_extractive"]
    unknown = set(configs) - {c for c, _ in CONFIGS}
    if unknown:
        sys.exit(f"unknown configuration(s): {', '.join(sorted(unknown))}")
    if args.qa_base:
        QA_BASES.insert(0, args.qa_base.rstrip("/"))

    os.makedirs(args.out, exist_ok=True)
    logf = os.path.join(args.out, "log.txt")
    log(f"KYBELE D10.3 evaluation runner v6, output folder: {os.path.abspath(args.out)}", logf)
    if args.probe:
        probe(logf)
        return
    cand_path = os.path.join(args.out, "candidates.csv")
    prepared = os.path.exists(cand_path) and not os.path.exists(os.path.join(args.out, "treatments.jsonl"))
    if prepared:
        # A curated question file supplied directly (e.g. the trophic-guild set): no Plazi sampling.
        docs = []
        log("[1/3] Using the curated question file supplied in this folder (no sampling needed)", logf)
    else:
        docs = stage_sample(args.out, args.per_query, logf)
        if not docs:
            log("No treatments sampled; check the connection to biodiversitypmc.sibils.org and re-run.", logf)
            make_zip(args.out, logf)
            sys.exit(1)
    rows = stage_questions(args.out, docs, args.target, args.seed, logf)
    if not rows:
        log("No candidate questions could be built from the sampled treatments.", logf)
        make_zip(args.out, logf)
        sys.exit(1)
    stage_qa(args.out, rows, args.workers, logf, configs)
    make_zip(args.out, logf)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to resume where it stopped.")
