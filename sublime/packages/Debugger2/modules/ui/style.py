from __future__ import annotations


# Menlo advance width relative to the font size; used to clip text to the space a slot has.
CH = 0.602
# Geometry taken from the mockups (values in rem, 1rem = preview font size).
PAD = 1.1            # toolbar / tabs / footer horizontal padding
PANE_PAD = 1.3       # debugger pane horizontal padding
PANE_CONTENT = 56    # widest a lone pane's rows get, so their action icons stay near the text
STACK_SHARE = 0.2    # the call stack's share of the Debugger tab; the variables take the rest
STACK_MIN = 20       # ...but never narrower than this, so frame names stay readable
ROW = 2.2            # debugger pane row height
LINE = 2.03          # console / terminal transcript row height
CONTROL = 1.7        # chevron / breakpoint marker slot
ACTION = 2.2         # inline action button slot (edit, remove, add)
TOOL = 2.65          # toolbar button slot
TOOLBAR = 3.8
TABS_HEIGHT = 3.4
FOOTER = 2.75
TAB_PAD = 1.0
ZW = '<span>&#8203;</span>'  # zero-width text that keeps a row's line box at the 1rem text height
TEXT_LINE = 1.46     # minihtml's natural line box for 1rem Menlo text (measured)
HEADING_LINE = 1.54  # the same for the 1.15rem section headings
TOOLBAR_PAD = 1.145  # vertical padding around the toolbar's line box (3.8rem bar with 1.2rem icons)
# Tab order. Console and Terminal only appear once a run produces them, and slot in right after
# the call stack so a run's output sits next to its frames. Breakpoints are global rather than
# configuration-owned, so their control lives in the toolbar instead of this tab row.
TABS = (('debugger', 'Call Stack / Variables', None), ('console', 'Console', None), ('terminal', 'Terminal', None),
	('debugger_console', 'Debug Console', None), ('watch', 'Watch', None))
# The tabs drawn by the live ui itself, in tab order, with the debugger attribute holding each panel
DASHBOARDS = (('debugger', 'callstack'), ('watch', 'watch_panel'), ('breakpoints', 'breakpoints_panel'))


# Every dimension is in rem so the preview scales with the preview font size. `line-height`
# on its own is not honoured by minihtml, so rows use an explicit height plus line-height,
# while bars holding padded inline controls (toolbar, filters, footer) use vertical padding.
CSS = '''
html { font-size: $fontpx; }
body { margin: 0; padding: 0; font-family: $fontfamily; font-size: 1rem; color: var(--foreground); background-color: var(--background); }
a { color: var(--foreground); text-decoration: none; }
.slot { display: inline-block; white-space: nowrap; }
.center { text-align: center; }
.right { text-align: right; }
.icon { margin: 0; padding: 0; }
.muted { color: color(var(--foreground) alpha(0.72)); }
.faint { color: color(var(--foreground) alpha(0.5)); }
.small { font-size: 0.9rem; }
.string, .infoish { color: color(var(--greenish) min-contrast(var(--background) 4)); }
.number, .link-color { color: var(--bluish); }
.warnish { color: color(var(--yellowish) min-contrast(var(--background) 4)); }
.errorish { color: var(--redish); }
.toolbar { padding-top: $toolpadrem; padding-bottom: $toolpadrem; background-color: var(--background); white-space: nowrap; }
.toolbar.brand-cell { padding-left: $padrem; border-left: 1px solid $line; border-radius: 0.4rem 0 0 0; }
.toolbar.controls-cell { padding-right: $padrem; border-right: 1px solid $line; border-radius: 0 0.4rem 0 0; }
.toolbar.joined { padding-left: $padrem; padding-right: $padrem; border-left: 1px solid $line; border-right: 1px solid $line; }
.toolbar.continued { border-radius: 0; }
.toolbar.strip { border-left: none; border-right: none; border-top: none; border-bottom: none; border-radius: 0; }
.brand { color: color(var(--foreground) alpha(0.72)); }
.picker { padding: 0.43rem 0.95rem; border: 1px solid color(var(--foreground) alpha(0.16)); border-radius: 0.4rem; background-color: color(var(--foreground) alpha(0.08)); font-weight: bold; }
.state { padding: 0.27rem 0.5rem; border-radius: 1rem; font-weight: bold; }
.paused { color: color(var(--yellowish) min-contrast(var(--background) 4)); background-color: color(var(--yellowish) alpha(0.15)); }
.running { color: color(var(--greenish) min-contrast(var(--background) 4)); background-color: color(var(--greenish) alpha(0.15)); }
.stopped { padding: 0.43rem 0.8rem; color: var(--foreground); background-color: $selection; }
.breakpoints-control { padding: 0.43rem 0.85rem; border-radius: 1rem; color: var(--foreground); background-color: $selection; }
.breakpoints-control.active { font-weight: bold; }
.separator { color: color(var(--foreground) alpha(0.25)); }
.tool { padding-top: 0.77rem; padding-bottom: 0.23rem; padding-left: 0.6rem; padding-right: 0.6rem; border-radius: 0.4rem; }
.tool.primary { background-color: $selection; }
.icon-button { padding: 0.2rem 0.3rem; border-radius: 0.3rem; }
.tabs { padding-left: $padrem; padding-right: $padrem; border-top: 1px solid $line; border-left: 1px solid $line; border-right: 1px solid $line; border-bottom: 1px solid $line; white-space: nowrap; }
.tabrow { padding-top: $tabpadrem; padding-bottom: $tabpadrem; white-space: nowrap; }
.tab { padding-left: $tabsiderem; padding-right: $tabsiderem; color: color(var(--foreground) alpha(0.72)); }
.tab.active { color: var(--foreground); font-weight: bold; }
.underline { height: 2px; background-color: var(--foreground); }
.bar { padding-top: 1.17rem; padding-bottom: 1.17rem; padding-left: 1.25rem; padding-right: 1.25rem; border-left: 1px solid $line; border-right: 1px solid $line; border-bottom: 1px solid $line; white-space: nowrap; }
.bar.tall { padding-top: 1.08rem; padding-bottom: 1.08rem; }
.chip { padding: 0.27rem 0.85rem; border: 1px solid color(var(--foreground) alpha(0.18)); border-radius: 1rem; color: color(var(--foreground) alpha(0.85)); background-color: $field; }
.chip.active { background-color: var(--foreground); color: var(--background); border: 1px solid var(--foreground); }
.transcript { padding: 1rem 1.25rem; border-left: 1px solid $line; border-right: 1px solid $line; }
.line { padding-top: $linepadrem; padding-bottom: $linepadrem; white-space: nowrap; }
.input { padding-top: 0.82rem; padding-bottom: 0.82rem; padding-left: 1.35rem; padding-right: 1.35rem; border-left: 1px solid $line; border-right: 1px solid $line; border-top: 1px solid $line; white-space: nowrap; }
.caret { color: var(--foreground); }
.footer { padding-top: 0.55rem; padding-bottom: 0.55rem; padding-left: $padrem; padding-right: $padrem; border: 1px solid $line; border-radius: 0 0 0.4rem 0.4rem; background-color: $raised; color: color(var(--foreground) alpha(0.72)); white-space: nowrap; }
.footer b { color: var(--foreground); }
.pane { padding-top: 0.8rem; padding-left: $panepadrem; padding-right: $panepadrem; white-space: nowrap; }
.pane.columns { border-right: 1px solid $line; }
.pane.first { border-left: 1px solid $line; }
.pane.last { border-right: 1px solid $line; }
.section-title { padding-top: $headpadrem; padding-bottom: $headpadrem; font-weight: bold; font-size: 1.15rem; white-space: nowrap; }
.row { padding-top: $rowpadrem; padding-bottom: $rowpadrem; white-space: nowrap; }
.gap { height: 0.4rem; }
.gap-large { height: 0.8rem; }
.group { font-size: 0.8rem; font-weight: bold; color: color(var(--foreground) alpha(0.7)); }
.thread { padding-top: 0.47rem; padding-bottom: 0.47rem; padding-left: 0.9rem; padding-right: 0.9rem; border-radius: 0.3rem; background-color: color(var(--foreground) alpha(0.05)); font-weight: bold; white-space: nowrap; }
.frame { padding-top: 0.57rem; padding-bottom: 0.57rem; margin-top: 0.1rem; margin-bottom: 0.1rem; padding-left: 0.9rem; padding-right: 0.9rem; border-radius: 0.3rem; white-space: nowrap; }
.frame.selected { background-color: $selection; }
.selected a, .selected .muted { color: var(--foreground); }
.pane-status { padding-top: 0.6rem; padding-bottom: 0.6rem; border-top: 1px solid $line; color: color(var(--foreground) alpha(0.78)); }
'''
COLORS = {
	'$line': 'color(var(--foreground) alpha(0.2))',
	'$raised': 'color(var(--background) lightness(+ 2%))',
	'$field': 'color(var(--background) lightness(+ 4%))',
}
