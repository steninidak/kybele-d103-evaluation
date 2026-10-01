#!/usr/bin/env python3
"""
Check that the copies of the trait-mining pipeline in this repository still match upstream.

This repository reproduces three parts of github.com/ecsltae/collembola-trait-mining instead of
importing them (the upstream code needs `requests`, and the network scripts here stay standard
library only):
  kybele_d103_eval.py   the "pipeline" configuration: phrase-search terms, fields and hit count,
                        question templates, endpoint and payload of the species and genus paths
  score_trophic.py      GENUS_KEYWORDS, the genus classifier of collembola_trophic_batch.py
  score_traits.py and   the answer the pipeline keeps (first non-empty answer, species; highest
  score_trophic.py      answer_score, genus)

It reads the upstream files (by default at the pinned commit, or from a local checkout with
--repo) and compares the constants by parsing the source, without running it. It exits with
status 1 when something differs, so that it can run in CI before a re-evaluation.

Usage: python3 scripts/check_pipeline_sync.py [--repo PATH_TO_CHECKOUT | --commit SHA]
"""

import argparse
import ast
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kybele_d103_eval as runner  # noqa: E402

FILES = ("scripts/collembola_species_traits.py", "scripts/collembola_trophic_batch.py")


def source(repo, commit, name):
    if repo:
        return (Path(repo) / name).read_text(encoding="utf-8")
    url = f"https://raw.githubusercontent.com/ecsltae/collembola-trait-mining/{commit}/{name}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8")


def assigned(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return ast.literal_eval(node.value)
    return None


def function(tree, name):
    return next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name), None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="")
    ap.add_argument("--commit", default=runner.PIPELINE_COMMIT)
    args = ap.parse_args()
    species_src = source(args.repo, args.commit, FILES[0])
    genus_src = source(args.repo, args.commit, FILES[1])
    sp, ge = ast.parse(species_src), ast.parse(genus_src)
    problems = []

    def same(label, ours, theirs):
        status = "ok" if ours == theirs else "DIFFERS"
        print(f"{status:8} {label}")
        if ours != theirs:
            problems.append(label)
            print(f"         here:     {ours!r}\n         upstream: {theirs!r}")

    same("species: TRAIT_TERMS", runner.PIPELINE_TRAIT_TERMS, assigned(sp, "TRAIT_TERMS"))
    same("species: COL_FIELDS", runner.PIPELINE_COL_FIELDS, assigned(sp, "COL_FIELDS"))
    f = function(sp, "phrase_search_ids")
    n_default = ast.literal_eval(f.args.defaults[-1]) if f and f.args.defaults else None
    same("species: phrase_search_ids n", runner.PIPELINE_N, n_default)
    same("species: phrase search is a must-phrase on the binomial",
         True, '"must":   [{"multi_match": {"query": binomial, "type": "phrase"' in species_src)
    q = assigned(function(sp, "main"), "QUESTIONS")
    ours_q = {"trophic": "What does {sp} feed on?", "size": "What is the body length of {sp}?",
              "habitat": "What is the habitat of {sp}?"}
    same("species: question templates", ours_q, q)
    qa = ast.get_source_segment(species_src, function(sp, "query_qa_docrefs")) or ""
    same("species: POST /qa, generative, doc_refs",
         True, '/qa"' in qa and '"mode": "generative", "doc_refs": ids' in qa)
    same("species: keeps the first non-empty answer", True, 'and not best:' in qa)
    gq = ast.get_source_segment(genus_src, function(ge, "query_biomoqa")) or ""
    same("genus: POST /qa, generative, sparse, 'What does {genus} feed on?'",
         True, '/qa"' in gq and '"mode": "generative"' in gq and '"retrieval": "sparse"' in gq
         and 'f"What does {genus} feed on?"' in gq)
    gp = ast.get_source_segment(genus_src, function(ge, "parse_biomoqa_response")) or ""
    same("genus: keeps the highest answer_score", True, "score > best_score" in gp)
    try:
        import score_trophic  # noqa: E402  (needs trait_extraction_v3.py)
        same("genus: GENUS_KEYWORDS", score_trophic.GENUS_KEYWORDS, assigned(ge, "GUILD_KEYWORDS"))
    except SystemExit:
        print("skipped  genus: GENUS_KEYWORDS (trait_extraction_v3.py is missing)")
    print(f"\n{'All checks passed' if not problems else str(len(problems)) + ' difference(s)'} "
          f"against {'the checkout ' + args.repo if args.repo else 'commit ' + args.commit}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
