"""
23_build_before_after_erd.py — the BEFORE and AFTER data models, side by side.

BEFORE  the four files exactly as delivered. Flat, redundant, no keys declared, no calendar.
AFTER   the gold star schema: conformed dimensions, surrogate keys, role-playing dates.

Showing both is the point. A star schema on its own says "here is a data model"; the pair
says "here is what changed and why", which is the actual modelling argument. Every arrow on
the BEFORE diagram is an IMPLICIT join — a string match nobody validated — and every arrow on
the AFTER diagram is an enforced dbt relationships test.

Writes docs/erd_before_after.html and PNG-ready SVG for embedding in the report.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import TABLES as REG, TIERS

NAVY, TEAL, AMBER, RED, PURPLE, GREY, LINE = ("#12305B", "#0E8B8B", "#E8A317", "#C0392B",
                                              "#7B4B94", "#5A6672", "#C9D6E6")

# ---------------------------------------------------------------- BEFORE: the raw files
SOURCES = [
    ("MerchantSales.csv", 26_500, [
        ("Date", "text"), ("MerchantID", "text"), ("Merchant", "REDUNDANT"),
        ("Region", "REDUNDANT"), ("Channel", "REDUNDANT"), ("VoucherType", "text"),
        ("SalesValue", "text"), ("Transactions", "text")]),
    ("VoucherRedemptions.csv", 120_969, [
        ("VoucherID", "text"), ("MerchantID", "text"), ("Merchant", "REDUNDANT"),
        ("SoldDate", "text"), ("VoucherType", "text"), ("VoucherValue", "text"),
        ("Redeemed", "text"), ("RedeemedDate", "text")]),
    ("SupportTickets.csv", 1_363, [
        ("TicketID", "text"), ("Date", "text"), ("MerchantID", "text"),
        ("Merchant", "REDUNDANT"), ("Region", "REDUNDANT"), ("TicketType", "text"),
        ("Priority", "text"), ("ResolutionHours", "text"), ("SLAHours", "text"),
        ("Status", "text")]),
    ("MerchantReference.csv", 25, [
        ("MerchantID", "text"), ("Merchant", "text"), ("Region", "text"),
        ("Channel", "text"), ("ActiveStatus", "text"), ("OnboardedDate", "text"),
        ("AccountManager", "text"), ("BaseMonthlySalesTarget", "text")]),
]

PROBLEMS = [
    ("No date table", "Every date is a string in four different files. Power BI time "
                      "intelligence cannot work without a contiguous calendar."),
    ("Descriptive columns duplicated", "Merchant, Region and Channel appear on three facts "
                                       "AND on the reference file — four places one value "
                                       "can disagree with itself."),
    ("No declared keys", "MerchantID joins by string match. Nothing enforces that every "
                         "value resolves, and nothing would notice if one stopped."),
    ("Everything is text", "SalesValue, Transactions, ResolutionHours all arrive as strings. "
                           "Any aggregate silently depends on implicit coercion."),
    ("No conformed dimensions", "VoucherType, Priority, TicketType and Status exist only as "
                                "repeated strings — no sort order, no grouping, no metadata."),
    ("Two grains, one shape", "Daily aggregates and voucher-level rows look alike but count "
                              "different populations: 510,127 transactions vs 120,969 "
                              "vouchers."),
]

# ---------------------------------------------------------------- AFTER: from the manifest
MAN = json.loads((ROOT / "dbt" / "target" / "manifest.json").read_text(encoding="utf-8"))
short = lambda u: u.split(".")[-1]
CAT_P = ROOT / "dbt" / "target" / "catalog.json"
CAT = json.loads(CAT_P.read_text(encoding="utf-8")) if CAT_P.exists() else {"nodes": {}}

fks = []
for uid, n in MAN["nodes"].items():
    if n["resource_type"] != "test":
        continue
    meta = n.get("test_metadata") or {}
    if meta.get("name") != "relationships":
        continue
    kw = meta.get("kwargs", {})
    to = re.search(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", kw.get("to", "") or "")
    frm = (n.get("attached_node") or "").split(".")[-1]
    if to and frm and kw.get("column_name"):
        fks.append((frm, kw["column_name"].strip('"'), to.group(1)))

rows = {}
for uid, c in CAT.get("nodes", {}).items():
    st = (c.get("stats") or {}).get("row_count") or {}
    if st.get("value") is not None:
        rows[short(uid)] = int(st["value"])



# Connector colour keyed on the target table — see the note in 24_render_erd_png.py. A single
# colour across 15 lines shows that joins exist but not which reaches what.
JOIN_COLOURS = ["#0E8B8B", "#12305B", "#B8860B", "#7B4B94", "#C0392B",
                "#1E8449", "#1B6CA8", "#D6336C", "#8B6914"]
_tg = sorted({t for _f, _c, t in fks})
TCOL = {t: JOIN_COLOURS[i % len(JOIN_COLOURS)] for i, t in enumerate(_tg)}

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ================================================================ BEFORE svg
def svg_before():
    W, BW, RH, HDR = 1080, 236, 15, 30
    pos = {"MerchantSales.csv": (40, 60), "VoucherRedemptions.csv": (40, 300),
           "SupportTickets.csv": (760, 60), "MerchantReference.csv": (400, 330)}
    h = {n: HDR + len(c) * RH + 12 for n, _, c in SOURCES}
    H = 620
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'style="width:100%;height:auto;font-family:Segoe UI,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#FDF6F5"/>']

    # implicit joins — dashed, because nothing enforces them
    ref = pos["MerchantReference.csv"]
    for src in ["MerchantSales.csv", "VoucherRedemptions.csv", "SupportTickets.csv"]:
        x, y = pos[src]
        x1 = x + (BW if x < ref[0] else 0)
        y1 = y + h[src] / 2
        x2 = ref[0] + (0 if x < ref[0] else BW)
        y2 = ref[1] + h["MerchantReference.csv"] / 2
        mx = (x1 + x2) / 2
        s.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" fill="none" '
                 f'stroke="{RED}" stroke-width="1.6" stroke-dasharray="6 4" opacity=".65"/>')
        s.append(f'<text x="{mx}" y="{(y1+y2)/2 - 6}" text-anchor="middle" font-size="10" '
                 f'fill="{RED}" font-weight="700">implicit</text>')

    for name, nrows, cols in SOURCES:
        x, y = pos[name]
        bh = h[name]
        s.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{bh}" rx="6" fill="#fff" '
                 f'stroke="{LINE}"/>')
        s.append(f'<path d="M{x},{y+6} a6,6 0 0 1 6,-6 h{BW-12} a6,6 0 0 1 6,6 v{HDR-6} '
                 f'h-{BW} Z" fill="{RED}"/>')
        s.append(f'<text x="{x+9}" y="{y+20}" font-size="12" font-weight="700" fill="#fff">'
                 f'{esc(name)}  ·  {nrows:,}</text>')
        for i, (c, kind) in enumerate(cols):
            ty = y + HDR + 12 + i * RH
            col = RED if kind == "REDUNDANT" else GREY
            wt = "700" if kind == "REDUNDANT" else "400"
            s.append(f'<text x="{x+9}" y="{ty}" font-size="10" fill="{col}" '
                     f'font-weight="{wt}">{esc(c)}</text>')
            if kind == "REDUNDANT":
                s.append(f'<text x="{x+BW-8}" y="{ty}" font-size="8" text-anchor="end" '
                         f'fill="{RED}" font-weight="700">DUP</text>')
    s.append(f'<text x="{W/2}" y="26" text-anchor="middle" font-size="14" '
             f'font-weight="700" fill="{RED}">BEFORE — four flat files, no keys, no calendar,'
             f' 9 duplicated attribute columns</text>')
    return "\n".join(s) + "</svg>"


# ================================================================ AFTER svg
def svg_after():
    tables = {t: REG[t] for t in REG}
    facts = sorted(t for t in tables if t.startswith("fct_"))
    dims = sorted(t for t in tables if t.startswith("dim_"))
    other = sorted(t for t in tables if t.startswith(("mart_", "snap_")))
    W, BW, RH, HDR = 1080, 200, 14, 28

    def bh(t):
        return HDR + min(len(cols_of(t)), 7) * RH + 10

    def cols_of(t):
        for uid, c in CAT.get("nodes", {}).items():
            if short(uid) == t:
                return [v["name"] for v in sorted(c["columns"].values(),
                                                  key=lambda x: x["index"])]
        return []

    pos, y = {}, 56
    for t in dims[:4]:
        pos[t] = (30, y); y += bh(t) + 10
    yl = y
    y = 56
    for t in dims[4:]:
        pos[t] = (W - BW - 30, y); y += bh(t) + 10
    yr = y
    y = 56
    for t in facts + other:
        pos[t] = ((W - BW) / 2, y); y += bh(t) + 10
    # Space reserved beneath the boxes for an explicit join list. The boxes show WHERE each
    # line goes; only naming the columns shows HOW. Tracing a line across a 14-box diagram
    # cannot tell a reader whether a fact reaches dim_date on date_key, sold_date_key or
    # redeemed_date_key — and on this model the answer is all three.
    JOIN_ROWS = (len(fks) + 2) // 3
    JOIN_H = 34 + JOIN_ROWS * 15 + 14
    H = max(yl, yr, y) + 30 + JOIN_H

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
         f'style="width:100%;height:auto;font-family:Segoe UI,Arial,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#F2F9F8"/>']

    for frm, col, to in fks:
        if frm not in pos or to not in pos:
            continue
        ax, ay = pos[to]; bx, by = pos[frm]
        a_r = ax < bx
        x1 = ax + (BW if a_r else 0); y1 = ay + bh(to) / 2
        x2 = bx + (0 if a_r else BW); y2 = by + bh(frm) / 2
        mx = (x1 + x2) / 2
        _c = TCOL.get(to, TEAL)
        s.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" fill="none" '
                 f'stroke="{_c}" stroke-width="1.6" opacity=".8"/>')
        s.append(f'<circle cx="{x1}" cy="{y1}" r="3.2" fill="{_c}"/>')

    for t, meta in tables.items():
        if t not in pos:
            continue
        x, y0 = pos[t]
        c = TIERS[meta["tier"]][1]
        s.append(f'<rect x="{x}" y="{y0}" width="{BW}" height="{bh(t)}" rx="6" fill="#fff" '
                 f'stroke="{LINE}"/>')
        s.append(f'<path d="M{x},{y0+6} a6,6 0 0 1 6,-6 h{BW-12} a6,6 0 0 1 6,6 v{HDR-6} '
                 f'h-{BW} Z" fill="{c}"/>')
        n = rows.get(t, meta["rows"])
        s.append(f'<text x="{x+8}" y="{y0+19}" font-size="11" font-weight="700" fill="#fff">'
                 f'{esc(t)}  ·  {n:,}</text>')
        for i, cn in enumerate(cols_of(t)[:7]):
            is_k = cn.endswith("_key") or cn.endswith("_id")
            s.append(f'<text x="{x+8}" y="{y0+HDR+11+i*RH}" font-size="9.5" '
                     f'fill="{NAVY if is_k else GREY}" '
                     f'font-weight="{"700" if is_k else "400"}">{esc(cn)}</text>')
    s.append(f'<text x="{W/2}" y="26" text-anchor="middle" font-size="14" font-weight="700" '
             f'fill="{TEAL}">AFTER — {len(tables)} tables, {len(fks)} ENFORCED foreign keys, '
             f'conformed dimensions, contiguous calendar</text>')

    # ---- every join, stated explicitly, in three columns
    jy = H - JOIN_H + 6
    s.append(f'<rect x="20" y="{jy}" width="{W-40}" height="{JOIN_H-16}" rx="8" '
             f'fill="#F4F7FB" stroke="{LINE}"/>')
    s.append(f'<text x="34" y="{jy+20}" font-size="11.5" font-weight="700" fill="{NAVY}">'
             f'How the tables join — every one an enforced dbt relationships test</text>')
    colw = (W - 68) / 3
    for i, (frm, col, to) in enumerate(sorted(fks, key=lambda r: (r[2], r[0]))):
        cx = 34 + (i % 3) * colw
        cy = jy + 40 + (i // 3) * 15
        _c = TCOL.get(to, TEAL)
        s.append(f'<rect x="{cx}" y="{cy-7}" width="8" height="8" rx="2" fill="{_c}"/>')
        s.append(f'<text x="{cx+13}" y="{cy}" font-size="9" fill="#12203A">'
                 f'{esc(frm)}.{esc(col)} &#8594; '
                 f'<tspan font-weight="700">{esc(to)}</tspan></text>')
    return "\n".join(s) + "</svg>"


before, after = svg_before(), svg_after()

CHANGES = [
    ("No date table", "dim_date — 365 contiguous days, tested for gaps",
     "Time intelligence returns wrong answers, not errors, on a gapped calendar"),
    ("Merchant/Region/Channel on 3 facts", "Dropped from facts; live only on dim_merchant",
     "Profiling proved 100% agreement, so removal is lossless — and it stops two "
     "versions of 'Region' ever existing"),
    ("String joins, nothing enforced", f"{len(fks)} relationships tests, run on every build",
     "A broken join now fails the pipeline instead of silently returning fewer rows"),
    ("Everything text", "Typed at silver; decimals, dates and ints declared",
     "No implicit coercion hiding inside an aggregate"),
    ("Repeated category strings", "dim_voucher_type, dim_priority, dim_ticket_type, "
                                  "dim_ticket_status",
     "Sort order, grouping and metadata that do not exist in the source"),
    ("Redemption date only as a column", "Role-playing date: sold_date_key ACTIVE, "
                                         "redeemed_date_key INACTIVE",
     "Without it, late redemptions are attributed back to the sale month and a backlog "
     "is invisible"),
    ("No history", "snap_merchant SCD2 + dim_merchant_history",
     "MerchantReference overwrites; 'when did this merchant become At Risk' was "
     "unanswerable"),
    ("Two grains conflated", "Separate facts; mart_reconciliation records the 4.2:1 ratio "
                             "as an EXPECTED variance",
     "Stops someone reporting a R43.5m 'break' that is not a break"),
]

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Data model — before and after</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#EEF3F9;margin:0;padding:24px;color:#12203A}}
h1{{color:{NAVY};font-size:24px;margin:0 0 4px}}h2{{color:{NAVY};font-size:17px;margin:26px 0 8px}}
.sub{{color:{GREY};font-size:13px;margin-bottom:18px}}
.card{{background:#fff;border-radius:12px;padding:16px;box-shadow:0 6px 22px rgba(18,48,91,.10);
 margin-bottom:18px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff;border-radius:10px;
 overflow:hidden;box-shadow:0 6px 22px rgba(18,48,91,.10)}}
th{{background:{NAVY};color:#fff;text-align:left;padding:9px 12px;font-size:11px;
 text-transform:uppercase;letter-spacing:.5px}}
td{{border-bottom:1px solid #E4EAF2;padding:9px 12px;vertical-align:top}}
td.b{{color:{RED};font-weight:600;width:26%}}td.a{{color:{TEAL};font-weight:600;width:30%}}
td.w{{color:{GREY}}}
.note{{background:#FDF0EE;border-left:4px solid {RED};padding:12px 15px;border-radius:0 8px 8px 0;
 font-size:13px;line-height:1.6;margin-top:14px}}
.good{{background:#F0F9F9;border-left-color:{TEAL}}}
</style></head><body>
<h1>Data model &mdash; before and after</h1>
<div class="sub">What was delivered, what was built, and why each change was necessary</div>

<div class="card">{before}</div>
<div class="note"><b>What is wrong with the delivered shape.</b><ul style="margin:8px 0 0 18px">
{''.join(f'<li><b>{esc(t)}</b> &mdash; {esc(d)}</li>' for t, d in PROBLEMS)}
</ul></div>

<div class="card" style="margin-top:22px">{after}</div>
<div class="note good"><b>Every arrow above is an enforced test.</b> The dashed red arrows on
the BEFORE diagram are implicit string joins that nothing validates. The teal arrows on the
AFTER diagram are {len(fks)} <code>relationships</code> tests that run on every
<code>dbt build</code> &mdash; drop a join and the build fails.</div>

<h2>Change by change</h2>
<table><thead><tr><th>Before</th><th>After</th><th>Why it matters</th></tr></thead><tbody>
{''.join(f'<tr><td class="b">{esc(b)}</td><td class="a">{esc(a)}</td><td class="w">{esc(w)}</td></tr>' for b, a, w in CHANGES)}
</tbody></table>
</body></html>"""

(ROOT / "docs" / "erd_before_after.html").write_text(html, encoding="utf-8")
(ROOT / "docs" / "erd_before.svg").write_text(before, encoding="utf-8")
(ROOT / "docs" / "erd_after.svg").write_text(after, encoding="utf-8")
print(f"  BEFORE: {len(SOURCES)} flat files, {sum(1 for _,_,c in SOURCES for _,k in c if k=='REDUNDANT')} duplicated columns, 0 enforced keys")
print(f"  AFTER : {len(REG)} tables, {len(fks)} enforced foreign keys")
print(f"  wrote docs/erd_before_after.html, erd_before.svg, erd_after.svg")
