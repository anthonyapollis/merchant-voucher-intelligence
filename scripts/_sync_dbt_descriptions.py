"""
_sync_dbt_descriptions.py — push the table registry's justification into the dbt schema YAML.

Keeps `dbt docs` telling the same story as the ERD, the Word report and the Excel pack. The
registry is the source; this rewrites only the `description:` of each model it owns, leaving
every column, test and config untouched.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _table_registry import TABLES, TIERS

ROOT = Path(__file__).resolve().parents[1]
YMLS = [
    ROOT / "dbt" / "models" / "marts" / "core" / "_core_models.yml",
    ROOT / "dbt" / "models" / "marts" / "analytics" / "_analytics_models.yml",
]

updated = 0
for yml in YMLS:
    if not yml.exists():
        continue
    text = yml.read_text(encoding="utf-8")
    out, i = [], 0
    lines = text.splitlines()
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)- name: (\w+)\s*$", line)
        out.append(line)
        i += 1
        if not m:
            continue
        indent, name = m.group(1), m.group(2)
        if name not in TABLES:
            continue
        reg = TABLES[name]
        tier_label = TIERS[reg["tier"]][0]

        # Drop any existing description block for this model
        if i < len(lines) and re.match(rf"^{indent}  description:", lines[i]):
            i += 1
            while i < len(lines) and (lines[i].strip() == "" or
                                      lines[i].startswith(indent + "    ")):
                if lines[i].strip() and not lines[i].startswith(indent + "    "):
                    break
                i += 1

        body = f"[{tier_label}] {reg['why']} {reg['detail']}"
        body = re.sub(r"\s+", " ", body).strip()
        pad = indent + "      "
        wrapped, cur = [], ""
        for word in body.split():
            if len(cur) + len(word) + 1 > 92:
                wrapped.append(cur); cur = word
            else:
                cur = f"{cur} {word}".strip()
        wrapped.append(cur)
        out.append(f"{indent}  description: >")
        out += [pad + w for w in wrapped]
        updated += 1

    yml.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  updated {yml.relative_to(ROOT)}")

print(f"\nSynced {updated} model descriptions from the registry.")
