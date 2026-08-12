"""Render the dbt DAG as text from target/manifest.json.

`dbt docs serve` needs a browser on localhost, which is blocked in this environment, so the
lineage is extracted from the manifest instead. Same source of truth, no server required.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
man = json.load(open(ROOT / "dbt" / "target" / "manifest.json"))

nodes = man["nodes"]
short = lambda uid: uid.split(".")[-1]

models = {uid: n for uid, n in nodes.items()
          if n["resource_type"] in ("model", "snapshot")}
tests_by_model = defaultdict(int)
for uid, n in nodes.items():
    if n["resource_type"] == "test":
        for dep in n["depends_on"]["nodes"]:
            tests_by_model[dep] += 1

LAYERS = [
    ("SOURCES  (bronze)", lambda n: False),
    ("STAGING  (silver)", lambda n: "staging" in n.get("fqn", [])),
    ("INTERMEDIATE", lambda n: "intermediate" in n.get("fqn", [])),
    ("SNAPSHOTS  (SCD2 capture)", lambda n: n["resource_type"] == "snapshot"),
    ("MARTS / CORE  (gold star schema)", lambda n: "core" in n.get("fqn", [])),
    ("MARTS / ANALYTICS", lambda n: "analytics" in n.get("fqn", [])),
]

print("=" * 96)
print("dbt MODEL LINEAGE")
print("=" * 96)

for src_uid, s in sorted(man["sources"].items()):
    kids = [short(u) for u, n in models.items() if src_uid in n["depends_on"]["nodes"]]
    print(f"  source: {s['name']:<32} -> {', '.join(sorted(kids))}")

for label, pred in LAYERS[1:]:
    sel = {u: n for u, n in models.items() if pred(n)}
    if not sel:
        continue
    print(f"\n{label}")
    print("-" * 96)
    for uid, n in sorted(sel.items(), key=lambda kv: short(kv[0])):
        deps = sorted({short(d) for d in n["depends_on"]["nodes"]})
        mat = n["config"].get("materialized", "?")
        t = tests_by_model.get(uid, 0)
        print(f"  {short(uid):<28} [{mat:<11}] tests:{t:<3} <- {', '.join(deps) or '(sources)'}")

# Reverse dependency: what breaks if a model changes
print("\n" + "=" * 96)
print("DOWNSTREAM IMPACT  (change this -> these rebuild)")
print("=" * 96)
children = defaultdict(list)
for uid, n in models.items():
    for d in n["depends_on"]["nodes"]:
        children[d].append(short(uid))
for uid in sorted(models, key=short):
    kids = sorted(children.get(uid, []))
    if kids:
        print(f"  {short(uid):<28} -> {', '.join(kids)}")

exposures = man.get("exposures", {})
print("\n" + "=" * 96)
print("EXPOSURES  (what consumes the marts)")
print("=" * 96)
for uid, e in exposures.items():
    print(f"  {e['name']}  [{e['type']}]  depends on {len(e['depends_on']['nodes'])} models")

n_models = sum(1 for n in models.values() if n["resource_type"] == "model")
n_snaps = sum(1 for n in models.values() if n["resource_type"] == "snapshot")
n_tests = sum(1 for n in nodes.values() if n["resource_type"] == "test")
print("\n" + "=" * 96)
print(f"{n_models} models · {n_snaps} snapshot · {n_tests} tests · "
      f"{len(man['sources'])} sources · {len(exposures)} exposures")
print("=" * 96)
