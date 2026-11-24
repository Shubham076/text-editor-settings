"""Helpers for the views this package writes to and reads solutions from."""

import os

import sublime
import sublime_plugin

from ..core import config
from ..core.problem import DEFAULT_LANGUAGE, SolutionInfo, language_for_extension, parse_header

SOLUTION_SETTING = "leetcode_solution"


class LeetcodeSetTextCommand(sublime_plugin.TextCommand):
    """Replace the whole buffer. Unlike the ``insert`` command this never auto-indents."""

    def run(self, edit, text):
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(0))


class LeetcodeReplaceHeaderCommand(sublime_plugin.TextCommand):
    """Replace the first ``length`` characters, the problem header, leaving the code and the
    cursor where they are."""

    def run(self, edit, text, length):
        self.view.replace(edit, sublime.Region(0, length), text)


def set_text(view, text, read_only=True):
    view.set_read_only(False)
    view.run_command("leetcode_set_text", {"text": text})
    view.set_read_only(read_only)


def mark_solution(view, slug, language):
    view.settings().set(SOLUTION_SETTING, {"slug": slug, "language": language})


def solution_info(view):
    """Which problem and language a view holds a solution for, or None if it is not one."""
    from . import problems  # problems imports this module

    known = view.settings().get(SOLUTION_SETTING)
    if known:
        return SolutionInfo(known["slug"], known["language"])
    if view.element() is not None or view.is_loading():
        return None
    info = parse_header(view.substr(sublime.Region(0, 4000)), problems.slug_for_title)
    if not info:
        return None
    extension = os.path.splitext(view.file_name() or "")[1]
    language = (info.language or language_for_extension(extension)
                or config.get("default_language", DEFAULT_LANGUAGE))
    mark_solution(view, info.slug, language)
    return SolutionInfo(info.slug, language)
