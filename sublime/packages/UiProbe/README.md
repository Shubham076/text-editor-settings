# UiProbe

Throwaway probe answering one question: can Sublime stack a **fixed header** above a
**scrollable body** without an io panel's input strip?

minihtml has no flexbox, `overflow`, percentage heights or `position: fixed`, and only one
output panel is visible at a time, so the browser-style header/body/footer layout cannot be
done inside one phantom. The only native stacking primitive left is a **row layout with two
groups**, each holding a plain scratch view.

- `UI Probe: Open fixed header + scrollable body` (Command Palette) splits the window into two
  rows. The top group gets a one-line scratch view with a **red** header phantom; the bottom
  group gets a 300-line scratch view with **blue** marker phantoms.
- The top row is a *fraction* of the window, so a poll rescales it every 400 ms until the
  header's text area matches the height of the header band itself. Resize the window and watch
  it re-fit.
- `UI Probe: Close` (or closing either view) restores the previous layout and tab visibility.

## Findings (Sublime Text 4, macOS)

- **Works.** The red band never moves while the blue body scrolls. No input strip is involved.
- **Fit.** Scaling the row fraction by wanted/current converges in two or three polls to within
  a pixel or two of the requested height (60px asked, 58 to 59px measured).
- **Tabs cannot be hidden per group.** Tab visibility is a per-window toggle (`toggle_tabs`).
  A theme extension *does* load from this package (an unkeyed `tab_label` rule recoloured every
  tab), but a rule keyed on the probe's view setting (`"settings": ["ui_probe"]`) never applied
  to `tabset_control`, `tab_control` or `tab_label`: tab-strip rules read global preferences
  only. The theme files were removed again. So the strip between header and body goes away only
  by hiding tabs for the whole window (`hide_tabs`, on by default here), or by putting the probe
  in its own window with tabs off (`separate_window`), which leaves the editor window untouched.
- **Divider.** A one-pixel group border remains between the rows. It comes from the theme's
  `grid_layout_control` and is likewise global.
- **User drag.** The divider between rows is draggable; the poll drags it back.

Nothing here touches the Debugger packages.
