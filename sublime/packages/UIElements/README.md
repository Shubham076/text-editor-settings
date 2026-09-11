# UIElements

Reusable, color-scheme-aware controls for Sublime Text 4: floating dropdowns, anchored dropdowns, callback buttons, and mixed toolbars with icons. Controls are drawn as phantoms; they do not insert text into the document or move its selections.

## Try the components

Open the Command Palette and run:

- **UIElements: Open Demo** — opens a scratch view with examples.
- **UIElements: Draw in Current Editor** — draws both dropdown types, all four button variants, and a Debugger-style toolbar prototype below the current cursor line. Running it again replaces the previous demo controls instead of duplicating them.

The demo uses sample model names only. Button clicks show a status message. There are no custom keybindings.

## Installation and imports

The package directory must be named `UIElements` inside Sublime's `Packages` directory, or symlinked there. It includes a `.python-version` file containing `3.8`. Packages importing UIElements must also use the Python 3.8 plugin host.

Inside a Python module at the root of **this package**:

```python
from . import anchored_dropdown, buttons, dropdown, floating_dropdown, toolbar
```

From **another Sublime package**:

```python
from UIElements import anchored_dropdown, buttons, dropdown, floating_dropdown, toolbar
```

From a nested module inside UIElements, use the appropriate relative import, such as `from .. import buttons` one level below the package root.

Importing the modules does not draw anything. Call `attach()` from a command, event handler, or `plugin_loaded()` when a view is available. Construct option and button objects there too, rather than storing them at module import time during plugin development/reloads.

The previous `AnchoredDropdown` package name is no longer the import path.

## Anchored dropdown

The anchored version expands below the clicked button. It temporarily takes up space in the editor layout without changing the document.

```python
import sublime

from . import anchored_dropdown, dropdown


def show_format_selector(view):
    def changed(key, value):
        sublime.status_message("{} = {}".format(key, value))

    return anchored_dropdown.attach(
        view,
        [dropdown.Field("format", "Format", ["JSON", "HTML", "SARIF"])],
        region=sublime.Region(view.line(view.sel()[0]).end()),
        values={"format": "HTML"},
        on_change=changed,
    )
```

Use the external import form above if this code lives in another package.

## Floating dropdown

The floating version overlays the editor rather than expanding the layout. It shares the same field model and callback API:

```python
from . import dropdown, floating_dropdown


def show_severity_selector(view):
    return floating_dropdown.attach(
        view,
        [dropdown.Field("severity", "Severity", ["Critical", "High", "Low"])],
        on_change=lambda key, value: view.set_status("severity", value),
    )
```

**Positioning limitation:** Sublime's popup API anchors to a text-buffer position, not an HTML button rectangle. The floating menu may appear at the left of an empty line rather than underneath the clicked button. Use `anchored_dropdown` when button alignment matters more than overlay behavior.

### Open a menu from an existing toolbar or button

Use `floating_dropdown.show()` when the host already draws its own trigger. This opens only the popup: no button, phantom, buffer edit, or selection change is added.

```python
from UIElements import floating_dropdown


def open_format_menu(view, choose, open_search):
    return floating_dropdown.show(
        view, ["JSON", "HTML", "SARIF"],
        selected="JSON",
        on_select=choose,
        location=view.visible_region().end(),
        caption="Select Format",
        on_search=open_search,
    )
```

The handle has `selected`, `closed`, and an idempotent `close()` method. `on_select(value)` runs after the menu closes, including when the user selects the current value. Optional `on_hide()` runs once when the menu closes. Providing `on_search()` adds a **Search...** link, allowing a host to retain its native searchable picker. `max_width` and `max_height` default to 520. Empty options or an invalid view return `None`; an unknown selected value raises `ValueError`.

Set `keep_on_selection_modified=True` for output views whose caret follows incoming logs; it suppresses selection-change dismissal but still closes on view deactivation or an explicit dismissal.

Pass `font_size=<px>` when the host view's own font is not the size the menu should be read at (for example a phantom-only panel that shrinks its font to hide anchor characters); by default the menu follows the view's font.

For Debugger's fixed bottom toolbar, host the menu on the console/output view, not its separate input-strip view. The input-strip popup did not appear in live testing on Sublime build 4200. The toolbar can remain in place while its menu overlays the console, with the same text-position anchoring limitation.

### Labels, values, descriptions, and groups

Strings are shorthand options whose label and value are identical. Use `Option` for separate stored values and display labels:

```python
field = dropdown.Field("model", "Model", [
    dropdown.Option("fast", "Fast model", "Shorter answers", "Recently used"),
    dropdown.Option("balanced", "Balanced model", "General-purpose profile", "Recommended"),
])
```

- `Field(key, caption, options)` identifies a dropdown.
- `Option(value, label, description="", group="")` describes an option.
- Field keys must be unique, non-empty strings within a row.
- Option values must be unique strings within their field.
- Empty option lists render a non-clickable `No options` button with value `None`.
- Without an initial `values` entry, the first option is selected.
- `on_change(key, value)` runs only when the selected value changes.

### Dropdown handle

Both dropdown modules expose:

```python
row = anchored_dropdown.attach(
    view, fields,
    region=None,
    on_change=None,
    values=None,
    heading=None,
)

current = row.values
row.set("format", "JSON")
row.open("format")
row.close()
row.render()
row.detach()
```

`region=None` means buffer position zero. Pass a `sublime.Region` to choose a different line. `heading` optionally labels the row. An optional `phantom_key` groups the control's phantoms; each instance still removes only its own phantom IDs.

`values` returns a copy. `set()` validates the field and option, redraws the label, and calls `on_change` if the value changed. Opening an already-open field toggles it closed.

## Buttons and click handlers

Each button has its own **zero-argument Python callback**. Use a function, bound method, or lambda. Creating a button does not call its handler.

```python
import sublime

from . import buttons


def show_actions(view):
    def run_action():
        sublime.status_message("Run clicked")

    def cancel_action():
        sublime.status_message("Cancel clicked")

    return buttons.attach(view, [
        buttons.btn("run", "Run", on_click=run_action),
        buttons.btn_red("cancel", "Cancel", on_click=cancel_action),
        buttons.btn_green("apply", "Apply", on_click=lambda: sublime.status_message("Apply clicked")),
        buttons.btn_yellow("review", "Review", on_click=lambda: sublime.status_message("Review clicked")),
    ], heading="Actions")
```

| Python factory | Variant name | Theme color |
| --- | --- | --- |
| `buttons.btn(...)` | `btn` | Editor-derived neutral background |
| `buttons.btn_red(...)` | `btn-red` | `var(--redish)` |
| `buttons.btn_green(...)` | `btn-green` | `var(--greenish)` |
| `buttons.btn_yellow(...)` | `btn-yellow` | `var(--yellowish)` |

Hyphenated names are CSS variants. Python factory names use underscores.

You can also construct a button directly:

```python
button = buttons.Button("apply", "Apply", on_click=apply_changes, variant="btn-green")
row = buttons.attach(view, [button], region=sublime.Region(0))
```

Button keys must be unique, non-empty strings within the row. Labels are escaped as text. Unknown variants and non-callable handlers are rejected. `buttons.attach()` also accepts `heading` and `phantom_key`, and returns a handle with `render()` and `detach()`.

The colored variants use the editor's foreground for readable labels and semantic palette variables for tinted backgrounds and borders. `--yellowish` uses two leading hyphens, just like the other CSS variables. No fixed red, green, or yellow RGB values are built into the component.

## Toolbars and icons

`toolbar.attach()` combines existing `Button` and `Field` objects in the order supplied, inside one phantom. The dropdown therefore aligns with the icons and buttons around it rather than living in a separate input panel. The toolbar has one padded, rounded frame with a background and border derived from the editor's foreground/background colors, adapting to light and dark schemes. Inside it, controls have no visible borders: normal buttons are text-style, dropdowns retain a subtle fill, and separators divide the icon, dropdown, and button groups. Standalone buttons retain their original styling. The expanded menu stays outside this frame, aligned with its dropdown button.

```python
import sublime

from . import buttons, dropdown, toolbar


def show_toolbar(view):
    def report(action):
        sublime.status_message("Preview: " + action)

    return toolbar.attach(view, [
        buttons.icon("settings", "settings", lambda: report("Settings"), title="Settings"),
        buttons.icon("run", "play", lambda: report("Run"), title="Run configuration"),
        buttons.icon("restart", "restart", lambda: report("Restart")),
        buttons.icon("stop", "stop", lambda: report("Stop")),
        dropdown.Field("configuration", "", ["Run Installer", "Launch Application", "Attach Process"]),
        buttons.btn("console", "Console", lambda: report("Console")),
        buttons.btn("callstack", "Callstack", lambda: report("Callstack")),
    ], on_change=lambda key, value: report("Selected " + value))
```

- `menu_mode="inline"` is the default: the menu expands below its toolbar button. Use `menu_mode="popup"` to compare the floating version, with the same text-anchor limitation described above.
- `region`, `phantom_key`, `values`, `heading`, and `on_change` behave like the standalone dropdown options.
- The handle supports `values`, `set()`, `open()`, `close()`, `render()`, and `detach()`.
- Every item key must be unique across the whole toolbar, including button and dropdown keys.
- `Console` and `Callstack` are ordinary callback buttons, not built-in tabs or Debugger integrations.
- A toolbar is a document-positioned phantom, not a sticky native toolbar.

`buttons.icon(key, name, on_click, title=None)` creates an icon-only button. Supported names are `settings`, `play`, `restart`, and `stop`. The optional title appears as a tooltip. Icon buttons also work in `buttons.attach()`.

Icons are generated locally as antialiased PNG data URIs, tinted with the editor foreground. They do not depend on Debugger, an icon font, or external image files.

## Lifecycle and composition

Keep the returned handles when you need to update or remove controls:

```python
controls = []


def plugin_unloaded():
    for control in controls:
        control.detach()
    controls.clear()
```

- Call `detach()` when your feature is removed or your owning plugin unloads. Calling it twice is safe.
- UIElements also cleans up its controls when a view closes.
- Buttons and dropdown rows can share the same region. Their attachment order is preserved during redraws.
- Only one dropdown is open per view. Selecting an action button closes that view's open dropdown before invoking the button callback.
- Callbacks execute on the UI thread. Keep them short; schedule expensive work separately.
- After changing the component's Python files during development, redraw or reattach the controls to bind the new implementation.

## Verification

```sh
python3 -B -m unittest discover -s tests -v
```

The tests cover state, callbacks, escaping, stale events, and shared-position ordering. Actual minihtml layout must also be checked in Sublime using the demo, including repeated switching between the floating and anchored rows and checking the selected highlight and footer at different font sizes.
