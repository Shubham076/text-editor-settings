#!/usr/bin/env python3
"""
JetBrains to rhun theme converter.

Reads JetBrains UI themes (*.theme.json, which point at an editor scheme via
"editorScheme") or bare editor schemes (*.xml / *.icls) and writes rhun
.theme files (https://github.com/vshvedov/rhun, runtime/themes/*.theme).

    ./jetbrains_to_rhun.py                          convert every theme in the default source dir
    ./jetbrains_to_rhun.py --kind light             only light themes
    ./jetbrains_to_rhun.py path/to/foo.theme.json   convert specific files or directories
    ./jetbrains_to_rhun.py -o out/ ...              write somewhere other than ./themes

Colors missing from a scheme fall back along a chain of related JetBrains keys,
then to colors derived from bg/fg, so every rhun key is always written.
"""

import argparse
import colorsys
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path.home() / "IdeaProjects/Dark-Themes/src/main/resources/themes"
DEFAULT_OUT = HERE / "themes"

# rhun's built-in theme ids (runtime/themes/*.theme). User themes are keyed by
# file stem, so a converted theme with one of these ids gets a "-jb" suffix.
RHUN_BUILTINS = set("""
    ayu-light catppuccin-latte catppuccin-mocha dracula elflord-dark elflord-light ethereal
    everforest flexoki-light github-dark github-light gruvbox-dark gruvbox-light hackerman
    kanagawa last-horizon lumon lupine matte-black miasma min-dark min-light monokai nord
    one-dark one-light osaka-jade retro-82 rhun-dark rhun-light ristretto rose-pine-dawn
    rose-pine solarized-dark solarized-light solitude tokyo-night turbo-pascal vantablack white
""".split())


# ---------------------------------------------------------------- color utils

def norm_hex(value):
    """IntelliJ writes colors without '#' and strips leading zeros ("ff" is #0000ff)."""
    if not value:
        return None
    value = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{1,8}", value):
        return None
    if len(value) == 8:  # RRGGBBAA, drop alpha
        value = value[:6]
    return "#" + value.zfill(6).lower()


def to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    """Blend a toward b by t (0..1)."""
    ra, rb = to_rgb(a), to_rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb))


def hsv(hex_color):
    return colorsys.rgb_to_hsv(*(c / 255 for c in to_rgb(hex_color)))


def chromatic(hex_color):
    _, sat, val = hsv(hex_color)
    return sat > 0.25 and val > 0.25


# JetBrains' stock console/error colors: schemes that never customised them still
# carry these, and pure #ff0000 / #0000ff look out of place in a themed terminal.
STOCK = {
    "#ff0000", "#008000", "#ffcc00", "#ffff00", "#0000ff", "#ff00ff", "#00b2b2",
    "#ff6b68", "#a8c023", "#d6bf55", "#5394ec", "#ae8abe", "#299999",
}

# WCAG contrast the interface text (fg) and dim text (muted) are pushed to, on the panel.
UI_CONTRAST = 7.0
MUTED_CONTRAST = 4.5
BORDER_CONTRAST = 1.6

# Target hues (degrees) for picking ANSI colors out of the scheme's own palette.
HUES = {"red": 355, "yellow": 45, "green": 120, "cyan": 185, "blue": 220, "magenta": 295}


def nearest_hue(palette, target, max_dist=50):
    """Most frequent palette color whose hue is within max_dist of target."""
    best = None
    for color, count in palette.items():
        if not chromatic(color):
            continue
        dist = abs((hsv(color)[0] * 360 - target + 180) % 360 - 180)
        if dist <= max_dist:
            score = (dist // 15, -count)  # bucket hue distance, then prefer common colors
            if best is None or score < best[0]:
                best = (score, color)
    return best[1] if best else None


def luminance(hex_color):
    r, g, b = (c / 255 for c in to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio between two colors."""
    def rel(c):
        ch = [x / 255 for x in to_rgb(c)]
        ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((rel(a), rel(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(color, against, ratio):
    """Move color toward black (on light) or white (on dark) until it reaches ratio."""
    target = "#000000" if luminance(against) > 0.5 else "#ffffff"
    t = 0.0
    out = color
    while contrast(out, against) < ratio and t < 1:
        t += 0.02
        out = mix(color, target, t)
    return out


# ------------------------------------------------------------- scheme parsing

class Scheme:
    """Flattened view of a JetBrains editor color scheme."""

    def __init__(self, path):
        root = ET.parse(path).getroot()
        self.name = root.get("name", path.stem)
        self.colors = {}
        for opt in root.findall("./colors/option"):
            c = norm_hex(opt.get("value"))
            if c:
                self.colors[opt.get("name")] = c
        self.attrs = {}
        self.bases = {}
        for opt in root.findall("./attributes/option"):
            name = opt.get("name")
            if opt.get("baseAttributes"):
                self.bases[name] = opt.get("baseAttributes")
            vals = {}
            for v in opt.findall("./value/option"):
                c = norm_hex(v.get("value"))
                if c:
                    vals[v.get("name")] = c
            if vals:
                self.attrs[name] = vals

    def palette(self):
        """Foreground colors used by the scheme, with usage counts."""
        counts = {}
        for name, vals in self.attrs.items():
            if name.startswith("CONSOLE_"):
                continue
            c = vals.get("FOREGROUND")
            if c and c not in STOCK:
                counts[c] = counts.get(c, 0) + 1
        return counts

    def attr(self, name, field="FOREGROUND"):
        """Attribute field, following baseAttributes links."""
        seen = set()
        while name and name not in seen:
            seen.add(name)
            val = self.attrs.get(name, {}).get(field)
            if val:
                return val
            name = self.bases.get(name)
        return None

    def first(self, *keys, accept=None):
        """First defined color among keys. "NAME" is a <colors> option,
        "NAME.FIELD" an attribute field (FOREGROUND/BACKGROUND/EFFECT_COLOR...).
        accept, if given, filters candidates (e.g. to skip stock colors)."""
        for key in keys:
            val = None
            if key in self.colors:
                val = self.colors[key]
            elif "." in key:
                name, field = key.rsplit(".", 1)
                if field in ("FOREGROUND", "BACKGROUND", "EFFECT_COLOR", "ERROR_STRIPE_COLOR"):
                    val = self.attr(name, field)
            if val and (accept is None or accept(val)):
                return val
        return None


# ------------------------------------------------------------------- mapping

FG = ".FOREGROUND"

SYNTAX = {
    "keyword":     ["DEFAULT_KEYWORD" + FG],
    "type":        ["DEFAULT_CLASS_NAME" + FG, "DEFAULT_CLASS_REFERENCE" + FG, "DEFAULT_INTERFACE_NAME" + FG],
    "function":    ["DEFAULT_FUNCTION_DECLARATION" + FG, "DEFAULT_FUNCTION_CALL" + FG, "DEFAULT_INSTANCE_METHOD" + FG],
    "string":      ["DEFAULT_STRING" + FG],
    "number":      ["DEFAULT_NUMBER" + FG],
    "comment":     ["DEFAULT_LINE_COMMENT" + FG, "DEFAULT_BLOCK_COMMENT" + FG, "DEFAULT_DOC_COMMENT" + FG],
    "constant":    ["DEFAULT_CONSTANT" + FG, "DEFAULT_STATIC_FIELD" + FG, "DEFAULT_NUMBER" + FG],
    "operator":    ["DEFAULT_OPERATION_SIGN" + FG],
    # braces/parens/brackets only: when unset JetBrains draws them in the text color,
    # and a scheme's dot/comma color would otherwise leak onto every bracket
    "punctuation": ["DEFAULT_BRACES" + FG, "DEFAULT_PARENTHS" + FG, "DEFAULT_BRACKETS" + FG],
    "preproc":     ["DEFAULT_PREPROCESSOR_DIRECTIVE" + FG, "DEFAULT_METADATA" + FG],
    # rhun's builtin is globals like require/Object/print, which JetBrains paints as
    # function calls; DEFAULT_PREDEFINED_SYMBOL is for true/self and reads wrong here
    "builtin":     ["DEFAULT_FUNCTION_CALL" + FG, "DEFAULT_FUNCTION_DECLARATION" + FG],
    "attribute":   ["DEFAULT_ATTRIBUTE" + FG, "DEFAULT_METADATA" + FG, "DEFAULT_INSTANCE_FIELD" + FG],
    "tag":         ["DEFAULT_TAG" + FG, "HTML_TAG_NAME" + FG, "XML_TAG_NAME" + FG, "DEFAULT_KEYWORD" + FG],
    "heading":     ["MARKDOWN_HEADER_LEVEL_1" + FG, "MARKDOWN_HEADER_LEVEL_2" + FG, "DEFAULT_KEYWORD" + FG],
    "escape":      ["DEFAULT_VALID_STRING_ESCAPE" + FG, "DEFAULT_STRING" + FG],
}

# rhun terminal key -> JetBrains console attribute(s)
TERMINAL = {
    "black":          ["CONSOLE_BLACK_OUTPUT" + FG],
    "red":            ["CONSOLE_RED_OUTPUT" + FG],
    "green":          ["CONSOLE_GREEN_OUTPUT" + FG],
    "yellow":         ["CONSOLE_YELLOW_OUTPUT" + FG],
    "blue":           ["CONSOLE_BLUE_OUTPUT" + FG],
    "magenta":        ["CONSOLE_MAGENTA_OUTPUT" + FG],
    "cyan":           ["CONSOLE_CYAN_OUTPUT" + FG],
    "white":          ["CONSOLE_GRAY_OUTPUT" + FG],
    "bright_black":   ["CONSOLE_DARKGRAY_OUTPUT" + FG],
    "bright_red":     ["CONSOLE_RED_BRIGHT_OUTPUT" + FG, "CONSOLE_RED_OUTPUT" + FG],
    "bright_green":   ["CONSOLE_GREEN_BRIGHT_OUTPUT" + FG, "CONSOLE_GREEN_OUTPUT" + FG],
    "bright_yellow":  ["CONSOLE_YELLOW_BRIGHT_OUTPUT" + FG, "CONSOLE_YELLOW_OUTPUT" + FG],
    "bright_blue":    ["CONSOLE_BLUE_BRIGHT_OUTPUT" + FG, "CONSOLE_BLUE_OUTPUT" + FG],
    "bright_magenta": ["CONSOLE_MAGENTA_BRIGHT_OUTPUT" + FG, "CONSOLE_MAGENTA_OUTPUT" + FG],
    "bright_cyan":    ["CONSOLE_CYAN_BRIGHT_OUTPUT" + FG, "CONSOLE_CYAN_OUTPUT" + FG],
    "bright_white":   ["CONSOLE_WHITE_OUTPUT" + FG, "CONSOLE_GRAY_OUTPUT" + FG],
}


def build_theme(scheme, name, kind, ui_colors):
    s = scheme
    bg = s.first("TEXT.BACKGROUND", "CONSOLE_BACKGROUND_KEY", "GUTTER_BACKGROUND") \
        or norm_hex(ui_colors.get("background")) or ("#ffffff" if kind == "light" else "#1e1e1e")
    fg = s.first("TEXT.FOREGROUND", "CONSOLE_NORMAL_OUTPUT.FOREGROUND") \
        or norm_hex(ui_colors.get("foreground")) or ("#000000" if kind == "light" else "#d4d4d4")
    if kind is None:
        kind = "light" if luminance(bg) > 0.5 else "dark"

    syntax = {"text": fg, **{k: s.first(*keys) or fg for k, keys in SYNTAX.items()}}

    palette = s.palette()
    themed = lambda c: c not in STOCK and chromatic(c)

    # ANSI hues: the scheme's console colors unless stock, else the closest
    # hue the scheme itself uses, else a muted default.
    hue_default = {"red": "#d20f39", "yellow": "#df8e1d", "green": "#40a02b",
                   "cyan": "#179299", "blue": "#1e66f5", "magenta": "#8839ef"}
    ansi = {k: s.first(*TERMINAL[k], accept=themed) or nearest_hue(palette, h) or hue_default[k]
            for k, h in HUES.items()}

    near = lambda target: lambda c: themed(c) and nearest_hue({c: 1}, target) is not None
    error = s.first("ERRORS_ATTRIBUTES.EFFECT_COLOR", "WRONG_REFERENCES_ATTRIBUTES.FOREGROUND",
                    accept=near(HUES["red"])) or ansi["red"]
    warning = s.first("WARNING_ATTRIBUTES.EFFECT_COLOR", accept=near(HUES["yellow"])) or ansi["yellow"]
    success = ansi["green"]

    line_highlight = s.first("CARET_ROW_COLOR") or mix(bg, fg, 0.05)
    accent = syntax["function"] if syntax["function"] != fg else syntax["keyword"]
    # sidebar, tabs, status bar and settings cards: a step off the editor bg toward
    # the text, so darker on light themes and lighter on dark ones
    panel = mix(bg, fg, 0.10 if kind == "light" else 0.07)
    # JetBrains schemes often use a soft fg that's fine for code but leaves the
    # interface (tree, tabs, settings) washed out. rhun takes fg for the UI and
    # syntax "text" for code, so the UI gets a contrast-boosted fg and code keeps
    # the scheme's own.
    ui_fg = ensure_contrast(fg, panel, UI_CONTRAST)
    ui = {
        "bg": bg,
        "fg": ui_fg,
        "panel_fg": ui_fg,
        "accent": accent,
        "panel": panel,
        # rhun derives hover (tree rows, tabs) as panel + 6% fg, which vanishes on grey
        # light panels, and active (selected row) as panel + 17% accent. Hover stays a
        # neutral shade, a step stronger; active gets more accent so the two never meet.
        "hover": mix(panel, fg, 0.18 if kind == "light" else 0.16),
        "active": mix(panel, accent, 0.28 if kind == "light" else 0.32),
        # rhun draws dividers, button outlines and the off toggle track with border;
        # JetBrains' indent-guide color is meant to be faint, so lift it off the panel
        # (editor indent guides use rhun's separate guide color and stay unchanged)
        # On dark themes the indent guide is often a cool grey that clashes with warm
        # palettes, so borders there are the panel tinted toward the theme's own text,
        # checked against both bg and panel so outlines on the editor area, like the
        # settings buttons, show as well as the dividers.
        "border": ensure_contrast(s.first("INDENT_GUIDE", "TEARLINE_COLOR", "RIGHT_MARGIN_COLOR")
                                  or mix(bg, fg, 0.15), panel, BORDER_CONTRAST)
                  if kind == "light" else ensure_contrast(ensure_contrast(mix(panel, fg, 0.14), bg, 1.45),
                                                          panel, 1.45),
        "selection": s.first("SELECTION_BACKGROUND") or mix(bg, fg, 0.18),
        "line_highlight": line_highlight,
        # rhun derives muted (inactive tabs, sidebar headers) as fg 43% toward bg,
        # which is too faint on light themes whose fg is already soft
        "muted": ensure_contrast(mix(ui_fg, bg, 0.25 if kind == "light" else 0.3), panel, MUTED_CONTRAST),
        "line_number": s.first("LINE_NUMBERS_COLOR") or syntax["comment"],
        "cursor": s.first("CARET_COLOR") or fg,
        # text and knob on accent (buttons, the on toggle). rhun picks near-black or
        # white; on dark themes the theme's own panel reads softer when it's legible.
        **({"accent_fg": panel} if kind == "dark" and contrast(accent, panel) >= 4.5 else {}),
        "error": error,
        "warning": warning,
        "success": success,
    }

    dim = lambda c: mix(c, bg, 0.15)
    terminal = {
        "black": s.first(*TERMINAL["black"], accept=lambda c: c != "#000000")
                 or (bg if kind == "light" else mix(bg, fg, 0.1)),
        **{k: ansi[k] for k in ("red", "green", "yellow", "blue", "magenta", "cyan")},
        "white": s.first(*TERMINAL["white"]) or (fg if kind == "light" else dim(fg)),
        "bright_black": s.first(*TERMINAL["bright_black"]) or syntax["comment"],
    }
    for k in ("red", "green", "yellow", "blue", "magenta", "cyan"):
        terminal["bright_" + k] = s.first(*TERMINAL["bright_" + k][:1], accept=themed) or ansi[k]
    terminal["bright_white"] = s.first("CONSOLE_WHITE_OUTPUT.FOREGROUND",
                                       accept=lambda c: c != "#ffffff" or kind == "dark") or fg

    terminal = {k: terminal[k] for k in TERMINAL}
    return name, kind, ui, syntax, terminal


def render(name, kind, ui, syntax, terminal):
    def block(d):
        width = max(len(k) for k in d) + 1
        return "\n".join(f"{k.ljust(width)}= {v}" for k, v in d.items())

    return (f"name = {name}\nkind = {kind}\n\n{block(ui)}\n\n"
            f"[syntax]\n{block(syntax)}\n\n[terminal]\n{block(terminal)}\n")


# ---------------------------------------------------------------- discovery

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_source(path):
    """Return (scheme_path, name, kind or None, ui_colors) or None to skip."""
    if path.name.endswith(".theme.json"):
        data = json.loads(path.read_text())
        ref = data.get("editorScheme", "")
        scheme_path = path.parent / Path(ref).name
        if not ref or not scheme_path.is_file():
            print(f"skip {path.name}: editor scheme {ref!r} not found", file=sys.stderr)
            return None
        kind = "dark" if data.get("dark") else "light"
        return scheme_path, data.get("name") or path.stem, kind, data.get("colors", {})
    if path.suffix in (".xml", ".icls"):
        return path, None, None, {}
    return None


def collect(inputs):
    """Directories contribute their *.theme.json (name + dark flag); bare
    .xml/.icls schemes are converted only when passed explicitly."""
    files = []
    for p in inputs:
        if p.is_dir():
            files += sorted(p.glob("*.theme.json"))
        else:
            files.append(p)
    sources, claimed = [], set()
    for f in files:
        if f.name.endswith(".theme.json"):
            src = load_source(f)
            if src:
                sources.append(src)
                claimed.add(src[0].resolve())
    for f in files:
        if not f.name.endswith(".theme.json") and f.resolve() not in claimed:
            src = load_source(f)
            if src:
                sources.append(src)
    return sources


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", type=Path, default=[DEFAULT_SRC],
                    help=f"theme.json / xml / icls files or directories (default: {DEFAULT_SRC})")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--kind", choices=["light", "dark", "all"], default="all", help="which themes to convert")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for scheme_path, name, kind, ui_colors in collect(args.inputs):
        try:
            scheme = Scheme(scheme_path)
        except ET.ParseError as e:
            print(f"skip {scheme_path.name}: {e}", file=sys.stderr)
            continue
        name, kind, *rest = build_theme(scheme, name or scheme.name, kind, ui_colors)
        if args.kind != "all" and kind != args.kind:
            continue
        theme_id = slug(name)
        if theme_id in RHUN_BUILTINS:
            theme_id, name = theme_id + "-jb", name + " JB"
        out = args.out / f"{theme_id}.theme"
        out.write_text(render(name, kind, *rest))
        print(f"{scheme_path.name:32} -> {out.name}")
        written += 1
    print(f"{written} theme(s) written to {args.out}")


if __name__ == "__main__":
    main()
