"""The problem list: loading it, searching it, and the list panel."""

import sublime
import sublime_plugin

from ..core import client, config, problem_list
from ..core.problem_list import ListState
from .tasks import run_async
from .views import set_text

PANEL_NAME = "leetcode_problems"

_problems = []  # problem_list.Problem, in site order
_panels = {}  # window id -> ProblemsPanel


def load(on_done=None, force=False):
    """Make the problem list available, from memory, the cache or LeetCode, then call back."""
    global _problems
    if not force and not _problems:
        cached = config.read_cache("problems", config.get("cache_expiry", 86400))
        _problems = problem_list.problems_from_api(cached or [])
    if _problems and not force:
        if on_done:
            on_done()
        return

    def loaded(pairs):
        global _problems
        _problems = problem_list.problems_from_api(pairs)
        config.write_cache("problems", pairs)
        sublime.status_message("LeetCode: {} problems loaded".format(len(_problems)))
        if on_done:
            on_done()

    sublime.status_message("LeetCode: loading problems...")
    run_async(client.fetch_problem_list, loaded)


def slug_for_title(title):
    return next((problem.slug for problem in _problems if problem.title == title), None)


class ProblemsPanel:
    """A bottom panel holding one phantom: the styled, paged list. Clicks arrive as link
    navigations, so there is no mouse handling here."""

    def __init__(self, window):
        self.window = window
        self.state = ListState()
        self.view = window.create_output_panel(PANEL_NAME)
        settings = self.view.settings()
        for key, value in (("gutter", False), ("line_numbers", False), ("word_wrap", False),
                           ("scroll_past_end", False), ("draw_indent_guides", False),
                           ("highlight_line", False)):
            settings.set(key, value)
        set_text(self.view, "LeetCode problems")  # the phantom hangs below this line
        self.phantoms = sublime.PhantomSet(self.view, PANEL_NAME)  # must outlive the phantom

    def show(self):
        self.render()
        self.window.run_command("show_panel", {"panel": "output." + PANEL_NAME})

    def render(self):
        html = problem_list.render(_problems, self.state)
        self.phantoms.update([sublime.Phantom(sublime.Region(0), html, sublime.LAYOUT_BLOCK, self.navigate)])

    def navigate(self, href):
        kind, _, value = href.partition(":")
        if kind == "open":
            self.window.run_command("leetcode_open_problem", {"slug": value})
        elif kind == "search":
            self.window.run_command("leetcode_search")
        elif kind == "refresh":
            load(self.render, force=True)
        else:
            if kind == "page":
                self.state.page = int(value)
            else:  # "difficulty" or "status": a new filter starts from its first page
                setattr(self.state, kind, value)
                self.state.page = 0
            self.render()
            self.view.set_viewport_position((0, 0), False)


class LeetcodeSearchCommand(sublime_plugin.WindowCommand):
    """Pick a problem from a fuzzy-searchable list."""

    def run(self):
        load(self._show)

    def _show(self):
        items = [sublime.QuickPanelItem(
            "{}. {}".format(problem.number, problem.title),
            annotation=", ".join(note for note in (
                problem.difficulty, "solved" if problem.solved else "",
                "premium" if problem.premium else "") if note)) for problem in _problems]
        self.window.show_quick_panel(items, lambda index: index >= 0 and self.window.run_command(
            "leetcode_open_problem", {"slug": _problems[index].slug}))


class LeetcodeShowProblemsCommand(sublime_plugin.WindowCommand):
    """Show every problem in a bottom panel; clicking a row opens it."""

    def run(self):
        load(self._show)

    def _show(self):
        panel = _panels.get(self.window.id())
        if panel is None or not panel.view.is_valid():
            panel = _panels[self.window.id()] = ProblemsPanel(self.window)
        panel.show()


class LeetcodeRefreshProblemsCommand(sublime_plugin.WindowCommand):
    def run(self):
        panel = _panels.get(self.window.id())
        load(panel.render if panel else None, force=True)
