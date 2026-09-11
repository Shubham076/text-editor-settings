# Development checks

- Target Sublime Text's Python 3.8 plugin host; keep the component dependency-free.
- Run regression tests with `python3 -B -m unittest discover -s tests -v`.
- For visual verification, run `UIElements: Draw in Current Editor`, then click the anchored Format button, floating Format button, and anchored Format button again. Check row order, selected-row containment, footer visibility, and selection updates at small and large font sizes. Click all four button variants and verify their callback status messages. Check the toolbar's icon/dropdown alignment and its Console/Callstack callbacks; the demo must not launch real debug sessions.
- Mocked tests cannot verify minihtml geometry. On Sublime build 4200, the expanding inline-block menu needs an explicit width and bottom clearance; otherwise child backgrounds overflow and the footer is clipped.
- Phantoms sharing a buffer position are ordered by insertion. Redraw the component's co-located rows in registration order to preserve their visible order.
- Scope flat styles to the toolbar so standalone buttons stay unchanged. Dropdown alignment depends on matching invisible control/separator spacers and an inset accounting for the toolbar frame's horizontal padding and border.
