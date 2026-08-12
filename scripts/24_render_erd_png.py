"""
24_render_erd_png.py — render the before/after ERDs straight to PNG with matplotlib.

The SVG versions are for the browser. Word and reportlab both want a raster, and the usual
SVG converters are awkward on Windows: cairosvg needs libcairo-2.dll, which pip does not
install, and Inkscape/ImageMagick are not present. Drawing the diagram directly avoids the
conversion step entirely rather than adding a native dependency for one image.
"""
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import TABLES as REG, TIERS, TIER_ORDER

NAVY, TEAL, AMBER, RED, PURPLE, GREY, LINE = ("#12305B", "#0E8B8B", "#E8A317", "#C0392B",
                                              "#7B4B94", "#5A6672", "#C9D6E6")

SOURCES = [
    ("MerchantSales.csv", 26_500,
     ["Date", "MerchantID", "Merchant*", "Region*", "Channel*", "VoucherType",
      "SalesValue", "Transactions"]),
    ("VoucherRedemptions.csv", 120_969,
     ["VoucherID", "MerchantID", "Merchant*", "SoldDate", "VoucherType",
      "VoucherValue", "Redeemed", "RedeemedDate"]),
    ("SupportTickets.csv", 1_363,
     ["TicketID", "Date", "MerchantID", "Merchant*", "Region*", "TicketType",
      "Priority", "ResolutionHours", "SLAHours", "Status"]),
    ("MerchantReference.csv", 25,
     ["MerchantID", "Merchant", "Region", "Channel", "ActiveStatus",
      "OnboardedDate", "AccountManager", "BaseMonthlySalesTarget"]),
]


def box(ax, x, y, w, h, header, lines, hdr_colour, flag_char=None):
    ax.add_patch(FancyBboxPatch((x, y - h), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                                fc="white", ec=LINE, lw=1.0, zorder=3))
    ax.add_patch(FancyBboxPatch((x, y - 0.42), w, 0.42,
                                boxstyle="round,pad=0,rounding_size=0.12",
                                fc=hdr_colour, ec="none", zorder=4))
    ax.text(x + 0.12, y - 0.21, header, va="center", ha="left", fontsize=8.4,
            color="white", fontweight="bold", zorder=5)
    for i, ln in enumerate(lines):
        dup = ln.endswith("*")
        ax.text(x + 0.12, y - 0.66 - i * 0.235, ln.rstrip("*"), va="center", ha="left",
                fontsize=6.9, color=RED if dup else GREY,
                fontweight="bold" if dup else "normal", zorder=5)
        if dup and flag_char:
            ax.text(x + w - 0.12, y - 0.66 - i * 0.235, flag_char, va="center", ha="right",
                    fontsize=6.0, color=RED, fontweight="bold", zorder=5)


# ================================================================ BEFORE
fig, ax = plt.subplots(figsize=(15, 8.2), dpi=170)
ax.set_xlim(0, 15); ax.set_ylim(0, 8.2); ax.axis("off")
fig.patch.set_facecolor("#FDF6F5")

POS = {"MerchantSales.csv": (0.4, 7.3), "VoucherRedemptions.csv": (0.4, 4.0),
       "SupportTickets.csv": (10.9, 7.3), "MerchantReference.csv": (5.6, 3.5)}
BW = 3.6
H = {n: 0.55 + len(c) * 0.235 for n, _, c in SOURCES}

rx, ry = POS["MerchantReference.csv"]
for name, nrows, cols in SOURCES:
    if name == "MerchantReference.csv":
        continue
    x, y = POS[name]
    x1 = x + (BW if x < rx else 0)
    y1 = y - H[name] / 2
    x2 = rx + (0 if x < rx else BW)
    y2 = ry - H["MerchantReference.csv"] / 2
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), connectionstyle="arc3,rad=0.16",
                                 arrowstyle="-", color=RED, lw=1.3, ls=(0, (5, 3)),
                                 alpha=.7, zorder=2))
    ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.14, "implicit", ha="center", fontsize=6.6,
            color=RED, fontweight="bold", zorder=6)

for name, nrows, cols in SOURCES:
    x, y = POS[name]
    box(ax, x, y, BW, H[name], f"{name}   {nrows:,}", cols, RED, "DUP")

ax.text(7.5, 7.95, "BEFORE — four flat files · 6 duplicated attribute columns · "
                   "0 enforced keys · every value text",
        ha="center", fontsize=11.5, color=RED, fontweight="bold")
ax.text(7.5, 0.42, "Dashed arrows are implicit string joins. Nothing validates them, and "
                   "nothing would notice if one stopped resolving.",
        ha="center", fontsize=8, color=GREY, style="italic")
fig.savefig(ROOT / "docs" / "erd_before.png", bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close(fig)

# ================================================================ AFTER
MAN = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text(encoding="utf-8"))
CAT_P = ROOT / "dbt" / "target" / "catalog.json"
CAT = json.loads(CAT_P.read_text(encoding="utf-8")) if CAT_P.exists() else {"nodes": {}}
short = lambda u: u.split(".")[-1]

fks = []
for uid, n in MAN["nodes"].items():
    if n["resource_type"] != "test":
        continue
    md = n.get("test_metadata") or {}
    if md.get("name") != "relationships":
        continue
    kw = md.get("kwargs", {})
    to = re.search(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", kw.get("to", "") or "")
    frm = (n.get("attached_node") or "").split(".")[-1]
    if to and frm:
        # The joining COLUMN is captured, not just the two table names. Without it the
        # diagram can show that two tables are related but not on what — and this model has
        # three different columns reaching dim_date, so "related to dim_date" is not an answer.
        fks.append((frm, to.group(1), (kw.get("column_name") or "").strip('"')))


# Line colour is keyed on the TARGET table, not assigned at random: every join to dim_date is
# one colour, every join to dim_merchant another. That makes the colour carry information —
# the eye groups the three different columns that all reach the calendar — instead of being
# decoration. The join list underneath reuses the same colour per row.
JOIN_COLOURS = ["#0E8B8B", "#12305B", "#B8860B", "#7B4B94", "#C0392B",
                "#1E8449", "#1B6CA8", "#D6336C", "#8B6914"]
_targets = sorted({to for _f, to, _c in fks})
TCOL = {t: JOIN_COLOURS[i % len(JOIN_COLOURS)] for i, t in enumerate(_targets)}

cols_of = {}
rows_of = {}
for uid, c in CAT.get("nodes", {}).items():
    nm = short(uid)
    cols_of[nm] = [v["name"] for v in sorted(c["columns"].values(),
                                             key=lambda x: x["index"])][:6]
    st = (c.get("stats") or {}).get("row_count") or {}
    if st.get("value") is not None:
        rows_of[nm] = int(st["value"])

facts = sorted(t for t in REG if t.startswith("fct_"))
dims = sorted(t for t in REG if t.startswith("dim_"))
other = sorted(t for t in REG if t.startswith(("mart_", "snap_")))

# Cap the column list per table so no box runs away, and size the canvas from the tallest
# column rather than guessing — the previous version overflowed the figure and the legend
# landed on top of a table.
MAXC = 5
for k in cols_of:
    cols_of[k] = cols_of[k][:MAXC]
bh = lambda t: 0.55 + len(cols_of.get(t, [])) * 0.235

# Four columns: dims split left/right, facts centre-left, marts + snapshot centre-right
COLS = [
    (0.30, dims[:4]),
    (4.05, facts),
    (7.80, other),
    (11.55, dims[4:]),
]
GAP, TOP = 0.20, 0.62
need = max(sum(bh(t) + GAP for t in grp) for _, grp in COLS) + TOP + 0.95

fig, ax = plt.subplots(figsize=(15, max(need, 7.0)), dpi=170)
JOIN_ROWS = (len(fks) + 2) // 3
JOIN_H = 0.30 + JOIN_ROWS * 0.19
ax.set_xlim(0, 15); ax.set_ylim(-JOIN_H, max(need, 7.0)); ax.axis("off")
fig.patch.set_facecolor("#F2F9F8")

BW2 = 3.15
pos = {}
for x0, grp in COLS:
    y = max(need, 7.0) - TOP
    for t in grp:
        pos[t] = (x0, y)
        y -= bh(t) + GAP

for frm, to, _col in fks:
    if frm not in pos or to not in pos:
        continue
    ax_, ay = pos[to]; bx, by = pos[frm]
    a_r = ax_ < bx
    x1 = ax_ + (BW2 if a_r else 0); y1 = ay - bh(to) / 2
    x2 = bx + (0 if a_r else BW2); y2 = by - bh(frm) / 2
    _c = TCOL.get(to, TEAL)
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), connectionstyle="arc3,rad=0.12",
                                 arrowstyle="-", color=_c, lw=1.25, alpha=.75, zorder=2))
    ax.plot([x1], [y1], "o", ms=3.4, color=_c, zorder=6)

for t, meta in REG.items():
    if t not in pos:
        continue
    x, y0 = pos[t]
    n = rows_of.get(t, meta["rows"])
    box(ax, x, y0, BW2, bh(t), f"{t}   {n:,}", cols_of.get(t, []),
        TIERS[meta["tier"]][1])

_H = max(need, 7.0)
ax.text(7.5, _H - 0.22, f"AFTER — {len(REG)} tables · {len(fks)} ENFORCED foreign keys · "
                        f"conformed dimensions · contiguous calendar",
        ha="center", fontsize=11.5, color=TEAL, fontweight="bold")
# Legend in reserved space at the very bottom, so it cannot land on a table
for i, k in enumerate(TIER_ORDER):
    n = sum(1 for v in REG.values() if v["tier"] == k)
    x = 1.9 + i * 3.1
    ax.add_patch(FancyBboxPatch((x, 0.28), 0.26, 0.20,
                                boxstyle="round,pad=0,rounding_size=0.05",
                                fc=TIERS[k][1], ec="none"))
    ax.text(x + 0.38, 0.38, f"{TIERS[k][0]} ({n})", va="center", fontsize=8.4, color=GREY)
# ---- every join stated explicitly, three columns, beneath the legend
ax.text(0.35, -0.10, "How the tables join — every one an enforced dbt relationships test",
        va="center", fontsize=8.6, color=NAVY, fontweight="bold")
for i, (frm, to, col) in enumerate(sorted(fks, key=lambda r: (r[1], r[0]))):
    cx = 0.35 + (i % 3) * 4.90
    cy = -0.34 - (i // 3) * 0.19
    _c = TCOL.get(to, TEAL)
    ax.add_patch(FancyBboxPatch((cx, cy - 0.045), 0.09, 0.09,
                                boxstyle="round,pad=0,rounding_size=0.02",
                                fc=_c, ec="none"))
    ax.text(cx + 0.16, cy, f"{frm}.{col}  →  {to}", va="center", fontsize=6.4,
            color="#12203A")

fig.savefig(ROOT / "docs" / "erd_after.png", bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close(fig)

for f in ("erd_before.png", "erd_after.png"):
    p = ROOT / "docs" / f
    print(f"  {f:<22} {p.stat().st_size/1024:>6.0f} KB")
print(f"  {len(fks)} enforced foreign keys drawn")
