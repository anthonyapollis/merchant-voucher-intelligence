"""
18_port_models_to_tsql.py — replace DuckDB dialect with the portability macros.

Mechanical, reviewable substitutions only. Anything that needs judgement is listed at the
end for manual attention rather than guessed at.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "dbt"

# (pattern, replacement) — applied in order. Deliberately narrow so a partial match cannot
# silently corrupt surrounding SQL.
SUBS = [
    # datediff('part', a, b) -> macro
    (r"datediff\(\s*'(\w+)'\s*,\s*([^,]+?)\s*,\s*([\s\S]+?)\)(?=[\s,)\n])",
     r"{{ mvi_datediff('\1', '\2', '\3') }}"),

    # cast(strftime(col, '%Y%m%d') as integer) -> date key macro
    (r"cast\(\s*strftime\(\s*([^,]+?)\s*,\s*'%Y%m%d'\s*\)\s*as\s+integer\s*\)",
     r"{{ mvi_date_key('\1') }}"),

    # strftime(col, '%Y-%m') -> year month
    (r"strftime\(\s*([^,]+?)\s*,\s*'%Y-%m'\s*\)", r"{{ mvi_year_month('\1') }}"),

    # date_trunc('month', col)
    (r"date_trunc\(\s*'month'\s*,\s*([^)]+?)\s*\)", r"{{ mvi_month_start('\1') }}"),

    # isodow(col)
    (r"\bisodow\(\s*([^)]+?)\s*\)", r"{{ mvi_isodow('\1') }}"),

    # week(col)  — only when used as a function on a date column
    (r"(?<![\w.])week\(\s*(date_day|[\w.]*date)\s*\)", r"{{ mvi_week('\1') }}"),

    # median(col)
    (r"\bmedian\(\s*([^)]+?)\s*\)", r"{{ mvi_median('\1') }}"),

    # quantile_cont(col, p)
    (r"quantile_cont\(\s*([^,]+?)\s*,\s*([\d.]+)\s*\)", r"{{ mvi_percentile('\1', \2) }}"),

    # arg_max(a, b)
    (r"arg_max\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)", r"{{ mvi_arg_max('\1', '\2') }}"),

    # stddev(col)
    (r"\bstddev\(\s*([^)]+?)\s*\)", r"{{ mvi_stddev('\1') }}"),

    # try_cast(col as type)
    (r"try_cast\(\s*([\w.\"]+)\s+as\s+(\w+)\s*\)", r"{{ mvi_try_cast('\1', '\2') }}"),
]

# Files where a substitution would be wrong or the SQL needs a human decision
MANUAL = {
    "dim_date.sql": "date spine (generate_series/unnest) and interval arithmetic — "
                    "rewritten by hand to use mvi_date_spine",
}

changed, notes = [], []
for f in sorted((ROOT / "models").rglob("*.sql")) + sorted((ROOT / "snapshots").rglob("*.sql")):
    src = f.read_text(encoding="utf-8")
    out = src
    hits = []
    for pat, rep in SUBS:
        out, n = re.subn(pat, rep, out)
        if n:
            hits.append(f"{pat.split('(')[0].strip(chr(92)).strip()}:{n}")
    if out != src:
        f.write_text(out, encoding="utf-8")
        changed.append((f.relative_to(ROOT), hits))

print("=" * 88)
print("PORTED TO ADAPTER-DISPATCHED MACROS")
print("=" * 88)
for p, hits in changed:
    print(f"  {str(p):<52} {', '.join(hits)}")
print(f"\n  {len(changed)} file(s) changed")

# Anything dialect-specific still left behind
print("\n  Remaining dialect-specific SQL (needs a human):")
LEFT = ["generate_series", "unnest(", "interval ", "::", "epoch("]
found = False
for f in sorted((ROOT / "models").rglob("*.sql")):
    txt = f.read_text(encoding="utf-8")
    hits = [k for k in LEFT if k in txt]
    if hits:
        found = True
        note = MANUAL.get(f.name, "review")
        print(f"    {f.relative_to(ROOT):<50} {', '.join(hits):<28} {note}")
if not found:
    print("    none")
