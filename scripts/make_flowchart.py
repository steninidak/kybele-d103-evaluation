"""
Draw the flowchart of the D10.3 evaluation: inputs, the systems under test (L1, L2), the KYBELE
D10.3 evaluation in this repository (L3) and the report sections each part feeds.

  results/figures/flowchart.(png|svg)

Usage: python3 scripts/make_flowchart.py   (needs matplotlib; run from the repository root)
"""

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "figures"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#d9d8d3", "#ffffff"
ACCENT, ACCENT_BG = "#2a78d6", "#e8f1fc"
NEUTRAL_BG, DELIV_BG = "#f3f2ef", "#fdeee7"
ORANGE = "#eb6834"

# Boxes: key -> (x, y, w, h, title, body, fill, edge). Coordinates in a 100 x 64 canvas; boxes that
# connect are aligned so that every arrow is straight.
BOXES = {
    "d102": (1, 49, 21, 7, "D10.2 (SIB)", "BioASQ evaluation of the service", NEUTRAL_BG, GRID),
    "sibils": (1, 40, 21, 7, "SIBiLS collections", "Medline · PMC · Plazi", NEUTRAL_BG, GRID),
    "bold": (1, 24, 21, 7, "BOLD COI dataset", "330 Collembola species", NEUTRAL_BG, GRID),
    "review": (1, 15, 21, 7, "Expert review", "56 adjudicated pairs", NEUTRAL_BG, GRID),

    "l1": (26, 39, 19, 17, "L1 · SIB QA service", "BioMoQA-RAG, qa.sibils.org\nBM25 or dense retrieval\nBioBERT or Qwen3-8B", ACCENT_BG, ACCENT),
    "l2": (26, 13, 19, 19, "L2 · Trait pipeline", "collembola-trait-mining\nphrase search → QA (doc_refs)\n→ trait_extraction_v3\n→ trait table (version 3)", ACCENT_BG, ACCENT),

    "bench": (51, 49, 22, 9, "Benchmarks (data/)", "curated from SIBiLS documents\ntraits 126 · trophic 102\nnegatives 60 · population 300*", SURFACE, ACCENT),
    "runner": (51, 39.5, 22, 7.5, "kybele_d103_eval.py", "5 service configurations + the\npipeline's route, with both readers", SURFACE, ACCENT),
    "score": (51, 24, 22, 10.5, "Scorers", "score.py · score_traits.py\nscore_trophic.py\nscore_pipeline_output.py\nattribution.py", SURFACE, ACCENT),
    "sync": (51, 15.5, 18, 5.5, "check_pipeline_sync.py", "", SURFACE, ACCENT),
    "results": (51, 3, 22, 8, "results/", "runs.jsonl · summaries\nfigures (make_*figures.py)", SURFACE, ACCENT),

    "s2": (78, 49.5, 21, 8, "§2 Test questions", "the questions asked and\ntheir checked answers", DELIV_BG, ORANGE),
    "s3": (78, 39, 21, 8.5, "§3 How it was tested", "seven ways of asking the\nservice; comparison with D10.2", DELIV_BG, ORANGE),
    "s4": (78, 21, 21, 15.5, "§4 Results", "body size and habitat\nthe published trait table\ndiet\nquestions with no answer\nwhere correct answers get lost\nthe two readers compared\nprecision and recall", DELIV_BG, ORANGE),
    "s5": (78, 14.5, 21, 5, "§5 What goes wrong", "", DELIV_BG, ORANGE),
    "s6": (78, 7.5, 21, 5.5, "§6 Fixes", "5 made, 24 planned", DELIV_BG, ORANGE),
    "s7": (78, 1.5, 21, 5, "§7 Conclusions", "", DELIV_BG, ORANGE),
}

# Straight arrows: (start point, end point, label, label offset (dx, dy), both heads)
ARROWS = [
    ((22, 52.5), (26, 52.5), "", (0, 0), False),
    ((22, 43.5), (26, 43.5), "", (0, 0), False),
    ((22, 27.5), (26, 27.5), "", (0, 0), False),
    ((22, 18.5), (26, 18.5), "", (0, 0), False),
    ((35.5, 32), (35.5, 39), "asks", (2.2, 0), False),
    ((51, 43.25), (45, 43.25), "questions,\nanswers", (0, 2.6), True),
    ((45, 29.25), (51, 29.25), "extractor,\ntables", (0, 2.6), False),
    ((45, 18.25), (51, 18.25), "source\ncode", (0, 2.6), False),
    ((62, 49), (62, 47), "", (0, 0), False),
    ((62, 39.5), (62, 34.5), "", (0, 0), False),
    ((71, 24), (71, 11), "", (0, 0), False),
    ((73, 53.5), (78, 53.5), "", (0, 0), False),
    ((73, 43.25), (78, 43.25), "", (0, 0), False),
    ((75.5, 28.75), (78, 28.75), "", (0, 0), False),
    ((75.5, 17), (78, 17), "", (0, 0), False),
    ((75.5, 10.25), (78, 10.25), "", (0, 0), False),
    ((75.5, 4), (78, 4), "", (0, 0), False),
]
BUS = [((73, 7), (75.5, 7)), ((75.5, 4), (75.5, 28.75))]  # results/ feeds sections 4 to 7
# Small labels on the input arrows' left boxes are unnecessary: the input names say what flows.


def main():
    fig, ax = plt.subplots(figsize=(12, 8.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.83, bottom=0.03)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 64)
    ax.axis("off")

    for x0, w, title in ((0, 23, "Inputs"), (25, 23, "Systems under test"), (49.5, 25, "KYBELE D10.3"),
                         (76.5, 23.5, "Report sections")):
        ax.add_patch(FancyBboxPatch((x0, 0.8), w, 61.5, boxstyle="round,pad=0,rounding_size=1.2",
                                    facecolor="none", edgecolor=GRID, linewidth=1, linestyle=(0, (3, 3))))
        ax.text(x0 + 1, 61, title, fontsize=10.5, fontweight="bold", color=INK2, va="center", ha="left")

    for key, (x, y, w, h, title, body, fill, edge) in BOXES.items():
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8",
                                    facecolor=fill, edgecolor=edge, linewidth=1.4, zorder=2))
        if body:
            ax.text(x + 1, y + h - 1.3, title, fontsize=9.5, fontweight="bold", color=INK, va="top", ha="left", zorder=3)
            ax.text(x + 1, y + h - 3.6, body, fontsize=8.2, color=INK2, va="top", ha="left", linespacing=1.35, zorder=3)
        else:
            ax.text(x + 1, y + h / 2, title, fontsize=9.5, fontweight="bold", color=INK, va="center", ha="left", zorder=3)

    for (x1, y1), (x2, y2) in BUS:
        ax.plot([x1, x2], [y1, y2], color=INK2, linewidth=1.1, zorder=1, solid_capstyle="round")
    for p, q, label, (dx, dy), both in ARROWS:
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="<|-|>" if both else "-|>", mutation_scale=11, color=INK2,
                                     linewidth=1.1, shrinkA=1, shrinkB=1, zorder=1))
        if label:
            ax.text((p[0] + q[0]) / 2 + dx, (p[1] + q[1]) / 2 + dy, label, fontsize=7.6, color=INK2,
                    ha="center", va="center", zorder=4, linespacing=1.2)

    if os.environ.get("KYBELE_DOC") != "1":
        fig.text(0.012, 0.985, "KYBELE D10.3: what is evaluated, by which part of the repository,\n"
                 "and where each result goes in the deliverable", fontsize=13, fontweight="bold", color=INK,
                 va="top", linespacing=1.3)
        fig.text(0.012, 0.895, "L1 and L2 are tested from outside: the runner asks the QA service the way the service configurations\n"
                 "and the trait pipeline do, and the scorers read the answers with the pipeline's own extractor against the\n"
                 "independent gold.  * Population benchmark sampled, awaiting specialist curation.",
                 fontsize=8.8, color=INK2, va="top", linespacing=1.4)
    doc = os.environ.get("KYBELE_DOC") == "1"
    out = OUT / "doc" if doc else OUT
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(out / f"flowchart.{ext}", facecolor=SURFACE, **({"bbox_inches": "tight", "pad_inches": 0.15} if doc else {}))
    print("wrote", out / "flowchart.png")


if __name__ == "__main__":
    main()
