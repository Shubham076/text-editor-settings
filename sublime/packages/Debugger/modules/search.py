'''Searching what a panel of the debugger has printed

Sublime's Find is a panel and a window shows one panel at a time, so it cannot be used on the
console: it would take the console's place. The text of the console is the text of a view
though, so it can be searched from here. The query is asked for in the command palette, which is
an overlay and leaves the panel alone, and every match is highlighted in the panel as it is typed.

	debugger_search         asks for the text; enter lands on the match nearest the end
	debugger_search_next    the next match up (older output), or down with `forward`

The same search, keys and behaviour as the one Terminus has for its terminals (a terminal the
debugger opened is a Terminus view and is searched by Terminus). Upper case in the query makes
the search case sensitive. The matches are highlighted while the popup is open and not after:
enter leaves the panel scrolled to the match. Stepping marks the one match it lands on, until
the panel is written to or typed into.
'''

from __future__ import annotations
from typing import Any

import json
import os

import sublime
import sublime_plugin


ALL_KEY = 'debugger.search'
CURRENT_KEY = 'debugger.search.current'

# The fill of a match is the selection colour and the one stepped to is a light green, both with
# the text left in its own colour: as Terminus draws them in a terminal. No colour scheme has
# rules for these two scopes, so they are added to the one in use (`ensure_colours`). Until that
# has been done a match is drawn in the text colour, with the text on it in the background colour.
MATCH_SCOPE = 'debugger.search.match'
CURRENT_SCOPE = 'debugger.search.current'

# what was last written for a colour scheme, by its name
_colours: dict[str, str] = {}


def ensure_colours(view: sublime.View) -> None:
	'''Adds the rules for the two search scopes to the colour scheme the panel is drawn in

	A panel of the debugger is drawn in the colour scheme of the editor, which is not the
	debugger's to edit. Sublime merges every file that has the name of a colour scheme into it,
	wherever in Packages it is, so the two rules go in a file of that name under
	`User/Debugger`: the scheme itself and the overrides the user has for it are left alone.
	The colours are read off the panel and written out as they are, since a rule cannot refer to
	the selection colour of the scheme it is merged into. Written again when they change.
	'''
	try:
		scheme = view.settings().get('color_scheme')
		if not scheme or scheme == 'auto':
			scheme = sublime.ui_info().get('color_scheme', {}).get('resolved_value')
		if not scheme:
			return
		name = os.path.splitext(os.path.basename(scheme))[0]
		style = view.style()
		foreground = style.get('foreground')
		background = style.get('background')
		selection = style.get('selection')
		green = view.style_for_scope('region.greenish').get('foreground') or style.get('greenish')
		if not (foreground and background and selection and green):
			return
		content = json.dumps({
			'rules': [
				{'scope': MATCH_SCOPE, 'foreground': foreground, 'background': selection},
				{'scope': CURRENT_SCOPE, 'foreground': foreground, 'background': f'color({green} blend({background} 50%))'},
			],
		}, indent='\t')
		if _colours.get(name) == content:
			return
		path = os.path.join(sublime.packages_path(), 'User', 'Debugger', name + '.sublime-color-scheme')
		existing = None
		if os.path.exists(path):
			with open(path) as file:
				existing = file.read()
		if existing != content:
			os.makedirs(os.path.dirname(path), exist_ok=True)
			with open(path, 'w') as file:
				file.write(content)
		_colours[name] = content
	except Exception as error:
		print('Debugger: search colours not written:', error)

COUNT = '<span style="color: var(--foreground)">{}</span>'

# view id -> {'query': what was searched for, 'index': the match stepped to, 'shown': highlights are up}
_searches: dict[int, dict[str, Any]] = {}


def target(window: sublime.Window | None, panel_name: str | None = None) -> sublime.View | None:
	'''The panel a search is for: the one named, else the one showing, if it is the debugger's own'''
	if not window:
		return None
	if not panel_name:
		active = window.active_panel() or ''
		panel_name = active[len('output.'):] if active.startswith('output.') else None
	view = window.find_output_panel(panel_name) if panel_name else None
	if not view:
		return None
	settings = view.settings()
	if not settings.get('debugger.output') or settings.get('terminus_view'):
		return None
	return view


def matches(view: sublime.View, query: str) -> list[sublime.Region]:
	if not query:
		return []
	flags = sublime.LITERAL
	if query == query.lower():
		flags |= sublime.IGNORECASE
	return view.find_all(query, flags)


def highlight(view: sublime.View, query: str, index: int | None = None, others: bool = True) -> tuple[list[sublime.Region], int | None]:
	'''Fills every match of `query`, and the one at `index` (the last, left out) in green

	Without `others` only the one at `index` is marked. Returns the matches and the index marked.
	'''
	found = matches(view, query)
	if not found:
		clear(view, forget=False)
		return found, None
	if index is None:
		# the same text again (the popup opened again on it): the match stepped to stays
		state = _searches.get(view.id(), {})
		kept = state.get('index') if state.get('query') == query else None
		index = kept if kept is not None else len(found) - 1
	index %= len(found)
	ensure_colours(view)
	view.add_regions(ALL_KEY, found[:index] + found[index + 1:] if others else [], MATCH_SCOPE, '', sublime.DRAW_NO_OUTLINE)
	view.add_regions(CURRENT_KEY, [found[index]], CURRENT_SCOPE, '', sublime.DRAW_NO_OUTLINE)
	view.show(found[index], True)
	state = _searches.setdefault(view.id(), {})
	state.update(query=query, index=index, shown=True)
	return found, index


def clear(view: sublime.View, forget: bool = True) -> None:
	view.erase_regions(ALL_KEY)
	view.erase_regions(CURRENT_KEY)
	if forget:
		_searches.pop(view.id(), None)
	elif view.id() in _searches:
		_searches[view.id()]['shown'] = False


def report(window: sublime.Window, found: list[sublime.Region], index: int | None) -> None:
	if not found or index is None:
		window.status_message('Debugger: no match')
	else:
		window.status_message(f'Debugger: match {index + 1} of {len(found)}')


def ask(window: sublime.Window, panel_name: str | None = None) -> None:
	'''Opens the palette on the search, for the panel of `panel_name` or the one showing'''
	args = {'panel_name': panel_name} if panel_name else {}
	# the palette has to be opened once with nothing typed, or it does not find the command
	window.run_command('show_overlay', {'overlay': 'command_palette', 'text': ''})
	window.run_command('hide_overlay')
	window.run_command('show_overlay', {'overlay': 'command_palette', 'command': 'debugger_search', 'args': args})


class DebuggerSearchCommand(sublime_plugin.WindowCommand):
	def run(self, query: str | None = None, panel_name: str | None = None):  # type: ignore
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
		if state.get('query') == query and state.get('index') is not None and state.get('shown'):
			index = state['index'] - 1
		report(self.window, *highlight(view, query, index))
		window = self.window
		sublime.set_timeout(lambda: ask(window, panel_name), 0)

	def is_enabled(self, **kwargs: Any):  # type: ignore
		return bool(target(self.window, kwargs.get('panel_name')))

	def input(self, args: dict[str, Any]):  # type: ignore
		if 'query' in args:
			return None
		view = target(self.window, args.get('panel_name'))
		if not view:
			return None
		return DebuggerSearchInputHandler(view)

	def input_description(self):
		return 'Search'


class DebuggerSearchInputHandler(sublime_plugin.TextInputHandler):
	def __init__(self, view: sublime.View):
		super().__init__()
		self.view = view

	def name(self):
		return 'query'

	def initial_text(self):
		return _searches.get(self.view.id(), {}).get('query', '')

	def placeholder(self):
		return 'text to find in the panel'

	def preview(self, text: str):  # type: ignore
		# called as the text changes: the panel behind the palette shows the matches at once
		if not self.view.is_valid():
			return None
		if not text:
			clear(self.view, forget=False)
			return None
		found, index = highlight(self.view, text)
		# in the text colour, said outright: the palette draws a plain string in a colour of the
		# theme, which on a light theme is white on light grey
		if not found:
			return sublime.Html(COUNT.format('no match'))
		return sublime.Html(COUNT.format('match {} of {} · enter for the next, escape to close'.format(index + 1, len(found))))

	def cancel(self):
		if self.view.is_valid():
			clear(self.view)


class DebuggerSearchNextCommand(sublime_plugin.WindowCommand):
	'''Steps to the next match of the last search: up, to older output, or down with `forward`'''

	def run(self, forward: bool = False):  # type: ignore
		view = target(self.window)
		if not view:
			return
		state = _searches.get(view.id())
		if not state or not state.get('query'):
			ask(self.window)
			return
		index = state.get('index')
		if index is not None and state.get('shown'):
			index += 1 if forward else -1
		report(self.window, *highlight(view, state['query'], index, others=False))

	def is_enabled(self, **kwargs: Any):  # type: ignore
		return bool(target(self.window))


class DebuggerSearchListener(sublime_plugin.EventListener):
	def on_modified(self, view: sublime.View):
		# more was printed, or something was typed: the mark is in the way, the search is kept
		state = _searches.get(view.id())
		if state and state.get('shown'):
			clear(view, forget=False)

	def on_pre_close(self, view: sublime.View):
		_searches.pop(view.id(), None)
