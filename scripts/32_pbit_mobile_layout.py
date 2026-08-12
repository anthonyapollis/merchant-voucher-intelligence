"""
32_pbit_mobile_layout.py — phone layout for every page of the .pbit.

There are two Power BI artifacts in this project and they had drifted apart:

    powerbi/MerchantVoucherIntelligence.pbit          12 pages  <- the file that gets opened
    powerbi/MerchantVoucherIntelligence.Report/       8 pages   <- PBIR folder, .pbip format

Script 11 writes the phone layout into the PBIR folder only. That was fine when the two were
in step, but the pages added later went into the .pbit alone — so the delivered template had
NO phone layout on any page, while the build log happily reported "phone layout added to 8
pages". This writes it into the .pbit, which is what is actually shipped.

Power BI stores a phone layout as a second entry in each visualContainer's `layouts` array:
id 0 is the desktop canvas, id 1 is the 320x568 phone canvas. A visual with no id-1 entry is
simply absent from the phone view — which is the correct outcome for decorative banners, so
those are deliberately left out rather than stacked.
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

W, GUTTER = 320, 8
CARD_W = (W - GUTTER * 3) // 2      # two KPI tiles per row
FULL_W = W - GUTTER * 2
H_CARD, H_CHART, H_TABLE, H_TEXT = 90, 200, 260, 110

z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

layout = json.loads(members["Report/Layout"].decode("utf-16-le"))

pages = 0
placed = 0
skipped = 0

for sec in layout.get("sections", []):
    items = []
    for vc in sec.get("visualContainers", []):
        try:
            cfg = json.loads(vc["config"])
        except Exception:
            continue
        sv = cfg.get("singleVisual") or {}
        vt = sv.get("visualType", "")

        # A full-width coloured band is page furniture. On a 320px canvas it is noise, so it
        # is excluded from the phone view instead of consuming a row.
        is_band = vt == "textbox" and vc.get("width", 0) > 600 and vc.get("height", 0) < 60
        if is_band:
            skipped += 1
            continue
        items.append((vc, cfg, sv, vt))

    if not items:
        continue

    # Preserve the reading order of the desktop page: top to bottom, then left to right.
    items.sort(key=lambda it: (round(it[0].get("y", 0) / 40), it[0].get("x", 0)))

    y = GUTTER
    i = 0
    while i < len(items):
        vc, cfg, sv, vt = items[i]
        card = vt in ("card", "kpi")
        nxt = items[i + 1] if i + 1 < len(items) else None
        pair = card and nxt and nxt[3] in ("card", "kpi")

        if pair:
            for j, (v, c, _s, _t) in enumerate((items[i], nxt)):
                c.setdefault("layouts", [])
                c["layouts"] = [l for l in c["layouts"] if l.get("id") != 1]
                c["layouts"].append({"id": 1, "position": {
                    "x": GUTTER + j * (CARD_W + GUTTER), "y": y,
                    "width": CARD_W, "height": H_CARD, "z": placed}})
                v["config"] = json.dumps(c, separators=(",", ":"))
                placed += 1
            y += H_CARD + GUTTER
            i += 2
            continue

        h = (H_CARD if card else
             H_TABLE if vt in ("tableEx", "pivotTable", "matrix") else
             H_TEXT if vt == "textbox" else
             H_CHART)
        cfg.setdefault("layouts", [])
        cfg["layouts"] = [l for l in cfg["layouts"] if l.get("id") != 1]
        cfg["layouts"].append({"id": 1, "position": {
            "x": GUTTER, "y": y, "width": FULL_W, "height": h, "z": placed}})
        vc["config"] = json.dumps(cfg, separators=(",", ":"))
        placed += 1
        y += h + GUTTER
        i += 1

    pages += 1

members["Report/Layout"] = json.dumps(layout, separators=(",", ":")).encode("utf-16-le")

tmp = PBIT.with_suffix(".tmp")
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for n in names:
        zo.writestr(n, members[n])
tmp.replace(PBIT)

# ---------------------------------------------------------------- verify
zc = zipfile.ZipFile(PBIT)
for part in ("Report/Layout", "DataModelSchema"):
    if zc.read(part)[:2] in (b"\xff\xfe", b"\xfe\xff", b"\xef\xbb"):
        raise SystemExit(f"ENCODING ERROR: {part} has a BOM — template will not open")
chk = json.loads(zc.read("Report/Layout").decode("utf-16-le"))
zc.close()

no_phone = []
for sec in chk["sections"]:
    n = sum(1 for vc in sec["visualContainers"]
            if any(l.get("id") == 1 for l in json.loads(vc["config"]).get("layouts", [])))
    if n == 0:
        no_phone.append(sec["displayName"])
    # A phone visual wider than the canvas is clipped, which is the defect this whole
    # exercise exists to avoid — fail rather than ship it.
    for vc in sec["visualContainers"]:
        for l in json.loads(vc["config"]).get("layouts", []):
            if l.get("id") == 1:
                p = l["position"]
                if p["x"] + p["width"] > W:
                    raise SystemExit(f"phone visual overflows {W}px on {sec['displayName']}")
if no_phone:
    raise SystemExit(f"pages with no phone layout: {', '.join(no_phone)}")

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

print(f"  phone layout written to {pages} pages · {placed} visuals placed")
print(f"  {skipped} decorative banners excluded from the phone view")
print(f"  canvas {W}x568 · no visual exceeds the canvas width (checked)")
print(f"  encoding verified · {PBIT.stat().st_size/1024:.0f} KB")
