"""
Draw the D10.3 performance figures (curves) from the raw and scored results.

  results/figures/perf_position.(png|svg)     body size read correctly against where the value sits in
                                              the treatment, for the two readers given the treatment
  results/figures/perf_threshold.(png|svg)    the extractive reader's answer score as a threshold:
                                              correct answers kept against values given where nothing
                                              is documented (an ROC-type curve), body size and diet
  results/figures/perf_pr.(png|svg)           precision and recall: extractive curves (score threshold) and the
                                              operating points of the generative configurations and the pipeline
  results/figures/perf_value_error.(png|svg)  body size: how far off the stated values are (error size)
  results/figures/perf_labels.(png|svg)       label-level precision and recall for feeding groups and habitat classes
  results/figures/perf_selective.(png|svg)    accuracy against coverage for three confidence signals
  results/figures/perf_calibration.(png|svg)  observed accuracy against the extractive answer score
  results/figures/perf_latency.(png|svg)      response time per configuration (median, quartiles, 5-95 %)

Only the extractive reader returns an answer score (answer_score); the generative reader returns
none, so the threshold and calibration figures cover the extractive configurations only.

Usage: python3 scripts/make_performance_figures.py   (needs matplotlib; run from the repository root)
"""

import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_figures as mf  # noqa: E402  (style, colours, Wilson intervals)
import score_trophic as so  # noqa: E402  (needs trait_extraction_v3.py)

plt = mf.plt
ROOT, OUT = mf.ROOT, mf.OUT
ACCENT, ORANGE, INK, INK2, GRID, SURFACE, DARK = mf.ACCENT, mf.ORANGE, mf.INK, mf.INK2, mf.GRID, mf.SURFACE, mf.DARK
AQUA = "#1baf7a"  # third categorical slot; blue, orange and aqua validate as an all-pairs set


def scored(path):
    return list(csv.DictReader(open(ROOT / path, encoding="utf-8")))


def runs(path):
    latest = {}
    for line in open(ROOT / path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if not r.get("error") and r.get("response"):
                latest[(r["qid"], r["config"])] = r
    return latest


def plazi_score(resp):
    for c in resp.get("collection_results") or []:
        if c.get("collection") == "plazi":
            a = (c.get("answers") or [{}])[0]
            return a.get("answer_score")
    return None


def best_score(resp):
    s = [((c.get("answers") or [{}])[0].get("answer_score") or 0.0) for c in resp.get("collection_results") or []
         if (c.get("answers") or [{}])[0].get("answer")]
    return max(s) if s else None


def frame(fig, title, subtitle, sub_y=0.88):
    fig.patch.set_facecolor(SURFACE)
    if mf.DOC:
        return
    fig.text(0.012, 0.985, title, fontsize=12, fontweight="bold", color=INK, va="top", linespacing=1.3)
    fig.text(0.012, sub_y, subtitle, fontsize=8.8, color=INK2, va="top", linespacing=1.4)


def axes_style(ax, xlabel=None, ylabel=None, pct_x=False, pct_y=True):
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(axis="both", length=0, colors=INK2, labelsize=9)
    if pct_y:
        ax.set_ylim(-3, 103)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_yticklabels(["0 %", "25 %", "50 %", "75 %", "100 %"])
    if pct_x:
        ax.set_xlim(-3, 103)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(["0 %", "25 %", "50 %", "75 %", "100 %"])
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=9, color=INK2)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=9, color=INK2)


def legend(fig, handles, y, ncol=2, x=0.08):
    if mf.DOC:
        # Text is scaled up in document mode, so a legend hung from y would grow into the panel titles:
        # stand it on a line just above the titles instead (the saved figure is cropped tight).
        y0 = fig.subplotpars.top + 0.45 / fig.get_figheight()
        fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(x, y0), ncol=ncol, frameon=False, fontsize=9)
        return
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(x, y), ncol=ncol, frameon=False, fontsize=9)


def line_handle(color, label, hollow=False, marker="o"):
    return plt.Line2D([], [], marker=marker, color=color, markerfacecolor=SURFACE if hollow else color,
                      linewidth=2, markersize=7, label=label)


# ---------------------------------------------------------------------------

BINS = [(0, 600, "0–600"), (600, 1500, "600–1,500"), (1500, 10 ** 9, "over 1,500")]


def perf_position():
    rows = [r for r in scored("results/traits_main/scored_traits.csv") if r["trait"] == "body_size"]
    series = [("doc_extractive", "Extractive reader (sees about 1,500 characters)", ACCENT, "o"),
              ("doc_generative", "Generative reader (sees about 600 characters)", ORANGE, "s")]
    fig, ax = plt.subplots(figsize=(8.6, 5.4), dpi=200)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.70, bottom=0.14)
    xs = list(range(len(BINS)))
    for j, (cfg, lab, col, mk) in enumerate(series):
        pts = []
        for i, (lo, hi, _) in enumerate(BINS):
            rs = [r for r in rows if r["config"] == cfg and lo <= int(r["answer_offset"]) < hi]
            k, n = sum(r["plazi"] == "correct" for r in rs), len(rs)
            l, h = mf.wilson(k, n)
            x = i + (-0.06 if j == 0 else 0.06)
            ax.plot([x, x], [l, h], color=col, linewidth=2, solid_capstyle="round", zorder=2)
            pts.append((x, 100 * k / n, n, k))
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, linewidth=2, zorder=2)
        for x, y, n, k in pts:
            ax.scatter([x], [y], s=64, marker=mk, color=col, edgecolors=SURFACE, linewidths=2, zorder=3)
            ax.text(x + (-0.09 if j == 0 else 0.09), y, f"{round(y)} %", ha="right" if j == 0 else "left",
                    va="center", fontsize=9, color=INK)
    ns = [sum(1 for r in rows if r["config"] == "doc_extractive" and lo <= int(r["answer_offset"]) < hi)
          for lo, hi, _ in BINS]
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{lab} characters\nn = {n}" for (_, _, lab), n in zip(BINS, ns)])
    ax.set_xlim(-0.5, len(BINS) - 0.5)
    axes_style(ax, xlabel="Position of the body length in the treatment text",
               ylabel="Body length read correctly")
    frame(fig, "The extractive reader finds every body length in the first 600 characters\n"
          "but only 4 of 12 beyond its 1,500-character window",
          "Treatment benchmark, body-size questions (n = 60), gold treatment supplied. 95 % Wilson intervals.\n"
          "The generative reader is shown about 600 characters chosen by keyword overlap, not the start of the text,\n"
          "so its accuracy does not depend on position: about half the body lengths at every position.", sub_y=0.885)
    legend(fig, [line_handle(c, l, marker=m) for _, l, c, m in series], 0.75, ncol=2, x=0.09)
    return fig


def labelled(cfg, panel):
    """Answerable (pos) and negative (neg) items of one configuration, as each benchmark is scored.
    pos: (score, outcome) with outcome correct / wrong / no_answer; neg: (score, value_given).
    Body size: the treatment benchmark (Plazi answer). Diet: the trophic benchmark (the
    highest-scoring answer). Negatives: the negative items (Plazi answer, as in their table).
    Scores exist for the extractive reader only (None otherwise)."""
    if panel == "body_size":
        folder = "results/traits_pipeline" if cfg == "pipeline" else "results/traits_main"
        rows = [r for r in scored(folder + "/scored_traits.csv") if r["config"] == cfg and r["trait"] == "body_size"]
        rr = runs(folder + "/runs.jsonl")
        key = "pipeline" if cfg == "pipeline" else "plazi"
        pos = [(plazi_score(rr[(r["qid"], cfg)]["response"]), r[key]) for r in rows]
    else:
        folder = "results/trophic_pipeline" if cfg == "pipeline" else "results/trophic"
        rows = [r for r in scored(folder + "/scored_trophic.csv") if r["config"] == cfg]
        rr = runs(folder + "/runs.jsonl")
        pos = [(best_score(rr[(r["qid"], cfg)]["response"]), r["answer"]) for r in rows]
    trait = "body_size_negative" if panel == "body_size" else "trophic_guild_negative"
    nrows = [r for r in scored("results/negatives/scored_traits.csv") if r["config"] == cfg and r["trait"] == trait]
    nbench = {b["qid"]: b for b in csv.DictReader(open(ROOT / "data/benchmark_negatives.csv", encoding="utf-8"))}
    nr = runs("results/negatives/runs.jsonl")
    key = "pipeline" if cfg == "pipeline" else "plazi"
    if panel == "body_size":
        neg = [(plazi_score(nr[(r["qid"], cfg)]["response"]), r[key] == "wrong") for r in nrows]
    else:  # diet: read like the answerable questions (any feeding group stated counts as a value given)
        ans_key = "pipeline_answer" if cfg == "pipeline" else "plazi_answer"
        neg = [(plazi_score(nr[(r["qid"], cfg)]["response"]), bool(so.answer_guilds(r[ans_key], r["qid"] and
                nbench[r["qid"]]["taxon"]))) for r in nrows]
    return pos, neg, rows, nrows


def threshold_points(pos, neg):
    """pos: [(score, correct, asserted)], neg: [(score, asserted)]. Sweep the score threshold."""
    thresholds = sorted({s for s, _, _ in pos} | {s for s, _ in neg} | {0.0}, reverse=True)
    pts = [(0.0, 0.0, 1.01)]
    for t in thresholds:
        y = sum(1 for s, c, a in pos if c and s >= t) / len(pos)
        x = sum(1 for s, a in neg if a and s >= t) / len(neg)
        pts.append((100 * x, 100 * y, t))
    return pts


def perf_threshold():
    configs = [("doc_extractive", "Gold document, extractive", ACCENT),
               ("e2e_sparse_extractive", "End to end, sparse, extractive", ORANGE)]
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 5.4), dpi=200, sharey=True)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.62, bottom=0.13, wspace=0.12)
    for ax, panel in zip(axes, ("body_size", "trophic_guild")):
        for cfg, lab, col in configs:
            p_, n_, _, _ = labelled(cfg, panel)
            pos = [(sc or 0.0, o == "correct", o in ("correct", "wrong")) for sc, o in p_]
            neg = [(sc or 0.0, given) for sc, given in n_]
            pts = threshold_points(pos, neg)
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, linewidth=2, drawstyle="steps-post", zorder=2)
            x0, y0, _ = pts[-1]  # threshold 0: every answer kept, as run
            ax.scatter([x0], [y0], s=64, color=col, edgecolors=SURFACE, linewidths=2, zorder=3)
            lab = f"as run: {round(y0)} % / {round(x0)} %"
            if y0 < x0 and x0 > 60:  # under the diagonal, far right: from the empty lower-right corner, with an arrow
                ax.annotate(lab, (x0, y0), xytext=(99, max(8, y0 - 33)), ha="right", va="center", fontsize=8.5,
                            color=INK, arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.8, shrinkB=5))
            elif y0 < x0:  # under the diagonal: beneath the dot, clear of the curve that rises to it
                ax.text(x0 + 2, y0 - 4, lab, ha="left", va="top", fontsize=8.5, color=INK)
            else:
                ax.text(x0 - 2 if x0 > 60 else x0 + 2, y0 + 4, lab, ha="right" if x0 > 60 else "left", va="bottom",
                        fontsize=8.5, color=INK)
            # the threshold 0.5, a common default
            p5 = min(pts, key=lambda p: abs(p[2] - 0.5) if p[2] <= 1 else 9)
            ax.scatter([p5[0]], [p5[1]], s=56, facecolors=SURFACE, edgecolors=col, linewidths=2, zorder=3)
        ax.plot([0, 100], [0, 100], color=INK2, linewidth=1, linestyle=(0, (2, 2)), zorder=1)
        axes_style(ax, xlabel="Questions with nothing documented given a value", pct_x=True)
        n_pos = len(labelled("doc_extractive", panel)[0])
        ax.set_title(("Body size" if panel == "body_size" else "Diet (guild)") + f": {n_pos} answerable, 30 not",
                     loc="left", fontsize=9.5, color=INK)
    axes[0].set_ylabel("Answerable questions answered correctly", fontsize=9, color=INK2)
    frame(fig, "End to end, the extractive answer score cannot filter invented values:\n"
          "for body size it is no better than chance at separating them from correct answers",
          "Each curve sweeps a threshold on the reader's answer score: below it the answer is withheld. Filled dot:\n"
          "every answer kept, as run (correct / given a value with nothing documented). Hollow dot: threshold 0.5.\n"
          "Dashed: no better than chance. The generative reader returns no score. Body size: the Plazi answer. Diet: the highest-\n"
          "scoring answer; any feeding group it states counts as a value, for answerable and no-answer questions alike.",
          sub_y=0.89)
    legend(fig, [line_handle(c, l) for _, l, c in configs], 0.715, ncol=2, x=0.09)
    return fig


RC = ROOT / "results/reader_comparison/summary.json"
RIGOR = ROOT / "results/rigor/summary.json"
SET_COLOR = {"gold document": ACCENT, "service retrieval": ORANGE, "pipeline documents": None}  # aqua set below
CFG_OF = {"gold document": ("doc_extractive", "doc_generative"),
          "service retrieval": ("e2e_sparse_extractive", "e2e_sparse_generative"),
          "pipeline documents": ("pipeline_extractive", "pipeline")}
CFG_LABEL = {"doc_extractive": "Gold document, extractive", "doc_generative": "Gold document, generative",
             "e2e_sparse_extractive": "Service search, extractive", "e2e_sparse_generative": "Service search, generative",
             "pipeline_extractive": "Pipeline's documents, extractive", "pipeline": "Trait pipeline (generative)"}


def perf_value_error():
    """How far off the stated body sizes are (Domazetoski et al. 2025 score numerical traits by error size)."""
    rig = json.load(open(RIGOR))["numeric_error"]
    colors = {"gold document": ACCENT, "service retrieval": ORANGE, "pipeline documents": AQUA}
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 5.6), dpi=200, sharey=True)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.64, bottom=0.15, wspace=0.10)
    for ax, (reader, idx) in zip(axes, (("Extractive reader", 0), ("Generative reader", 1))):
        for setting, col in colors.items():
            v = rig[f"{CFG_OF[setting][idx]} | answer"]
            errs = [max(e, 0.001) * 100 for e in v["rel_errors"]]
            n = len(errs)
            xs = [0.1] + errs + [1e4]
            ys = [0] + [100 * (i + 1) / n for i in range(n)] + [100]
            ax.step(xs, ys, where="post", color=col, linewidth=2,
                    label=f"{setting[0].upper() + setting[1:]}: {n} ({v['negatives_with_value']}/30)")
        ax.axvline(2, color=INK2, linewidth=1, linestyle=(0, (2, 2)))
        ax.axvline(25, color=INK2, linewidth=1, linestyle=(0, (1, 3)))
        ax.text(2.2, 45, "2 %", fontsize=8, color=INK2)
        ax.text(27, 45, "25 %", fontsize=8, color=INK2)
        ax.set_xscale("log")
        ax.set_xlim(0.08, 1.2e4)
        ax.set_xticks([0.1, 1, 10, 100, 1000])
        ax.set_xticklabels(["exact", "1 %", "10 %", "100 %", "1,000 %"])
        axes_style(ax)
        ax.set_title(reader, loc="left", fontsize=10, color=INK, fontweight="bold")
        lg = ax.legend(loc="lower right", frameon=True, fontsize=7.5, title="Values stated (and given\nwhere none documented)",
                       title_fontsize=7.5, alignment="left", facecolor=SURFACE, edgecolor=SURFACE, framealpha=1)
        lg.set_zorder(5)
    axes[0].set_ylabel("Answers with a value (cumulative)", fontsize=9, color=INK2)
    fig.text(0.53, 0.06, "Relative error of the stated body length (closest gold value, log scale)", fontsize=9,
             color=INK2, ha="center")
    frame(fig, "Wrong body sizes are rarely near misses: with the service's own search, 13 of the extractive\n"
          "reader's 20 wrong values are more than 25 % off, mostly another species' size",
          "Cumulative share of answers that state a body length, by the relative error of the stated value closest to a gold value\n"
          "(answers to the 60 body-size questions). Steps at \"exact\" are answers within rounding. In brackets: of the 30 species\n"
          "with nothing documented, how many were given a value anyway (no gold value, so not plotted). Normalised mean absolute error of\n"
          "the wrong values: 3.8 (service, extractive), 0.41 (service, generative), 0.55 (pipeline). Extractive: the gold-document\n"
          "line lies under the pipeline line (both all exact).", sub_y=0.89)
    return fig


def perf_labels():
    """Label-level precision and recall for the categorical traits (Domazetoski et al. 2025; Keck et al. 2025)."""
    rig = json.load(open(RIGOR))
    lab, dq, base = rig["labels"], rig["diet_questions"], rig["fungi_baseline"]
    cfgs = list(CFG_LABEL)
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 6.2), dpi=200, sharey=True)
    fig.subplots_adjust(left=0.22, right=0.985, top=0.64, bottom=0.09, wspace=0.08)
    for ax, trait in zip(axes, ("diet", "habitat")):
        for i, cfg in enumerate(cfgs):
            y = len(cfgs) - 1 - i
            v = lab[f"{trait} | {cfg} | answer"]
            for key, ci, col, mk, dy in (("micro_precision", "precision_ci95", ACCENT, "o", 0.16),
                                         ("micro_recall", "recall_ci95", ORANGE, "s", -0.16)):
                x = 100 * v[key]
                lo, hi = (100 * c for c in v[ci])
                ax.plot([lo, hi], [y + dy, y + dy], color=col, linewidth=2, zorder=2)
                ax.scatter([x], [y + dy], s=50, marker=mk, color=col, edgecolors=SURFACE, linewidths=1.5, zorder=3)
            if trait == "diet":
                lenient = 100 * dq[f"{cfg} | answer"]["precision"]
                ax.scatter([lenient], [y + 0.16], s=50, marker="o", facecolors=SURFACE, edgecolors=INK2,
                           linewidths=1.5, zorder=3)
                b = base["per-question gold (gold document)" if cfg.startswith("doc") else "taxon gold (end to end, pipeline)"]
                ax.plot([100 * b["label_precision"]] * 2, [y - 0.38, y + 0.38], color=INK2, linewidth=1,
                        linestyle=(0, (2, 2)), zorder=1)
        axes_style(ax, pct_x=True, pct_y=False)
        ax.grid(axis="y", visible=False)
        ax.set_title("Diet: feeding groups" if trait == "diet" else "Habitat: habitat classes", loc="left",
                     fontsize=10, color=INK, fontweight="bold")
    axes[0].set_yticks(range(len(cfgs)))
    axes[0].set_yticklabels([CFG_LABEL[c] for c in reversed(cfgs)], fontsize=9, color=INK)
    frame(fig, "Scored label by label, end-to-end generative diets are 58–60 % precise, as precise as always\n"
          "answering \"fungi\" (58 %), but they recover more of the documented groups (45–62 % against 34 %)",
          "Micro-averaged over labels, with bootstrap 95 % intervals: precision = feeding groups or habitat classes given that are in\n"
          "the gold (labels given for the 30 diet questions with nothing documented count as wrong); recall = gold labels recovered.\n"
          "Open grey circle: per-question precision (right when any group matches). Dashed: precision of the constant answer \"fungi\".\n"
          "A group supported by another document counts as wrong, so label precision is a lower bound and per-question an upper one.",
          sub_y=0.895)
    legend(fig, [line_handle(ACCENT, "Label precision"), line_handle(ORANGE, "Label recall", marker="s"),
                 plt.Line2D([], [], marker="o", color=INK2, markerfacecolor=SURFACE, linewidth=0, markersize=7,
                            label="Per-question precision (diet)"),
                 plt.Line2D([], [], color=INK2, linewidth=1, linestyle=(0, (2, 2)), label='Constant "fungi"')],
           0.725, ncol=4, x=0.22)
    return fig


def perf_selective():
    """Accuracy against coverage for three confidence signals (Münch et al. 2026)."""
    sel = json.load(open(RIGOR))["selective"]
    settings = [("gold document", "Gold document"), ("service retrieval", "Service search"),
                ("pipeline documents", "Pipeline's documents")]
    fig, axes = plt.subplots(2, 3, figsize=(10.4, 7.9), dpi=200, sharex=True, sharey=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.67, bottom=0.08, wspace=0.16, hspace=0.25)
    for row, trait in enumerate(("body size", "diet")):
        for col, (setting, title) in enumerate(settings):
            ax = axes[row][col]
            v = sel[f"{trait} | {setting}"]
            share = 100 * v["n_answerable"] / v["n_questions"]
            ax.axvline(share, color=INK2, linewidth=1, linestyle=(0, (2, 2)))
            curve = v["extractive_score_curve"]
            ax.plot([100 * c["coverage"] for c in curve], [100 * c["accuracy"] for c in curve], color=ACCENT,
                    linewidth=2, zorder=2)
            for key, mk, face, col_ in (("generative_all", "s", SURFACE, ORANGE), ("generative_plain", "^", SURFACE, ORANGE),
                                        ("readers_agree", "D", AQUA, AQUA)):
                p = v[key]
                if p["accuracy"] is not None:
                    ax.scatter([100 * p["coverage"]], [100 * p["accuracy"]], s=62, marker=mk, facecolors=face,
                               edgecolors=col_, linewidths=2, zorder=4)
            axes_style(ax, pct_x=True)
            ax.set_xticks([0, 50, 100])
            ax.set_xticklabels(["0 %", "50 %", "100 %"])
            ax.set_ylim(30, 104)
            ax.set_yticks([40, 60, 80, 100])
            ax.set_yticklabels(["40 %", "60 %", "80 %", "100 %"])
            if row == 0:
                ax.set_title(title, loc="left", fontsize=10, color=INK, fontweight="bold")
            if row == 1:
                ax.set_xlabel("Questions given a value (coverage)", fontsize=9, color=INK2)
            if col == 0:
                ax.set_ylabel(("Body size" if trait == "body size" else "Diet") + "\nValues given that are right",
                              fontsize=9, color=INK2)
    frame(fig, "When the two readers agree, 97–100 % of diet answers are right; the extractive score separates\n"
          "good from bad diet answers, but not body sizes found by the service's own search",
          "Each panel: answerable and no-answer questions together (90 for body size, 132 for diet). x: share of questions given a\n"
          "value; y: share of those values that are right. Blue line: extractive answers kept above a falling score threshold. Orange:\n"
          "all generative answers (square) and only plainly worded ones (triangle). Aqua: generative answers kept only when the\n"
          "extractive reader gives an agreeing value on the same documents (where it hides a triangle, both are at the same point).\n"
          "Dashed: share of questions that have an answer.", sub_y=0.895)
    handles = [line_handle(ACCENT, "Extractive, score threshold"),
               plt.Line2D([], [], marker="s", color=ORANGE, markerfacecolor=SURFACE, linewidth=0, markersize=7,
                          markeredgewidth=2, label="Generative, all"),
               plt.Line2D([], [], marker="^", color=ORANGE, markerfacecolor=SURFACE, linewidth=0, markersize=7,
                          markeredgewidth=2, label="Generative, plain wording"),
               plt.Line2D([], [], marker="D", color=AQUA, linewidth=0, markersize=7, label="Both readers agree")]
    legend(fig, handles, 0.735, ncol=4, x=0.08)
    return fig
SETTING_SHAPE = {"service retrieval": ("o", "service"), "pipeline documents": ("s", "pipeline docs"),
                 "gold document": ("D", "gold doc")}


def perf_readers():
    """Paired comparison of the two readers on identical documents (reader_comparison.py)."""
    rc = json.load(open(RC))["readers"]
    settings = ["gold document", "service retrieval", "pipeline documents"]
    measures = ["body size correct", "habitat correct", "diet guild correct", "food named",
                "no body size given (negative)", "no diet given (negative)",
                "body size stored correctly", "habitat stored correctly", "diet guild stored correctly"]
    labels = ["Body size correct", "Habitat correct", "Diet guild correct", "Food named",
              "Negative: no body size given", "Negative: no diet given",
              "Body size stored (version 3)", "Habitat stored (version 3)", "Diet guild stored (version 3)"]
    fig, axes = plt.subplots(1, 3, figsize=(10.4, 7.4), dpi=200, sharey=True)
    fig.subplots_adjust(left=0.22, right=0.985, top=0.64, bottom=0.07, wspace=0.08)
    for ax, setting in zip(axes, settings):
        res = rc[setting]
        for i, m in enumerate(measures):
            y = len(measures) - 1 - i
            v = res[m]
            e, g = 100 * v["extractive"], 100 * v["generative"]
            ax.plot([e, g], [y, y], color=GRID, linewidth=3, zorder=1, solid_capstyle="round")
            ax.scatter([e], [y], s=56, marker="o", color=ACCENT, edgecolors=SURFACE, linewidths=1.5, zorder=3)
            ax.scatter([g], [y], s=56, marker="s", color=ORANGE, edgecolors=SURFACE, linewidths=1.5, zorder=3)
            if v["mcnemar_p"] < 0.05:
                pv = v["mcnemar_p"]
                ax.text(max(e, g) + 3, y, "p < 0.001" if pv < 0.001 else f"p = {pv:.3f}" if pv < 0.01 else f"p = {pv:.2f}",
                        fontsize=7.5, color=INK, va="center", ha="left")
        axes_style(ax, pct_x=True, pct_y=False)
        ax.set_xlim(-3, 125)
        ax.set_xticks([0, 50, 100])
        ax.set_xticklabels(["0 %", "50 %", "100 %"])
        ax.grid(axis="y", visible=False)
        n_body = res["body size correct"]["n"]
        ax.set_title(f"{setting[0].upper() + setting[1:]}", loc="left", fontsize=10, color=INK, fontweight="bold")
        for k in range(3, len(measures), 3):
            ax.axhline(len(measures) - k - 0.5, color=GRID, linewidth=0.8)
    axes[0].set_yticks(range(len(measures)))
    axes[0].set_yticklabels(list(reversed(labels)), fontsize=9, color=INK)
    frame(fig, "On the same documents, the generative reader carries the diet; the extractive reader reads\n"
          "body size more often from the right documents, but its diets can rarely be stored",
          "Share of questions per reader, paired on identical documents in each retrieval setting (n = 60 body size, 55 habitat,\n"
          "102 diet, 30 + 30 negative questions). p: exact McNemar test on the questions only one reader gets right, shown when\n"
          "below 0.05. \"Stored\" is the value trait_extraction_v3 writes from the answer; extractive spans rarely name the species\n"
          "(1–6 % against 83–89 %), so the extractor binds few of their diets. Negative items: the extractive reader returns a\n"
          "substrate such as \"leaf litter\" as a diet (p = 0.02 and 0.004); no body-size difference is significant (p = 0.06).", sub_y=0.885)
    legend(fig, [plt.Line2D([], [], marker="o", color=ACCENT, linewidth=0, markersize=7, label="Extractive reader (BioBERT)"),
                 plt.Line2D([], [], marker="s", color=ORANGE, linewidth=0, markersize=7, label="Generative reader (Qwen3-8B)")],
           0.715, ncol=2, x=0.22)
    return fig


def perf_pr():
    """Retrieval x reader x output on the precision-recall plane: rows trait, columns retrieval."""
    grid = json.load(open(RC))["precision_recall"]
    settings = [("service retrieval", "Service retrieval (BM25)"), ("pipeline documents", "Pipeline's phrase search"),
                ("gold document", "Curated gold document")]
    fig, axes = plt.subplots(2, 3, figsize=(10.4, 8.4), dpi=200, sharex=True, sharey=True)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.70, bottom=0.07, wspace=0.16 if mf.DOC else 0.08, hspace=0.30)
    for row, trait in enumerate(("body size", "diet")):
        g = grid[trait]
        for col, (setting, title) in enumerate(settings):
            ax = axes[row][col]
            for f1 in (0.4, 0.6, 0.8):
                r = [f1 / (2 - f1)] + [x / 1000 for x in range(int(1000 * f1 / (2 - f1)) + 1, 1001)]
                pr = [(100 * x, min(100.0, 100 * f1 * x / (2 * x - f1))) for x in r]
                ax.plot([a for a, _ in pr], [b for _, b in pr], color=GRID, linewidth=1, zorder=0)
                if row == 0 and col == 0 and not mf.DOC:  # in the report the caption names the curves
                    ax.text(pr[0][0] + 1, 100.5, f"F1 {f1}", fontsize=7, color=INK2, ha="left", va="bottom")
            pt = lambda lvl: (100 * g[f"{setting} | {lvl}"]["recall"], 100 * g[f"{setting} | {lvl}"]["precision"])
            ex, ga = pt("extractive | answer"), pt("generative | answer")
            rig = json.load(open(RIGOR))["body_size_facts" if trait == "body size" else "diet_questions"]
            cfg_of = {"service retrieval": ("e2e_sparse_extractive", "e2e_sparse_generative"),
                      "pipeline documents": ("pipeline_extractive", "pipeline"),
                      "gold document": ("doc_extractive", "doc_generative")}[setting]
            for cfg, lvl, ccol in ((cfg_of[0], "answer", ACCENT), (cfg_of[1], "answer", ORANGE), (cfg_of[1], "stored", ORANGE)):
                v = rig[f"{cfg} | {lvl}"]
                x, y = 100 * v["recall"], 100 * v["precision"]
                (rl, rh), (pl, ph) = v["recall_ci95"], v["precision_ci95"]
                ax.plot([100 * rl, 100 * rh], [y, y], color=ccol, linewidth=1, alpha=0.55, zorder=1)
                ax.plot([x, x], [100 * pl, 100 * ph], color=ccol, linewidth=1, alpha=0.55, zorder=1)
            gs, gp = pt("generative | stored"), pt("generative | answer_plain")
            for dst, ls in ((gs, "-"), (gp, ":")):
                ax.annotate("", xy=dst, xytext=ga, zorder=2,
                            arrowprops=dict(arrowstyle="-|>", color=INK2, lw=1, linestyle=ls, shrinkA=5, shrinkB=5))
            ax.scatter(*ex, s=70, marker="o", color=ACCENT, edgecolors=SURFACE, linewidths=1.5, zorder=4)
            ax.scatter(*ga, s=70, marker="s", facecolors=SURFACE, edgecolors=ORANGE, linewidths=2, zorder=4)
            ax.scatter(*gs, s=70, marker="s", color=ORANGE, edgecolors=SURFACE, linewidths=1.5, zorder=4)
            ax.scatter(*gp, s=70, marker="^", facecolors=SURFACE, edgecolors=ORANGE, linewidths=1.5, zorder=4)
            axes_style(ax, pct_x=True)
            ax.set_xticks([0, 50, 100])
            ax.set_xticklabels(["0 %", "50 %", "100 %"])
            ax.set_ylim(30, 104)
            ax.set_yticks([40, 60, 80, 100])
            ax.set_yticklabels(["40 %", "60 %", "80 %", "100 %"])
            if row == 0:
                ax.set_title(title, loc="left", fontsize=10, color=INK, fontweight="bold")
            if row == 1:
                ax.set_xlabel("Recall", fontsize=9, color=INK2)
            if col == 0:
                n_pos = g["service retrieval | generative | answer"]["n_pos"]
                ax.set_ylabel(("Body size" if trait == "body size" else "Diet (guild)") +
                              f", {n_pos} + 30 negative\nPrecision", fontsize=9, color=INK2)
    frame(fig, "Body size: the pipeline's retrieval and version 3 extraction lift precision to 93–100 %, costing recall;\n"
          "the curated gold document lifts both for the extractive reader. Diet: generative paths differ in recall",
          "Each panel: one retrieval setting. A value is a true positive when it matches the gold and a false positive when it is wrong\n"
          "or the question has nothing documented (30 negative items per trait). Solid arrow: from the generative answer to the value\n"
          "trait_extraction_v3 stores; dotted arrow: keeping only plainly worded generative answers. Thin lines: bootstrap 95 %\n"
          "intervals. Diet counts a question as right when any feeding group matches; per label, precision is 58–70 % (perf_labels).",
          sub_y=0.895)
    handles = [plt.Line2D([], [], marker="o", color=ACCENT, linewidth=0, markersize=7, label="Extractive answer"),
               plt.Line2D([], [], marker="s", color=ORANGE, linewidth=0, markersize=7, markerfacecolor=SURFACE,
                          markeredgewidth=2, label="Generative answer"),
               plt.Line2D([], [], marker="s", color=ORANGE, linewidth=0, markersize=7, label="Generative, stored by version 3"),
               plt.Line2D([], [], marker="^", color=ORANGE, linewidth=0, markersize=7, markerfacecolor=SURFACE,
                          markeredgewidth=1.5, label="Generative, plain wording only")]
    legend(fig, handles, 0.77, ncol=4, x=0.08)
    return fig


def perf_prevalence():
    """Precision as the share of unanswerable questions grows (reader_comparison.py counts)."""
    grid = json.load(open(RC))["precision_recall"]
    series = [("service retrieval | extractive | answer", "Service, extractive", ACCENT, "-"),
              ("service retrieval | generative | answer", "Service, generative answer", ORANGE, "-"),
              ("service retrieval | generative | stored", "Service, generative, stored (v3)", ORANGE, "--"),
              ("pipeline documents | generative | stored", "Trait pipeline, stored (v3)", AQUA, "-")]
    real = {"body size": 0.92, "diet": 0.76}
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 6.2), dpi=200, sharey=True)
    fig.subplots_adjust(left=0.09, right=0.98, top=0.60, bottom=0.11, wspace=0.10)
    qs = [i / 100 for i in range(0, 96)]
    for ax, trait in zip(axes, ("body size", "diet")):
        g = grid[trait]
        ax.axvline(100 * real[trait], color=INK2, linewidth=1, linestyle=(0, (2, 2)))
        ax.text(100 * real[trait] - 1.5, {"body size": 33, "diet": 52}[trait], f"pipeline's use\n≈ {round(100 * real[trait])} %", fontsize=7.5,
                color=INK2, ha="right", va="bottom")
        for key, lab, col, ls in series:
            v = g[key]
            tp, fpp, fpn, npos, nneg = v["tp"], v["fp_wrong"], v["fp_negative"], v["n_pos"], v["n_neg"]
            ys = []
            for q in qs:
                den = (1 - q) * (tp + fpp) / npos + q * fpn / nneg
                ys.append(100 * (1 - q) * tp / npos / den if den else float("nan"))
            ax.plot([100 * q for q in qs], ys, color=col, linewidth=2, linestyle=ls)
        axes_style(ax, xlabel="Share of questions with nothing documented", pct_x=True)
        ax.set_xlim(-3, 97)
        ax.set_title("Body size" if trait == "body size" else "Diet (guild)", loc="left", fontsize=9.5, color=INK, pad=8)
    axes[0].set_ylabel("Precision: values given that are correct", fontsize=9, color=INK2)
    frame(fig, "At the pipeline's share of unanswerable questions, 6–10 % of the service's body sizes\n"
          "are correct, 56 % once stored by version 3, and 100 % via the pipeline's own path",
          "Precision re-weighted to a given share of unanswerable questions, from the answerable and negative items of each\n"
          "configuration. Dashed vertical: the share in the pipeline's own use (version 3 answers that state no value, plus\n"
          "species with no document): 92 % for body size, 76 % for diet. A curve ends flat when no negative item was\n"
          "given a value; such estimates rest on 30 negative items per trait. Diet: 93–95 % through the pipeline; with the service's\n"
          "own search, one invented diet among the 30 no-answer questions brings precision to 83 % at the pipeline's mix.",
          sub_y=0.885)
    handles = [plt.Line2D([], [], color=c, linewidth=2, linestyle=ls, label=l) for _, l, c, ls in series]
    legend(fig, handles, 0.715, ncol=2, x=0.09)
    return fig


def perf_calibration():
    traits = scored("results/traits_main/scored_traits.csv")
    tr_runs = runs("results/traits_main/runs.jsonl")
    troph = scored("results/trophic/scored_trophic.csv")
    tro_runs = runs("results/trophic/runs.jsonl")
    configs = [("doc_extractive", "Gold document", ACCENT, "o"),
               ("e2e_sparse_extractive", "Service retrieval", ORANGE, "s")]
    edges = [0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.4, 5.8), dpi=200, gridspec_kw={"width_ratios": [1.35, 1]})
    fig.subplots_adjust(left=0.08, right=0.98, top=0.66, bottom=0.12, wspace=0.22)
    ax.plot([0, 100], [0, 100], color=INK2, linewidth=1, linestyle=(0, (2, 2)), zorder=1)
    for j, (cfg, lab, col, mk) in enumerate(configs):
        items = []
        for r in traits:
            if r["config"] == cfg and r["trait"] in ("body_size", "habitat") and r["plazi"] != "unscored":
                s_ = plazi_score(tr_runs[(r["qid"], cfg)]["response"])
                if s_ is not None:
                    items.append((s_, r["plazi"] == "correct"))
        for r in troph:
            if r["config"] == cfg:
                s_ = best_score(tro_runs[(r["qid"], cfg)]["response"])
                if s_ is not None:
                    items.append((s_, r["answer"] == "correct"))
        pts = []
        for lo, hi in zip(edges, edges[1:]):
            b = [c for s_, c in items if lo <= s_ < hi]
            if len(b) >= 5:
                k, n = sum(b), len(b)
                l, h = mf.wilson(k, n)
                x = 100 * sum(s_ for s_, _ in items if lo <= s_ < hi) / n + (-0.8 if j == 0 else 0.8)
                ax.plot([x, x], [l, h], color=col, linewidth=2, zorder=2)
                pts.append((x, 100 * k / n))
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, linewidth=2, zorder=2)
        for x, y in pts:
            ax.scatter([x], [y], s=56, marker=mk, color=col, edgecolors=SURFACE, linewidths=2, zorder=3)
    axes_style(ax, xlabel="Extractive answer score (mean within a bin of width 0.2)", ylabel="Answers correct", pct_x=True)
    ax.set_xticklabels(["0", "0.25", "0.5", "0.75", "1"])
    ax.set_title("Extractive reader: by answer score", loc="left", fontsize=9.5, color=INK)
    ax.legend(handles=[line_handle(c, l, marker=m) for _, l, c, m in configs], loc="upper left", frameon=False, fontsize=8.5)

    wd = json.load(open(RC))["wording"]
    cats = [("plain", "Plain\nassertion"), ("hedged", "Hedged"), ("denies", "Denies the\ntrait")]
    for j, (setting, (mk, short)) in enumerate(SETTING_SHAPE.items()):
        for i, (cat, _) in enumerate(cats):
            v = wd[setting].get(f"answerable | {cat}")
            if not v:
                continue
            l, h = mf.wilson(v["correct"], v["n"])
            x = i + (j - 1) * 0.18
            ax2.plot([x, x], [l, h], color=ORANGE, linewidth=2, zorder=2)
            ax2.scatter([x], [100 * v["rate"]], s=56, marker=mk, color=ORANGE, edgecolors=SURFACE, linewidths=1.5, zorder=3)
    axes_style(ax2, ylabel=None)
    ax2.set_xticks(range(len(cats)))
    ax2.set_xticklabels([c[1] for c in cats], fontsize=8.5)
    ax2.set_xlim(-0.5, len(cats) - 0.5)
    ax2.grid(axis="x", visible=False)
    ax2.set_title("Generative reader: by wording (no score)", loc="left", fontsize=9.5, color=INK)
    ax2.legend(handles=[plt.Line2D([], [], marker=SETTING_SHAPE[s][0], color=ORANGE, linewidth=0, markersize=7,
                                   label=lab) for s, lab in (("service retrieval", "Service retrieval"),
                                                             ("pipeline documents", "Pipeline's documents"),
                                                             ("gold document", "Gold document"))],
               loc="center", frameon=False, fontsize=8.5)
    frame(fig, "The extractive score is calibrated only given the right document; the generative reader has no\n"
          "score, but its wording works as one: plain answers are right 91–98 % of the time, hedged ones 76–82 %",
          "Left: extractive answers by score bin (treatment and trophic benchmarks pooled; bins with at least 5 answers; dashed:\n"
          "perfect calibration). Right: generative answers to answerable questions by wording, from reader_comparison.py; the\n"
          "service returns no answer score for generative answers (answer_score is set to None in BioMoQA-RAG). On negative\n"
          "items with service retrieval, 14 of 16 hedged generative answers gave an invented value. 95 % Wilson intervals.",
          sub_y=0.895)
    return fig


def quantile(v, q):
    v = sorted(v)
    i = (len(v) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def perf_latency():
    sources = {"traits": ("results/traits_main/scored_traits.csv", "results/traits_pipeline/scored_traits.csv"),
               "trophic": ("results/trophic/scored_trophic.csv", "results/trophic_pipeline/scored_trophic.csv")}
    series = [("traits", "Treatment benchmark", ACCENT, "o"), ("trophic", "Trophic benchmark", DARK, "s")]
    fig, ax = plt.subplots(figsize=(8.6, 6.4), dpi=200)
    fig.subplots_adjust(left=0.37, right=0.96, top=0.76, bottom=0.09)
    for i, (cfg, name) in enumerate(mf.CONFIGS):
        y0 = len(mf.CONFIGS) - 1 - i
        for j, (bench, lab, col, mk) in enumerate(series):
            folder = mf.SOURCES[bench].get(cfg, "results/traits_main" if bench == "traits" else "results/trophic")
            src = folder + ("/scored_traits.csv" if bench == "traits" else "/scored_trophic.csv")
            v = [float(r["wall_s"]) for r in scored(src) if r["config"] == cfg and r["wall_s"] not in ("", "None")]
            v = [x for x in v if x > 0]
            y = y0 + (0.14 if j == 0 else -0.14)
            ax.plot([quantile(v, 0.05), quantile(v, 0.95)], [y, y], color=col, linewidth=1.2, zorder=2)
            ax.plot([quantile(v, 0.25), quantile(v, 0.75)], [y, y], color=col, linewidth=5, solid_capstyle="butt",
                    zorder=2, alpha=0.55)
            med = quantile(v, 0.5)
            ax.scatter([med], [y], s=56, marker=mk, color=col, edgecolors=SURFACE, linewidths=2, zorder=3)
            ax.text(quantile(v, 0.95) * 1.08, y, f"{med:.1f} s", va="center", ha="left", fontsize=8.5, color=INK)
        name1 = name.replace("\n", " ") if len(name) < 40 else name
        ax.text(0.5, y0, name1, ha="right", va="center", fontsize=9.5, color=INK, transform=ax.get_yaxis_transform())
    ax.set_xscale("log")
    ax.set_xlim(0.2, 60)
    ax.set_xticks([0.25, 0.5, 1, 2, 5, 10, 20, 50])
    ax.set_xticklabels(["0.25", "0.5", "1", "2", "5", "10", "20", "50 s"])
    ax.set_yticks([])
    ax.set_ylim(-0.7, len(mf.CONFIGS) - 0.4)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="both", length=0, colors=INK2, labelsize=9)
    for t in ax.texts:
        if t.get_transform() == ax.get_yaxis_transform():
            t.set_x(-0.03)
    frame(fig, "Gold-document generative answers take under a second; the pipeline's\n"
          "phrase search plus generation takes about 5 s per question",
          "Wall-clock time per question measured by the client (log scale). Dot: median (labelled); thick bar:\n"
          "interquartile range; thin line: 5th to 95th percentile. Dense retrieval: successful requests only.",
          sub_y=0.885)
    legend(fig, [line_handle(c, l, marker=m) for _, l, c, m in series], 0.80, ncol=2, x=0.37)
    return fig


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("perf_position", perf_position), ("perf_threshold", perf_threshold), ("perf_pr", perf_pr),
                       ("perf_readers", perf_readers), ("perf_prevalence", perf_prevalence),
                       ("perf_value_error", perf_value_error), ("perf_labels", perf_labels),
                       ("perf_selective", perf_selective),
                       ("perf_calibration", perf_calibration), ("perf_latency", perf_latency)):
        fig = make()
        mf.doc_scale(fig)
        for ext in ("png", "svg"):
            fig.savefig(OUT / f"{name}.{ext}", facecolor=SURFACE, **({"bbox_inches": "tight", "pad_inches": 0.15} if mf.DOC else {}))
        plt.close(fig)
        print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
