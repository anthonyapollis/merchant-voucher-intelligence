"""
21_pbit_isolate.py — build four .pbit variants to isolate what Power BI is rejecting.

The error ("Either the file is encrypted or corrupted" / "Invalid report document format")
names no part and no line, so guessing is expensive. Each variant below changes exactly one
thing on top of the pristine original. Whichever is the FIRST to fail identifies the cause.

  test_1_repack_only   unzipped and rezipped, nothing altered
                       -> if this fails, the problem is my zip/encoding round-trip
  test_2_theme_only    original layout, my theme
                       -> if this fails, the theme JSON is the problem
  test_3_layout_only   original theme, my repositioning
                       -> if this fails, the layout rewrite is the problem
  test_4_full          theme + layout + the three new pages
                       -> if only this fails, the new pages are the problem
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PB = ROOT / "powerbi"
ORIG = PB / "_MerchantVoucherIntelligence.original.pbit"
OUT = PB / "_isolation_tests"
OUT.mkdir(exist_ok=True)
THEME_SRC = (PB / "MerchantVoucherIntelligence.Report" / "StaticResources" /
             "RegisteredResources" / "MerchantVoucherIntelligence.json")

THEME_KEY = "Report/StaticResources/RegisteredResources/MerchantVoucherIntelligence.json"
LAY = "Report/Layout"


def read_pbit(p):
    z = zipfile.ZipFile(p)
    m = {n: z.read(n) for n in z.namelist()}
    order = z.namelist()
    z.close()
    return m, order


def write_pbit(members, order, dest):
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, members[n])
    tmp.replace(dest)
    return dest


def enc(obj):
    """UTF-16-LE, no BOM — what Power BI writes and the only thing it accepts."""
    return json.dumps(obj, separators=(",", ":")).encode("utf-16-le")


def reflow(layout):
    CANVAS_W, M, G = 1280, 16, 12
    H = {"textbox": 44, "card": 104, "slicer": 76, "actionButton": 44, "shape": 44,
         "image": 120, "multiRowCard": 150}

    def vh(vt):
        if vt in H:
            return H[vt]
        if vt in ("tableEx", "pivotTable", "matrix"):
            return 300
        if vt in ("shapeMap", "map", "filledMap"):
            return 470
        return 268

    for sec in layout.get("sections", []):
        vcs = sec.get("visualContainers", [])
        if not vcs or (sec.get("width", 0) or 0) < 700:
            continue
        parsed = []
        for vc in vcs:
            try:
                cfg = json.loads(vc["config"])
            except Exception:
                cfg = {}
            parsed.append((vc, cfg, (cfg.get("singleVisual") or {}).get("visualType", "")))
        parsed.sort(key=lambda t: (round((t[0].get("y") or 0) / 40), t[0].get("x") or 0))
        rows, cur, last = [], [], None
        for it in parsed:
            band = round((it[0].get("y") or 0) / 40)
            if last is not None and band != last:
                rows.append(cur); cur = []
            cur.append(it); last = band
        if cur:
            rows.append(cur)
        y = M
        for row in rows:
            n = len(row)
            avail = CANVAS_W - 2 * M - (n - 1) * G
            tot = sum((vc.get("width") or 1) for vc, _, _ in row) or 1
            h = max(vh(vt) for _, _, vt in row)
            x = M
            for i, (vc, cfg, vt) in enumerate(row):
                w = int(avail * (vc.get("width") or 1) / tot) if n > 1 else avail
                if i == n - 1:
                    w = CANVAS_W - M - x
                vc["x"], vc["y"], vc["width"], vc["height"] = x, y, w, h
                lays = cfg.get("layouts")
                if isinstance(lays, list) and lays:
                    pos = lays[0].setdefault("position", {})
                    pos.update({"x": x, "y": y, "width": w, "height": h,
                                "z": pos.get("z", vc.get("z", 0))})
                    vc["config"] = json.dumps(cfg, separators=(",", ":"))
                x += w + G
            y += h + G
        sec["width"], sec["height"] = CANVAS_W, max(860, y + M)
    return layout


print("Building isolation variants from the pristine original\n")

m, o = read_pbit(ORIG)
p = write_pbit(m, o, OUT / "test_1_repack_only.pbit")
print(f"  test_1_repack_only.pbit    {p.stat().st_size/1024:>5.0f} KB  (nothing changed)")

m, o = read_pbit(ORIG)
m[THEME_KEY] = THEME_SRC.read_bytes()
p = write_pbit(m, o, OUT / "test_2_theme_only.pbit")
print(f"  test_2_theme_only.pbit     {p.stat().st_size/1024:>5.0f} KB  (my theme)")

m, o = read_pbit(ORIG)
m[LAY] = enc(reflow(json.loads(m[LAY].decode("utf-16-le"))))
p = write_pbit(m, o, OUT / "test_3_layout_only.pbit")
print(f"  test_3_layout_only.pbit    {p.stat().st_size/1024:>5.0f} KB  (my repositioning)")

shutil.copy2(PB / "MerchantVoucherIntelligence.pbit", OUT / "test_4_full.pbit")
print(f"  test_4_full.pbit           "
      f"{(OUT / 'test_4_full.pbit').stat().st_size/1024:>5.0f} KB  (theme + layout + 3 pages)")

print("\nOpen them in order. The FIRST that fails names the cause:")
print("  1 fails -> my zip/encoding round-trip")
print("  2 fails -> the theme JSON")
print("  3 fails -> the layout rewrite")
print("  4 only  -> the three new pages")
print(f"\n  {OUT}")
