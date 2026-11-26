"""Searching what a terminal has printed

Sublime's Find is a panel and a window shows one panel at a time, so it cannot be used on a
terminal that lives in a panel: it would take the terminal's place. What a terminal printed
is the text of a view though, scrollback included, so it can be searched from a plugin. The
query is asked for in the command palette, which is an overlay and leaves the panel alone,
and every match is highlighted in the terminal as it is typed.

    terminus_search         asks for the text; enter lands on the match nearest the end
    terminus_search_next    the next match up (older output), or down with `forward`

Upper case in the query makes the search case sensitive, as in vim and less. The matches are
highlighted while the popup is open and not after: enter leaves the terminal scrolled to the
match. Stepping marks the one match it lands on, until a key is typed into the terminal.
"""

import sublime
import sublime_plugin


ALL_KEY = "terminus_search"
CURRENT_KEY = "terminus_search.current"

COUNT = '<span style="color: var(--foreground)">{}</span>'

# terminal view id -> {"query": what was searched for, "index": the match stepped to, "shown": highlights are up}
_searches = {}


def target(window, panel_name=None):
    """The terminal a search is for: the panel named, else the one showing, else the tab in focus"""
    if not window:
        return None
    if not panel_name:
        active = window.active_panel() or ""
        panel_name = active[len("output."):] if active.startswith("output.") else None
    view = window.find_output_panel(panel_name) if panel_name else None
    if view and view.settings().get("terminus_view"):
        return view
    view = window.active_view()
    if view and view.settings().get("terminus_view"):
        return view
    return None


def matches(view, query):
    if not query:
        return []
    flags = sublime.LITERAL
    if query == query.lower():
        flags |= sublime.IGNORECASE
    return view.find_all(query, flags)


def highlight(view, query, index=None, others=True):
    """Fills every match of `query`, and the one at `index` (the last, left out) in green

    Without `others` only the one at `index` is marked. Returns the matches and the index marked.
    """
    found = matches(view, query)
    if not found:
        clear(view, forget=False)
        return found, None
    if index is None:
        # the same text again (the popup opened again on it): the match stepped to stays
        state = _searches.get(view.id(), {})
        kept = state.get("index") if state.get("query") == query else None
        index = kept if kept is not None else len(found) - 1
    index %= len(found)
    # Two scopes the terminal's colour scheme defines for this (`Terminus.hidden-color-scheme`).
    # A rule that has a background fills the region with it and draws the text in its
    # foreground: a match is the text colour as the fill with the selection colour on it, the
    # one stepped to has its text in green.
    view.add_regions(
        ALL_KEY, found[:index] + found[index + 1:] if others else [],
        "terminus.search.match", "", sublime.DRAW_NO_OUTLINE)
    view.add_regions(CURRENT_KEY, [found[index]], "terminus.search.current", "", sublime.DRAW_NO_OUTLINE)
    view.show(found[index], True)
    state = _searches.setdefault(view.id(), {})
    state.update(query=query, index=index, shown=True)
    return found, index


def clear(view, forget=True):
    view.erase_regions(ALL_KEY)
    view.erase_regions(CURRENT_KEY)
    if forget:
        _searches.pop(view.id(), None)
    elif view.id() in _searches:
        _searches[view.id()]["shown"] = False


def report(window, found, index):
    if not found:
        window.status_message("Terminus: no match")
    else:
        window.status_message("Terminus: match {} of {}".format(index + 1, len(found)))


def ask(window, panel_name=None):
    """Opens the palette on the search, for the terminal of `panel_name` or the one showing"""
    args = {"panel_name": panel_name} if panel_name else {}
    # the palette has to be opened once with nothing typed, or it does not find the command
    window.run_command("show_overlay", {"overlay": "command_palette", "text": ""})
    window.run_command("hide_overlay")
    window.run_command("show_overlay", {"overlay": "command_palette", "command": "terminus_search", "args": args})


class TerminusSearchCommand(sublime_plugin.WindowCommand):
    def run(self, query=None, panel_name=None):
        view = target(self.window, panel_name)
        if not view:
            return
        if query is None:
            # from a key binding: nothing asks for the text unless the palette is opened on it
            ask(self.window, panel_name)
            return
        if not query:
            clear(view)
            self.window.focus_view(view)
            return
        # Enter does not end the search: it steps to the next match up, and the popup, which
        # enter closed, is opened again on the same text. Only escape ends it (`cancel`).
        state = _searches.get(view.id(), {})
        index = None
        if state.get("query") == query and state.get("index") is not None and state.get("shown"):
            index = state["index"] - 1
        report(self.window, *highlight(view, query, index))
        window = self.window
        sublime.set_timeout(lambda: ask(window, panel_name), 0)

    def is_enabled(self, **kwargs):
        return bool(target(self.window, kwargs.get("panel_name")))

    def input(self, args):
        if "query" in args:
            return None
        view = target(self.window, args.get("panel_name"))
        if not view:
            return None
        return TerminusSearchInputHandler(view)

    def input_description(self):
        return "Search"


class TerminusSearchInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, view):
        super().__init__()
        self.view = view

    def name(self):
        return "query"

    def initial_text(self):
        return _searches.get(self.view.id(), {}).get("query", "")

    def placeholder(self):
        return "text to find in the terminal"

    def preview(self, text):
        # called as the text changes: the terminal behind the palette shows the matches at once
        if not self.view.is_valid():
            return None
        if not text:
            clear(self.view, forget=False)
            return None
        found, index = highlight(self.view, text)
        # in the text colour, said outright: the palette draws a plain string in a colour of the
        # theme, which on a light theme is white on light grey
        if not found:
            return sublime.Html(COUNT.format("no match"))
        return sublime.Html(COUNT.format("match {} of {} · enter for the next, escape to close".format(index + 1, len(found))))

    def cancel(self):
        if self.view.is_valid():
            clear(self.view)


class TerminusSearchNextCommand(sublime_plugin.WindowCommand):
    """Steps to the next match of the last search: up, to older output, or down with `forward`"""

    def run(self, forward=False):
        view = target(self.window)
        state = _searches.get(view.id()) if view else None
        if not state or not state.get("query"):
            if view:
                ask(self.window)
            return
        index = state.get("index")
        if index is not None and state.get("shown"):
            index += 1 if forward else -1
        report(self.window, *highlight(view, state["query"], index, others=False))

    def is_enabled(self, **kwargs):
        return bool(target(self.window))


class TerminusSearchListener(sublime_plugin.EventListener):
    def on_post_text_command(self, view, command_name, args):
        # back to typing: the highlights are in the way, the search is kept for the next step
        if command_name != "terminus_keypress":
            return
        state = _searches.get(view.id())
        if state and state.get("shown"):
            clear(view, forget=False)

    def on_pre_close(self, view):
        _searches.pop(view.id(), None)
