#!/usr/bin/env python3
"""Vector figures from verified aggregate outputs only."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

HERE = Path(__file__).resolve().parent
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.labelsize": 9, "axes.titlesize": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
})

data = json.loads((HERE / "stress-results.json").read_text())
summary = json.loads((HERE / "public-aggregate-results.json").read_text())["summary"]
total = summary["requisitions"]
certified = [summary["initial_certified"], summary["final_certified"]]
unresolved = [total - count for count in certified]
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6), gridspec_kw={"width_ratios": [1, 1.12]})
ax = axes[0]
ax.barh([1, 0], certified, color="#226F54", height=.48, label="Certified")
ax.barh([1, 0], unresolved, left=certified, color="#DADDE0", height=.48, label="Unresolved")
for y, count in zip((1, 0), certified):
    ax.text(count / 2, y, str(count), color="white", ha="center", va="center", fontweight="bold")
    ax.text(count + (total-count)/2, y, str(total-count), color="#333333", ha="center", va="center")
ax.set(yticks=[0, 1], yticklabels=["After recorded\nadjudications", "Before\nadjudication"],
       xlim=(0, total), xlabel=f"Requisitions (n = {total})", title="(a) Exact membership verdicts")
ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
ax.set_ylim(-.6, 1.6)
ax.legend(loc="upper center", bbox_to_anchor=(.48, -.27), ncol=2,
          frameon=False, fontsize=7.5, handlelength=1.1, columnspacing=1)

ax = axes[1]
styles = [("uniform_relevant", "Relevant variables", "#226F54", "o"),
          ("pick_first_uniform_blockers", "Pick first + blockers", "#4477AA", "s"),
          ("pick_first_max_blockers", "Pick first + max blockers", "#CC7733", "^")]
counts = sorted({r["queries"] for key, *_ in styles
                 for r in data["policies"][key]["query_count"]["distribution"]})
query_axis = range(min(counts), max(counts) + 1)
for key, label, color, marker in styles:
    rows = data["policies"][key]["query_count"]["distribution"]
    mass = {r["queries"]: r["probability"] for r in rows}
    ax.plot(query_axis, [mass.get(k, 0) for k in query_axis],
            marker=marker, markersize=4, linewidth=1.15, color=color, label=label)
ax.set(xlabel="Adjudication queries across ten requisitions", ylabel="Probability over priority orders",
       xticks=list(query_axis), ylim=(-.01, .38), title="(b) Exact query-order sensitivity")
ax.legend(frameon=False, fontsize=7, loc="upper left", handlelength=1.3)
fig.tight_layout(w_pad=2.0)
fig.subplots_adjust(bottom=.24)
fig.savefig(OUT / "certification-and-queries.pdf", bbox_inches="tight", pad_inches=.035)
fig.savefig(OUT / "certification-and-queries.png", dpi=200, bbox_inches="tight", pad_inches=.035)
plt.close(fig)
print("Created figures/certification-and-queries.pdf and .png")
