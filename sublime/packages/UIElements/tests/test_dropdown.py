import ast
from collections import OrderedDict
import importlib
import json
from pathlib import Path
import re
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Region:
    def __init__(self, point):
        self.point = point

    def begin(self):
        return self.point

    def end(self):
        return self.point


class View:
    def __init__(self):
        self.phantoms = OrderedDict()
        self.serial = 0
        self.visible = False
        self.popup_count = 0
        self.hide_count = 0

    def id(self):
        return id(self)

    def is_valid(self):
        return True

    def style(self):
        return {"background": "#fcf5f5", "foreground": "#606060"}

    def add_phantom(self, key, region, content, layout, on_navigate):
        self.serial += 1
        self.phantoms[self.serial] = (region, content, on_navigate)
        return self.serial

    def erase_phantom_by_id(self, pid):
        self.phantoms.pop(pid, None)

    def query_phantom(self, pid):
        return [self.phantoms[pid][0]]

    def line(self, point):
        return Region(point)

    def size(self):
        return 100

    def show_popup(self, content, **kwargs):
        self.visible = True
        self.popup_count += 1
        self.popup_content = content
        self.popup_flags = kwargs.get("flags", 0)
        self.on_pick = kwargs["on_navigate"]
        self.on_hide = kwargs["on_hide"]

    def is_popup_visible(self):
        return self.visible

    def hide_popup(self):
        self.visible = False
        self.hide_count += 1
        if hasattr(self, "on_hide"):
            self.on_hide()


class DropdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {name: sys.modules.get(name) for name in ("sublime", "sublime_plugin")}
        sublime = types.ModuleType("sublime")
        sublime.Region, sublime.LAYOUT_BLOCK = Region, 2
        sublime.KEEP_ON_SELECTION_MODIFIED = 16
        plugin = types.ModuleType("sublime_plugin")
        plugin.EventListener = type("EventListener", (), {})
        package = types.ModuleType("_dropdown_test_package")
        package.__path__ = [str(ROOT)]
        sys.modules.update(sublime=sublime, sublime_plugin=plugin, _dropdown_test_package=package)
        cls.dropdown = importlib.import_module("_dropdown_test_package.dropdown")
        cls.html = importlib.import_module("_dropdown_test_package.dropdown_html")

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in list(sys.modules):
            if name.startswith("_dropdown_test_package"):
                sys.modules.pop(name)

    def setUp(self):
        self.view = View()
        self.changes = []
        self.fields = [
            self.dropdown.Field("model", "Model", ["Wide model", "Small"]),
            self.dropdown.Field("format", "Format", ["JSON", "HTML", "SARIF"]),
        ]
        self.floating = self.attach("popup")
        self.inline = self.attach("inline")

    def tearDown(self):
        self.dropdown.plugin_unloaded()

    def attach(self, mode, point=0, view=None):
        return self.dropdown.attach(
            view or self.view, self.fields, region=Region(point), menu_mode=mode,
            on_change=lambda key, value: self.changes.append((key, value)))

    def click(self, row, href):
        row.view.phantoms[row._pid][2](href)

    def content(self, row):
        return row.view.phantoms[row._pid][1]

    def assert_order(self):
        self.assertEqual(list(self.view.phantoms), [self.floating._pid, self.inline._pid])

    def test_bottom_top_bottom_keeps_creation_order(self):
        self.assert_order()
        for _ in range(5):
            self.click(self.inline, "open:1")
            self.assert_order()
            self.click(self.floating, "open:1")
            self.assert_order()
            self.assertIsNone(self.inline.open_field)
            self.click(self.inline, "open:1")
            self.assert_order()
            self.assertIsNone(self.floating.open_field)
            self.click(self.inline, "close")
            self.assert_order()

    def test_selection_rerender_keeps_order(self):
        self.click(self.inline, "open:1")
        self.click(self.inline, "pick:1")
        self.assertEqual(self.inline.values["format"], "HTML")
        self.assertEqual(self.changes, [("format", "HTML")])
        self.assert_order()
        self.click(self.floating, "open:1")
        self.view.on_pick("pick:2")
        self.assertEqual(self.floating.values["format"], "SARIF")
        self.assert_order()

    def test_other_positions_and_views_are_not_redrawn(self):
        elsewhere = self.attach("inline", point=20)
        other_view = self.attach("inline", view=View())
        other_ids = elsewhere._pid, other_view._pid
        self.inline.open("format")
        self.assertEqual(other_ids, (elsewhere._pid, other_view._pid))

    def test_buffer_edits_preserve_shared_anchor_and_order(self):
        for pid, (_, content, callback) in list(self.view.phantoms.items()):
            self.view.phantoms[pid] = (Region(30), content, callback)
        self.inline.open("format")
        self.assert_order()
        self.assertTrue(all(item[0].begin() == 30 for item in self.view.phantoms.values()))

    def test_stale_callbacks_cannot_select_another_field(self):
        self.inline.open("format")
        callback = self.view.phantoms[self.inline._pid][2]
        self.inline.open("model")
        callback("pick:1")
        callback("close")
        self.assertEqual(self.inline.values["model"], "Wide model")
        self.assertEqual(self.inline.open_field, "model")

    def test_inline_has_explicit_width_and_footer_clearance(self):
        self.inline.open("format")
        content = self.content(self.inline)
        self.assertRegex(content, r"\.inline-menu\s*\{[^}]*width:\s*24rem;")
        self.assertRegex(content, r"\.expanded\s*\{[^}]*padding-bottom:\s*2rem;")
        self.assertIn('class="menu inline-menu"', content)
        self.assertIn('class="item active" href="pick:0"', content)
        self.assertEqual(self.view.popup_count, 0)
        button = re.search(r'<a class="button" href="open:0">(.*?)</a>', content).group(1)
        spacer = re.search(r'<span class="button spacer">(.*?)</span>&nbsp;', content).group(1)
        self.assertEqual(button, spacer)

    def test_inline_close_does_not_hide_unrelated_popup(self):
        self.view.visible = True
        self.inline.open("format")
        self.click(self.inline, "close")
        self.assertTrue(self.view.visible)
        self.assertEqual(self.view.hide_count, 0)

    def test_detach_leaves_other_row_intact(self):
        self.inline.open("format")
        self.floating.detach()
        self.assertEqual(list(self.view.phantoms), [self.inline._pid])
        self.assertEqual(self.inline.open_field, "format")
        self.inline.detach()
        self.inline.detach()
        self.assertFalse(self.view.phantoms)

    def test_menu_only_selection_without_phantoms(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        selected, hidden = [], []
        ids = list(self.view.phantoms)
        menu = floating.show(self.view, ["JSON", "HTML"], selected="JSON", on_select=selected.append,
                             on_hide=lambda: hidden.append(True))
        self.assertEqual(list(self.view.phantoms), ids)
        self.view.on_pick("pick:0")
        self.assertEqual(selected, ["JSON"])
        self.assertEqual(hidden, [True])
        self.assertTrue(menu.closed)
        menu.close()
        self.assertEqual(hidden, [True])

    def test_menu_only_search_and_stale_callbacks(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        events = []
        floating.show(self.view, ["JSON", "HTML"], on_select=lambda value: events.append(value))
        previous = self.view.on_pick
        floating.show(self.view, ["JSON"], on_hide=lambda: events.append("hidden"),
                      on_search=lambda: events.append("search"))
        self.assertIn('href="search"', self.view.popup_content)
        self.assertLess(self.view.popup_content.index('href="search"'), self.view.popup_content.index('href="pick:0"'))
        previous("pick:1")
        self.assertEqual(events, [])
        self.view.on_pick("search")
        self.assertEqual(events, ["hidden", "search"])

    def test_menu_only_lifecycle_and_validation(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        self.assertIsNone(floating.show(self.view, []))
        with self.assertRaises(ValueError):
            floating.show(self.view, ["JSON"], selected="missing")
        menu = floating.show(self.view, ["JSON"])
        self.dropdown.UiElementsListener().on_close(self.view)
        self.assertTrue(menu.closed)
        self.assertNotIn(self.view.id(), self.dropdown._active)

    def test_menu_only_can_follow_console_output_without_dismissal(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        menu = floating.show(self.view, ["JSON"], keep_on_selection_modified=True)
        self.assertEqual(self.view.popup_flags, 16)
        listener = self.dropdown.UiElementsListener()
        listener.on_selection_modified(self.view)
        self.assertFalse(menu.closed)
        listener.on_deactivated(self.view)
        self.assertTrue(menu.closed)

    def test_menu_only_font_size_and_aligned_marks(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        floating.show(self.view, ["JSON", "HTML"], selected="HTML")
        self.assertNotIn("html { font-size:", self.view.popup_content)
        floating.show(self.view, ["JSON", "HTML"], selected="HTML", font_size=14)
        self.assertIn("html { font-size: 14px; }", self.view.popup_content)
        self.assertIn('<span class="mark"></span><span class="label">JSON</span>', self.view.popup_content)
        self.assertIn('<span class="mark">&#10003;</span><span class="label">HTML</span>', self.view.popup_content)

    def test_menu_only_badges_groups_and_footer_action(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        events = []
        options = [self.dropdown.Option("api", "API Server", "Python · launch", "Launch", "Paused", "yellowish"),
                   self.dropdown.Option("tests", "Integration Tests", "Python · tests", "Tests", "Stopped")]
        with self.assertRaises(ValueError):
            floating.show(self.view, options, action=("Edit", "not callable"))
        menu = floating.show(self.view, options, selected="api", action=("Edit configurations", lambda: events.append("edit")))
        content = self.view.popup_content
        self.assertIn('<div class="group">LAUNCH</div>', content)
        self.assertIn('<span class="badge badge-yellowish">&#9679; Paused</span>', content)
        self.assertIn('<span class="badge">&#9679; Stopped</span>', content)
        self.assertIn('<a class="action" href="action">Edit configurations</a>', content)
        self.assertIn('<a class="hint" href="close">Esc to close</a>', content)
        self.view.on_pick("action")
        self.assertEqual(events, ["edit"])
        self.assertTrue(menu.closed)
        with self.assertRaises(ValueError):
            self.dropdown._normalize_options([self.dropdown.Option("x", "X", badge=1)])

    def test_named_dropdown_components(self):
        floating = importlib.import_module("_dropdown_test_package.floating_dropdown")
        anchored = importlib.import_module("_dropdown_test_package.anchored_dropdown")
        self.assertEqual(floating.attach(self.view, self.fields).menu_mode, "popup")
        self.assertEqual(anchored.attach(self.view, self.fields).menu_mode, "inline")

    def test_button_variants_and_callbacks(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        clicked = []
        row = buttons.attach(self.view, [
            buttons.btn("default", "Default", lambda: clicked.append("default")),
            buttons.btn_red("red", "Red", lambda: clicked.append("red")),
            buttons.btn_green("green", "Green", lambda: clicked.append("green")),
            buttons.btn_yellow("yellow", "Yellow", lambda: clicked.append("yellow")),
        ])
        content = self.content(row)
        for color in ("redish", "greenish", "yellowish"):
            self.assertIn("var(--{})".format(color), content)
        for index, variant in enumerate(("btn", "btn-red", "btn-green", "btn-yellow")):
            self.assertIn('class="button {}" href="click:{}"'.format(variant, index), content)
        for index, expected in enumerate(("default", "red", "green", "yellow")):
            self.click(row, "click:{}".format(index))
            self.assertEqual(clicked[-1], expected)
        self.inline.open("format")
        self.assertEqual(list(self.view.phantoms), [self.floating._pid, self.inline._pid, row._pid])
        self.click(row, "click:0")
        self.assertIsNone(self.inline.open_field)
        self.assertEqual(len(clicked), 5)

    def test_buttons_validate_escape_and_ignore_detached_clicks(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        clicked = []
        row = buttons.attach(self.view, [buttons.btn('key:"', '<Save & Run>', lambda: clicked.append(True))])
        self.assertIn("&lt;Save &amp; Run&gt;", self.content(row))
        self.assertNotIn('key:"', self.content(row))
        callback = self.view.phantoms[row._pid][2]
        row.detach()
        callback("click:0")
        self.assertEqual(clicked, [])
        with self.assertRaises(ValueError):
            buttons.attach(self.view, [buttons.Button("x", "X", lambda: None, "invalid")])
        with self.assertRaises(ValueError):
            buttons.attach(self.view, [buttons.btn("x", "X", lambda: None)] * 2)
        with self.assertRaises(ValueError):
            buttons.attach(self.view, [buttons.Button("x", "X", None)])

    def test_buttons_ignore_invalid_and_stale_events(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        clicked = []
        row = buttons.attach(self.view, [buttons.btn("run", "Run", lambda: clicked.append(True))])
        for href in ("click:-1", "click:100", "click:abc", "open:0", "close"):
            self.click(row, href)
        self.assertEqual(clicked, [])
        callback = self.view.phantoms[row._pid][2]
        row.render()
        callback("click:0")
        self.assertEqual(clicked, [])
        self.click(row, "click:0")
        self.assertEqual(clicked, [True])

    def test_toolbar_mixes_controls_and_routes_clicks(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        toolbar = importlib.import_module("_dropdown_test_package.toolbar")
        clicked = []
        row = toolbar.attach(self.view, [
            buttons.icon("run", "play", lambda: clicked.append("run"), title="Run configuration"),
            self.dropdown.Field("configuration", "", ["Run Installer", "Attach Process"]),
            buttons.btn("console", "Console", lambda: clicked.append("console")),
            buttons.btn("callstack", "Callstack", lambda: clicked.append("callstack")),
        ], on_change=lambda key, value: self.changes.append((key, value)))
        self.click(row, "open:0")
        self.assertIn('class="menu inline-menu"', self.content(row))
        self.click(row, "pick:1")
        self.assertEqual(row.values["configuration"], "Attach Process")
        self.assertEqual(self.changes, [("configuration", "Attach Process")])
        for index in range(3):
            self.click(row, "click:{}".format(index))
        self.assertEqual(clicked, ["run", "console", "callstack"])
        self.assertEqual(list(self.view.phantoms), [self.floating._pid, self.inline._pid, row._pid])

    def test_toolbar_spacers_and_floating_mode(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        toolbar = importlib.import_module("_dropdown_test_package.toolbar")
        items = [buttons.icon("settings", "settings", lambda: None), self.fields[0], self.fields[1]]
        row = toolbar.attach(self.view, items)
        self.click(row, "open:1")
        content = self.content(row)
        self.assertIn('class="icon-button spacer"', content)
        self.assertIn('class="button spacer"', content)
        self.assertIn('src="data:image/png;base64,', content)
        other = toolbar.attach(self.view, items, menu_mode="popup")
        self.click(other, "open:0")
        self.assertTrue(self.view.visible)
        self.assertIsNone(row.open_field)

    def test_toolbar_has_a_theme_derived_frame(self):
        toolbar = importlib.import_module("_dropdown_test_package.toolbar")
        row = toolbar.attach(self.view, self.fields)
        self.assertIn('<div class="toolbar">', self.content(row))
        self.assertNotIn('<div class="toolbar">', self.content(self.inline))
        self.click(row, "open:1")
        self.assertIn('<div class="toolbar-menu"><div class="expanded">', self.content(row))
        light = self.html._palette(self.view)
        self.assertNotEqual(light["toolbar_background"], light["background"])
        self.assertNotEqual(light["toolbar_background"], light["button"])
        self.view.style = lambda: {"background": "#202020", "foreground": "#dddddd"}
        dark = self.html._palette(self.view)
        self.assertGreater(int(dark["toolbar_background"][1:3], 16), 0x20)
        row.render()
        self.assertIn("background-color: " + dark["toolbar_background"], self.content(row))

    def test_toolbar_flat_controls_and_group_separators(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        toolbar = importlib.import_module("_dropdown_test_package.toolbar")
        row = toolbar.attach(self.view, [
            buttons.icon("run", "play", lambda: None), self.fields[0],
            buttons.btn("console", "Console", lambda: None),
        ])
        self.click(row, "open:0")
        content = self.content(row)
        self.assertRegex(content, r"\.toolbar \.button\s*\{[^}]*border-color:\s*transparent;")
        self.assertRegex(content, r"\.toolbar \.btn\s*\{[^}]*background-color:\s*transparent;")
        self.assertIn('.toolbar-divider { color: ' + self.view.style()['foreground'] + ';', content)
        self.assertEqual(content.count('<span class="toolbar-divider">'), 2)
        self.assertEqual(content.count('<span class="toolbar-divider spacer">'), 1)
        self.assertNotIn('<span class="toolbar-divider">', self.content(self.inline))

    def test_toolbar_rejects_bad_items_and_duplicate_keys(self):
        buttons = importlib.import_module("_dropdown_test_package.buttons")
        toolbar = importlib.import_module("_dropdown_test_package.toolbar")
        with self.assertRaises(ValueError):
            toolbar.attach(self.view, [object()])
        with self.assertRaises(ValueError):
            toolbar.attach(self.view, [self.fields[0], buttons.btn("model", "Run", lambda: None)])
        with self.assertRaises(ValueError):
            toolbar.attach(self.view, [buttons.icon("icon", "unknown", lambda: None)])

    def test_icons_are_color_aware_png_images(self):
        import base64
        import struct
        icons = importlib.import_module("_dropdown_test_package.icons")
        for name in ("settings", "play", "restart", "stop"):
            uri = icons.data_uri(name, "#606060")
            png = base64.b64decode(uri.split(",", 1)[1])
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", png[16:24]), (16, 16))
            self.assertNotEqual(uri, icons.data_uri(name, "#ffffff"))

    def test_python_38_syntax_and_commands(self):
        for path in ROOT.glob("*.py"):
            source = path.read_text()
            ast.parse(source, feature_version=(3, 8))
            compile(source, str(path), "exec")
        self.assertEqual(json.loads((ROOT / "Default.sublime-keymap").read_text()), [])
        commands = json.loads((ROOT / "Default.sublime-commands").read_text())
        self.assertEqual([c["command"] for c in commands], ["ui_elements_demo", "ui_elements_draw"])


if __name__ == "__main__":
    unittest.main()
