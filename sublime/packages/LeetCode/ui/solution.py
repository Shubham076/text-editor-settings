"""Opening a problem as a solution file, and running or submitting the solution in a view."""

import os

import sublime
import sublime_plugin

from ..core import client, config, testcases
from ..core.problem import (DEFAULT_LANGUAGE, extract_code, file_name, refreshed_header,
                            render_template)
from . import test_panel
from .tasks import run_async
from .views import mark_solution, set_text, solution_info

SUBMIT_PANEL = "leetcode_submit"


class LeetcodeOpenProblemCommand(sublime_plugin.WindowCommand):
    """Open a problem by slug: the existing solution if there is one, a new template otherwise."""

    def run(self, slug):
        language = config.get("default_language", DEFAULT_LANGUAGE)
        sublime.status_message("LeetCode: opening {}...".format(slug))
        run_async(lambda: client.fetch_question(slug), lambda question: self._open(question, language))

    def _open(self, question, language):
        if not question.content and not question.snippets:
            sublime.error_message("LeetCode: '{}' is a premium problem this account cannot open."
                                  .format(question.title))
            return
        name = file_name(question, language)
        folder = self._folder()
        if folder:
            path = os.path.join(folder, name)
            view = self.window.find_open_file(path)
            if not view and os.path.exists(path):
                view = self.window.open_file(path)  # never overwrite a solution already on disk
            elif not view:
                view = self._new_view(question, language, name)
                view.retarget(path)
        else:
            view = next((v for v in self.window.views() if v.name() == name), None)
            if not view:
                view = self._new_view(question, language, name)
                view.set_scratch(True)
        mark_solution(view, question.slug, language)
        self.window.focus_view(view)
        _when_loaded(view, lambda: _refresh_header(view, question, language))
        test_panel.panel_for(self.window).show(view, question, language)

    def _folder(self):
        """Where solution files are saved, or None to use an unsaved buffer."""
        if not config.get("save_problems_as_files", False):
            return None
        folders = self.window.folders()
        return config.get("problems_directory") or (folders[0] if folders else None)

    def _new_view(self, question, language, name):
        view = self.window.new_file()
        view.set_name(name)
        syntax = sublime.find_syntax_for_file(name)
        if syntax:
            view.assign_syntax(syntax)
        set_text(view, render_template(question, language), read_only=False)
        return view


def _when_loaded(view, action):
    if view.is_loading():
        sublime.set_timeout(lambda: _when_loaded(view, action), 50)
    elif view.is_valid():
        action()


def _refresh_header(view, question, language):
    """Bring the problem header of an existing solution up to date; the code is not touched
    and the file is not saved."""
    change = refreshed_header(view.substr(sublime.Region(0, view.size())), question, language)
    if change and not view.is_read_only():
        view.run_command("leetcode_replace_header", {"text": change[0], "length": change[1]})


class _SolutionCommand(sublime_plugin.WindowCommand):
    """Base for commands that act on the LeetCode solution in the active view."""

    def is_enabled(self):
        view = self.window.active_view()
        return bool(view and solution_info(view))


class LeetcodeShowTestCasesCommand(_SolutionCommand):
    def run(self):
        test_panel.open_for(self.window.active_view())


class LeetcodeRunTestsCommand(_SolutionCommand):
    """Run every test case of the active solution on LeetCode's judge."""

    def run(self):
        test_panel.open_for(self.window.active_view(), lambda panel: panel.run())


class LeetcodeAddTestCaseCommand(_SolutionCommand):
    def run(self):
        test_panel.open_for(self.window.active_view(), lambda panel: panel.add())


class LeetcodeSubmitSolutionCommand(sublime_plugin.WindowCommand):
    """Submit the active solution, or the one the test panel is showing."""

    def _solution_view(self):
        view = self.window.active_view()
        if view and solution_info(view):
            return view
        return test_panel.current_source(self.window)

    def is_enabled(self):
        return self._solution_view() is not None

    def run(self):
        view = self._solution_view()
        info = solution_info(view)
        code = extract_code(view.substr(sublime.Region(0, view.size())))
        output = self.window.create_output_panel(SUBMIT_PANEL)
        self.window.run_command("show_panel", {"panel": "output." + SUBMIT_PANEL})
        set_text(output, "Submitting {} ({})...\n".format(info.slug, info.language))

        def work():
            return client.submit(client.fetch_question(info.slug), info.language, code)

        run_async(work, lambda response: set_text(output, testcases.format_submission(response)),
                  lambda message: set_text(output, message + "\n"))
