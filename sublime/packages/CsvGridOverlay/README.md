# CsvGridOverlay

CsvGridOverlay is an editor-native reading mode for CSV/TSV files in Sublime Text.
It leaves the delimited text untouched in the buffer, folds the source, and renders
the data as a sortable, paginated grid phantom in the same view.

Built on the same idea as [MarkdownPreviewOverlay](../MarkdownPreviewOverlay): fold the
source, draw a `minihtml` phantom over it, restore everything on the way out.

## Features

- **Grid over the source**: no split pane, no external viewer, no temporary buffer.
- **Sortable columns**: click a column name to cycle ascending → descending → unsorted.
  Numeric columns sort numerically (`1,234.00` included), blanks always sort last.
- **Repeated column-name row**: pages are sized to the viewport, so the header band is
  drawn at the top of whatever you are looking at.
- **All columns, rows paginate**: every column is drawn at its content width and the
  view scrolls sideways; only rows are paged (10,000 per page by default).
- **Click a cell to edit it**: the value opens in an input panel and is written back to
  that one record, correctly re-quoted, as a normal undoable buffer edit.
- **Type-aware alignment**: mostly-numeric columns are right-aligned, everything else left.
- **Delimiter sniffing**: `,`, `\t`, `;`, and `|` from the extension or the contents,
  with proper RFC 4180 quoting (embedded commas, quotes, and newlines survive).
- **Non-destructive by default**: the buffer is folded and read-only; sorting, paging,
  and column widths are view state and never touch the file. Only an explicit cell edit
  writes, and it rewrites exactly one record.

## Usage

### Buttons

- **Edit mode**: click the **`▦ Grid`** badge on the first line (a compact `▦` icon when
  the first line is long) to fold the source and open the grid.
- **Grid mode**: the toolbar above the grid carries `◀ ✏️ Edit source`, the sort state,
  row/column pagers, and `⟳` refresh.

### Command palette

| Command | Description |
| :--- | :--- |
| `CSV Grid: Toggle` | Switch between grid and source. |
| `CSV Grid: Grid Mode` | Fold the source and render the grid. |
| `CSV Grid: Edit Mode` | Restore the source, selections, scroll, and folds. |
| `CSV Grid: Refresh` | Re-read the buffer and redraw. |
| `CSV Grid: Sort By Column…` | Pick a column to sort from the quick panel. |
| `CSV Grid: Edit Cell…` | Edit a cell by row number and column, without clicking. |
| `CSV Grid: Column Width…` | Pin one column to a width (`fit` for max content, `auto` to release). |
| `CSV Grid: Reset Column Widths` | Drop every pinned width. |
| `CSV Grid: Next / Previous Page` | Page through rows. |
| `CSV Grid: Scroll Columns Left / Right` | Move the visible column window. |

### Key bindings

None by default. `Preferences → Package Settings → CsvGridOverlay → Key Bindings`
has a ready-made set (`primary+alt+g` to toggle, `alt+←/→` to page,
`shift+alt+←/→` for columns).

## Settings

`Preferences → Package Settings → CsvGridOverlay → Settings`.

| Setting | Default | Description |
| :--- | :--- | :--- |
| `show_grid_button` | `true` | Show the `▦ Grid` badge in edit mode. |
| `show_status_indicator` | `true` | Show `CsvGrid` in the status bar. |
| `hide_line_numbers` | `true` | Hide gutter and line numbers in grid mode. |
| `delimiter` | `null` | Force a delimiter (`","`, `"tab"`, `";"`, `"\|"`). |
| `has_header` | `true` | Treat the first record as column names. |
| `editable` | `true` | Clicking a cell opens an input panel to edit it. |
| `grid_max_width` | `0` | Grid width in characters; `0` fits the viewport. |
| `rows_per_page` | `10000` | Rows per page, capped at 50,000; `0` fits the viewport height. |
| `repeat_header_every` | `25` | Redraw the column-name row every N rows; `0` disables. |
| `column_fit` | `"all"` | `"all"` draws every column and lets the view scroll sideways; `"content"` pages through columns instead; `"even"` shrinks them all to fit. |
| `min_column_width` / `max_column_width` | `8` / `60` | Column width bounds. |
| `show_column_resize_handles` | `false` | Draw `◂ ▸` nudge links in each column name. |
| `line_height` / `row_padding` | `1.6` / `0.15` | Vertical rhythm, in rem. |
| `row_separators` | `true` | Hairline between rows. |
| `font_size` | `1.0` | Grid font size in rem, relative to the editor font. |
| `cell_padding` | `1` | Spaces between a separator and its value, each side. |
| `max_rows` | `50000` | Parse cap; `0` reads the whole file. |
| `empty_placeholder` | `""` | Text drawn in an empty cell. |
| `zebra_stripes` | `true` | Tint alternating rows. |

## Column widths

Columns size themselves to their widest value, capped by `max_column_width`. When the
grid is wider than the window, `column_fit` decides what gives: `"all"` (the default)
draws every column anyway and leaves horizontal scrolling to the view, `"content"` keeps
the widths but pages through columns sideways, and `"even"` squeezes every column until
they all fit at once.

To override a single column, run `CSV Grid: Column Width…` (or the `↔` toolbar link),
pick the column, and enter a number, `fit` to match its widest value, or `auto` to hand
it back to automatic sizing. Pinned widths ignore `min_column_width`/`max_column_width`,
survive toggling in and out of grid mode, and are cleared with the toolbar's `✕` or
`CSV Grid: Reset Column Widths`. Setting `show_column_resize_handles` to `true` puts
`◂ ▸` links in every column name for 4-character nudges, at the cost of two characters
of the name.

## Editing

Click any cell and its value opens in Sublime's input panel; press `Enter` and the plugin
rewrites that record in the buffer — re-quoting only where the new value needs it — then
re-parses and redraws. It is an ordinary buffer edit, so `undo` works and the file is not
saved until you save it. Records that span several lines through a quoted newline are
tracked by line span and rewritten in place. `CSV Grid: Edit Cell…` does the same from
the palette, and `editable: false` turns the whole thing off.

The cell is not a real text box: `minihtml` has no `<input>` and no keyboard focus, so
the input panel at the bottom of the window is where the typing happens.

## Limitations

`minihtml` has no `<table>`, no JavaScript, and no `<input>`, so the grid is drawn as
monospace `white-space: pre` rows with padded cells, and every interaction has to be a
link click.

- **No sticky header.** A phantom scrolls with the buffer, so the column-name row cannot
  be pinned. `repeat_header_every` redraws the band periodically instead.
- **No drag-to-resize.** A phantom receives link clicks, never drag or pointer events.
  The `◂ ▸` handles and `CSV Grid: Column Width…` are the click-driven stand-ins.
- **Large pages are heavy.** At `rows_per_page: 10000` every cell is a link, so a page of
  a wide file is megabytes of markup. Lower it if rendering feels slow.
