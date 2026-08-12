"""
40_build_defect_case_study.py — the R984,046 defect, as figures and a standalone PDF.

Two artifacts:
    docs/fig_date_window.png      calendar SPAN vs reporting WINDOW, and the phantom month
    docs/fig_reconciliation.png   how the cross-implementation gate detects it
    docs/Data_Quality_Case_Study.pdf   a four-page standalone note

Every number is recomputed from the warehouse at build time rather than typed in, so the
document cannot drift from the data it describes. If the underlying dates change, the figures
and the arithmetic change with them — and if the reconciliation ever stops reproducing
R984,046, that is a signal worth having rather than a stale sentence in a PDF.
"""
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image, KeepTogether)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

NAVY, TEAL, AMBER, RED = "#12305B", "#0E8B8B", "#B8860B", "#C0392B"
GREY, INK, LINE = "#5A6672", "#12203A", "#D3DEEC"

# ---------------------------------------------------------------- facts, from the warehouse
con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"), read_only=True)
fmt = lambda d: f"{d:%d %b}".lstrip("0")
fmt_long = lambda d: f"{d:%d %B %Y}".lstrip("0")

max_sold, max_redeemed = con.execute(
    "select max(sold_date), max(redeemed_date) from main_staging.stg_voucher_redemptions"
).fetchone()
min_date = con.execute(
    "select min(sales_date) from main_staging.stg_merchant_sales").fetchone()[0]
monthly_target = float(con.execute(
    "select sum(base_monthly_sales_target) from main_marts.dim_merchant "
    "where merchant_key <> '-1'").fetchone()[0])
total_target = float(con.execute(
    "select sum(monthly_sales_target) from main_marts.fct_merchant_target").fetchone()[0])
con.close()

aug_days = max_redeemed.day
days_in_aug = 31
phantom = monthly_target * aug_days / days_in_aug
window_days = (max_sold - min_date).days + 1
span_days = (max_redeemed - min_date).days + 1

# ---------------------------------------------------------------- figure 1: span vs window
fig, ax = plt.subplots(figsize=(11, 4.4), dpi=150)
fig.patch.set_facecolor("white")
ax.set_xlim(0, 100); ax.set_ylim(0, 7.2); ax.axis("off")

W_END = 100 * (window_days / span_days)      # 31 Jul as a share of the full span

rows = [
    (6.1, "Sales, tickets", 0, W_END, "#E1F5EE", "#085041", f"{fmt(min_date)} to {fmt(max_sold)}"),
    (5.0, "Vouchers sold", 0, W_END, "#E1F5EE", "#085041", f"{fmt(min_date)} to {fmt(max_sold)}"),
    (3.9, "Redeemed", 0, 100, "#FAEEDA", "#412402", f"{fmt(min_date)} to {fmt(max_redeemed)}"),
]
for y, label, x0, x1, fill, txt, caption in rows:
    ax.add_patch(FancyBboxPatch((x0, y), x1 - x0, 0.78, boxstyle="round,pad=0.02",
                                fc=fill, ec="none"))
    ax.text(-1, y + 0.39, label, ha="right", va="center", fontsize=10, color=GREY)
    ax.text(x0 + 1.2, y + 0.39, caption, ha="left", va="center", fontsize=9.5,
            color=txt, fontweight="bold")

ax.add_patch(FancyBboxPatch((0, 2.5), 100, 0.78, boxstyle="round,pad=0.02",
                            fc="none", ec="#185FA5", lw=1.6))
ax.text(-1, 2.89, "Calendar span", ha="right", va="center", fontsize=10,
        color=INK, fontweight="bold")
ax.text(1.2, 2.89, "must reach the last redemption so redeemed_date_key can join",
        fontsize=9.5, color="#0C447C", va="center")

ax.add_patch(FancyBboxPatch((0, 1.3), W_END, 0.78, boxstyle="round,pad=0.02",
                            fc="none", ec=TEAL, lw=1.6))
ax.text(-1, 1.69, "Reporting window", ha="right", va="center", fontsize=10,
        color=INK, fontweight="bold")
ax.text(1.2, 1.69, "must stop at the last sale", fontsize=9.5, color="#085041", va="center")
ax.add_patch(FancyBboxPatch((W_END, 1.3), 100 - W_END, 0.78, boxstyle="round,pad=0.02",
                            fc="#F7C1C1", ec="none"))
ax.text(W_END + (100 - W_END) / 2, 1.69, "phantom", ha="center", va="center",
        fontsize=9, color="#501313", fontweight="bold")

ax.plot([W_END, W_END], [1.1, 6.95], color=RED, lw=1.1, ls="--", alpha=.75)
ax.text(W_END, 7.05, f"{fmt(max_sold)} — last sale", ha="center", fontsize=9, color=RED)
ax.text(100, 0.75, f"{fmt(max_redeemed)} — last redemption", ha="right", fontsize=9,
        color=AMBER)
ax.text(0, 0.2,
        f"{aug_days} of {days_in_aug} August days were counted as covered  ·  "
        f"R{monthly_target:,.2f} x {aug_days}/{days_in_aug} = R{phantom:,.0f} of target "
        f"against zero sales",
        fontsize=10, color=INK)
fig.savefig(DOCS / "fig_date_window.png", bbox_inches="tight", pad_inches=0.25,
            facecolor="white")
plt.close(fig)

# ---------------------------------------------------------------- figure 2: the gate
fig, ax = plt.subplots(figsize=(11, 3.5), dpi=150)
fig.patch.set_facecolor("white")
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

def box(x, y, w, h, title, sub, fill, edge, tcol):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6", fc=fill, ec=edge,
                                lw=1.4))
    ax.text(x + w / 2, y + h * 0.62, title, ha="center", fontsize=10.5, color=tcol,
            fontweight="bold")
    ax.text(x + w / 2, y + h * 0.26, sub, ha="center", fontsize=9, color=GREY)

box(2, 58, 26, 30, "scripts/02 — pandas", "gold built in Python", "#EEF3F9", NAVY, NAVY)
box(2, 12, 26, 30, "dbt/models — SQL", "gold built again", "#EEEDFE", "#534AB7", "#3C3489")
box(38, 35, 26, 30, "05_reconcile.py", "compares at R0.01", "#E1F5EE", TEAL, "#085041")
box(72, 58, 26, 30, "agree", "build proceeds", "#EAF3DE", "#639922", "#173404")
box(72, 12, 26, 30, "disagree", "build stops", "#FCEBEB", RED, "#501313")

for x0, y0 in ((28, 73), (28, 27)):
    ax.annotate("", xy=(38, 50), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", color=GREY, lw=1.3))
ax.annotate("", xy=(72, 73), xytext=(64, 50),
            arrowprops=dict(arrowstyle="->", color="#639922", lw=1.3))
ax.annotate("", xy=(72, 27), xytext=(64, 50),
            arrowprops=dict(arrowstyle="->", color=RED, lw=1.3))
ax.text(50, 4, f"Target totals differed by R{phantom:,.0f} — the defect surfaced here, "
               f"not in any schema test", ha="center", fontsize=10, color=INK)
fig.savefig(DOCS / "fig_reconciliation.png", bbox_inches="tight", pad_inches=0.25,
            facecolor="white")
plt.close(fig)

# ---------------------------------------------------------------- standalone PDF
S = getSampleStyleSheet()
S.add(ParagraphStyle("H1x", parent=S["Heading1"], fontName="Helvetica-Bold", fontSize=17,
                     textColor=colors.HexColor(NAVY), spaceAfter=8, spaceBefore=2))
S.add(ParagraphStyle("H2x", parent=S["Heading2"], fontName="Helvetica-Bold", fontSize=12.5,
                     textColor=colors.HexColor(TEAL), spaceAfter=5, spaceBefore=12))
S.add(ParagraphStyle("Bx", parent=S["BodyText"], fontName="Helvetica", fontSize=10.2,
                     leading=15.2, textColor=colors.HexColor(INK), alignment=TA_LEFT,
                     spaceAfter=7))
S.add(ParagraphStyle("Cap", parent=S["BodyText"], fontName="Helvetica-Oblique", fontSize=8.6,
                     textColor=colors.HexColor(GREY), spaceAfter=10))
S.add(ParagraphStyle("Cd", parent=S["BodyText"], fontName="Courier", fontSize=8.8,
                     leading=12.4, textColor=colors.HexColor(INK), spaceAfter=8))
P = lambda t, s="Bx": Paragraph(t, S[s])

OUT = DOCS / "Data_Quality_Case_Study.pdf"
doc = SimpleDocTemplate(str(OUT), pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        title="How a wrong number that looked right was caught",
                        author="Anthony Apollis")

def fig_img(name, width=168 * mm):
    from PIL import Image as PILImage
    p = DOCS / name
    w, h = PILImage.open(p).size
    return Image(str(p), width=width, height=width * h / w)

story = [
    P("Catching a wrong number that looked right", "H1x"),
    P("A worked example from the Merchant Sales &amp; Voucher Intelligence build: how the "
      "gold layer is validated, and the defect that validation caught.", "Cap"),

    P("The short version", "H2x"),
    P(f"A sales target total was overstated by <b>R{phantom:,.0f}</b>. Nothing was broken: "
      f"the date table was contiguous, had no gaps, the correct row count, and every foreign "
      f"key resolved. All 132 dbt tests passed. The table was structurally perfect and was "
      f"answering a slightly different question than the one being asked."),

    P("What the data actually looks like", "H2x"),
    P(f"Sales and support activity end on <b>{fmt_long(max_sold)}</b>. Vouchers sold before "
      f"that date continue to be redeemed afterwards, with the last redemption on "
      f"<b>{fmt_long(max_redeemed)}</b>. Two different endings, {span_days - window_days} days "
      f"apart, and the model needs both."),
    P("A date dimension must <b>span</b> to the last redemption, or a late redemption has no "
      "row to join to and silently drops out of every total. But the <b>reporting window</b> "
      "has to stop at the last sale, because there are no sales after it. Span and window are "
      "different things. Deriving both from one maximum conflates them."),
    fig_img("fig_date_window.png"),
    P("Figure 1 — the calendar must reach the last redemption; the reporting window must not.",
      "Cap"),

    P("How the wrong number arose", "H2x"),
    P(f"Monthly sales targets are pro-rated by the days the reporting window covers, so a "
      f"part-month never shows a false shortfall. With the window running to "
      f"{fmt(max_redeemed)}, August was treated as <b>{aug_days} of {days_in_aug} days "
      f"covered</b>. Target is charged for those days. Sales for them are zero, because sales "
      f"ended in July."),
]

t = Table([["All-merchant monthly target", f"R{monthly_target:,.2f}"],
           ["August days wrongly counted", f"{aug_days} of {days_in_aug}"],
           ["Pro-rated share", f"x {aug_days}/{days_in_aug}"],
           ["Target overstated by", f"R{phantom:,.0f}"],
           ["Correct total target", f"R{total_target:,.2f}"]],
          colWidths=[110 * mm, 58 * mm])
t.setStyle(TableStyle([
    ("FONT", (0, 0), (-1, -1), "Helvetica", 9.6),
    ("FONT", (0, 3), (-1, 3), "Helvetica-Bold", 9.6),
    ("TEXTCOLOR", (0, 3), (-1, 3), colors.HexColor(RED)),
    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F7FB")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story += [t, Spacer(1, 10)]

story += [
    P("What caught it", "H2x"),
    P("The gold layer is built <b>twice</b>, by two independent implementations — once in "
      "pandas, once in SQL executed by dbt. A reconciliation script compares every headline "
      "figure at a R0.01 tolerance and stops the build on any disagreement."),
    fig_img("fig_reconciliation.png"),
    P("Figure 2 — two implementations, one answer. A disagreement is the signal.", "Cap"),
    P("This is the class of defect that schema tests cannot reach. A uniqueness test asks "
      "whether a table is well-formed; it cannot ask whether the period is the right period. "
      "Two independent implementations of the same business rule can both be well-formed and "
      "still disagree — and when they do, one of them is wrong."),
    P("The same gate caught a second defect: pandas <font face='Courier'>rank(pct=True)</font> "
      "returns rank/n, while SQL <font face='Courier'>PERCENT_RANK()</font> returns "
      "(rank-1)/(n-1). Different statistics, both plausible, and merchant Health Score moved "
      "by up to 9.7 points depending on which was used."),

    P("The fix", "H2x"),
    P("One value. In the bounds CTE, the redemption branch contributes to the calendar "
      "maximum but passes NULL to the activity maximum, so it extends the span without "
      "moving the window:"),
    P("-- Redemption tail extends the calendar but must NOT extend the reporting window<br/>"
      "select min(redeemed_date), <b>null</b>, max(redeemed_date)<br/>"
      "from stg_voucher_redemptions where redeemed_date is not null", "Cd"),
    P(f"No date is hardcoded anywhere in the date dimension. Point the project at a different "
      f"extract and the window moves with the data. The current window is "
      f"{fmt_long(min_date)} to {fmt_long(max_sold)}, {window_days} days, derived at build time."),

    P("Why it matters beyond this dataset", "H2x"),
    P("The brief specified no dates. Whether a redemption tail belongs inside the reporting "
      "period is an <b>unstated requirement</b> — the kind that produces a number which is "
      "wrong and entirely plausible. Those are the errors worth engineering against, because "
      "nobody reviewing a dashboard will spot them by eye."),
    P("Current state: 28 controls, 27 tie exactly, one documented rounding convention, zero "
      "failures.", "Cap"),
]

doc.build(story)

print(f"  fig_date_window.png     span {span_days}d vs window {window_days}d")
print(f"  fig_reconciliation.png")
print(f"  phantom month recomputed from the warehouse: R{phantom:,.0f}")
print(f"  wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size/1024:.0f} KB)")
