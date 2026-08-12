"""
26_render_dag_png.py — render the dbt DAG as a PNG, straight from the manifest.

The dbt docs lineage graph is the right picture but it only exists inside a browser at
localhost. Drawing it from target/manifest.json gives the same information as a file that can
go into the deck, the Word report and the PDF — and it stays correct automatically, because
it is generated from the same manifest dbt itself uses.

Layered left to right in build order: sources -> staging -> intermediate -> marts -> exposures.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
MAN = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text(encoding="utf-8"))

NAVY, TEAL, AMBER, PURPLE, GREY, GREEN = ("#12305B", "#0E8B8B", "#E8A317", "#7B4B94",
                                          "#5A6672", "#1E8449")
short = lambda u: u.split(".")[-1]

nodes, deps = {}, defaultdict(set)

for uid, s in MAN.get("sources", {}).items():
    nodes[uid] = {"name": s["name"], "layer": 0, "colour": AMBER}

for uid, n in MAN["nodes"].items():
    rt = n["resource_type"]
    if rt == "test":
        continue
    fqn = n.get("fqn", [])
    if rt == "snapshot":
        layer, col = 2, PURPLE
    elif "staging" in fqn:
        layer, col = 1, GREY
    elif "intermediate" in fqn:
        layer, col = 2, "#9C6ABF"
    elif "analytics" in fqn:
        layer, col = 4, PURPLE
    elif "core" in fqn:
        layer, col = 3, TEAL
    elif rt == "seed":
        layer, col = 1, "#C9A227"
    else:
        layer, col = 3, TEAL
    nodes[uid] = {"name": short(uid), "layer": layer, "colour": col}
    # Seeds have no depends_on.nodes key at all
    for d in (n.get("depends_on") or {}).get("nodes", []):
        deps[uid].add(d)

for uid, e in MAN.get("exposures", {}).items():
    nodes[uid] = {"name": e["name"], "layer": 5, "colour": GREEN}
    for d in (e.get("depends_on") or {}).get("nodes", []):
        deps[uid].add(d)

# Facts are built from dimensions here, so a pure topological layer can push them right —
# pin the declared layer instead and let the edges cross, which reads better than a
# 9-column DAG.
by_layer = defaultdict(list)
for uid, m in nodes.items():
    by_layer[m["layer"]].append(uid)
for l in by_layer:
    by_layer[l].sort(key=lambda u: nodes[u]["name"])

LABELS = {0: "SOURCES\nbronze", 1: "STAGING\nsilver", 2: "INTERMEDIATE\n+ snapshot",
          3: "MARTS / CORE\ngold star", 4: "MARTS\nanalytics", 5: "EXPOSURES\nconsumers"}

COL_W, BOX_H, GAP = 2.55, 0.40, 0.20
maxn = max(len(v) for v in by_layer.values())
W = COL_W * (max(by_layer) + 1) + 0.6
H = maxn * (BOX_H + GAP) + 1.5

fig, ax = plt.subplots(figsize=(W, max(H, 5.5)), dpi=175)
ax.set_xlim(0, W); ax.set_ylim(0, max(H, 5.5)); ax.axis("off")
fig.patch.set_facecolor("#F7FAFC")

pos = {}
for layer, uids in sorted(by_layer.items()):
    x = 0.3 + layer * COL_W
    total = len(uids) * (BOX_H + GAP)
    y = (max(H, 5.5) - 0.9 + total) / 2
    for uid in uids:
        pos[uid] = (x, y)
        y -= BOX_H + GAP
    ax.text(x + COL_W * 0.36, max(H, 5.5) - 0.35, LABELS.get(layer, ""), ha="center",
            va="top", fontsize=8.6, color=NAVY, fontweight="bold", linespacing=1.5)

for tgt, srcs in deps.items():
    if tgt not in pos:
        continue
    tx, ty = pos[tgt]
    for s in srcs:
        if s not in pos:
            continue
        sx, sy = pos[s]
        ax.add_patch(FancyArrowPatch(
            (sx + COL_W * 0.72, sy), (tx, ty), connectionstyle="arc3,rad=0.07",
            arrowstyle="-|>,head_width=1.6,head_length=3", color="#B9C7DA",
            lw=0.7, alpha=.75, zorder=1, mutation_scale=4))

for uid, (x, y) in pos.items():
    m = nodes[uid]
    ax.add_patch(FancyBboxPatch((x, y - BOX_H / 2), COL_W * 0.72, BOX_H,
                                boxstyle="round,pad=0,rounding_size=0.07",
                                fc=m["colour"], ec="none", zorder=3))
    label = m["name"]
    if len(label) > 26:
        label = label[:24] + "…"
    ax.text(x + COL_W * 0.36, y, label, ha="center", va="center", fontsize=6.4,
            color="white", fontweight="bold", zorder=4)

n_models = sum(1 for n in MAN["nodes"].values() if n["resource_type"] == "model")
n_tests = sum(1 for n in MAN["nodes"].values() if n["resource_type"] == "test")
ax.text(W / 2, 0.28, f"{n_models} models · 1 snapshot · {n_tests} tests · "
                     f"{len(MAN.get('sources', {}))} sources · "
                     f"{len(MAN.get('exposures', {}))} exposures  —  generated from "
                     f"target/manifest.json",
        ha="center", fontsize=8, color=GREY, style="italic")

out = ROOT / "docs" / "dbt_dag.png"
fig.savefig(out, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.close(fig)
print(f"  {out.name}  {out.stat().st_size/1024:.0f} KB")
print(f"  {len(pos)} nodes across {len(by_layer)} layers, "
      f"{sum(len(v) for v in deps.values())} edges")
