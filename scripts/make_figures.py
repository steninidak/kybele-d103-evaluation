"""
Draw the D10.3 result figures from the scored results.

  results/figures/fig_traits.(png|svg)           treatment benchmark: correct answers for body size and
                                                 habitat, five service configurations and the pipeline
  results/figures/fig_trophic.(png|svg)          trophic-guild benchmark: food named, guild of the answer,
                                                 guild recorded by the pipeline, with the constant "fungi" baseline
  results/figures/fig_pipeline_losses.(png|svg)  the pipeline's own request path, stage by stage, with the
                                                 answer-selection change P18 simulated on the same responses
  results/figures/fig_negatives.(png|svg)        negative items: correct abstention per configuration
  results/figures/fig_pipeline_tables.(png|svg)  the pipeline's version 3 and genus tables against the gold

Percentages are over scorable answers to successful requests: failed requests (the dense-retrieval
server error) are left out, so e2e_dense_generative is scored on 24 of 126 trait requests and
80 of 102 trophic requests. Whiskers are 95 % Wilson intervals.

Usage: python3 scripts/make_figures.py   (needs matplotlib; run from the repository root)
"""

import csv
import json
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# KYBELE_DOC=1 draws the figures for the deliverable: no title or subtitle inside the image (the
# report's caption carries them), cropped, into results/figures/doc/.
DOC = os.environ.get("KYBELE_DOC") == "1"
OUT = ROOT / "results" / "figures" / ("doc" if DOC else "")

CONFIGS = [
    ("doc_extractive", "Gold document, extractive"),
    ("doc_generative", "Gold document, generative"),
    ("e2e_sparse_extractive", "End to end, sparse, extractive"),
    ("e2e_sparse_generative", "End to end, sparse, generative\n(API default; pipeline's genus batch)"),
    ("e2e_dense_generative", "End to end, dense, generative"),
    ("pipeline", "Trait pipeline: phrase search,\ngenerative on its documents"),
    ("pipeline_extractive", "Pipeline's documents, extractive\nreader (analysis only)"),
]
# Where each configuration's runs and scores live; the pipeline was run separately (runner v6).
SOURCES = {"traits": {"pipeline": "results/traits_pipeline", "pipeline_extractive": "results/traits_pipeline_extractive"},
           "trophic": {"pipeline": "results/trophic_pipeline", "pipeline_extractive": "results/trophic_pipeline_extractive"},
           "negatives": {"pipeline_extractive": "results/negatives_pipeline_extractive"}}
ORANGE, LIGHT = "#eb6834", "#d9d8d3"
ACCENT, DARK, MID = "#2a78d6", "#52514e", "#7f7e79"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"


def doc_scale(fig):
    """In document mode, enlarge all text in proportion to how much the figure will be shrunk to
    fit the report's 6.3-inch text width (figures are drawn 8.6-10.4 inches wide)."""
    if not DOC:
        return
    f = max(1.0, fig.get_figwidth() / 7.5)
    for t in fig.findobj(matplotlib.text.Text):
        t.set_fontsize(t.get_fontsize() * f)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def is_server_error(run):
    r = run.get("response") or {}
    if run.get("no_docs"):  # the pipeline found no document with the binomial: a valid abstention
        return False
    return bool(run.get("error")) or (not r.get("collection_results") and not r.get("model")
                                      and r.get("pipeline_time") is None)


def valid_requests(runs_path, qids):
    latest = {}
    for line in open(runs_path, encoding="utf-8"):
        if line.strip():
            x = json.loads(line)
            if x["qid"] in qids:
                latest.setdefault((x["qid"], x["config"]), []).append(x)
    ok = {}
    for (q, c), xs in latest.items():
        if any(not is_server_error(x) for x in xs):
            ok[c] = ok.get(c, 0) + 1
    return ok


def style(ax, title, subtitle):
    ax.set_xlim(-2, 102)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0 %", "25 %", "50 %", "75 %", "100 %"], color=INK2, fontsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", length=0)
    if DOC:
        return
    t = ax.figure.text(0.012, 0.985, title, fontsize=12, fontweight="bold", color=INK, va="top", linespacing=1.3)
    ax.figure.text(0.012, 0.895 if ax.figure.get_figheight() > 6 else 0.88, subtitle, fontsize=8.8, color=INK2,
                   va="top", linespacing=1.4)


def point(ax, x, y, lo, hi, color, hollow=False, marker="o", label_value=True, dy=0.0):
    ax.plot([lo, hi], [y, y], color=color, linewidth=2, solid_capstyle="round", zorder=2)
    ax.scatter([x], [y], s=64, marker=marker, zorder=3, linewidths=2,
               facecolors=SURFACE if hollow else color, edgecolors=color)
    if label_value:
        if hi > 96:  # no room on the right: label to the left of the interval
            ax.text(lo - 1.2, y + dy, f"{round(x)} %", va="center", ha="right", fontsize=9, color=INK)
        else:
            ax.text(hi + 1.2, y + dy, f"{round(x)} %", va="center", ha="left", fontsize=9, color=INK)


def row_label(ax, y0, name, lines):
    """Configuration name, then its n and request lines, right-aligned left of the plot."""
    two = "\n" in name
    ax.text(-3, y0 + (0.14 if two else 0.10), name, ha="right", va="center", fontsize=9.5, color=INK)
    first = y0 - (0.30 if two else 0.18)
    for k, line in enumerate(lines):
        ax.text(-3, first - 0.17 * k, line, ha="right", va="center", fontsize=8, color=INK2)


def load(kind, cfg, scored):
    folder = ROOT / SOURCES[kind].get(cfg, {"traits": "results/traits_main", "trophic": "results/trophic",
                                            "negatives": "results/negatives"}[kind])
    rows = [r for r in csv.DictReader(open(folder / scored, encoding="utf-8")) if r["config"] == cfg]
    return rows, folder / "runs.jsonl"


def fig_traits():
    qids = {r["qid"] for r in csv.DictReader(open(ROOT / "data/benchmark_traits.csv", encoding="utf-8"))}
    series = [("body_size", "Body size", ACCENT, False, "o"), ("habitat", "Habitat", DARK, False, "s")]
    fig, ax = plt.subplots(figsize=(8.6, 7.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.78, bottom=0.06)
    for i, (cfg, name) in enumerate(CONFIGS):
        rows, runs = load("traits", cfg, "scored_traits.csv")
        ok = valid_requests(runs, qids)
        key = "pipeline" if cfg.startswith("pipeline") else "plazi"
        y0 = len(CONFIGS) - 1 - i
        ns = []
        for j, (trait, lab, col, hollow, mk) in enumerate(series):
            rs = [r for r in rows if r["trait"] == trait and r["plazi"] != "unscored"]
            k, n = sum(r[key] == "correct" for r in rs), len(rs)
            lo, hi = wilson(k, n)
            point(ax, 100 * k / n, y0 + (0.14 if j == 0 else -0.14), lo, hi, col, hollow, mk)
            ns.append(n)
        lines = [f"n = {ns[0]} body size, {ns[1]} habitat"]
        if ok.get(cfg, 0) < len(qids):
            lines.append(f"{ok.get(cfg, 0)} of {len(qids)} requests succeeded")
        row_label(ax, y0, name, lines)
    ax.set_yticks([])
    ax.set_ylim(-0.75, len(CONFIGS) - 0.4)
    style(ax, "Given the right treatment, body size is read in 83 % of cases;\nthe pipeline's own request path reaches 43 %",
          "Treatment benchmark: correct answers per configuration, with 95 % Wilson intervals. Service\n"
          "configurations: the Plazi answer; pipeline: the answer it keeps. Dense retrieval: successful requests only.")
    handles = [plt.Line2D([], [], marker=mk, color=col, markerfacecolor=SURFACE if h else col, linewidth=2,
                          markersize=7, label=lab) for _, lab, col, h, mk in series]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.37, 0.80), ncol=2, frameon=False, fontsize=9)
    return fig


def fig_trophic():
    qids = {r["qid"] for r in csv.DictReader(open(ROOT / "data/benchmark_trophic.csv", encoding="utf-8"))}
    base = json.load(open(ROOT / "results/trophic/summary_trophic.json"))["baselines"]
    b_doc, b_e2e = 100 * base["constant 'fungi' (doc gold)"], 100 * base["constant 'fungi' (e2e gold)"]
    series = [("food", "Food named", ACCENT, False, "o"), ("answer", "Guild of the answer", DARK, False, "s"),
              ("pipeline", "Guild recorded by the pipeline", MID, True, "o")]
    fig, ax = plt.subplots(figsize=(8.6, 8.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.77, bottom=0.05)
    for i, (cfg, name) in enumerate(CONFIGS):
        rs, runs = load("trophic", cfg, "scored_trophic.csv")
        ok = valid_requests(runs, qids)
        y0 = len(CONFIGS) - 1 - i
        n = len(rs)
        bx = b_doc if cfg.startswith("doc") else b_e2e
        ax.plot([bx, bx], [y0 - 0.36, y0 + 0.36], color=INK2, linewidth=1.2, linestyle=(0, (2, 2)), zorder=1)
        for j, (key, lab, col, hollow, mk) in enumerate(series):
            if key == "pipeline" and "generative" not in cfg and cfg != "pipeline":
                continue
            k = (sum(int(r["food_match"]) for r in rs) if key == "food"
                 else sum(r[key] == "correct" for r in rs))
            lo, hi = wilson(k, n)
            point(ax, 100 * k / n, y0 + 0.22 - 0.22 * j, lo, hi, col, hollow, mk)
        lines = [f"n = {n}"]
        if ok.get(cfg, 0) < len(qids):
            lines.append(f"{ok.get(cfg, 0)} of {len(qids)} requests succeeded")
        row_label(ax, y0, name, lines)
    ax.set_yticks([])
    ax.set_ylim(-0.75, len(CONFIGS) - 0.4)
    style(ax, "Generative answers name the documented food in 69 % of cases given the source,\n44 % end to end and 33 % through the pipeline's own request path",
          "Trophic-guild benchmark (102 diet questions), with 95 % Wilson intervals. Dashed line: the constant answer \"fungi\",\n"
          "scored against per-question gold guilds (gold document) or the taxon's gold guilds (end to end). The pipeline\n"
          "runs in generative mode only. Dense retrieval is scored on its successful requests only.")
    handles = [plt.Line2D([], [], marker=mk, color=col, markerfacecolor=SURFACE if h else col, linewidth=2,
                          markersize=7, label=lab) for _, lab, col, h, mk in series]
    handles.append(plt.Line2D([], [], color=INK2, linewidth=1.2, linestyle=(0, (2, 2)), label='Constant "fungi" answer'))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.37, 0.80), ncol=2, frameon=False, fontsize=9)
    return fig


def selection(bench_key, rule, measure):
    a = json.load(open(ROOT / "results/attribution/attribution.json"))
    sel = a["traits"]["traits_pipeline/pipeline/selection_rules"] if bench_key == "traits" \
        else a["trophic"]["trophic_pipeline/pipeline/selection_rules(species)"]
    return sel[rule][measure]["k"], sel[rule][measure]["n"]


def fig_pipeline_losses():
    """Stage by stage along the pipeline's request path, on the same items; hollow: P18 simulated."""
    tr = [r for r in csv.DictReader(open(ROOT / "results/traits_pipeline/scored_traits.csv", encoding="utf-8"))
          if r["trait"] in ("body_size", "habitat") and r["plazi"] != "unscored"]
    di = [r for r in csv.DictReader(open(ROOT / "results/trophic_pipeline/scored_trophic.csv", encoding="utf-8"))
          if r["rank"] == "species"]
    panels = [
        ("Treatment benchmark: body size and habitat", len(tr), [
            ("Gold document reached the reader", sum(int(r["gold_in_pipeline_ids"]) for r in tr), None),
            ("Answer the pipeline keeps is correct", sum(r["pipeline"] == "correct" for r in tr),
             selection("traits", "first_not_denying", "answer_correct")[0]),
            ("Value it stores is correct", sum(r["stored"] == "correct" for r in tr),
             selection("traits", "first_not_denying", "stored_correct")[0])]),
        ("Trophic benchmark: species diet (guild)", len(di), [
            ("Gold document reached the reader", sum(int(r["gold_retrieved"]) for r in di), None),
            ("Answer the pipeline keeps is correct", sum(r["answer"] == "correct" for r in di),
             selection("trophic", "first_not_denying", "answer_correct")[0]),
            ("Value it stores is correct", sum(r["pipeline"] == "correct" for r in di),
             selection("trophic", "first_not_denying", "stored_correct")[0])]),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(8.6, 6.8), dpi=200, sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.70, bottom=0.07, hspace=0.42)
    for ax, (title, n, stages) in zip(axes, panels):
        for i, (lab, k, k18) in enumerate(stages):
            y = len(stages) - 1 - i
            lo, hi = wilson(k, n)
            point(ax, 100 * k / n, y + (0.13 if k18 is not None else 0), lo, hi, ACCENT)
            if k18 is not None:
                lo18, hi18 = wilson(k18, n)
                point(ax, 100 * k18 / n, y - 0.17, lo18, hi18, ACCENT, hollow=True)
            ax.text(-3, y, lab, ha="right", va="center", fontsize=9.5, color=INK)
        ax.set_yticks([])
        ax.set_ylim(-0.6, len(stages) - 0.4)
        ax.set_xlim(-2, 102)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(["0 %", "25 %", "50 %", "75 %", "100 %"], color=INK2, fontsize=9)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(axis="both", length=0)
        ax.set_title(f"{title} (n = {n})", loc="left", fontsize=9.5, color=INK, x=-0.53, pad=6)
    fig.text(0.012, 0.985, "Where the pipeline's own request path loses correct values:\n"
             "answer selection for trait questions, retrieval for diet", fontsize=12, fontweight="bold",
             color=INK, va="top", linespacing=1.3)
    fig.text(0.012, 0.885, "Same items through each stage, with 95 % Wilson intervals. Hollow: the same responses if the\n"
             "pipeline kept the first answer that does not deny the trait (action P18) instead of the first non-empty one.",
             fontsize=8.8, color=INK2, va="top", linespacing=1.4)
    handles = [plt.Line2D([], [], marker="o", color=ACCENT, markerfacecolor=ACCENT, linewidth=2, markersize=7,
                          label="As run"),
               plt.Line2D([], [], marker="o", color=ACCENT, markerfacecolor=SURFACE, linewidth=2, markersize=7,
                          label="With P18 (simulated)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.37, 0.80), ncol=2, frameon=False, fontsize=9)
    return fig


def fig_negatives():
    rows = []
    for c, _ in CONFIGS:
        rows += load("negatives", c, "scored_traits.csv")[0] if (ROOT / SOURCES["negatives"].get(c, "results/negatives")).exists() else []
    cfgs = [(c, n) for c, n in CONFIGS if any(r["config"] == c for r in rows)]
    series = [("body_size_negative", "Body size", ACCENT, False, "o"),
              ("trophic_guild_negative", "Diet", DARK, False, "s")]
    fig, ax = plt.subplots(figsize=(8.6, 6.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.76, bottom=0.07)
    for i, (cfg, name) in enumerate(cfgs):
        y0 = len(cfgs) - 1 - i
        key = "pipeline" if cfg.startswith("pipeline") else "plazi"
        ns = []
        for j, (trait, lab, col, hollow, mk) in enumerate(series):
            rs = [r for r in rows if r["config"] == cfg and r["trait"] == trait]
            if trait == "trophic_guild_negative":
                # read like the answerable diet questions: any feeding group the answer states is a value given
                import score_trophic as so  # noqa: E402  (needs trait_extraction_v3.py)
                taxa = {b["qid"]: b["taxon"] for b in csv.DictReader(open(ROOT / "data/benchmark_negatives.csv", encoding="utf-8"))}
                ans = "pipeline_answer" if cfg.startswith("pipeline") else "plazi_answer"
                k = sum(not so.answer_guilds(r[ans], taxa[r["qid"]]) for r in rs)
            else:
                k = sum(r[key] == "correct" for r in rs)
            n = len(rs)
            lo, hi = wilson(k, n)
            point(ax, 100 * k / n, y0 + (0.14 if j == 0 else -0.14), lo, hi, col, hollow, mk)
            ns.append(n)
        row_label(ax, y0, name, [f"n = {ns[0]} body size, {ns[1]} diet"])
    ax.set_yticks([])
    ax.set_ylim(-0.75, len(cfgs) - 0.4)
    style(ax, "When nothing is documented, the pipeline abstains; the service's own\nretrieval gives a body size for half the species or more",
          "Negative items (trait not documented in the treatment or in any document the pipeline's phrase\n"
          "search returns): share answered correctly by giving no value, with 95 % Wilson intervals. Diet: any feeding group\n"
          "the answer states counts as a value (an extractive \"leaf litter\" counts), as for the answerable diet questions.")
    handles = [plt.Line2D([], [], marker=mk, color=col, markerfacecolor=col, linewidth=2,
                          markersize=7, label=lab) for _, lab, col, h, mk in series]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.37, 0.80), ncol=2, frameon=False, fontsize=9)
    return fig


def fig_pipeline_tables():
    rows = list(csv.DictReader(open(ROOT / "results/pipeline_output/scored_pipeline_output.csv", encoding="utf-8")))
    tro = [r for r in rows if r["trait"] == "trophic_guild"]
    bars = [
        ("Version 3, all species", [r for r in tro if r["version"] == "v3"]),
        ("Version 3, not in the expert review", [r for r in tro if r["version"] == "v3" and r["in_expert_review"] == "0"]),
        ("Version 3, in the expert review", [r for r in tro if r["version"] == "v3" and r["in_expert_review"] == "1"]),
        ("Genus table", [r for r in tro if r["version"] == "genus_batch"]),
    ]
    cats = [("correct", "Right guild stored", ACCENT, SURFACE), ("wrong", "Wrong guild stored", ORANGE, INK),
            ("abstained", "Nothing stored", LIGHT, INK)]
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.70, bottom=0.08)
    for i, (lab, rs) in enumerate(bars):
        y = len(bars) - 1 - i
        n, left = len(rs), 0.0
        for key, _, col, txt in cats:
            k = sum(r["outcome"] == key for r in rs)
            w = 100 * k / n
            if k:
                ax.barh(y, w - 0.4, left=left + 0.2, height=0.56, color=col, edgecolor=SURFACE, linewidth=0)
                if w >= 3:
                    ax.text(left + w / 2, y, str(k), ha="center", va="center", fontsize=9 if w >= 7 else 8, color=txt)
            left += w
        unit = "genera" if lab.startswith("Genus") else "species"
        ax.text(-3, y + 0.1, lab, ha="right", va="center", fontsize=9.5, color=INK)
        ax.text(-3, y - 0.2, f"n = {n} {unit} with a documented diet", ha="right", va="center", fontsize=8, color=INK2)
    ax.set_yticks([])
    ax.set_ylim(-0.6, len(bars) - 0.4)
    style(ax, "Version 3 stores no wrong species guild, but a guild for only\n4 of the 21 species the expert review did not cover",
          "The version 3 trait table and the genus table of the pipeline (collembola-trait-mining, commit 1d5b5b6),\n"
          "for the species and genera of the trophic benchmark, against its gold guilds. Numbers inside bars are counts.")
    handles = [plt.Rectangle((0, 0), 1, 1, color=col, label=lab) for _, lab, col, _ in cats]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.37, 0.78), ncol=3, frameon=False, fontsize=9)
    return fig


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("fig_traits", fig_traits), ("fig_trophic", fig_trophic),
                       ("fig_pipeline_losses", fig_pipeline_losses), ("fig_negatives", fig_negatives),
                       ("fig_pipeline_tables", fig_pipeline_tables)):
        fig = make()
        doc_scale(fig)
        for ext in ("png", "svg"):
            fig.savefig(OUT / f"{name}.{ext}", facecolor=SURFACE, **({"bbox_inches": "tight", "pad_inches": 0.15} if DOC else {}))
        plt.close(fig)
        print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
