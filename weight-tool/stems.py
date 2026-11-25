#!/usr/bin/env python3
"""
stems.py — measure the stem thickness of a TTF.

    python3 stems.py Font.ttf [More.ttf ...]

Prints, for each font, the width of the upright stroke of `l` (vertical stem)
and the thickness of the crossbar of `H` (horizontal stem), in font units, plus
the em size so the two can be compared across fonts.

Also importable: measure(font) -> (vertical_stem, horizontal_stem), either may
be None if the glyph is missing or the scan finds no ink.
"""
import sys

import pathops
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen


def _runs(glyph_set, name, horizontal):
    """Scan a line through the middle of a glyph and return the lengths of the
    filled runs it crosses.  horizontal=True scans left→right at mid-height,
    False scans bottom→top at mid-width."""
    rec = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(rec)
    p = pathops.Path()
    rec.replay(p.getPen())
    if p.bounds is None:
        return []
    x0, y0, x1, y1 = p.bounds
    if horizontal:
        pts = [(x + .5, (y0 + y1) / 2) for x in range(int(x0) - 2, int(x1) + 3)]
    else:
        pts = [((x0 + x1) / 2, y + .5) for y in range(int(y0) - 2, int(y1) + 3)]
    out, inside, start = [], False, 0
    for i, pt in enumerate(pts):
        c = p.contains(pt)
        if c and not inside:
            start, inside = i, True
        if not c and inside:
            out.append(i - start)
            inside = False
    return out


def measure(font):
    """(vertical stem of `l`, horizontal stem of `H`) in font units, or None."""
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    def stem(ch, horizontal):
        name = cmap.get(ord(ch))
        if not name:
            return None
        runs = _runs(gs, name, horizontal)
        return runs[0] if runs else None
    return stem("l", True), stem("H", False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for fp in sys.argv[1:]:
        f = TTFont(fp)
        v, h = measure(f)
        upem = f["head"].unitsPerEm
        print(f"{fp:40s} {upem:5d}/em   l stem={v}   H crossbar={h}")
