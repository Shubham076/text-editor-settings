"""Visual examples of the importable UIElements components."""

import sublime
import sublime_plugin

from . import anchored_dropdown, buttons, dropdown, floating_dropdown, toolbar


SETTING_DEMO = "ui_elements_demo"
SETTING_VALUES = "ui_elements_demo_values"
_rows = {}

MODELS = [
    ("astra", "GPT-6 Astra Medium", "Balanced reasoning for everyday tasks", "Recently used"),
    ("opus", "Claude Opus 4.7", "Detailed answers and complex problem solving", "Recently used"),
    ("swe", "SWE-1.7 Medium", "A coding-focused profile", "Recommended"),
    ("fast", "SWE-1.7 Lightning", "Shorter answers, faster iteration", "Recommended"),
    ("thinking", "GPT-5.4 Low Thinking", "A lightweight reasoning profile", "Recommended"),
]

CONTENT = """
  UI ELEMENTS

  Floating dropdown


  Click Model or Format to open a floating popup.
  Sublime anchors this version to text, not the clicked button.
  Sample data only. No network requests or model connections.

  Anchored dropdown


  Click Model or Format to open a menu below that button.
  This version expands the view layout without changing its text.
  Click an option, the button again, or Close to dismiss the menu.

  Buttons


  Click a button to call its Python handler and see a status message.
  Red, green and yellow use the current color scheme palette.
  All components are mouse-operated; no custom keybindings.

  Toolbar prototype


  Settings, run, restart, stop, a configuration picker, Console and Callstack.
  This is a standalone UI preview, not connected to Debugger.
  Every button only reports its click in the status bar.

  Import inside this package:
      from . import anchored_dropdown, buttons, dropdown, floating_dropdown, toolbar

  Import from another package:
      from UIElements import anchored_dropdown, buttons, dropdown, floating_dropdown, toolbar

  See README.md in the UIElements package for complete examples.
"""


def _attach(view, point=None):
    for row in _rows.pop(view.id(), []):
        row.detach()
    saved = view.settings().get(SETTING_VALUES, {})

    def changed(key, value):
        saved[key] = value
        view.settings().set(SETTING_VALUES, saved)
        view.set_status(SETTING_DEMO, "Selected {}: {}".format(key, value))

    def clicked(label):
        message = "Clicked: {}".format(label)
        view.set_status(SETTING_DEMO, message)
        sublime.status_message(message)

    fields = [
        dropdown.Field("model", "Model", [dropdown.Option(*option) for option in MODELS]),
        dropdown.Field("format", "Format", ["JSON", "HTML", "SARIF"]),
    ]
    groups = [
        (3, floating_dropdown, "Floating dropdown - anchored to editor text"),
        (10, anchored_dropdown, "Anchored dropdown - expands below the button"),
    ]
    rows = _rows[view.id()] = []
    values = {f.key: saved[f.key] for f in fields if f.key in saved and any(
        (o.value if isinstance(o, dropdown.Option) else o) == saved[f.key] for o in f.options)}
    for index, (line, component, heading) in enumerate(groups):
        key = "ui_elements_demo_{}".format(index)
        view.erase_phantoms(key)
        rows.append(component.attach(
            view, fields, region=sublime.Region(point if point is not None else view.text_point(line, 0)),
            phantom_key=key, values=values, on_change=changed, heading=heading))
    key = "ui_elements_demo_buttons"
    view.erase_phantoms(key)
    rows.append(buttons.attach(view, [
        buttons.btn("default", "btn", lambda: clicked("btn")),
        buttons.btn_red("red", "btn-red", lambda: clicked("btn-red")),
        buttons.btn_green("green", "btn-green", lambda: clicked("btn-green")),
        buttons.btn_yellow("yellow", "btn-yellow", lambda: clicked("btn-yellow")),
    ], region=sublime.Region(point if point is not None else view.text_point(17, 0)),
        phantom_key=key, heading="Buttons - Python on_click callbacks"))

    def toolbar_clicked(action):
        clicked("{}: {}".format(action, toolbar_row.values["configuration"]))

    configurations = ["Run Installer", "Launch Application", "Attach Process"]
    selected = saved.get("configuration", configurations[0])
    selected = selected if selected in configurations else configurations[0]
    key = "ui_elements_demo_toolbar"
    view.erase_phantoms(key)
    toolbar_row = toolbar.attach(view, [
        buttons.icon("settings", "settings", lambda: toolbar_clicked("Settings"), title="Settings"),
        buttons.icon("run", "play", lambda: toolbar_clicked("Run"), title="Run selected configuration"),
        buttons.icon("restart", "restart", lambda: toolbar_clicked("Restart"), title="Restart selected configuration"),
        buttons.icon("stop", "stop", lambda: toolbar_clicked("Stop"), title="Stop selected configuration"),
        dropdown.Field("configuration", "", configurations),
        buttons.btn("console", "Console", lambda: clicked("Console")),
        buttons.btn("callstack", "Callstack", lambda: clicked("Callstack")),
    ], region=sublime.Region(point if point is not None else view.text_point(24, 0)),
        phantom_key=key, values={"configuration": selected}, on_change=changed,
        heading="Debugger-style toolbar - preview only")
    rows.append(toolbar_row)


class UiElementsDrawCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        selections = self.view.sel()
        point = self.view.line(selections[0].end()).end() if selections else 0
        _attach(self.view, point=point)
        self.view.show(point)


class UiElementsDemoCommand(sublime_plugin.WindowCommand):
    def run(self):
        for view in self.window.views():
            if view.settings().get(SETTING_DEMO):
                self.window.focus_view(view)
                _attach(view)
                return
        view = self.window.new_file()
        view.set_name("UIElements Demo")
        view.set_scratch(True)
        view.settings().set(SETTING_DEMO, True)
        view.settings().set("word_wrap", False)
        view.settings().set("line_numbers", False)
        view.settings().set("gutter", False)
        view.settings().set("draw_white_space", "none")
        view.run_command("append", {"characters": CONTENT})
        view.set_read_only(True)
        _attach(view)


class UiElementsDemoListener(sublime_plugin.EventListener):
    def on_close(self, view):
        for row in _rows.pop(view.id(), []):
            row.detach()


def plugin_loaded():
    for window in sublime.windows():
        for view in window.views():
            for key in ("dropdown_buttons", "dropdown_buttons_html",
                        "anchored_dropdown_demo_0", "anchored_dropdown_demo_1"):
                view.erase_phantoms(key)
            view.settings().erase("dropdown_html_menu_open")
            if view.settings().get(SETTING_DEMO):
                _attach(view)


def plugin_unloaded():
    for rows in list(_rows.values()):
        for row in rows:
            row.detach()
    _rows.clear()
