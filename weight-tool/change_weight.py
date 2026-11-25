#!/usr/bin/env python3
"""
change_weight.py — make a bolder (or thinner) copy of a TTF font.

    python3 change_weight.py In.ttf Out.ttf --v 28 --h 36 --style SemiBold --keep-advance

UNITS
    Every number here is in *font units*. A font is drawn on a grid of
    `unitsPerEm` squares per em (1000 for Wumpus Mono Pro, 2048 for Envy Code R). Stem widths,
    advance widths, V and H all use that grid. Pixels never appear in this
    script; an app scales the whole grid to the chosen font size when it draws
    the text.

V AND H
    V  is ADDED to the thickness of vertical strokes   (the upright of `l`).
    H  is ADDED to the thickness of horizontal strokes (the crossbar of `H`).
    A stem of 84 units with V=28 becomes 112 units. Negative values thin.

PIPELINE  (see each function's docstring for detail)
    load font
    for each glyph:   flatten -> embolden -> back to TrueType -> (fit in cell) -> metrics
                      (CFF/OTF fonts: the TrueType glyph is then converted to a
                       CFF charstring, so .otf in gives .otf out)
    drop hinting
    update weight class / style bits / names
    save

FORMATS
    .ttf (glyf outlines) and .otf (CFF outlines) are both accepted.  All the
    geometry is done on a format-neutral Skia path; only the first and last
    step differ.  CFF2 / variable fonts are not supported.
"""
import argparse
import sys

import pathops
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen


# --------------------------------------------------------------------------- #
#  Step 1: glyph outline  ->  Skia path
# --------------------------------------------------------------------------- #
def glyph_to_path(glyph_set, name):
    """Return the glyph's outline as a Skia path we can do geometry on.

    Composite glyphs (e.g. `é` = `e` + accent reference) are decomposed into
    plain contours first, so every glyph is treated as a flat shape.
    """
    recorder = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(recorder)          # record the drawing commands
    path = pathops.Path()
    recorder.replay(path.getPen())          # replay them into a Skia path
    return path


# --------------------------------------------------------------------------- #
#  Step 2: the actual weight change
# --------------------------------------------------------------------------- #
def embolden_path(path, v, h):
    """Grow (or shrink) a filled shape by v units horizontally and h vertically.

    How a round pen emboldens: tracing the outline with a round pen of
    diameter D and adding the ink to the fill pushes every edge out by D/2,
    so a stroke gets D thicker in every direction equally.

    We want different amounts in the two directions, so:
      1. stretch the shape vertically by v/h,
      2. trace it with a round pen of diameter v,
      3. squash it back by h/v.
    After squashing, the pen's ink is an ellipse v wide and h tall, so vertical
    stems grow by v and horizontal stems grow by h.

    Negative values subtract the pen's ink from the fill instead, thinning.
    """
    if v == 0 and h == 0:
        return path

    amount = v if v != 0 else h             # pen diameter
    sy = amount / h if h else 1.0           # vertical stretch factor

    # 1. stretch
    stretched = pathops.Path()
    path.draw(TransformPen(stretched.getPen(), (1, 0, 0, sy, 0, 0)))

    # 2. trace with a round pen
    ink = pathops.Path(stretched)
    ink.stroke(abs(amount), pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4.0)
    ink.convertConicsToQuads()

    if amount > 0:
        result = pathops.op(stretched, ink, pathops.PathOp.UNION, fix_winding=True)       # bolder
    else:
        result = pathops.op(stretched, ink, pathops.PathOp.DIFFERENCE, fix_winding=True)  # thinner
    result.convertConicsToQuads()

    # 3. squash back
    out = pathops.Path()
    result.draw(TransformPen(out.getPen(), (1, 0, 0, 1 / sy, 0, 0)))
    out.simplify(fix_winding=True)          # merge overlaps left by the union
    out.convertConicsToQuads()
    return out


# --------------------------------------------------------------------------- #
#  Step 3: Skia path  ->  TrueType glyph
# --------------------------------------------------------------------------- #
def path_to_glyph(path, x_shift):
    """Convert a Skia path back into a TrueType glyph, moved right by x_shift.

    TrueType only stores quadratic curves, so any cubic curves are converted
    (Cu2QuPen) with a maximum error of 1 unit.
    """
    tt_pen = TTGlyphPen(None)
    quad_pen = Cu2QuPen(tt_pen, max_err=1.0, reverse_direction=False)
    path.draw(TransformPen(quad_pen, (1, 0, 0, 1, x_shift, 0)))
    return tt_pen.glyph()


# --------------------------------------------------------------------------- #
#  Step 3b: keep the glyph inside its cell (monospace only)
# --------------------------------------------------------------------------- #
def fit_in_cell(glyph, orig_bounds, advance):
    """Make sure an emboldened glyph does not stick out of its fixed-width cell.

    The cell is `advance` units wide (600 in Wumpus, 1100 in Envy).  Emboldening pushes
    both edges out by V/2, so a glyph that filled its cell (em dash, `==`
    ligature) or had tiny side bearings (`ď`) would now overhang its neighbours.

    Works on the finished TrueType glyph (integer coordinates) so that curve
    conversion and rounding cannot push it back out afterwards.

    Limits:  left_limit  = 0        or the original xMin if that was < 0
             right_limit = advance  or the original xMax if that was > advance
    i.e. the cell, widened only where the SOURCE glyph already overhung by
    design (Ъ, Ω΄, Υ΄ in Wumpus).  We never make an overhang bigger, but we
    don't redesign those glyphs either.

      1. if the glyph is wider than right_limit - left_limit, squeeze it
         horizontally about its own centre (a few percent at most; stems lose
         1–3 units, invisible).  Height is untouched.
      2. if it still pokes past a limit on one side, slide it back in.

    Returns None, "squeezed" or "nudged".
    """
    if advance <= 0 or not glyph.numberOfContours:
        return None
    ox0, _, ox1, _ = orig_bounds
    left_limit = min(0, int(round(ox0)))
    right_limit = max(advance, int(round(ox1)))
    allowed = right_limit - left_limit
    status = None

    glyph.recalcBounds(None)
    # 1. squeeze (retry once with a 1-unit smaller target if rounding overshoots)
    for target in (allowed, allowed - 1):
        width = glyph.xMax - glyph.xMin
        if width <= allowed:
            break
        sx = target / width
        cx = (glyph.xMin + glyph.xMax) / 2
        glyph.coordinates.transform(((sx, 0), (0, 1)))
        glyph.coordinates.translate((cx * (1 - sx), 0))
        glyph.coordinates.toInt()
        glyph.recalcBounds(None)
        status = "squeezed"

    # 2. nudge
    dx = 0
    if glyph.xMin < left_limit:
        dx = left_limit - glyph.xMin
    elif glyph.xMax > right_limit:
        dx = right_limit - glyph.xMax
    if dx:
        glyph.coordinates.translate((dx, 0))
        glyph.recalcBounds(None)
        status = status or "nudged"
    return status


# --------------------------------------------------------------------------- #
#  Step 4: metrics
# --------------------------------------------------------------------------- #
def new_metrics(advance, glyph, v, keep_advance):
    """Return the (advance, left side bearing) for the emboldened glyph.

    The left side bearing MUST equal the outline's xMin: TrueType renderers
    shift the outline by (lsb - xMin), so a stale lsb would move the glyph
    sideways.  We therefore always read it back from the new outline.

    keep_advance=True   advance unchanged, glyph grew in place (monospace);
                        each side bearing is V/2 smaller than before.
    keep_advance=False  advance grows by V; the glyph was shifted right by V/2
                        so the side bearings stay the same (proportional font).
    """
    glyph.recalcBounds(None)
    lsb = glyph.xMin if glyph.numberOfContours else 0
    if keep_advance:
        return advance, lsb
    return max(0, int(round(advance + v))), lsb


# --------------------------------------------------------------------------- #
#  Step 4b: TrueType glyph  ->  CFF charstring  (OTF fonts only)
# --------------------------------------------------------------------------- #
def glyph_to_charstring(glyph, advance, private, global_subrs):
    """Re-encode a finished TrueType glyph as a CFF Type 2 charstring.

    The TrueType glyph holds integer coordinates and quadratic curves; the
    T2 pen converts each quadratic to an exact cubic, so nothing is lost and
    the cell-fitting done on the integer glyph is preserved.  The charstring
    is written without hints (the old hints described the old outline).
    """
    pen = T2CharStringPen(advance, None)
    glyph.draw(pen, None)                   # simple glyph: glyfTable unused
    return pen.getCharString(private=private, globalSubrs=global_subrs)


def finish_cff(font, v, h):
    """Update the CFF-wide numbers after every charstring has been replaced:
    the standard stem widths in the Private dict (hinting hints for the
    rasterizer) grow by V/H, and the FontBBox / head bbox are recomputed."""
    cff = font["CFF "].cff
    top = cff.topDictIndex[0]
    priv = top.Private
    for key, delta in (("StdVW", v), ("StdHW", h)):
        if hasattr(priv, key):
            setattr(priv, key, int(round(getattr(priv, key) + delta)))
    for key, delta in (("StemSnapV", v), ("StemSnapH", h)):
        if hasattr(priv, key):
            setattr(priv, key, [int(round(x + delta)) for x in getattr(priv, key)])

    cs = top.CharStrings
    boxes = [b for b in (cs[n].calcBounds(cs) for n in cs.keys()) if b]
    if boxes:
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
        top.FontBBox = [int(x0), int(y0), int(x1), int(y1)]
        head = font["head"]
        head.xMin, head.yMin, head.xMax, head.yMax = top.FontBBox


# --------------------------------------------------------------------------- #
#  Step 5: font-wide bookkeeping
# --------------------------------------------------------------------------- #
HINTING_TABLES = ("fpgm", "prep", "cvt ", "hdmx", "LTSH", "VDMX", "gasp", "DSIG")

STYLE_WEIGHTS = {"Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400,
                 "Medium": 500, "SemiBold": 600, "Bold": 700, "ExtraBold": 800, "Black": 900}
PANOSE_WEIGHTS = {100: 2, 200: 3, 300: 4, 400: 5, 500: 6, 600: 7, 700: 8, 800: 9, 900: 10}


def strip_hinting(font):
    """Delete hinting tables. Hints are instructions tied to the old outlines
    and would distort the new ones; renderers autohint instead."""
    for tag in HINTING_TABLES:
        if tag in font:
            del font[tag]


def set_weight_and_style_bits(font, style):
    """Set usWeightClass, PANOSE weight, fsSelection and macStyle from the
    style name, e.g. "SemiBold" -> 600, not bold-flagged (only >= 700 is)."""
    base_style = style.replace(" Italic", "").replace("Italic", "").strip() or "Regular"
    italic = "Italic" in style
    weight = STYLE_WEIGHTS.get(base_style.replace(" ", ""), 500)
    bold = weight >= 700

    os2 = font["OS/2"]
    os2.usWeightClass = weight
    if os2.panose.bWeight:                  # only touch PANOSE if it was filled in
        os2.panose.bWeight = PANOSE_WEIGHTS[weight]

    REGULAR, BOLD, ITALIC = 1 << 6, 1 << 5, 1 << 0
    os2.fsSelection &= ~(REGULAR | BOLD | ITALIC)
    if bold:
        os2.fsSelection |= BOLD
    if italic:
        os2.fsSelection |= ITALIC
    if not bold and not italic and base_style == "Regular":
        os2.fsSelection |= REGULAR

    font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    font["head"].flags |= 1 << 3            # "integer scaling" — fine after re-rounding
    return base_style, bold, italic


def set_names(font, style, base_style, bold, italic):
    """Rewrite the name table so the new file is its own style of the family.

    Legacy family/subfamily (IDs 1/2) may only say Regular/Bold/Italic/Bold Italic
    (the "RIBBI" rule), so non-RIBBI styles put the style in the family name:
        ID 1 "Wumpus Mono Pro SemiBold"   ID 2 "Regular"
    The typographic names (IDs 16/17) carry the real family/style:
        ID 16 "Wumpus Mono Pro"           ID 17 "SemiBold"
    """
    nm = font["name"]
    typo_family = nm.getDebugName(16) or nm.getDebugName(1) or "Font"

    ribbi = base_style in ("Regular", "Bold")
    legacy_family = typo_family if ribbi else f"{typo_family} {base_style}"
    legacy_sub = (("Bold" if bold else "Regular") + (" Italic" if italic else "")
                  ).replace("Regular Italic", "Italic")
    full_name = f"{typo_family} {style}".replace(" Regular", "") if style != "Regular" else typo_family
    ps_name = f"{typo_family.replace(' ', '')}-{style.replace(' ', '')}"
    old_unique = nm.getDebugName(3) or ""
    unique = old_unique.rsplit(";", 1)[0] + ";" + ps_name if ";" in old_unique else ps_name

    new_names = {1: legacy_family, 2: legacy_sub, 3: unique, 4: full_name, 6: ps_name,
                 16: typo_family, 17: style}
    for rec in list(nm.names):
        if rec.nameID in new_names:
            nm.removeNames(nameID=rec.nameID)
    for nid, val in new_names.items():
        nm.setName(val, nid, 3, 1, 0x409)   # Windows, Unicode BMP, en-US
        nm.setName(val, nid, 1, 0, 0)       # Macintosh, Roman, English


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def change_weight(src, dst, v, h, style, keep_advance=False):
    """Read `src`, embolden every glyph by v/h, update metadata, write `dst`."""
    font = TTFont(src)
    is_cff = "CFF " in font
    if is_cff:
        cff = font["CFF "].cff
        top = cff.topDictIndex[0]
        if hasattr(top, "FDArray"):
            raise ValueError("CID-keyed CFF fonts are not supported")
        charstrings, private, gsubrs = top.CharStrings, top.Private, cff.GlobalSubrs
    elif "glyf" in font:
        glyf = font["glyf"]
    else:
        raise ValueError("no glyf or CFF table: not a TrueType/OpenType font with outlines")
    hmtx = font["hmtx"]
    glyph_set = font.getGlyphSet()
    x_shift = 0.0 if keep_advance else v / 2.0

    fixed = {"squeezed": [], "nudged": []}
    for name in font.getGlyphOrder():
        if not is_cff and glyf[name].numberOfContours == 0 and not glyf[name].isComposite():
            continue                        # empty glyph (space etc.) — nothing to embolden

        adv, _ = hmtx[name]
        path = glyph_to_path(glyph_set, name)             # 1
        orig_bounds = path.bounds
        if orig_bounds is None:
            continue                        # no ink (CFF space etc.)
        path = embolden_path(path, v, h)                  # 2
        glyph = path_to_glyph(path, x_shift)              # 3
        if keep_advance:
            status = fit_in_cell(glyph, orig_bounds, adv) # 3b
            if status:
                fixed[status].append(name)
        hmtx[name] = new_metrics(adv, glyph, v, keep_advance)   # 4
        if is_cff:
            cs = glyph_to_charstring(glyph, hmtx[name][0], private, gsubrs)  # 4b
            charstrings[name] = cs
            # CFF bounds are the true curve extent, not the control points, so
            # re-read the lsb from the charstring to keep hmtx consistent.
            bounds = cs.calcBounds(charstrings)
            hmtx[name] = (hmtx[name][0], int(round(bounds[0])) if bounds else 0)
        else:
            glyf[name] = glyph

    if keep_advance:
        print(f"  kept inside cell: squeezed {len(fixed['squeezed'])} glyph(s) {fixed['squeezed'][:8]}{'…' if len(fixed['squeezed'])>8 else ''}, "
              f"nudged {len(fixed['nudged'])} {fixed['nudged']}")

    strip_hinting(font)                                   # 5
    if is_cff:
        finish_cff(font, v, h)
    base_style, bold, italic = set_weight_and_style_bits(font, style)
    set_names(font, style, base_style, bold, italic)

    font.recalcBBoxes = True
    font.save(dst)
    print(f"wrote {dst}  (V={v}, H={h}, style={style})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--v", type=float, default=40, help="units added to vertical stems")
    ap.add_argument("--h", type=float, default=None, help="units added to horizontal stems (default 0.75*V)")
    ap.add_argument("--style", default="Bold", help="style name to write (Medium, SemiBold, Bold, Black...)")
    ap.add_argument("--keep-advance", action="store_true",
                    help="keep advance widths unchanged (use for monospaced fonts)")
    a = ap.parse_args()
    h = a.h if a.h is not None else 0.75 * a.v
    try:
        change_weight(a.src, a.dst, a.v, h, a.style, a.keep_advance)
    except Exception as e:
        sys.exit(f"error: {e}")
