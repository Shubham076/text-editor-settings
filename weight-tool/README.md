# weight-tool

Generates heavier weights of a **monospaced TTF or OTF** from its Regular,
without touching the monospace grid. Works on any Regular: the recipe is expressed as a
percentage of the source font's own stem thickness, which the script measures.

```
Any-Regular.ttf  ──►  make_weights.sh  ──►  <PSName>-Medium.ttf
                                        └─►  <PSName>-SemiBold.ttf
```

| File               | Role |
|--------------------|------|
| `change_weight.py` | The engine. Emboldens one TTF/OTF by a given amount (font units) and writes a new one in the same format. |
| `stems.py`         | The ruler. Measures the `l` stem and `H` crossbar of a TTF. |
| `make_weights.sh`  | The recipe. Measures the source, turns percentages into units, calls the engine once per weight and prints a summary. |

## Usage

```bash
./make_weights.sh path/to/Regular.ttf                 # Medium + SemiBold
./make_weights.sh path/to/Regular.ttf Medium          # only the styles you list
./make_weights.sh path/to/Regular.ttf Medium Bold Black
./make_weights.sh path/to/Regular.ttf Medium=10/10    # own percentages: +10% V, +10% H
OUT_DIR=out ./make_weights.sh path/to/Regular.ttf     # write somewhere else
```

Output files are named after the font's PostScript name, keep the input's
extension (`.ttf` in gives `.ttf` out, `.otf` gives `.otf`) and are written
next to the script unless `OUT_DIR` is set. Known styles: `Medium`, `SemiBold`, `Bold`,
`Black`. Dependencies (`fonttools`, `skia-pathops`) are installed
automatically if missing.

### Per-font commands

| Font | Command | Output |
|------|---------|--------|
| Wumpus Mono Pro | `./make_weights.sh WumpusMonoPro-Regular.ttf` | `WumpusMonoPro-Medium.ttf`, `WumpusMonoPro-SemiBold.ttf` |
| Envy Code R VS (installed copy) | `./make_weights.sh ~/Library/Fonts/Envy\ Code\ R\ VS.ttf Medium=15/15` | `EnvyCodeRVS-Medium.ttf` (+15%, see below) |
| Miosevka (Iosevka build) | `OUT_DIR=~/Downloads/Fonts/Miosevka16 ./make_weights.sh ~/Downloads/Fonts/Miosevka16/Miosevka-Regular.ttf Medium` | `Miosevka-Medium.ttf` next to the Regular |
| Riosevka (Iosevka build) | `OUT_DIR=~/Downloads/Fonts/Miosevka16 ./make_weights.sh ~/Downloads/Fonts/Miosevka16/Riosevka-Regular.ttf Medium` | `Riosevka-Medium.ttf` next to the Regular |
| Codelia (OTF, CFF outlines) | `./make_weights.sh Codelia-Regular.otf Medium=15/15` | `Codelia-Medium.otf` |
| Any other Regular | `./make_weights.sh path/to/Font-Regular.ttf [styles…]` | `<PSName>-<Style>.ttf` |

To install a result on macOS, copy the TTF into `~/Library/Fonts/`. To measure
what you got:

```bash
python3 stems.py WumpusMonoPro-Regular.ttf WumpusMonoPro-Medium.ttf EnvyCodeRVS-Medium.ttf
```

The engine can also be called directly with absolute units, for a one-off:

```bash
python3 change_weight.py In.ttf Out.ttf --v 16 --h 16 --style Medium --keep-advance
```

## Units

A font is drawn on a square grid, like graph paper. Each font picks its own
grid size (`head.unitsPerEm`): Wumpus Mono Pro uses **1000 squares per em**,
Envy Code R uses **2048**. Every number in a font file and in these scripts is a
count of those squares, so numbers are only comparable across fonts after
dividing by the em:

| Thing | Wumpus Mono Pro (1000/em) | Envy Code R VS (2048/em) |
|---|---|---|
| width of the upright stroke of `l` (Regular) | 84 | 158 |
| cap height | 700 | 1422 |
| x-height | 500 | 1106 |
| advance width of every normal glyph | 600 | 1100 |
| `V`, `H` | whatever you pass in | whatever you pass in |

This is why `make_weights.sh` works in percent of the measured stem rather
than in fixed units.

There are **no pixels anywhere in the scripts**. When an app draws text at
14 px it scales the whole 1000-unit grid down to 14 px, and everything on it
shrinks together. You only ever think in grid units when editing the font.

## The cell

Each glyph lives in a **cell as wide as its advance width** (600 units in
Wumpus, 1100 in Envy). That is the horizontal grid of a monospaced font. The
em is only the vertical scale; it is not the cell. Vertically, glyphs may and do extend past the em
(descenders, accents) in the Regular already, and that is normal.

Horizontally the rule is: **an emboldened glyph never sticks out of its cell
further than the Regular did.** Emboldening pushes both edges out by `V/2`,
so glyphs that filled the cell (em dash, `==` ligature) or had tiny side
bearings (`ď`) would otherwise overhang their neighbours. The `fit_in_cell`
step squeezes those few glyphs horizontally by a few percent and slides any
that poke out on one side back in. Glyphs that overhang in the Regular by
design (`Ъ`, `Ω΄`, `Υ΄` in Wumpus) are kept at their original overhang, not
widened and not redesigned. Box-drawing glyphs that fill the cell edge to edge
are squeezed back to exactly the cell, so they still join up with their
neighbours.

## The two knobs: V and H

Both are **added** to stroke thickness (not multiplied):

| Knob | Affects | Example (stem of 84u) |
|------|---------|-----------------------|
| `V`  | vertical stems: `l`, `H` uprights, `n` legs | `V=16` → 100u |
| `H`  | horizontal stems: `H` crossbar, `n` arch, top/bottom of `o` | `H=16` → 100u |

Diagonals and curves get a blend of the two. Counters (the holes in `o`, `e`,
`a`) shrink by the same amount the strokes grow.

`make_weights.sh` states the recipe in **percent of the source stems** and
converts to units per font after measuring them with `stems.py`:

| Style    | +V % | +H % | Wumpus (84u stems) V/H → stems | Envy (158u stems) V/H → stems | Notes |
|----------|------|------|--------------------------------|-------------------------------|-------|
| Regular  | –    | –    | – → 84 / 84                    | – → 158 / 158                 | source |
| Medium   | 19   | 19   | 16/16 → 100 / 100              | 30/30 → 188 / 188 (built at 15/15 → 182) | monolinear like the Regular |
| SemiBold | 33   | 43   | 28/36 → 112 / 120              | 52/68 → 210 / 226             | |
| Bold     | 48   | 38   | 40/32 → 124 / 116              | 76/60 → 234 / 218             | untested starting point |
| Black    | 62   | 50   | 52/42 → 136 / 126              | 98/79 → 256 / 237             | untested starting point |

Appending `=V/H` to a style name replaces the percentages for that run only,
without touching the shared recipe. Envy Code R is built with `Medium=15/15`
(V=H=24 → 182u stems): its glyphs sit tight in their 1100u cell, so a gentler
step was chosen for it. With the default +19% it would be 188u.

If `l` or `H` cannot be measured (missing glyph), the script falls back to the
Wumpus unit values scaled by `unitsPerEm / 1000`.

## Pseudo-logic

### `make_weights.sh`

```
IN     = first argument (required)
STYLES = remaining arguments, or [Medium, SemiBold]
OUT_DIR from the environment, or the script's folder

ensure python modules fontTools and pathops import, else pip install them

BASE  = PostScript name of IN with the style stripped   ("EnvyCodeRVS")
UPEM  = IN.head.unitsPerEm
STEM_V, STEM_H = stems.measure(IN)                      # l upright, H crossbar

gen(STYLE[=V%/H%]):
    PCT = the percentages after '=' if given, else PCT_V/PCT_H[STYLE]
    if stems measured:  V = STEM_V * PCT_V / 100
                        H = STEM_H * PCT_H / 100
    else:               V = FALLBACK_V[STYLE] * UPEM / 1000   (same for H)
    OUT = OUT_DIR / BASE-<STYLE>.ttf
    run  change_weight.py IN OUT --v V --h H --style STYLE --keep-advance
    open OUT and print: family / subfamily names, weight class,
                        style flags, set of distinct advance widths

for STYLE in STYLES: gen(STYLE)
```

### `stems.py`

```
measure(font):
    l = glyph for U+006C, H = glyph for U+0048   (via the cmap)
    vertical stem   = length of the first filled run when scanning a
                      horizontal line through the middle of `l`
    horizontal stem = length of the first filled run when scanning a
                      vertical line through the middle of `H`
    return (vertical, horizontal), None where the glyph is missing
```

### `change_weight.py`

```
load the source font

for each glyph in the font:
    skip if it has no outline (space, control chars)

    path  = glyph_to_path(glyph)          # 1. flatten composites, load into Skia
    path  = embolden_path(path, V, H)     # 2. the weight change (see below)
    glyph = path_to_glyph(path, x_shift)  # 3. back to TrueType quadratics
    if --keep-advance:
        fit_in_cell(glyph, original bounds, advance)   # 3b. never leave the cell
    hmtx  = new_metrics(adv, glyph, V, keep_advance)   # 4. advance / side bearing

        x_shift = 0           if --keep-advance   (glyph grows in place)
                = V/2         otherwise           (glyph moves right)
        advance = old advance if --keep-advance
                = old + V     otherwise
        lsb     = the new outline's xMin, always  (renderers shift a glyph by
                  lsb - xMin, so a stale lsb would move it sideways)

strip_hinting(font)
    delete fpgm, prep, cvt, hdmx, LTSH, VDMX, gasp, DSIG
    – hints were written for the old outlines

set_weight_and_style_bits(font, style)
    OS/2.usWeightClass from the style name  (Medium=500, SemiBold=600, Bold=700 …)
    PANOSE weight to match, if PANOSE was filled in
    fsSelection / macStyle bold+italic bits (only >= 700 counts as bold)

set_names(font, style)
    rewrite name records:
    nameID 1  legacy family     "Wumpus Mono Pro SemiBold"   (RIBBI rule: only
    nameID 2  legacy subfamily  "Regular"                     Regular/Bold/Italic
    nameID 4  full name         "Wumpus Mono Pro SemiBold"    may live in ID 2)
    nameID 6  PostScript name   "WumpusMonoPro-SemiBold"
    nameID 16 typographic family    "Wumpus Mono Pro"
    nameID 17 typographic subfamily "SemiBold"
    nameID 3  unique id          old prefix + ";" + PostScript name

recalculate bounding boxes and save
```

### `embolden_path(path, V, H)`

The trick: one round pen gives an isotropic offset. To get a different amount
horizontally and vertically, stretch the outline first so the pen becomes an
ellipse.

```
if V == 0 and H == 0: return path unchanged

sy = V / H

scale the path vertically by sy          # now a round pen of width V
                                         # covers V horizontally, H vertically
stroke = copy of path, stroked with a round pen of diameter |V|
         (round caps, round joins)

if V > 0:   result = path UNION stroke        # bolder
else:       result = path MINUS stroke        # thinner

scale result vertically by 1/sy          # undo the stretch
simplify (remove overlaps, fix winding)
convert conics to quadratics
return result
```

Effect on a stroke: every outline edge moves outward by `V/2` left and right and
by `H/2` up and down, so a vertical stem grows by `V` and a horizontal stem by `H`.

### `fit_in_cell(glyph, original_bounds, advance)`

```
left_limit  = 0        or original xMin if that was already < 0
right_limit = advance  or original xMax if that was already > advance
allowed     = right_limit - left_limit          # the cell, widened only where
                                                # the Regular already overhung
if glyph width > allowed:
    squeeze horizontally about the glyph's centre by allowed / width
    (retry with a 1-unit smaller target if integer rounding overshoots)

if glyph pokes past left_limit or right_limit:
    slide it back inside
```

Typical effect: a dozen glyphs squeezed by 1–4 %, stems 1–3 units lighter
than the rest, not visible. Everything else is untouched.

## TTF vs OTF

A `.ttf` stores outlines as quadratic curves in a `glyf` table; a `.otf`
stores them as cubic curves in a `CFF ` table. Everything in between (Skia
path, emboldening, cell fitting) is format-neutral, so only the first and last
step differ:

```
                      TTF                         OTF
read    glyph_to_path  glyf glyph -> Skia path    CFF charstring -> Skia path
write   path_to_glyph  Skia path -> glyf glyph    Skia path -> glyf glyph -> T2 charstring
```

For OTF the finished integer TrueType glyph is re-encoded as a Type 2
charstring (`glyph_to_charstring`); each quadratic becomes an exact cubic, so
the cell fitting is preserved. The charstrings are written without hints, and
`finish_cff` bumps the CFF `StdVW`/`StdHW` stem hints by V/H and recomputes
the FontBBox. CID-keyed CFF and CFF2/variable fonts are rejected.

## Why the font stays monospaced

Outline and advance width are stored separately in a TrueType font. With
`--keep-advance` the advance for every glyph is copied through unchanged, so the
advance widths of the Regular (600 / 1200 / 1800 / 2400 / 0 in Wumpus, 1100 / 0
in Envy) appear identically in every generated weight. The glyph grows symmetrically inside its fixed cell, so
each sidebearing shrinks by `V/2`, and `fit_in_cell` guarantees nothing grows
past the cell edge (see "The cell").

Without `--keep-advance` (for a proportional font) the advance grows by `V` and
the glyph is shifted right by `V/2` so the sidebearings stay the same.

## Checking the result

`stems.py` scans a horizontal line through the middle of `l` and reports the
filled run (the vertical stem), and a vertical line through the middle of `H`
for the crossbar:

```bash
python3 stems.py WumpusMonoPro-Regular.ttf WumpusMonoPro-Medium.ttf WumpusMonoPro-SemiBold.ttf
python3 stems.py ~/Library/Fonts/Envy\ Code\ R\ VS.ttf EnvyCodeRVS-Medium.ttf
```

```
WumpusMonoPro-Regular.ttf    1000/em   l stem=84    H crossbar=84
WumpusMonoPro-Medium.ttf     1000/em   l stem=100   H crossbar=100
WumpusMonoPro-SemiBold.ttf   1000/em   l stem=112   H crossbar=120
Envy Code R VS.ttf           2048/em   l stem=158   H crossbar=158
EnvyCodeRVS-Medium.ttf       2048/em   l stem=182   H crossbar=182
```

## Limits

- Hinting is dropped (TrueType instructions, or CFF charstring hints). Modern
  rasterizers autohint, so this is rarely visible.
- Large `V` eats sidebearings (`V/2` per side). Past the Bold range more glyphs
  hit the cell edge and get squeezed; the script prints how many. If the list
  grows long the weight is too heavy for the cell. Fonts with tight sidebearings
  (Envy Code R: ~155u on a 1100u cell) hit this earlier than Wumpus.
- Fonts with thousands of glyphs (Iosevka builds have ~11,600) take a few
  minutes and report over a thousand squeezed/nudged glyphs. That is the
  box-drawing, block and legacy-computing ranges, which fill the cell by
  design; the squeeze is under 3% and no ASCII glyph is touched.
- Only `l` and `H` are measured. A font whose `l` has a tail or whose `H` has an
  unusual crossbar may measure wrong; check the printed stems and, if needed,
  call `change_weight.py` directly with hand-picked `--v/--h`.
- Thin strokes get relatively bolder than thick ones because the change is
  additive. Near-monolinear fonts like Wumpus and Envy are not affected.
- Small counters (eye of `e`, `a`) close up at high values.
