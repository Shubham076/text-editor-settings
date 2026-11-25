#!/usr/bin/env bash
# Build heavier weights of a monospaced TTF or OTF from its Regular.
#
#   ./make_weights.sh path/to/Regular.ttf               # Medium + SemiBold
#   ./make_weights.sh path/to/Regular.ttf Medium        # only the styles you list
#   ./make_weights.sh path/to/Regular.ttf Medium Bold Black
#   ./make_weights.sh path/to/Regular.ttf Medium=10/10  # own percentages: +10% V, +10% H
#   OUT_DIR=out ./make_weights.sh path/to/Regular.ttf  # write somewhere else
#
# Output files are named after the font's PostScript name, e.g.
# WumpusMonoPro-Medium.ttf, EnvyCodeRVS-Medium.ttf, and written to OUT_DIR
# (default: the folder this script lives in).
#
# HOW THE WEIGHT IS CHOSEN
#   The recipe below is in PERCENT OF THE SOURCE FONT'S OWN STEMS, so it adapts
#   to any Regular: the script measures the upright of `l` (vertical stem) and
#   the crossbar of `H` (horizontal stem) with stems.py, then adds V% / H% of
#   those.  A font with 84u stems gets +16u for Medium, one with 158u stems
#   gets +30u.  Append =V/H to a style to use other percentages for this run
#   only (Medium=10/10), e.g. for a font whose cells are tight.  If `l` or `H`
#   cannot be measured it falls back to the FALLBACK table, in units per
#   1000 em, scaled to the font's unitsPerEm.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${OUT_DIR:-$HERE}"

[ $# -ge 1 ] || { sed -n '2,10p' "$0"; exit 1; }
IN="$1"; shift
EXT="${IN##*.}"; EXT="$(echo "$EXT" | tr 'A-Z' 'a-z')"   # ttf in -> ttf out, otf in -> otf out
STYLES=("$@")                        # remaining arguments: styles to build
[ ${#STYLES[@]} -eq 0 ] && STYLES=(Medium SemiBold)
mkdir -p "$OUT_DIR"

# Install the two Python libraries the engine needs, if they are missing.
python3 -c "import fontTools, pathops" 2>/dev/null || pip install --quiet fonttools skia-pathops

# Recipe: percent added to the vertical / horizontal stems of the source.
#   Medium   +19 / +19   monolinear, like the Regular
#   SemiBold +33 / +43
#   Bold     +48 / +38
#   Black    +62 / +50
declare -A PCT_V=( [Medium]=19 [SemiBold]=33 [Bold]=48 [Black]=62 )
declare -A PCT_H=( [Medium]=19 [SemiBold]=43 [Bold]=38 [Black]=50 )
# Fallback when stems cannot be measured: units per 1000 em (≈ the recipe
# applied to an 84u stem).
declare -A FB_V=( [Medium]=16 [SemiBold]=28 [Bold]=40 [Black]=52 )
declare -A FB_H=( [Medium]=16 [SemiBold]=36 [Bold]=32 [Black]=42 )

# Read output basename, em size and measured stems from the source font.
read -r BASE UPEM STEM_V STEM_H < <(cd "$HERE" && python3 - "$IN" <<'PY'
import sys, re, os
from fontTools.ttLib import TTFont
from stems import measure
f = TTFont(sys.argv[1]); n = f["name"]
ps = n.getDebugName(6) or n.getDebugName(16) or n.getDebugName(1) or os.path.basename(sys.argv[1])
ps = re.sub(r"[-\s].*$", "", ps)            # "WumpusMonoPro-Regular" -> "WumpusMonoPro"
v, h = measure(f)
print(re.sub(r"[^A-Za-z0-9]", "", ps), f["head"].unitsPerEm, v or 0, h or 0)
PY
)
echo "source : $IN"
echo "         ${UPEM} units/em, l stem=${STEM_V}u, H crossbar=${STEM_H}u, output ${OUT_DIR}/${BASE}-<Style>.${EXT}"

# gen STYLE[=V%/H%]
#   Builds one weight.  Works out how many font units to add to the stems,
#   runs the engine once, then prints what it wrote so mistakes are visible.
gen() {
  local arg="$1"                       # e.g. "Medium"  or  "Medium=10/10"
  local style="${arg%%=*}"             # "Medium"  (everything before '=')
  local out_file="$OUT_DIR/${BASE}-${style}.${EXT}"
  local percent_v percent_h            # percent to add to vertical / horizontal stems
  local add_v add_h                    # the same, converted to font units for THIS font

  [[ -v PCT_V[$style] ]] || { echo "unknown style '$style' (known: ${!PCT_V[*]})" >&2; exit 1; }

  # 1. Which percentages?  Given after '=' (Medium=10/10), else from the recipe table.
  if [[ "$arg" == *=* ]]; then
    local given="${arg#*=}"            # "10/10"
    percent_v="${given%%/*}"           # "10"  (before the slash)
    percent_h="${given#*/}"            # "10"  (after the slash)
  else
    percent_v="${PCT_V[$style]}"
    percent_h="${PCT_H[$style]}"
  fi

  # 2. Percent -> font units.  The engine only understands units, so multiply
  #    by the stem thickness measured in this font:  158u * 10 / 100 = 16u.
  if [ "$STEM_V" -gt 0 ] && [ "$STEM_H" -gt 0 ]; then
    add_v=$(python3 -c "print(round($STEM_V * $percent_v / 100))")
    add_h=$(python3 -c "print(round($STEM_H * $percent_h / 100))")
    echo "== $style  (+$percent_v% of ${STEM_V}u / +$percent_h% of ${STEM_H}u  ->  V=$add_v H=$add_h)"
  else
    # Stems could not be measured: use the per-1000-em table, scaled to this em.
    add_v=$(python3 -c "print(round(${FB_V[$style]} * $UPEM / 1000))")
    add_h=$(python3 -c "print(round(${FB_H[$style]} * $UPEM / 1000))")
    echo "== $style  (stems not measurable, fallback table  ->  V=$add_v H=$add_h)"
  fi

  # 3. Run the engine.  --keep-advance: do not widen the cells, the font must stay monospaced.
  python3 "$HERE/change_weight.py" "$IN" "$out_file" --v "$add_v" --h "$add_h" --style "$style" --keep-advance

  # 4. Summary of what ended up in the file.
  python3 - "$out_file" <<'PY'
import sys
from fontTools.ttLib import TTFont
f = TTFont(sys.argv[1]); n = f["name"]; o = f["OS/2"]
print(f"  family/sub : {n.getDebugName(1)!r} / {n.getDebugName(2)!r}")
print(f"  typo       : {n.getDebugName(16)!r} / {n.getDebugName(17)!r}")
print(f"  full / ps  : {n.getDebugName(4)!r} / {n.getDebugName(6)!r}")
print(f"  weightClass: {o.usWeightClass}   fsSelection: {o.fsSelection:#010b}   macStyle: {f['head'].macStyle}")
print(f"  advances   : {sorted(set(a for a,_ in f['hmtx'].metrics.values()))}")   # must be multiples of the cell
PY
}

for style_arg in "${STYLES[@]}"; do gen "$style_arg"; done
