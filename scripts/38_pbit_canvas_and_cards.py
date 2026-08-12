"""
38_pbit_canvas_and_cards.py — tinted canvas, and tiles that read as tiles.

White visuals on a white canvas have no edges, so a report page reads as one undifferentiated
sheet: the eye cannot tell where one chart stops and the next begins, and the grouping that
the layout is trying to express is invisible.

The fix is the standard one and it is entirely about contrast between two surfaces:

    canvas    light blue-grey tint   #EDF1F7
    tile      white                  #FFFFFF   + hairline border + soft drop shadow

The tile is then the LIGHTEST thing on the page, which is what makes it appear to sit above
the canvas rather than be cut out of it. Doing it the other way round — white canvas, tinted
tiles — inverts the depth cue and the tiles look like holes.

Shadows are kept subtle. A heavy shadow on 90+ visuals turns into visual noise at the page
level even when each one looks fine in isolation.

Banner textboxes keep their own solid fills; they are meant to sit ON the canvas, not float
above it, so they get no shadow.
"""
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIT = ROOT / "powerbi" / "MerchantVoucherIntelligence.pbit"

CANVAS = "#EDF1F7"        # page background
TILE = "#FFFFFF"          # visual background — lighter than the canvas, deliberately
EDGE = "#D3DEEC"          # hairline border
SHADOW = "#12305B"        # navy-tinted shadow reads warmer than pure black on this palette


def L(v):
    return {"expr": {"Literal": {"Value": v}}}


def col(h):
    return {"solid": {"color": L(f"'{h}'")}}


def put(o, k, props):
    o.setdefault(k, [{}])[0].setdefault("properties", {}).update(props)


z = zipfile.ZipFile(PBIT)
members = {n: z.read(n) for n in z.namelist()}
names = z.namelist()
z.close()

layout = json.loads(members["Report/Layout"].decode("utf-16-le"))

pages = 0
tiles = 0
skipped = 0

for sec in layout.get("sections", []):
    # ---- page canvas -------------------------------------------------------------
    try:
        scfg = json.loads(sec.get("config") or "{}")
    except Exception:
        scfg = {}
    sobjs = scfg.setdefault("objects", {})
    put(sobjs, "background", {"color": col(CANVAS), "transparency": L("0D")})
    # outspace is the area around the canvas; matching it stops a white halo at the edges
    put(sobjs, "outspace", {"color": col(CANVAS), "transparency": L("0D")})
    sec["config"] = json.dumps(scfg, separators=(",", ":"))
    pages += 1

    for vc in sec.get("visualContainers", []):
        try:
            cfg = json.loads(vc["config"])
        except Exception:
            continue
        sv = cfg.get("singleVisual")
        if not sv:
            continue
        vt = sv.get("visualType", "")
        vobjs = sv.setdefault("vcObjects", {})

        # Textboxes are page furniture and are left entirely alone.
        #
        # An earlier version tried to be clever: read the existing fill, skip anything already
        # coloured, paint the rest white. It read the fill from one specific JSON path, and
        # where a band stored its colour in a different shape the lookup raised, the fill came
        # back None, the guard fell through — and every navy page banner was painted white.
        # The subtitle sitting on the band went opaque white on top of it too.
        #
        # There is no need to touch them at all. Banners carry their own fill from
        # 30_pbit_more_pages.py and the Insights blocks carry theirs from
        # 35_pbit_fill_insights.py. Anything this script does to a textbox can only undo a
        # decision another script already made deliberately.
        if vt == "textbox":
            skipped += 1
            continue

        put(vobjs, "background", {"show": L("true"), "color": col(TILE),
                                  "transparency": L("0D")})
        # Cards already carry a coloured accent border from 22_pbit_fonts.py. Only set a
        # border where one is not already defined, so that accent is not overwritten.
        if "border" not in vobjs:
            put(vobjs, "border", {"show": L("true"), "color": col(EDGE), "radius": L("8D")})
        else:
            put(vobjs, "border", {"show": L("true"), "radius": L("8D")})
        put(vobjs, "dropShadow", {"show": L("true"), "color": col(SHADOW),
                                  "position": L("'Outer'"), "preset": L("'BottomRight'"),
                                  "shadowSpread": L("3D"), "shadowBlur": L("7D"),
                                  "transparency": L("82D"), "angle": L("45D")})
        vc["config"] = json.dumps(cfg, separators=(",", ":"))
        tiles += 1

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

# The whole point is contrast between canvas and tile. If a page ended up with a canvas that
# is not darker than the tile, the depth cue is inverted and the styling has failed.
def lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


if lum(CANVAS) >= lum(TILE):
    raise SystemExit("canvas is not darker than the tile — tiles will read as holes")

def _bg(sv):
    """Background colour, checked in BOTH places Power BI stores it.

    This is the bug that made the original guard useless. Scripts 16 and 22 write a textbox
    fill to vcObjects.background; script 30 writes it to objects.background. Reading only one
    returned None for the other, the "skip coloured textboxes" test fell through, and six
    navy page banners were painted white.
    """
    for holder in ("vcObjects", "objects"):
        try:
            return str(sv[holder]["background"][0]["properties"]["color"]["solid"]["color"]
                       ["expr"]["Literal"]["Value"]).strip("'").upper()
        except Exception:
            continue
    return None


white_bands = []
for sec in chk["sections"]:
    for vc in sec["visualContainers"]:
        cfg = json.loads(vc["config"])
        sv = cfg.get("singleVisual") or {}
        if sv.get("visualType") == "textbox" and str(cfg.get("name", "")).endswith("Band"):
            if _bg(sv) in ("#FFFFFF", "FFFFFF"):
                white_bands.append(f"{sec.get('displayName')}/{cfg.get('name')}")
if white_bands:
    raise SystemExit("page banners painted white — they must keep their own fill: "
                     + ", ".join(white_bands))

bad = [s.get("displayName") for s in chk["sections"]
       if "background" not in (json.loads(s.get("config") or "{}").get("objects") or {})]
if bad:
    raise SystemExit(f"pages with no canvas colour: {', '.join(bad)}")

shutil.copy2(PBIT, ROOT / "MerchantVoucherIntelligence_PowerBI" /
             "MerchantVoucherIntelligence.pbit")

print(f"  canvas {CANVAS} applied to {pages} pages")
print(f"  {tiles} tiles set white with a hairline border and a soft shadow")
print(f"  {skipped} textboxes left untouched — banners keep their own fills")
print(f"  contrast check: canvas lum {lum(CANVAS):.3f} < tile lum {lum(TILE):.3f}")
print(f"  encoding verified · {PBIT.stat().st_size/1024:.0f} KB")
