"""
16_patch_pbit.py — apply the theme and layout fixes to the .pbit as well as the .pbip.

WHY THIS IS NEEDED. A Power BI Project (.pbip) and a Power BI Template (.pbit) do NOT share
a report definition. The .pbip stores it as PBIR — a folder of per-visual JSON files. The
.pbit stores it as a single UTF-16 `Report/Layout` blob inside the zip, plus its own copy of
the theme. Editing the PBIR folder therefore changes the .pbip and leaves the .pbit exactly
as it was, which is why the template still looked like the original after the earlier fix.

PBIR is also still a preview format: Power BI Desktop refuses to open a .pbip unless
"Store reports using enhanced metadata format" is enabled. So the .pbit is the file that
actually opens for most people, and it is the one that most needed fixing.

This applies the same two changes to the template:
  1. theme     -> the semantic palette and the larger type scale
  2. layout    -> reflow onto one grid; slicers get the 76px they need instead of 56,
                  which is what was clipping the "All" value on every page

Each visualContainer carries its geometry twice — as top-level x/y/width/height AND inside
its serialised `config` under layouts[0].position. Both must be updated or Desktop renders
from the stale copy.
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"
BAK = ROOT / "powerbi" / "_MerchantVoucherIntelligence.original.pbit"
THEME_SRC = (ROOT / "powerbi" / "MerchantVoucherIntelligence.Report" /
             "StaticResources" / "RegisteredResources" / "MerchantVoucherIntelligence.json")

if not BAK.exists():
    shutil.copy2(SRC, BAK)
    print(f"  backed up original -> {BAK.name}")

CANVAS_W, CANVAS_H = 1280, 860
M, G = 16, 12
H = {"textbox": 44, "card": 104, "slicer": 76, "actionButton": 44, "shape": 44,
     "image": 120, "multiRowCard": 150}
H_CHART, H_TABLE, H_MAP = 268, 300, 470


def vheight(vt, orig_h):
    if vt in H:
        return H[vt]
    if vt in ("tableEx", "pivotTable", "matrix"):
        return H_TABLE
    if vt in ("shapeMap", "map", "filledMap"):
        return H_MAP
    return H_CHART


zin = zipfile.ZipFile(SRC)
members = {n: zin.read(n) for n in zin.namelist()}
zin.close()

# ---------------------------------------------------------------- 1. theme
theme_key = next((n for n in members if n.endswith("RegisteredResources/"
                                                   "MerchantVoucherIntelligence.json")), None)
if theme_key and THEME_SRC.exists():
    members[theme_key] = THEME_SRC.read_bytes()
    print(f"  theme replaced in {theme_key}")

# ---------------------------------------------------------------- 2. layout
LAY = "Report/Layout"
raw = members[LAY]
# Report/Layout is UTF-16-LE, usually with a BOM. Preserve whichever it was.
had_bom = raw[:2] in (b"\xff\xfe", b"\xfe\xff")
text = raw.decode("utf-16")
layout = json.loads(text)

total_moved = 0
for sec in layout.get("sections", []):
    vcs = sec.get("visualContainers", [])
    if not vcs:
        continue

    # Skip tooltip pages — they are sized for hover, not for a canvas
    if (sec.get("width", 0) or 0) < 700:
        continue

    parsed = []
    for vc in vcs:
        try:
            cfg = json.loads(vc["config"])
        except Exception:
            cfg = {}
        vt = (cfg.get("singleVisual") or {}).get("visualType", "")
        parsed.append((vc, cfg, vt))

    # Row-band on the ORIGINAL y, then left-to-right, same as the PBIR reflow
    parsed.sort(key=lambda t: (round((t[0].get("y") or 0) / 40), t[0].get("x") or 0))

    rows, cur, last = [], [], None
    for item in parsed:
        band = round((item[0].get("y") or 0) / 40)
        if last is not None and band != last:
            rows.append(cur); cur = []
        cur.append(item); last = band
    if cur:
        rows.append(cur)

    y = M
    for row in rows:
        n = len(row)
        avail = CANVAS_W - 2 * M - (n - 1) * G
        tot = sum((vc.get("width") or 1) for vc, _, _ in row) or 1
        h = max(vheight(vt, vc.get("height") or 0) for vc, _, vt in row)
        x = M
        for i, (vc, cfg, vt) in enumerate(row):
            w = int(avail * (vc.get("width") or 1) / tot) if n > 1 else avail
            if i == n - 1:
                w = CANVAS_W - M - x
            vc["x"], vc["y"], vc["width"], vc["height"] = x, y, w, h
            # The config carries a SECOND copy of the geometry; Desktop reads that one.
            lay = cfg.get("layouts")
            if isinstance(lay, list) and lay:
                pos = lay[0].setdefault("position", {})
                pos.update({"x": x, "y": y, "width": w, "height": h,
                            "z": pos.get("z", vc.get("z", 0))})
                vc["config"] = json.dumps(cfg, separators=(",", ":"))
            x += w + G
            total_moved += 1
        y += h + G

    sec["width"], sec["height"] = CANVAS_W, max(CANVAS_H, y + M)
    sec["displayOption"] = 1          # FitToWidth
    print(f"  {sec.get('displayName', sec.get('name')):<32} {len(vcs):>2} visuals, "
          f"{len(rows)} rows, canvas {CANVAS_W}x{sec['height']}")

out = json.dumps(layout, separators=(",", ":"))
# ALWAYS utf-16-le with NO BOM. Python's "utf-16" codec prepends a BOM (ff fe), and Power BI
# Desktop rejects the whole template with "Either the file is encrypted or corrupted":
#     Unexpected character encountered while parsing value: ...
#     ReportDocument BOM: System.Text.UTF8Encoding
# The original file starts 7b 00 ({ in UTF-16-LE) with no BOM, and that must be preserved.
members[LAY] = out.encode("utf-16-le")

# ---------------------------------------------------------------- 3. repack
tmp = SRC.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    # "Version" must stay first or Desktop rejects the template
    order = ["Version"] + [n for n in members if n != "Version"]
    for n in order:
        z.writestr(n, members[n])
tmp.replace(SRC)

print(f"\n  repositioned {total_moved} visuals in the template")
print(f"  {SRC.name}  {SRC.stat().st_size/1024:.0f} KB")

# ---------------------------------------------------------------- 4. verify
zt = zipfile.ZipFile(SRC)
chk = json.loads(zt.read(LAY).decode("utf-16"))
bad = 0
for sec in chk["sections"]:
    vcs = sec.get("visualContainers", [])
    for i, a in enumerate(vcs):
        for b in vcs[i + 1:]:
            ox = max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
            oy = max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
            if ox > 0 and oy > 0:
                bad += 1
print(f"  verification: {len(chk['sections'])} sections readable, {bad} overlaps")
zt.close()
