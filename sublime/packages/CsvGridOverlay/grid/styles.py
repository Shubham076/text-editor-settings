"""minihtml styles and small HTML fragments for CsvGridOverlay."""

_GRID_STYLE_TEMPLATE = """
<style>
    html, body { margin: 0; padding: 0; }
    body {
        background-color: var(--background);
        color: var(--foreground);
        font-family: var(--font-mono, monospace);
    }
    .grid {
        display: block;
        font-family: monospace;
        font-size: __FONT_SIZE__rem;
        line-height: __LINE_HEIGHT__rem;
        white-space: pre;
        margin: 0 0 1.2rem 0;
        border: 1px solid color(var(--foreground) alpha(0.30));
        border-radius: 2px;
    }
    .row {
        display: block;
        margin: 0;
        padding: __ROW_PADDING__rem 0;
    }
    .header-row {
        background-color: color(var(--background) blend(var(--foreground) 86%));
        border-bottom: 1px solid color(var(--foreground) alpha(0.35));
        font-weight: bold;
    }
    .body-row { __ROW_SEPARATOR__ }
    .striped {
        background-color: color(var(--background) blend(var(--foreground) 96%));
    }
    .gutter {
        color: color(var(--foreground) alpha(0.45));
        background-color: color(var(--background) blend(var(--foreground) 92%));
    }
    .sep { color: color(var(--foreground) alpha(0.25)); }
    .empty { color: color(var(--foreground) alpha(0.35)); }
    .empty-note { color: color(var(--foreground) alpha(0.45)); padding: 0.3rem 0.6rem; }
    a.hdr {
        color: var(--foreground);
        text-decoration: none;
        font-weight: bold;
    }
    a.hdr.sorted { color: var(--cyanish); }
    a.cell {
        color: var(--foreground);
        text-decoration: none;
    }
    a.cell.empty { color: color(var(--foreground) alpha(0.35)); }
    a.handle {
        color: color(var(--foreground) alpha(0.40));
        text-decoration: none;
        font-weight: normal;
    }
</style>
"""


def build_grid_style(
    line_height=1.6,
    row_padding=0.15,
    row_separators=True,
    font_size=1.0,
):
    """Build the grid stylesheet with the configured vertical rhythm."""

    separator = (
        "border-bottom: 1px solid color(var(--foreground) alpha(0.10));"
        if row_separators
        else ""
    )
    return (
        _GRID_STYLE_TEMPLATE
        .replace("__LINE_HEIGHT__", "%.2f" % max(1.0, float(line_height)))
        .replace("__ROW_PADDING__", "%.2f" % max(0.0, float(row_padding)))
        .replace("__FONT_SIZE__", "%.2f" % max(0.5, float(font_size)))
        .replace("__ROW_SEPARATOR__", separator)
    )


TOOLBAR_STYLE = """
<style>
    html, body { margin: 0; padding: 0; }
    body { background-color: var(--background); }
    .toolbar {
        display: block;
        background-color: color(var(--background) blend(var(--foreground) 95%));
        border: 1px solid color(var(--foreground) alpha(0.12));
        border-left: 4px solid var(--cyanish);
        border-radius: 4px;
        padding: 0.5rem 0.8rem;
        margin: 0.5rem 0 0.8rem;
        font-family: var(--font-mono, monospace);
    }
    .toolbar a {
        color: var(--cyanish);
        font-weight: bold;
        text-decoration: none;
    }
    .toolbar a.muted { color: color(var(--foreground) alpha(0.35)); }
    .toolbar .info {
        color: color(var(--foreground) alpha(0.60));
        font-weight: normal;
    }
    .toolbar .gap { display: inline-block; width: 1.4rem; }
    .toolbar .warn { color: var(--yellowish); font-weight: normal; }
</style>
"""

ANNOTATION_HTML = """
<body id="csv-grid-overlay-control">
    <style>
        html, body { margin: 0; padding: 0; }
        a.grid-link {
            display: inline-block;
            color: var(--cyanish);
            font-weight: bold;
            line-height: 1;
            text-decoration: none;
        }
        span.grid-icon {
            display: inline-block;
            margin-left: -0.1rem;
            margin-right: 0.3rem;
            font-size: 1.1em;
        }
    </style>
    <a class="grid-link" href="overlay:grid"><span class="grid-icon">▦</span>Grid</a>
</body>
"""

INLINE_BUTTON_HTML = """
<body id="csv-grid-overlay-control">
    <style>
        html, body { margin: 0; padding: 0; }
        a.grid-icon-link {
            display: inline-block;
            padding: 0 0.15rem;
            font-size: 1.15rem;
            line-height: 1;
            color: var(--cyanish);
            text-decoration: none;
            background-color: var(--background);
        }
    </style>
    <a class="grid-icon-link" href="overlay:grid" title="Open grid view">▦</a>
</body>
"""

ANNOTATION_RESERVED_WIDTH = 130.0
