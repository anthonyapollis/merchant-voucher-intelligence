"""
37_build_core4_erd.py — the four supplied tables, and how they connect in dbt.

A standalone ERD covering ONLY the four tables that come from a supplied CSV:

    dim_merchant             MerchantReference.csv
    fct_merchant_sales       MerchantSales.csv
    fct_voucher_redemptions  VoucherRedemptions.csv
    fct_support_tickets      SupportTickets.csv

The full model has fourteen tables, which is the right answer to the brief but the wrong
diagram for explaining the SHAPE of the model. Reduced to four, the structure is obvious: one
conformed dimension, three facts at three different grains, every fact joining to the
dimension on merchant_key and never to each other.

Relationships are read from the dbt manifest — specifically from the `relationships` tests,
which are the enforced foreign keys — so the diagram cannot claim a join the project does not
actually test. Joins to tables OUTSIDE the four are drawn as stubs rather than hidden: a
diagram that silently omits date_key would misrepresent the model.

Writes docs/erd_core4.svg, docs/erd_core4.png and docs/erd_core4.html.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"
sys.path.insert(0, str(Path(__file__).parent))

NAVY, TEAL, AMBER, GREY, LINE = "#12305B", "#0E8B8B", "#B8860B", "#5A6672", "#C9D6E6"
INK, PAPER, PANEL = "#12203A", "#FFFFFF", "#F4F7FB"

CORE = {
    "dim_merchant": ("MerchantReference.csv", "Conformed dimension",
                     "The single filter path for every fact. Carries an Unknown (-1) member "
                     "so an unmatched fact row lands somewhere visible instead of vanishing "
                     "from every total."),
    "fct_merchant_sales": ("MerchantSales.csv", "Grain: Date x Merchant x VoucherType",
                           "Daily aggregate. Merchant, Region and Channel were dropped from "
                           "the fact — profiling proved 100% agreement with the reference "
                           "file, so keeping both would allow two versions of Region."),
    "fct_voucher_redemptions": ("VoucherRedemptions.csv", "Grain: one row per voucher",
                                "Accumulating snapshot, updated when the second event "
                                "(redemption) occurs. TWO date keys: sold active, redeemed "
                                "inactive."),
    "fct_support_tickets": ("SupportTickets.csv", "Grain: one row per ticket",
                            "sla_hours is stored ON the fact, so a future SLA policy change "
                            "cannot retrospectively restate a historic breach."),
}

MAN = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text(encoding="utf-8"))
CAT_P = ROOT / "dbt" / "target" / "catalog.json"
CAT = json.loads(CAT_P.read_text(encoding="utf-8")) if CAT_P.exists() else {"nodes": {}}

short = lambda u: u.split(".")[-1]
rows, cols = {}, {}
for uid, c in CAT.get("nodes", {}).items():
    n = short(uid)
    st = (c.get("stats") or {}).get("row_count") or {}
    if st.get("value") is not None:
        rows[n] = int(st["value"])
    cols[n] = [k for k in (c.get("columns") or {})]

# The dbt-duckdb adapter writes `has_stats` into the catalog but no row_count, so the block
# above yields nothing and every table rendered "0 rows" — a diagram that looks like an empty
# warehouse. Count them from the warehouse itself instead; the catalog is only a convenience.
try:
    import duckdb
    _con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"), read_only=True)
    for _t in CORE:
        if rows.get(_t):
            continue
        try:
            rows[_t] = int(_con.execute(f"select count(*) from main_marts.{_t}").fetchone()[0])
        except Exception:
            pass
    _con.close()
except Exception as _e:
    print(f"  could not read row counts from the warehouse: {_e}")

_zero = [t for t in CORE if not rows.get(t)]
if _zero:
    raise SystemExit("refusing to draw an ERD showing 0 rows for: " + ", ".join(_zero))

# Enforced foreign keys, straight from the relationships tests.
edges = []
for uid, n in MAN["nodes"].items():
    if n["resource_type"] != "test":
        continue
    md = n.get("test_metadata") or {}
    if md.get("name") != "relationships":
        continue
    kw = md.get("kwargs", {})
    to = re.search(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", kw.get("to", "") or "")
    frm = (n.get("attached_node") or "").split(".")[-1]
    if frm in CORE and to and kw.get("column_name"):
        edges.append((frm, kw["column_name"].strip('"'), to.group(1)))

internal = [e for e in edges if e[2] in CORE]
external = sorted({(e[2], e[1]) for e in edges if e[2] not in CORE})

# ---------------------------------------------------------------- layout
W, H = 1160, 700
BW, HDR, RH = 250, 34, 15.5
POS = {
    "dim_merchant": (455, 300),
    "fct_merchant_sales": (60, 70),
    "fct_voucher_redemptions": (850, 70),
    "fct_support_tickets": (455, 545),
}
SHOWN = 8


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bh(t):
    return HDR + min(len(cols.get(t, [])), SHOWN) * RH + 14


s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
     f'style="width:100%;height:auto;font-family:Segoe UI,Arial,sans-serif">',
     f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
     f'<text x="{W/2}" y="30" text-anchor="middle" font-size="17" font-weight="700" '
     f'fill="{NAVY}">The four supplied tables — one conformed dimension, three facts</text>',
     f'<text x="{W/2}" y="50" text-anchor="middle" font-size="11.5" fill="{GREY}">'
     f'Every relationship shown is an enforced dbt relationships test. Facts join to the '
     f'dimension, never to each other.</text>']

# ---- relationship lines drawn first so boxes sit on top
dx, dy = POS["dim_merchant"]
dcx, dcy = dx + BW / 2, dy + bh("dim_merchant") / 2
for frm, col, to in internal:
    fx, fy = POS[frm]
    fcx, fcy = fx + BW / 2, fy + bh(frm) / 2
    s.append(f'<path d="M{fcx},{fcy} L{dcx},{dcy}" stroke="{TEAL}" stroke-width="2.2" '
             f'fill="none" opacity=".75"/>')
    mx, my = (fcx + dcx) / 2, (fcy + dcy) / 2
    s.append(f'<rect x="{mx-52}" y="{my-11}" width="104" height="20" rx="10" '
             f'fill="{PAPER}" stroke="{TEAL}" stroke-width="1"/>')
    s.append(f'<text x="{mx}" y="{my+4}" text-anchor="middle" font-size="9.5" '
             f'font-weight="700" fill="{TEAL}">{esc(col)}</text>')
    # Crow's foot at the FACT end, a single bar at the DIMENSION end — the standard
    # many-to-one notation, drawn rather than spelled out in words.
    import math
    ang = math.atan2(dcy - fcy, dcx - fcx)
    fx0 = fcx + math.cos(ang) * 26
    fy0 = fcy + math.sin(ang) * 26
    for spread in (-0.30, 0.0, 0.30):
        ex = fx0 + math.cos(ang + spread) * 17
        ey = fy0 + math.sin(ang + spread) * 17
        s.append(f'<path d="M{fx0:.1f},{fy0:.1f} L{ex:.1f},{ey:.1f}" stroke="{TEAL}" '
                 f'stroke-width="1.7" fill="none"/>')
    bx = dcx - math.cos(ang) * 26
    by = dcy - math.sin(ang) * 26
    s.append(f'<path d="M{bx - math.sin(ang)*8:.1f},{by + math.cos(ang)*8:.1f} '
             f'L{bx + math.sin(ang)*8:.1f},{by - math.cos(ang)*8:.1f}" '
             f'stroke="{NAVY}" stroke-width="2.4"/>')

# ---- table boxes
for t, (src, grain, note) in CORE.items():
    x, y = POS[t]
    h = bh(t)
    is_dim = t.startswith("dim_")
    accent = NAVY if is_dim else TEAL
    s.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{h}" rx="7" fill="#fff" '
             f'stroke="{accent}" stroke-width="2"/>')
    s.append(f'<path d="M{x},{y+7} a7,7 0 0 1 7,-7 h{BW-14} a7,7 0 0 1 7,7 v{HDR-7} '
             f'h-{BW} Z" fill="{accent}"/>')
    n = rows.get(t, 0)
    s.append(f'<text x="{x+10}" y="{y+16}" font-size="11.5" font-weight="700" fill="#fff">'
             f'{esc(t)}</text>')
    s.append(f'<text x="{x+10}" y="{y+28}" font-size="9" fill="#CFE0F2">'
             f'{esc(src)}</text>')
    _lbl = f'{n:,} rows'
    _w = len(_lbl) * 6.0 + 12
    s.append(f'<rect x="{x+BW-_w-8}" y="{y+6}" width="{_w}" height="17" rx="8.5" '
             f'fill="#FFFFFF" opacity=".92"/>')
    s.append(f'<text x="{x+BW-8-_w/2}" y="{y+18}" text-anchor="middle" font-size="9.5" '
             f'font-weight="700" fill="{accent}">{_lbl}</text>')
    for i, cn in enumerate(cols.get(t, [])[:SHOWN]):
        is_k = cn.endswith("_key") or cn.endswith("_id")
        s.append(f'<text x="{x+10}" y="{y+HDR+13+i*RH}" font-size="9.5" '
                 f'fill="{NAVY if is_k else GREY}" '
                 f'font-weight="{"700" if is_k else "400"}">{esc(cn)}</text>')
        if is_k:
            s.append(f'<text x="{x+BW-10}" y="{y+HDR+13+i*RH}" font-size="8" '
                     f'text-anchor="end" fill="{AMBER}" font-weight="700">KEY</text>')
    if len(cols.get(t, [])) > SHOWN:
        s.append(f'<text x="{x+10}" y="{y+HDR+13+SHOWN*RH}" font-size="8.5" fill="{GREY}" '
                 f'font-style="italic">+{len(cols[t])-SHOWN} more</text>')
    s.append(f'<text x="{x}" y="{y+h+14}" font-size="9" fill="{GREY}" '
             f'font-style="italic">{esc(grain)}</text>')

# ---- stubs for the conformed dimensions outside the four
# Legend — a diagram that uses notation should say what the notation means.
lx, ly = 40, 92
s.append(f'<rect x="{lx-10}" y="{ly-16}" width="286" height="74" rx="7" fill="{PANEL}" '
         f'stroke="{LINE}"/>')
s.append(f'<text x="{lx}" y="{ly}" font-size="10" font-weight="700" fill="{NAVY}">'
         f'How to read this</text>')
s.append(f'<text x="{lx}" y="{ly+15}" font-size="9" fill="{GREY}">'
         f'Crow’s foot = many side · bar = one side</text>')
s.append(f'<text x="{lx}" y="{ly+29}" font-size="9" fill="{GREY}">'
         f'Bold column + KEY = joins to another table</text>')
s.append(f'<text x="{lx}" y="{ly+43}" font-size="9" fill="{GREY}">'
         f'Navy header = dimension · teal = fact</text>')

# What cleanup removed. The diagram otherwise shows only what survived, which understates the
# modelling work — nine redundant columns were dropped, and that is the reason the facts are
# this narrow.
dx2, dy2 = W - 340, 92
s.append(f'<rect x="{dx2-10}" y="{dy2-16}" width="330" height="74" rx="7" fill="#FDF6F5" '
         f'stroke="#F0997B"/>')
s.append(f'<text x="{dx2}" y="{dy2}" font-size="10" font-weight="700" fill="#993C1D">'
         f'Removed during cleanup — 9 redundant columns</text>')
s.append(f'<text x="{dx2}" y="{dy2+15}" font-size="9" fill="{GREY}">'
         f'Merchant, Region, Channel repeated on all three facts</text>')
s.append(f'<text x="{dx2}" y="{dy2+29}" font-size="9" fill="{GREY}">'
         f'Profiling proved 100% agreement, so removal was lossless</text>')
s.append(f'<text x="{dx2}" y="{dy2+43}" font-size="9" fill="{GREY}">'
         f'They now live once, on dim_merchant</text>')

sx, sy = 40, H - 130
s.append(f'<text x="{sx}" y="{sy}" font-size="11" font-weight="700" fill="{AMBER}">'
         f'Also joined, outside these four ({len(external)} enforced relationships):</text>')
line = ", ".join(f"{t} ({c})" for t, c in external)
for i, chunk in enumerate([line[j:j+118] for j in range(0, len(line), 118)]):
    s.append(f'<text x="{sx}" y="{sy+16+i*14}" font-size="9.5" fill="{GREY}">'
             f'{esc(chunk)}</text>')

svg = "\n".join(s) + "</svg>"
(OUT / "erd_core4.svg").write_text(svg, encoding="utf-8")

# ---------------------------------------------------------------- html wrapper
(OUT / "erd_core4.html").write_text(
    f"<!doctype html><meta charset='utf-8'><title>Core four ERD</title>"
    f"<style>body{{font-family:Segoe UI,Arial,sans-serif;background:{PANEL};margin:0;"
    f"padding:28px}}.c{{max-width:1200px;margin:auto;background:#fff;padding:22px;"
    f"border-radius:10px;box-shadow:0 2px 10px rgba(18,48,91,.10)}}"
    f"h1{{color:{NAVY};font-size:20px;margin:0 0 4px}}p{{color:{GREY};font-size:13px;"
    f"margin:0 0 18px}}</style><div class='c'><h1>The four supplied tables</h1>"
    f"<p>Relationships read from the dbt manifest — every line is an enforced "
    f"<code>relationships</code> test.</p>{svg}</div>", encoding="utf-8")

# ---------------------------------------------------------------- png
png_ok = False
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    fig, ax = plt.subplots(figsize=(W / 96, H / 96), dpi=150)
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    fig.patch.set_facecolor(PAPER)
    ax.text(W / 2, 30, "The four supplied tables — one conformed dimension, three facts",
            ha="center", fontsize=13, fontweight="bold", color=NAVY)
    ax.text(W / 2, 50, "Every relationship shown is an enforced dbt relationships test.",
            ha="center", fontsize=9, color=GREY)
    for frm, col, to in internal:
        fx, fy = POS[frm]
        ax.plot([fx + BW / 2, dcx], [fy + bh(frm) / 2, dcy], color=TEAL, lw=1.8, alpha=.75)
        mx = (fx + BW / 2 + dcx) / 2
        my = (fy + bh(frm) / 2 + dcy) / 2
        ax.text(mx, my, col, ha="center", va="center", fontsize=7.5, color=TEAL,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=PAPER, ec=TEAL, lw=0.8))
    for t, (src, grain, note) in CORE.items():
        x, y = POS[t]
        h = bh(t)
        accent = NAVY if t.startswith("dim_") else TEAL
        ax.add_patch(FancyBboxPatch((x, y), BW, h, boxstyle="round,pad=2",
                                    fc="white", ec=accent, lw=1.8))
        ax.add_patch(FancyBboxPatch((x, y), BW, HDR, boxstyle="square,pad=0",
                                    fc=accent, ec="none"))
        ax.text(x + 10, y + 15, t, fontsize=9, fontweight="bold", color="white", va="center")
        ax.text(x + 10, y + 27, f"{src}  ·  {rows.get(t,0):,} rows", fontsize=6.5,
                color="#CFE0F2", va="center")
        for i, cn in enumerate(cols.get(t, [])[:SHOWN]):
            is_k = cn.endswith("_key") or cn.endswith("_id")
            ax.text(x + 10, y + HDR + 11 + i * RH, cn, fontsize=7,
                    color=NAVY if is_k else GREY,
                    fontweight="bold" if is_k else "normal", va="center")
        ax.text(x, y + h + 12, grain, fontsize=7, color=GREY, style="italic", va="center")
    fig.savefig(OUT / "erd_core4.png", facecolor=PAPER, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    png_ok = True
except Exception as e:
    print(f"  PNG skipped: {e}")

print(f"  {len(CORE)} tables · {len(internal)} relationships between them")
for frm, col, to in sorted(internal):
    print(f"    {frm}.{col}  ->  {to}  (many-to-one)")
print(f"  {len(external)} further enforced relationships to dimensions outside these four")
print(f"  wrote docs/erd_core4.svg, docs/erd_core4.html"
      + (", docs/erd_core4.png" if png_ok else ""))
