"""minihtml grid rendering for CsvGridOverlay.

minihtml has no ``<table>`` support, so the grid is drawn the way a terminal
would draw it: monospace ``white-space: pre`` rows whose cells are padded to a
fixed character width, with box-drawing separators between columns.
"""

import html
import unicodedata

ELLIPSIS = "…"
SEPARATOR = "│"
SORT_GLYPHS = {"asc": "↑", "desc": "↓", None: "⇅"}
WIDEN_GLYPH = "▸"
NARROW_GLYPH = "◂"
RESIZE_STEP = 4
MAX_OVERRIDE_WIDTH = 240

DEFAULT_CELL_PADDING = 1   # spaces on each side of a cell value
SEPARATOR_WIDTH = 1


def char_width(char):
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    return 1


def str_width(text):
    return sum(char_width(char) for char in text)


def truncate(text, width):
    """Clip text to a display width, marking clipped text with an ellipsis."""

    if width <= 0:
        return ""
    if str_width(text) <= width:
        return text
    if width == 1:
        return ELLIPSIS

    kept = []
    used = 0
    for char in text:
        size = char_width(char)
        if used + size > width - 1:
            break
        kept.append(char)
        used += size
    return "".join(kept) + ELLIPSIS


def pad(text, width, align_right=False):
    padding = " " * max(0, width - str_width(text))
    return padding + text if align_right else text + padding


class GridRenderer:
    """Lay out and render a page of rows as a fixed-width minihtml grid."""

    def __init__(
        self,
        total_width=120,
        min_col_width=8,
        max_col_width=48,
        empty_placeholder="",
        zebra_stripes=True,
        column_fit="content",
        resize_handles=False,
        cell_padding=DEFAULT_CELL_PADDING,
        editable=False,
    ):
        self.total_width = max(40, total_width)
        self.min_col_width = max(3, min_col_width)
        self.max_col_width = max(self.min_col_width, max_col_width)
        self.empty_placeholder = empty_placeholder
        self.zebra_stripes = zebra_stripes
        self.column_fit = (
            column_fit if column_fit in ("all", "content", "even") else "all"
        )
        self.resize_handles = resize_handles
        self.cell_padding = max(0, min(int(cell_padding), 6))
        self.editable = editable

    @property
    def _overhead(self):
        """Characters a column costs on top of its value width."""

        return 2 * self.cell_padding + SEPARATOR_WIDTH

    # -- layout ----------------------------------------------------------

    def natural_widths(self, header, rows):
        """Measure the widest value in each column, header included."""

        # Raw content widths; min/max bounds are applied by preferred_widths so
        # a caller can cache this measurement across settings changes.
        column_count = len(header)
        widths = [1] * column_count
        for index, name in enumerate(header):
            # Headers also carry a space and a sort glyph.
            widths[index] = max(widths[index], str_width(name) + 2)
        for _, row in rows:
            for index in range(min(column_count, len(row))):
                value = row[index]
                if value:
                    widths[index] = max(widths[index], str_width(value))
        return widths

    def gutter_width(self, rows):
        largest = max((number for number, _ in rows), default=1)
        return max(2, len(str(largest)))

    def preferred_widths(self, natural, overrides=None):
        """Apply per-column overrides and the max-width cap to measured widths."""

        overrides = overrides or {}
        widths = []
        for index, width in enumerate(natural):
            override = overrides.get(index)
            if override:
                widths.append(
                    max(self.min_col_width, min(int(override), MAX_OVERRIDE_WIDTH))
                )
            else:
                widths.append(max(self.min_col_width, min(width, self.max_col_width)))
        return widths

    def layout(self, natural, gutter, start_col=0, overrides=None):
        """Choose which columns fit and how wide each one is.

        Columns keep their preferred width whenever the whole grid fits. When it
        does not, ``column_fit`` decides: ``"all"`` draws every column anyway and
        lets the view scroll sideways, ``"even"`` shrinks every column so they all
        fit on screen, and ``"content"`` keeps widths intact but windows the
        columns from ``start_col`` so the caller can paginate horizontally.
        """

        # A rendered row is: gutter + (sep + pad + value + pad) per column + sep.
        available = self.total_width - gutter - SEPARATOR_WIDTH
        overhead = self._overhead
        column_count = len(natural)
        if column_count == 0:
            return [], []

        preferred = self.preferred_widths(natural, overrides)
        if sum(width + overhead for width in preferred) <= available:
            return list(range(column_count)), preferred

        if self.column_fit == "all":
            return list(range(column_count)), preferred

        if self.column_fit == "even":
            shrunk = self._shrink_to_fit(preferred, available, overhead)
            if shrunk is not None:
                return list(range(column_count)), shrunk

        indexes = []
        widths = []
        used = 0
        for index in range(start_col, column_count):
            width = preferred[index]
            if indexes and used + width + overhead > available:
                break
            indexes.append(index)
            # A single column wider than the viewport is clipped to it.
            widths.append(min(width, available - overhead))
            used += width + overhead

        if not indexes:
            indexes = [min(start_col, column_count - 1)]
            widths = [max(self.min_col_width, available - overhead)]
        return indexes, widths

    def _shrink_to_fit(self, natural, available, overhead):
        """Cap every column at a common maximum, or return None if that cannot fit."""

        fixed = overhead * len(natural)
        room = available - fixed
        if room < self.min_col_width * len(natural):
            return None

        low, high = self.min_col_width, max(natural)
        while low < high:
            cap = (low + high + 1) // 2
            required = sum(max(self.min_col_width, min(width, cap)) for width in natural)
            if required <= room:
                low = cap
            else:
                high = cap - 1

        widths = [max(self.min_col_width, min(width, low)) for width in natural]
        # Hand leftover characters back to columns that are still clipped.
        remaining = room - sum(widths)
        for index, want in enumerate(natural):
            if remaining <= 0:
                break
            extra = min(want - widths[index], remaining)
            if extra > 0:
                widths[index] += extra
                remaining -= extra
        return widths

    # -- rendering -------------------------------------------------------

    def _separator(self):
        return '<span class="sep">%s</span>' % SEPARATOR

    def _cell_html(self, text, width, align_right, css_class=None, href=None):
        gap = " " * self.cell_padding
        content = pad(truncate(text, width), width, align_right)
        escaped = html.escape(content)
        if href:
            classes = "cell %s" % css_class if css_class else "cell"
            escaped = '<a class="%s" href="%s">%s</a>' % (classes, href, escaped)
        elif css_class:
            escaped = '<span class="%s">%s</span>' % (css_class, escaped)
        return gap + escaped + gap

    def header_html(self, header, indexes, widths, gutter, sort_state):
        sort_column, sort_direction = sort_state
        pieces = ['<span class="gutter">%s</span>' % (" " * gutter)]
        for slot, index in enumerate(indexes):
            width = widths[slot]
            # Two glyphs replace the last two cells of the header label, so a
            # column only gets handles when it can spare the room.
            handles = self.resize_handles and width >= self.min_col_width + 2
            is_sorted = index == sort_column
            glyph = SORT_GLYPHS[sort_direction if is_sorted else None]
            label_width = width - 2 if handles else width
            name = truncate(header[index] if index < len(header) else "", label_width - 2)
            label = pad("%s %s" % (name, glyph), label_width)
            classes = "hdr sorted" if is_sorted else "hdr"
            gap = " " * self.cell_padding
            pieces.append(self._separator())
            pieces.append(
                '%s<a class="%s" href="sort:%d">%s</a>'
                % (gap, classes, index, html.escape(label))
            )
            if handles:
                pieces.append(
                    '<a class="handle" href="narrow:%d" title="Narrower">%s</a>'
                    '<a class="handle" href="widen:%d" title="Wider">%s</a>'
                    % (index, NARROW_GLYPH, index, WIDEN_GLYPH)
                )
            pieces.append(gap)
        pieces.append(self._separator())
        return '<div class="row header-row">%s</div>' % "".join(pieces)

    def row_html(self, number, row, indexes, widths, gutter, numeric_cols, striped):
        pieces = ['<span class="gutter">%s</span>' % pad(str(number), gutter, True)]
        for slot, index in enumerate(indexes):
            width = widths[slot]
            value = row[index] if index < len(row) else ""
            href = "edit:%d,%d" % (number, index) if self.editable else None
            pieces.append(self._separator())
            if value.strip():
                pieces.append(
                    self._cell_html(value, width, index in numeric_cols, href=href)
                )
            else:
                pieces.append(
                    self._cell_html(
                        self.empty_placeholder,
                        width,
                        False,
                        css_class="empty",
                        href=href,
                    )
                )
        pieces.append(self._separator())
        classes = "row body-row striped" if striped else "row body-row"
        return '<div class="%s">%s</div>' % (classes, "".join(pieces))

    def render(
        self,
        header,
        page_rows,
        indexes,
        widths,
        gutter,
        sort_state,
        numeric_cols,
        repeat_header_every=0,
    ):
        """Render one page of rows, repeating the header band if configured."""

        header_row = self.header_html(header, indexes, widths, gutter, sort_state)
        parts = [header_row]
        for position, (number, row) in enumerate(page_rows):
            if (
                repeat_header_every
                and position
                and position % repeat_header_every == 0
            ):
                parts.append(header_row)
            striped = self.zebra_stripes and position % 2 == 1
            parts.append(
                self.row_html(
                    number, row, indexes, widths, gutter, numeric_cols, striped
                )
            )
        if not page_rows:
            parts.append('<div class="row body-row empty-note">no rows</div>')
        return '<div class="grid">%s</div>' % "".join(parts)
