"""Render CSV/TSV files as an editor-native, sortable grid overlay."""

import html
import os
import sys
import threading

import sublime
import sublime_plugin

prefix = __package__ + "."
for module_name in [m for m in sys.modules if m.startswith(prefix) and m != __name__]:
    del sys.modules[module_name]

from .grid import csv_model
from .grid.render import GridRenderer, RESIZE_STEP
from .grid.styles import (
    ANNOTATION_HTML,
    ANNOTATION_RESERVED_WIDTH,
    INLINE_BUTTON_HTML,
    TOOLBAR_STYLE,
    build_grid_style,
)


PHANTOM_KEY = "csv_grid_overlay"
ANNOTATION_KEY = "csv_grid_overlay.control"
MODE_SETTING = "csv_grid_overlay.grid_mode"
ORIGINAL_STATE_SETTING = "csv_grid_overlay.original_state"
WIDTHS_SETTING = "csv_grid_overlay.column_widths"
STATUS_KEY = "csv_grid_overlay"
SETTINGS_NAME = "CsvGridOverlay.sublime-settings"
SETTINGS_KEY = "csv_grid_overlay.settings"
GRID_MARGIN = 16

CSV_EXTENSIONS = {".csv", ".tsv", ".tab", ".psv"}
DEFAULT_ROWS_PER_PAGE = 10000
MAX_ROWS_PER_PAGE = 50000
CSV_SELECTOR = "text.csv, text.tsv, text.delimited"


def _setting(name, fallback=None):
    try:
        value = sublime.load_settings(SETTINGS_NAME).get(name)
        return fallback if value is None else value
    except Exception:
        return fallback


def _float_setting(name, fallback):
    value = _setting(name, fallback)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return float(value)


def _int_setting(name, fallback):
    value = _setting(name, fallback)
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _is_csv_view(view):
    """Return whether a view holds delimited text this package should render."""

    if view is None or not view.is_valid() or view.settings().get("is_widget", False):
        return False

    file_name = view.file_name()
    if file_name and os.path.splitext(file_name)[1].lower() in CSV_EXTENSIONS:
        return True

    return bool(view.size()) and view.match_selector(0, CSV_SELECTOR)


def _can_show_grid_button(view):
    if not _is_csv_view(view):
        return False
    return bool(view.file_name()) and not view.is_scratch()


def _copy_regions(regions):
    return [sublime.Region(region.a, region.b) for region in regions]


def _capture_view_state(view):
    return {
        "read_only": view.is_read_only(),
        "gutter": view.settings().get("gutter"),
        "line_numbers": view.settings().get("line_numbers"),
        "highlight_line": view.settings().get("highlight_line"),
        "margin": view.settings().get("margin"),
        "word_wrap": view.settings().get("word_wrap"),
        "selections": [[s.a, s.b] for s in view.sel()],
        "viewport": list(view.viewport_position()),
        "folds": [[f.a, f.b] for f in view.folded_regions()],
    }


def _restore_view_state(view, saved_state):
    if not isinstance(saved_state, dict):
        saved_state = {}

    view.set_read_only(False)
    view.unfold(sublime.Region(0, view.size()))

    for bounds in saved_state.get("folds", []):
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            view.fold(sublime.Region(bounds[0], bounds[1]))

    for key in ("gutter", "line_numbers", "highlight_line", "margin", "word_wrap"):
        value = saved_state.get(key)
        if value is not None:
            view.settings().set(key, value)
        else:
            view.settings().erase(key)

    view.set_read_only(bool(saved_state.get("read_only", False)))

    selections = [
        sublime.Region(bounds[0], bounds[1])
        for bounds in saved_state.get("selections", [])
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2
    ] or [sublime.Region(0, 0)]
    viewport = tuple(saved_state.get("viewport", [0.0, 0.0]))
    if len(viewport) != 2:
        viewport = (0.0, 0.0)

    def restore_position():
        if not view.is_valid():
            return
        view.sel().clear()
        for selection in selections:
            view.sel().add(selection)
        view.set_viewport_position(viewport, False)

    sublime.set_timeout(restore_position)


class GridState(object):
    """Own the grid overlay, parsed data, and restoration state for one View."""

    def __init__(self, view):
        self.view = view
        self.phantom_set = sublime.PhantomSet(view, PHANTOM_KEY)
        self.gridding = False
        self.control_mode = None
        self.refresh_lock = threading.Lock()
        self.refresh_generation = 0
        self.control_generation = 0

        self.column_widths = self._load_column_widths()
        self._natural_widths = None
        self.sort_column = None
        self.sort_direction = None  # "asc" | "desc" | None
        self.page = 0
        self.start_col = 0

        self.header = []
        self.rows = []          # list of (row_number, fields)
        self.row_spans = {}     # row_number -> (first_line, last_line) in the buffer
        self.numeric_cols = set()
        self.truncated = False
        self.delimiter = ","

    # -- column widths -----------------------------------------------------

    def _load_column_widths(self):
        stored = self.view.settings().get(WIDTHS_SETTING)
        if not isinstance(stored, dict):
            return {}
        widths = {}
        for key, value in stored.items():
            try:
                widths[int(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return widths

    def _store_column_widths(self):
        if self.column_widths:
            self.view.settings().set(
                WIDTHS_SETTING,
                {str(key): value for key, value in self.column_widths.items()},
            )
        else:
            self.view.settings().erase(WIDTHS_SETTING)

    def natural_widths(self, renderer):
        """Measure content widths once per parse; sorting and paging reuse them."""

        if self._natural_widths is None:
            self._natural_widths = renderer.natural_widths(self.header, self.rows)
        return self._natural_widths

    def content_width(self, column):
        """Return the width the widest value in a column would need."""

        renderer = self._renderer()
        natural = self.natural_widths(renderer)
        if 0 <= column < len(natural):
            return max(renderer.min_col_width, natural[column])
        return renderer.min_col_width

    def set_column_width(self, column, width):
        """Pin a column to a width, or clear the override when width is None."""

        if width is None:
            self.column_widths.pop(column, None)
        else:
            self.column_widths[column] = max(3, int(width))
        self._store_column_widths()
        self._render_grid()

    def nudge_column_width(self, column, delta):
        renderer = self._renderer()
        current = self.column_widths.get(column)
        if current is None:
            natural = self.natural_widths(renderer)
            _indexes, widths = renderer.layout(
                natural, renderer.gutter_width(self.rows) if self.rows else 2,
                self.start_col, self.column_widths,
            )
            current = (
                widths[_indexes.index(column)]
                if column in _indexes
                else renderer.min_col_width
            )
        self.set_column_width(column, max(3, current + delta))

    def reset_column_widths(self):
        self.column_widths = {}
        self._store_column_widths()
        self._render_grid()

    # -- editing -----------------------------------------------------------

    def can_edit(self):
        """Whether cells should be clickable for editing."""

        return bool(_setting("editable", True))

    def row_fields(self, number):
        """Return the parsed fields for a displayed row number, if it still exists."""

        if 1 <= number <= len(self.rows):
            return self.rows[number - 1][1]
        return None

    def edit_cell(self, number, column):
        """Prompt for a new value for one cell and write it back to the buffer."""

        window = self.view.window()
        if window is None or not self.can_edit():
            return
        if number not in self.row_spans or column >= len(self.header):
            sublime.status_message("CSV Grid: that cell is no longer in the file")
            return

        row = self.row_fields(number)
        if row is None:
            return
        current = row[column] if column < len(row) else ""
        label = self.header[column] or "col %d" % (column + 1)

        window.show_input_panel(
            "row %d · %s:" % (number, label),
            current,
            lambda text: self.write_cell(number, column, text),
            None,
            None,
        )

    def write_cell(self, number, column, value):
        """Replace one field in the buffer, leaving every other record untouched."""

        span = self.row_spans.get(number)
        row = self.row_fields(number)
        if span is None or row is None:
            return
        if column < len(row) and row[column] == value:
            return

        record = list(row)
        while len(record) <= column:
            record.append("")
        record[column] = value

        first_line, last_line = span
        start = self.view.text_point(first_line, 0)
        end = self.view.line(self.view.text_point(last_line, 0)).end()
        replacement = csv_model.serialize_record(record, self.delimiter)

        was_read_only = self.view.is_read_only()
        self.view.set_read_only(False)
        self.view.run_command(
            "csv_grid_overlay_replace_region",
            {"start": start, "end": end, "text": replacement},
        )
        self.view.set_read_only(was_read_only)

        self.refresh()
        sublime.status_message(
            "CSV Grid: row %d · %s updated"
            % (number, self.header[column] or "col %d" % (column + 1))
        )

    # -- data ------------------------------------------------------------

    def load_data(self):
        """Parse the buffer into header, rows, and per-column type information."""

        self._natural_widths = None
        text = self.view.substr(sublime.Region(0, self.view.size()))
        self.delimiter = csv_model.sniff_delimiter(
            text, self.view.file_name(), _setting("delimiter")
        )
        records, spans, self.truncated, _total = csv_model.parse(
            text, self.delimiter, _int_setting("max_rows", 50000)
        )

        if not records:
            self.header = []
            self.rows = []
            self.row_spans = {}
            self.numeric_cols = set()
            return

        if _setting("has_header", True):
            self.header = list(records[0])
            data = records[1:]
            data_spans = spans[1:]
        else:
            self.header = ["col %d" % (i + 1) for i in range(len(records[0]))]
            data = records
            data_spans = spans

        self.rows = list(enumerate(data, start=1))
        self.row_spans = {
            number: data_spans[number - 1]
            for number, _row in self.rows
            if number - 1 < len(data_spans)
        }
        self.numeric_cols = csv_model.numeric_columns(data)

        if self.sort_column is not None and self.sort_column >= len(self.header):
            self.sort_column = None
            self.sort_direction = None

    def sorted_rows(self):
        if self.sort_column is None or self.sort_direction is None:
            return self.rows
        return csv_model.sort_rows(
            self.rows,
            self.sort_column,
            self.sort_direction == "desc",
            self.sort_column in self.numeric_cols,
        )

    # -- geometry --------------------------------------------------------

    def _total_width(self):
        configured = _int_setting("grid_max_width", 0)
        if configured > 0:
            return configured
        try:
            viewport_width, _ = self.view.viewport_extent()
            character_width = self.view.em_width()
            if viewport_width > 0 and character_width > 0:
                return max(40, int(viewport_width / character_width) - 4)
        except Exception:
            pass
        return 120

    def _rows_per_page(self):
        configured = _int_setting("rows_per_page", DEFAULT_ROWS_PER_PAGE)
        if configured > 0:
            return min(configured, MAX_ROWS_PER_PAGE)
        try:
            _, viewport_height = self.view.viewport_extent()
            line_height = self.view.line_height()
            if viewport_height > 0 and line_height > 0:
                # Grid rows are taller than buffer lines once line height and
                # row padding are applied, so scale the fit accordingly.
                row_scale = max(
                    0.5,
                    (
                        _float_setting("line_height", 1.6)
                        + 2 * _float_setting("row_padding", 0.15)
                    )
                    / 1.35,
                )
                fitting = int(viewport_height / (line_height * row_scale))
                return max(10, fitting - 5)
        except Exception:
            pass
        return 40

    def _renderer(self):
        return GridRenderer(
            total_width=self._total_width(),
            min_col_width=_int_setting("min_column_width", 8),
            max_col_width=_int_setting("max_column_width", 60),
            empty_placeholder=str(_setting("empty_placeholder", "")),
            zebra_stripes=bool(_setting("zebra_stripes", True)),
            column_fit=str(_setting("column_fit", "all")),
            resize_handles=bool(_setting("show_column_resize_handles", False)),
            cell_padding=_int_setting("cell_padding", 1),
            editable=self.can_edit(),
        )

    def _grid_style(self):
        return build_grid_style(
            line_height=_float_setting("line_height", 1.6),
            row_padding=_float_setting("row_padding", 0.15),
            row_separators=bool(_setting("row_separators", True)),
            font_size=_float_setting("font_size", 1.0),
        )

    # -- rendering -------------------------------------------------------

    def _toolbar_html(self, page_count, page_start, page_end, indexes, column_count):
        parts = [
            '<a href="overlay:edit" title="Back to source">◀ ✏️ Edit source</a>',
            '<span class="gap">&nbsp;</span>',
        ]

        name = os.path.basename(self.view.file_name() or "untitled")
        label = "%s · %d cols × %s rows" % (
            name,
            column_count,
            "{:,}".format(len(self.rows)),
        )
        parts.append('<span class="info">%s</span>' % html.escape(label))

        if self.sort_column is not None and self.sort_direction is not None:
            column_name = (
                self.header[self.sort_column]
                if self.sort_column < len(self.header)
                else str(self.sort_column)
            )
            parts.append('<span class="gap">&nbsp;</span>')
            parts.append(
                '<span class="info">sort: %s %s</span> '
                '<a href="sort:clear" title="Clear sort">✕</a>'
                % (
                    html.escape(column_name),
                    "↑" if self.sort_direction == "asc" else "↓",
                )
            )

        if page_count > 1:
            parts.append('<span class="gap">&nbsp;</span>')
            parts.append(
                '<span class="info">rows %s–%s</span> ' % (
                    "{:,}".format(page_start + 1),
                    "{:,}".format(page_end),
                )
            )
            parts.append(self._nav_link("page:prev", "◀", self.page > 0))
            parts.append(
                '<span class="info"> %d/%d </span>' % (self.page + 1, page_count)
            )
            parts.append(
                self._nav_link("page:next", "▶", self.page + 1 < page_count)
            )

        if indexes and len(indexes) < column_count:
            parts.append('<span class="gap">&nbsp;</span>')
            parts.append(
                '<span class="info">cols %d–%d of %d</span> '
                % (indexes[0] + 1, indexes[-1] + 1, column_count)
            )
            parts.append(self._nav_link("cols:prev", "◀", indexes[0] > 0))
            parts.append(" ")
            parts.append(
                self._nav_link("cols:next", "▶", indexes[-1] + 1 < column_count)
            )

        if self.truncated:
            parts.append('<span class="gap">&nbsp;</span>')
            parts.append(
                '<span class="warn">⚠ showing first %s rows</span>'
                % "{:,}".format(len(self.rows))
            )

        parts.append('<span class="gap">&nbsp;</span>')
        if self.column_widths:
            parts.append(
                '<a href="overlay:widths" title="Column width…">↔</a> '
                '<a href="overlay:reset-widths" title="Reset column widths">✕</a>'
                '<span class="gap">&nbsp;</span>'
            )
        else:
            parts.append(
                '<a href="overlay:widths" title="Column width…">↔</a>'
                '<span class="gap">&nbsp;</span>'
            )
        parts.append('<a href="overlay:refresh" title="Re-read the file">⟳</a>')

        return (
            '<body id="csv-grid-overlay-toolbar">%s<div class="toolbar">%s</div></body>'
            % (TOOLBAR_STYLE, "".join(parts))
        )

    @staticmethod
    def _nav_link(href, glyph, enabled):
        if not enabled:
            return '<a class="muted" href="overlay:noop">%s</a>' % glyph
        return '<a href="%s">%s</a>' % (href, glyph)

    def _render_grid(self):
        if not self.view.is_valid():
            return

        self.view.erase_regions(ANNOTATION_KEY)

        renderer = self._renderer()
        rows = self.sorted_rows()
        column_count = len(self.header)

        per_page = self._rows_per_page()
        page_count = max(1, -(-len(rows) // per_page)) if rows else 1
        self.page = max(0, min(self.page, page_count - 1))
        page_start = self.page * per_page
        page_rows = rows[page_start:page_start + per_page]

        gutter = renderer.gutter_width(rows) if rows else 2
        natural = self.natural_widths(renderer)
        self.start_col = max(0, min(self.start_col, max(0, column_count - 1)))
        indexes, widths = renderer.layout(
            natural, gutter, self.start_col, self.column_widths
        )

        grid_html = renderer.render(
            self.header,
            page_rows,
            indexes,
            widths,
            gutter,
            (self.sort_column, self.sort_direction),
            self.numeric_cols,
            _int_setting("repeat_header_every", 25),
        )

        anchor = sublime.Region(self.view.size())
        phantoms = [
            sublime.Phantom(
                anchor,
                self._toolbar_html(
                    page_count,
                    page_start,
                    page_start + len(page_rows),
                    indexes,
                    column_count,
                ),
                sublime.LAYOUT_BLOCK,
                self.on_navigate,
            ),
            sublime.Phantom(
                anchor,
                '<body id="csv-grid-overlay">%s%s</body>'
                % (self._grid_style(), grid_html),
                sublime.LAYOUT_BLOCK,
                self.on_navigate,
            ),
        ]
        self.phantom_set.update(phantoms)

    def _render_button(self):
        if not self.view.is_valid():
            return

        self.view.erase_regions(ANNOTATION_KEY)

        if not (_can_show_grid_button(self.view) and _setting("show_grid_button", True)):
            self.phantom_set.update([])
            self.control_mode = None
            return

        if self._should_use_annotation():
            self.phantom_set.update([])
            self.view.add_regions(
                ANNOTATION_KEY,
                [sublime.Region(0)],
                annotations=[ANNOTATION_HTML],
                annotation_color="#aaa0",
                on_navigate=self.on_navigate,
            )
            self.control_mode = "annotation"
            return

        self.phantom_set.update(
            [
                sublime.Phantom(
                    sublime.Region(0),
                    INLINE_BUTTON_HTML,
                    sublime.LAYOUT_INLINE,
                    self.on_navigate,
                )
            ]
        )
        self.control_mode = "inline"

    def _should_use_annotation(self):
        first_line = self.view.line(0)
        if not self.view.substr(first_line).strip():
            return True

        viewport_width = self.view.viewport_extent()[0]
        if viewport_width <= 0:
            return False

        start_xy = self.view.text_to_layout(first_line.begin())
        end_xy = self.view.text_to_layout(first_line.end())
        if end_xy[1] > start_xy[1]:
            return False
        return end_xy[0] <= viewport_width - ANNOTATION_RESERVED_WIDTH

    def render(self):
        if self.gridding:
            self._render_grid()
        else:
            self._render_button()

    # -- mode transitions -------------------------------------------------

    def show(self, preserve_saved_state=False):
        """Enter grid mode: fold the source and draw the overlay over it."""

        if self.gridding or not _is_csv_view(self.view):
            return

        if not preserve_saved_state or not self.view.settings().has(ORIGINAL_STATE_SETTING):
            self.view.settings().set(
                ORIGINAL_STATE_SETTING, _capture_view_state(self.view)
            )

        for region in _copy_regions(self.view.folded_regions()):
            self.view.unfold(region)

        source = sublime.Region(0, self.view.size())
        if not source.empty():
            self.view.fold(source)

        self.gridding = True
        self.view.settings().set(MODE_SETTING, True)
        if _setting("show_status_indicator", True):
            self.view.set_status(STATUS_KEY, "CsvGrid")
        else:
            self.view.erase_status(STATUS_KEY)

        self.view.settings().set("highlight_line", False)
        self.view.settings().set("word_wrap", False)
        if _setting("hide_line_numbers", True):
            self.view.settings().set("line_numbers", False)
            self.view.settings().set("gutter", False)
            self.view.settings().set("margin", GRID_MARGIN)
        self.view.set_read_only(True)

        self.load_data()
        self._render_grid()
        if not preserve_saved_state:
            self.view.set_viewport_position((0.0, 0.0), False)

    def hide(self):
        """Leave grid mode and restore the previous view presentation."""

        if not self.gridding and not self.view.settings().get(MODE_SETTING, False):
            self._render_button()
            return

        saved_state = self.view.settings().get(ORIGINAL_STATE_SETTING)
        _restore_view_state(self.view, saved_state)

        self.gridding = False
        self.view.settings().erase(MODE_SETTING)
        self.view.settings().erase(ORIGINAL_STATE_SETTING)
        self.view.erase_status(STATUS_KEY)
        self._render_button()
        if not _can_show_grid_button(self.view):
            _states.pop(self.view.id(), None)

    def refresh(self, reload_data=True):
        """Re-fold the buffer and rebuild the overlay, optionally re-parsing it."""

        if not self.gridding or not self.view.is_valid():
            return

        self.view.set_read_only(False)
        for fold in _copy_regions(self.view.folded_regions()):
            self.view.unfold(fold)
        source = sublime.Region(0, self.view.size())
        if not source.empty():
            self.view.fold(source)
        self.view.set_read_only(True)

        if reload_data:
            self.load_data()
        self.phantom_set = sublime.PhantomSet(self.view, PHANTOM_KEY)
        self._render_grid()

    def schedule_refresh(self):
        with self.refresh_lock:
            self.refresh_generation += 1
            generation = self.refresh_generation

        def refresh_if_current():
            with self.refresh_lock:
                if generation != self.refresh_generation:
                    return
            if self.gridding and self.view.is_valid():
                self.refresh()

        sublime.set_timeout(refresh_if_current, 100)

    def schedule_control_render(self):
        with self.refresh_lock:
            self.control_generation += 1
            generation = self.control_generation

        def render_if_current():
            with self.refresh_lock:
                if generation != self.control_generation:
                    return
            if not self.gridding and self.view.is_valid():
                self.update_control_placement()

        sublime.set_timeout(render_if_current, 100)

    def update_control_placement(self):
        if self.gridding or not self.view.is_valid():
            return
        if not (_can_show_grid_button(self.view) and _setting("show_grid_button", True)):
            if self.control_mode is not None:
                self._render_button()
            return
        desired = "annotation" if self._should_use_annotation() else "inline"
        if desired != self.control_mode:
            self._render_button()

    def dispose(self, restore=True):
        if restore and self.view.is_valid() and self.gridding:
            self.hide()
        if self.view.is_valid():
            self.view.erase_regions(ANNOTATION_KEY)
        self.phantom_set.update([])

    # -- interaction -------------------------------------------------------

    def cycle_sort(self, column):
        """Cycle a column through ascending, descending, and unsorted."""

        if column != self.sort_column:
            self.sort_column, self.sort_direction = column, "asc"
        elif self.sort_direction == "asc":
            self.sort_direction = "desc"
        else:
            self.sort_column, self.sort_direction = None, None
        self.page = 0
        self._render_grid()

    def move_page(self, delta):
        self.page = max(0, self.page + delta)
        self._render_grid()

    def move_columns(self, delta):
        self.start_col = max(0, self.start_col + delta)
        self._render_grid()

    def on_navigate(self, href):
        if href == "overlay:grid":
            self.view.run_command("csv_grid_overlay_show")
        elif href == "overlay:edit":
            self.view.run_command("csv_grid_overlay_hide")
        elif href == "overlay:refresh":
            self.refresh()
        elif href == "sort:clear":
            self.sort_column, self.sort_direction, self.page = None, None, 0
            self._render_grid()
        elif href.startswith("sort:"):
            try:
                self.cycle_sort(int(href[5:]))
            except ValueError:
                pass
        elif href.startswith("edit:"):
            try:
                number, column = href[5:].split(",", 1)
                self.edit_cell(int(number), int(column))
            except ValueError:
                pass
        elif href == "overlay:widths":
            self.view.run_command("csv_grid_overlay_column_width")
        elif href == "overlay:reset-widths":
            self.reset_column_widths()
        elif href.startswith("widen:"):
            try:
                self.nudge_column_width(int(href[6:]), RESIZE_STEP)
            except ValueError:
                pass
        elif href.startswith("narrow:"):
            try:
                self.nudge_column_width(int(href[7:]), -RESIZE_STEP)
            except ValueError:
                pass
        elif href == "page:next":
            self.move_page(1)
        elif href == "page:prev":
            self.move_page(-1)
        elif href == "cols:next":
            self.move_columns(1)
        elif href == "cols:prev":
            self.move_columns(-1)


_states = {}


def _state_for(view):
    state = _states.get(view.id())
    if state is None:
        state = GridState(view)
        _states[view.id()] = state
    return state


def _is_grid_mode(view):
    state = _states.get(view.id())
    return (state is not None and state.gridding) or bool(
        view.settings().get(MODE_SETTING, False)
    )


def _sync_view_mode(view):
    if not view.is_valid() or view.is_loading():
        return

    if not _is_csv_view(view):
        state = _states.pop(view.id(), None)
        if state is not None:
            state.dispose(restore=True)
        return

    if view.settings().get(MODE_SETTING, False):
        state = _state_for(view)
        if not state.gridding:
            state.show(preserve_saved_state=True)
        else:
            state.schedule_refresh()
        return

    if not _can_show_grid_button(view):
        state = _states.pop(view.id(), None)
        if state is not None and not state.gridding:
            state.dispose(restore=True)
        return

    state = _state_for(view)
    if state.gridding:
        state.hide()
    else:
        state._render_button()


class CsvGridOverlayToggleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        state = _state_for(self.view)
        if _is_grid_mode(self.view):
            state.hide()
        else:
            state.show()

    def is_enabled(self):
        return _is_csv_view(self.view)


class CsvGridOverlayShowCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _state_for(self.view).show()

    def is_enabled(self):
        return _is_csv_view(self.view) and not _is_grid_mode(self.view)


class CsvGridOverlayHideCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _state_for(self.view).hide()

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayRefreshCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        _state_for(self.view).refresh()

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayPageCommand(sublime_plugin.TextCommand):
    """Move between row pages while the grid is showing."""

    def run(self, edit, delta=1):
        _state_for(self.view).move_page(int(delta))

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayScrollColumnsCommand(sublime_plugin.TextCommand):
    """Move the visible column window while the grid is showing."""

    def run(self, edit, delta=1):
        _state_for(self.view).move_columns(int(delta))

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlaySortCommand(sublime_plugin.TextCommand):
    """Pick a column to sort by from the quick panel."""

    def run(self, edit):
        state = _state_for(self.view)
        window = self.view.window()
        if window is None or not state.header:
            return

        items = [
            [name or "col %d" % (index + 1), "sort this column"]
            for index, name in enumerate(state.header)
        ]

        def on_done(choice):
            if choice >= 0:
                state.cycle_sort(choice)

        window.show_quick_panel(items, on_done)

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayReplaceRegionCommand(sublime_plugin.TextCommand):
    """Apply one cell edit. Called by the overlay, not meant for the palette."""

    def run(self, edit, start, end, text):
        self.view.replace(edit, sublime.Region(int(start), int(end)), text)


class CsvGridOverlayEditCellCommand(sublime_plugin.TextCommand):
    """Edit a cell by picking its row and column from the quick panel."""

    def run(self, edit, row=None, column=None):
        state = _state_for(self.view)
        window = self.view.window()
        if window is None or not state.header:
            return

        if row is not None and column is not None:
            state.edit_cell(int(row), int(column))
            return

        def pick_column(number):
            items = []
            fields = state.row_fields(number) or []
            for index, name in enumerate(state.header):
                value = fields[index] if index < len(fields) else ""
                items.append([name or "col %d" % (index + 1), value or "(empty)"])

            def on_column(choice):
                if choice >= 0:
                    state.edit_cell(number, choice)

            window.show_quick_panel(items, on_column)

        def on_row(text):
            try:
                number = int(text.strip())
            except (AttributeError, ValueError):
                return
            if number in state.row_spans:
                sublime.set_timeout(lambda: pick_column(number), 10)
            else:
                sublime.status_message("CSV Grid: no row %s" % text)

        window.show_input_panel("Edit row number:", "1", on_row, None, None)

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayColumnWidthCommand(sublime_plugin.TextCommand):
    """Pick a column, then set its width in characters."""

    def run(self, edit, column=None, width=None):
        state = _state_for(self.view)
        window = self.view.window()
        if window is None or not state.header:
            return

        if column is not None:
            state.set_column_width(int(column), width)
            return

        def prompt_for_width(choice):
            if choice < 0:
                return
            current = state.column_widths.get(choice)
            initial = str(current if current else state.content_width(choice))
            window.show_input_panel(
                "Width for %s (number, \"fit\", or \"auto\")"
                % (state.header[choice] or "col %d" % (choice + 1)),
                initial,
                lambda text: self._apply(state, choice, text),
                None,
                None,
            )

        items = []
        for index, name in enumerate(state.header):
            current = state.column_widths.get(index)
            items.append(
                [
                    name or "col %d" % (index + 1),
                    "pinned to %d chars" % current if current else "auto width",
                ]
            )
        window.show_quick_panel(items, prompt_for_width)

    @staticmethod
    def _apply(state, column, text):
        text = (text or "").strip().lower()
        if text in ("auto", "-", ""):
            state.set_column_width(column, None)
            return
        if text == "fit":
            state.set_column_width(column, state.content_width(column))
            return
        try:
            state.set_column_width(column, int(text))
        except ValueError:
            sublime.status_message("CSV Grid: expected a number, \"fit\", or \"auto\"")

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayResetColumnWidthsCommand(sublime_plugin.TextCommand):
    """Drop every pinned column width and go back to automatic sizing."""

    def run(self, edit):
        _state_for(self.view).reset_column_widths()

    def is_enabled(self):
        return _is_csv_view(self.view) and _is_grid_mode(self.view)


class CsvGridOverlayListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        _sync_view_mode(view)

    def on_activated_async(self, view):
        _sync_view_mode(view)

    def on_reload_async(self, view):
        _sync_view_mode(view)

    def on_revert_async(self, view):
        _sync_view_mode(view)

    def on_post_save_async(self, view):
        _sync_view_mode(view)

    def on_modified_async(self, view):
        state = _states.get(view.id())
        if state is None:
            return
        if state.gridding:
            state.schedule_refresh()
        else:
            state.schedule_control_render()

    def on_selection_modified_async(self, view):
        state = _states.get(view.id())
        if state is not None and not state.gridding:
            sublime.set_timeout(state.update_control_placement)

    def on_close(self, view):
        state = _states.pop(view.id(), None)
        if state is not None:
            state.dispose(restore=True)


def _on_settings_change():
    for window in sublime.windows():
        for view in window.views():
            state = _states.get(view.id())
            if state is None:
                if _can_show_grid_button(view):
                    _state_for(view).render()
                continue
            if state.gridding:
                if _setting("hide_line_numbers", True):
                    view.settings().set("line_numbers", False)
                    view.settings().set("gutter", False)
                    view.settings().set("margin", GRID_MARGIN)
                state.refresh()
            else:
                state.render()


def plugin_loaded():
    sublime.load_settings(SETTINGS_NAME).add_on_change(SETTINGS_KEY, _on_settings_change)
    for window in sublime.windows():
        for view in window.views():
            _sync_view_mode(view)


def plugin_unloaded():
    sublime.load_settings(SETTINGS_NAME).clear_on_change(SETTINGS_KEY)
    for state in list(_states.values()):
        state.dispose(restore=False)
    _states.clear()
