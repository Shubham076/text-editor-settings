"""The test case panel: one per window, shown beside the solution it runs."""

import sublime
import sublime_plugin

from ..core import client, config, test_panel_html, testcases
from ..core.problem import extract_code
from ..core.testcases import TestCase
from .tasks import run_async
from .views import set_text, solution_info

PANEL_SETTING = "leetcode_test_panel"
DISMISSED_SETTING = "leetcode_test_panel_dismissed"  # on a solution whose panel the user closed
# On the panel view when this package split the window for it. Kept on the view, not in
# memory, so it survives a restart or a package reload and the split can still be undone.
SPLIT_SETTING = "leetcode_test_panel_split"
PANEL_NAME = "LeetCode Test Cases"
TWO_COLUMNS = {"cols": [0.0, 0.7, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]}
ONE_COLUMN = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}

_panels = {}  # window id -> TestPanel


def panel_for(window):
    if window.id() not in _panels:
        _panels[window.id()] = TestPanel(window)
    return _panels[window.id()]


def open_for(view, then=None, quiet=False):
    """Show the test panel for the solution in ``view``, then call ``then(panel)``.

    ``quiet`` reports a failure in the status bar instead of a dialog, for callers the user
    did not invoke directly.
    """
    window, info = view.window(), solution_info(view)
    if not window or not info:
        sublime.status_message("LeetCode: this is not a LeetCode solution file")
        return

    def ready(question):
        if not view.is_valid():
            return
        panel = panel_for(window)
        panel.show(view, question, info.language)
        if then:
            then(panel)

    run_async(lambda: client.fetch_question(info.slug), ready,
              sublime.status_message if quiet else None)


class TestPanel:
    def __init__(self, window):
        self.window = window
        self.view = None
        self.source = None  # the solution view the cases run against
        self.question = None
        self.language = ""
        self.cases = []
        self.message = ""  # compile/runtime error or request failure of the last run
        self.running = False
        self._phantoms = None  # must outlive the phantom it draws

    # -- state -------------------------------------------------------------------------

    def show(self, source, question, language):
        same = (self.source is not None and self.source.id() == source.id()
                and self.question is not None and self.question.slug == question.slug)
        self.source, self.question, self.language = source, question, language
        if not same:
            self.message = ""
            self.cases = testcases.example_cases(
                question.example_inputs, testcases.example_outputs(question.content),
                len(question.param_names))
            saved = config.read_cache(self._custom_cache()) or []
            self.cases += [TestCase(values, custom=True) for values in saved]
        source.settings().erase(DISMISSED_SETTING)
        self._ensure_view()
        self.render()

    def _custom_cache(self):
        return "testcases_" + self.question.slug

    def _save_custom(self):
        config.write_cache(self._custom_cache(), [case.values for case in self.cases if case.custom])

    # -- actions -----------------------------------------------------------------------

    def add(self):
        seed = self.cases[0].values if self.cases else []
        self._prompt("Add test case", seed, lambda values: self.cases.append(TestCase(values, custom=True)))

    def edit(self, index):
        case = self.cases[index]

        def update(values):
            case.values, case.expected = values, ""
            case.reset()

        self._prompt("Edit test case", case.values, update)

    def copy(self, index, field):
        """Put one value of a case on the clipboard, in full even when the panel cut it."""
        case = self.cases[index]
        text = {"input": "\n".join(case.values), "expected": case.expected,
                "output": case.actual, "stdout": case.stdout}.get(field) or ""
        sublime.set_clipboard(text)
        sublime.status_message("LeetCode: copied test {} {}".format(index + 1, field))

    def delete(self, index):
        del self.cases[index]
        self._save_custom()
        self.render()

    def _prompt(self, title, values, apply, text=None):
        """Ask for a test input, prefilled so the user edits values instead of retyping the shape."""
        names, slug = self.question.param_names, self.question.slug
        if text is None:
            text = testcases.format_input(values, names)

        def done(entered):
            if not entered.strip() or self.question.slug != slug:
                return
            try:
                parsed = testcases.parse_input(entered, names)
            except ValueError as error:
                sublime.error_message("LeetCode: {}".format(error))
                self._prompt(title, values, apply, entered)
                return
            apply(parsed)
            self._save_custom()
            self.render()

        self.window.show_input_panel("{} ({}):".format(title, ", ".join(names)), text, done, None, None)

    def run(self, index=None):
        """Run one case, or all of them, on LeetCode's judge in a single request."""
        if self.running:
            sublime.status_message("LeetCode: a run is already in progress")
            return
        if self.source is None or not self.source.is_valid():
            return
        selected = self.cases if index is None else [self.cases[index]]
        if not selected:
            sublime.status_message("LeetCode: there are no test cases to run")
            return
        code = extract_code(self.source.substr(sublime.Region(0, self.source.size())))
        question, language, data = self.question, self.language, testcases.data_input(selected)
        for case in selected:
            case.reset()
            case.status = "running"
        self.running, self.message = True, ""
        self.render(scroll_to_top=True)

        def finished(response):
            result = testcases.parse_run_result(response, len(selected))
            testcases.apply_run_result(selected, result)
            self._run_ended(result.error)

        def failed(message):
            for case in selected:
                case.reset()
            self._run_ended(message)

        run_async(lambda: client.run_code(question, language, code, data), finished, failed)

    def _run_ended(self, message):
        self.running, self.message = False, message
        self.render(scroll_to_top=True)

    # -- view --------------------------------------------------------------------------

    def _ensure_view(self):
        if self.view and self.view.is_valid():
            return
        restored = [v for v in self.window.views() if v.settings().get(PANEL_SETTING)]
        if restored:  # left over from the previous session
            self.view = restored[0]
            return
        made_split = self.window.num_groups() == 1
        if made_split:
            self.window.set_layout(TWO_COLUMNS)
        self.window.focus_group(self.window.num_groups() - 1)
        self.view = self.window.new_file()
        self.view.set_name(PANEL_NAME)
        self.view.set_scratch(True)
        settings = self.view.settings()
        for key, value in ((PANEL_SETTING, True), (SPLIT_SETTING, made_split), ("word_wrap", False),
                           ("line_numbers", False), ("gutter", False), ("rulers", []), ("draw_indent_guides", False),
                           ("highlight_line", False), ("scroll_past_end", False)):
            settings.set(key, value)
        self.window.focus_view(self.source)

    def render(self, scroll_to_top=False):
        """Draw the panel as a single phantom: every control is a link and nothing is text
        the user could edit. ``scroll_to_top`` brings the banner into view."""
        if not (self.view and self.view.is_valid()):
            return
        if self._phantoms is None or self._phantoms.view.id() != self.view.id():
            self._phantoms = sublime.PhantomSet(self.view, PANEL_SETTING)
        title = test_panel_html.title(self.question, self.language)
        if self.view.substr(sublime.Region(0, self.view.size())) != title:
            set_text(self.view, title)  # the phantom hangs below this line
        # A little short of the view's width, so no horizontal scrollbar appears.
        width = self.view.viewport_extent()[0] - 16
        html = test_panel_html.render(self.question, self.cases, self.message, self.running,
                                      width, self.view.em_width())
        self._phantoms.update([sublime.Phantom(sublime.Region(0), html, sublime.LAYOUT_BLOCK, self._navigate)])
        if scroll_to_top:
            self.view.set_viewport_position((0, 0), False)

    def _navigate(self, href):
        action, _, index = href.partition(":")
        if action == "submit":
            self.window.run_command("leetcode_submit_solution")
        elif action == "add":
            self.add()
        elif action.startswith("copy-") and index.isdigit() and int(index) < len(self.cases):
            self.copy(int(index), action[len("copy-"):])
        elif index.isdigit() and int(index) < len(self.cases):
            {"run": self.run, "edit": self.edit, "delete": self.delete}[action](int(index))
        elif action == "run":
            self.run()

    def close(self):
        """Close the panel and undo the split made for it. Also called when the user closes
        the panel's tab themselves."""
        view, self.view, self.source, self.question = self.view, None, None, None
        self._phantoms = None
        _panels.pop(self.window.id(), None)
        if view is None:
            return
        made_split = bool(view.settings().get(SPLIT_SETTING))
        # Closing a view from inside another view's close event is not safe; do it after.
        sublime.set_timeout(lambda: self._dispose(view, made_split))

    def _dispose(self, view, made_split):
        if view.is_valid():
            view.close()
        window = self.window
        if not (made_split and window.is_valid() and window.num_groups() == 2):
            return
        if all(other.id() == view.id() for other in window.views_in_group(1)):
            window.set_layout(ONE_COLUMN)  # the group held nothing but the panel


def current_source(window):
    """The solution view the window's panel is showing, if any."""
    panel = _panels.get(window.id())
    return panel.source if panel else None


class LeetcodeTestPanelListener(sublime_plugin.EventListener):
    def on_activated(self, view):
        self._follow(view)

    def on_load(self, view):
        # A file still loading when it got focus had no header to read yet.
        window = view.window()
        if window and window.active_view() == view:
            self._follow(view)

    def _follow(self, view):
        """Keep the window's panel on the focused solution.

        - A panel whose solution was closed moves to the solution that got focus, or closes.
        - A focused solution gets a panel (``auto_show_test_cases``), unless the user closed
          the panel while on it; then it stays closed until they ask for it.
        """
        window = view.window()
        if not window:
            return
        panel = _panels.get(window.id())
        if panel and panel.source is not None and panel.source.id() == view.id():
            return
        is_solution = not view.settings().get(PANEL_SETTING) and bool(solution_info(view))
        if panel and panel.source is None and not is_solution:
            if not view.is_loading():
                panel.close()
            return
        if not is_solution or not config.get("auto_show_test_cases", True):
            return
        if panel is None and view.settings().get(DISMISSED_SETTING):
            return
        open_for(view, quiet=True)

    def on_query_context(self, view, key, operator, operand, match_all):
        """``leetcode.solution``: lets key bindings apply only in solution files."""
        if key == "leetcode.solution":
            return bool(solution_info(view)) == bool(operand)
        return None

    def on_pre_close(self, view):
        for panel in list(_panels.values()):
            if panel.view is not None and panel.view.id() == view.id():
                if panel.source is not None:  # the user closed the panel: do not reopen it
                    panel.source.settings().set(DISMISSED_SETTING, True)
                panel.close()
            elif panel.source is not None and panel.source.id() == view.id():
                panel.source = None  # the view that gets focus next decides: see _follow
                others = [v for v in panel.window.views()
                          if v.id() != view.id() and not v.settings().get(PANEL_SETTING)]
                if not others:  # nothing left to take focus, so nothing would decide
                    panel.close()
