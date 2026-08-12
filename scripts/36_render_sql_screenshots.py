"""
36_render_sql_screenshots.py — render each SQL report-pack query and its RESULT as a PNG.

Screenshots of a query tool would show the same thing with more chrome and less legibility,
and would have to be recaptured by hand every time a number moves. These are generated from
the same queries in 34_build_sql_report_pack.py, executed live against the warehouse, so the
image and the data cannot drift apart.

One PNG per query: the SQL with its joins highlighted above, the returned rows below.
Written to docs/screenshots/sql/ and embedded in the Word report.
"""
import textwrap
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots" / "sql"
OUT.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "pack", Path(__file__).parent / "34_build_sql_report_pack.py")
NAVY, TEAL, AMBER, INK, SLATE = "#12305B", "#0E8B8B", "#B8860B", "#12203A", "#5A6672"
PAPER, PANEL, KEYW = "#FFFFFF", "#F4F7FB", "#7B4B94"

# Import the query list without re-running the module's file writes.
pack_path = Path(__file__).parent / "34_build_sql_report_pack.py"
src = pack_path.read_text(encoding="utf-8")
ns = {"__file__": str(pack_path)}
exec(src.split("con = duckdb.connect")[0], ns)
QUERIES = ns["QUERIES"]

con = duckdb.connect(str(ROOT / "data" / "mvi.duckdb"), read_only=True)

KEYWORDS = ("SELECT", "FROM", "INNER JOIN", "LEFT  JOIN", "LEFT JOIN", "GROUP BY", "ORDER BY",
            "WITH", "UNION ALL", "LIMIT", "ON", "AS", "CASE", "WHEN", "THEN", "ELSE", "END",
            "OVER", "AND", "NOT")

written = []
for i, (title, note, sql) in enumerate(QUERIES, 1):
    df = con.execute(sql).df()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].round(2)

    sql_lines = [ln for ln in sql.strip().splitlines()]
    show = df.head(10)
    tbl = show.to_string(index=False).splitlines()

    # Height driven by content so nothing is clipped — the failure mode these images exist
    # to avoid is a screenshot with the last row cut off.
    h = 1.5 + len(sql_lines) * 0.165 + len(tbl) * 0.20
    fig = plt.figure(figsize=(15.5, h), dpi=150)
    fig.patch.set_facecolor(PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, h)

    y = h - 0.34
    ax.add_patch(FancyBboxPatch((0.012, y - 0.10), 0.976, 0.40,
                                boxstyle="round,pad=0.01", fc=NAVY, ec="none"))
    ax.text(0.028, y + 0.06, title, fontsize=14, color="white",
            fontweight="bold", va="center", family="DejaVu Sans")
    y -= 0.44

    for ln in textwrap.wrap(note, 165):
        ax.text(0.028, y, ln, fontsize=9.5, color=SLATE, va="top", style="italic")
        y -= 0.20
    y -= 0.10

    sql_h = len(sql_lines) * 0.165 + 0.20
    ax.add_patch(FancyBboxPatch((0.012, y - sql_h + 0.06), 0.976, sql_h,
                                boxstyle="round,pad=0.008", fc=PANEL, ec="#D8E2EE"))
    for ln in sql_lines:
        up = ln.upper()
        is_join = "JOIN" in up
        colour = TEAL if is_join else (KEYW if any(up.strip().startswith(k)
                                                   for k in KEYWORDS) else INK)
        weight = "bold" if is_join or any(up.strip().startswith(k) for k in
                                          ("SELECT", "FROM", "WITH", "GROUP BY")) else "normal"
        ax.text(0.026, y, ln, fontsize=8.6, color=colour, family="DejaVu Sans Mono",
                va="top", fontweight=weight)
        y -= 0.165
    y -= 0.22

    ax.text(0.026, y, f"RESULT — {len(df)} row(s)"
                      + ("  (first 10 shown)" if len(df) > 10 else ""),
            fontsize=10, color=TEAL, fontweight="bold", va="top")
    y -= 0.26
    for j, ln in enumerate(tbl):
        ax.text(0.026, y, ln, fontsize=8.4, family="DejaVu Sans Mono", va="top",
                color=NAVY if j == 0 else INK,
                fontweight="bold" if j == 0 else "normal")
        y -= 0.20

    p = OUT / f"q{i}_{title.split()[0].lower()}.png"
    fig.savefig(p, facecolor=PAPER, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    written.append((p, len(df)))

con.close()

print(f"  rendered {len(written)} query screenshots to {OUT.relative_to(ROOT)}")
for p, n in written:
    print(f"    {p.name:<34} {n:>4} rows   {p.stat().st_size/1024:>5.0f} KB")
