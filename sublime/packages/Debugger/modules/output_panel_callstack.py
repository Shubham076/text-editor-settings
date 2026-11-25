from __future__ import annotations
from os.path import commonprefix
from typing import TYPE_CHECKING, Any

import sublime

from . import core, dap
from .output_panel import OutputPanel
from .settings import Settings

if TYPE_CHECKING:
	from .debugger import Debugger


class DashboardOutputPanel(OutputPanel):
	'''A panel drawn entirely by the live ui: the Call Stack / Variables, Breakpoints and Watch tabs

	`layout` picks what the panes hold (see `PanelUI.panes`). With `console_bar_position` at
	`bottom` every dashboard is an io panel whose one input strip holds the toolbar, below the
	panes, as the consoles do (`bottom_bar`). The Watch panel then takes its expression on a line
	of input under its rows, in the view itself (`input_line`, see `WatchOutputPanel`). With the
	toolbar above the tab row the Watch panel's strip is free, and is the prompt instead
	(`prompt_strip`): enter in the idle strip adds an expression and the edit button of a watch
	reuses it.
	'''

	def __init__(self, debugger: Debugger, layout: str, panel_name: str, name: str, prompt_strip: bool = False, bottom_bar: bool = False, input_line: bool = False) -> None:
		self.body = None
		self.input_line = input_line
		# a dashboard has nothing to select, so the selection is cleared as it changes, unless a
		# line of input is typed into, then `on_selection_modified` keeps the caret on that line
		super().__init__(debugger, panel_name, name, show_tabs_top=True, lock_selection=not input_line, unlisted=True, dashboard=True,
			prompt_strip=prompt_strip, bottom_bar=bottom_bar, layout=layout)
		self.layout = layout
		self.on_input = core.Event[str]()
		self.on_navigate = core.Event[dap.SourceLocation]()
		self.body = self.tabs_phantom.live
		self.update_settings()

	# the air above and below the input line's text, as a share of the font size (about two
	# pixels at the console's font); it goes on every line of the view, the anchor lines included
	LINE_PADDING = 0.125

	def update_settings(self):
		super().update_settings()
		if self.body:
			# the anchors of the phantoms are text, so they are made as small as text gets; not
			# with a line of input, whose text has to be read (it keeps the console's font)
			values = {'margin': 0, 'line_padding_top': 0, 'line_padding_bottom': 0}
			if not self.input_line:
				values['font_size'] = 2
			else:
				# a little air around the typed text
				font = self.view.settings().get('font_size') or 12
				padding = max(1, round(font * self.LINE_PADDING))
				values['line_padding_top'] = values['line_padding_bottom'] = padding
			for key, value in values.items():
				self.view.settings().set(key, value)
			self.body.invalidate()


def toolbar_in_strip() -> bool:
	return Settings.console_bar_position == 'bottom'


class CallstackOutputPanel(DashboardOutputPanel):
	'''The Call Stack / Variables tab: the call stack beside the variables of the selected frame'''

	def __init__(self, debugger: Debugger) -> None:
		super().__init__(debugger, 'debugger', 'Debugger Callstack', 'Debugger', bottom_bar=toolbar_in_strip())


class BreakpointsOutputPanel(DashboardOutputPanel):
	def __init__(self, debugger: Debugger) -> None:
		super().__init__(debugger, 'breakpoints', 'Debugger Breakpoints', 'Breakpoints', bottom_bar=toolbar_in_strip())


class WatchOutputPanel(DashboardOutputPanel):
	'''The Watch tab: the watched expressions, and a line to type the next one on

	With the toolbar in the strip below (`console_bar_position` at `bottom`) the expression is typed
	on the last line of the view, right under the rows, where the console has its `:` prompt. The
	line starts with a fixed marker (`PROMPT`) that is put back should an edit reach into it, the
	caret is kept on the line, enter (`watch_enter` in the keymap) adds the expression or answers a
	pending prompt (`prompt`, the edit button of a watch), and escape drops the prompt
	(`debugger_prompt_cancel`, keyed on the `debugger.prompt` view setting like the strip). While
	the line is empty the caption is shown in its place. It completes the way the prompt strip does,
	on the `debugger.prompt` scope of the prompt syntax. With the toolbar above the tabs the strip
	is the prompt instead and the view is the plain dashboard it was.
	'''

	# what the input line starts with: two spaces put the caret about under the text of the rows
	PROMPT = '  › '

	def __init__(self, debugger: Debugger) -> None:
		strip = toolbar_in_strip()
		self.restoring = False
		super().__init__(debugger, 'watch', 'Debugger Watch', 'Watch', prompt_strip=not strip, bottom_bar=strip, input_line=strip)
		if self.input_line:
			self.configure_input_line()

	# -- the input line ------------------------------------------------------------------------

	# The caption shown on the empty line is text in the buffer, not a phantom: a phantom's line
	# box never quite matches the view's text line, so it sat below the marker and the caret. It
	# starts with a zero-width space, which the prompt syntax dims to the end of the line and no
	# typed expression starts with, and lives in a tracked region so an edit anywhere near it can
	# be told apart from it
	PLACEHOLDER_MARK = '\u200b'
	PLACEHOLDER_REGION = 'debugger.placeholder'

	@property
	def has_prompt(self) -> bool:
		return self.input_line or super().has_prompt

	@property
	def prefix(self) -> str:
		'''Everything on the view before the typed text: the phantom anchors and the marker'''
		return self.body.anchor_text + self.PROMPT

	@property
	def input_start(self) -> int:
		return len(self.prefix)

	def configure_input_line(self):
		view = self.view
		view.assign_syntax(core.package_path_relative('contributes/Syntax/DebuggerPrompt.sublime-syntax'))
		settings = view.settings()
		for key, value in {
			'debugger.prompt': True,
			'auto_complete': True, 'auto_complete_selector': self.PROMPT_SCOPE, 'auto_complete_include_snippets': False,
			'auto_complete_include_snippets_when_typing': False, 'auto_complete_use_history': False,
			'auto_complete_triggers': self.completion_triggers(None, self.PROMPT_SCOPE),
		}.items():
			settings.set(key, value)
		self.edit(lambda edit: view.insert(edit, view.size(), self.PROMPT))
		self.update_prompt_hint()
		self.focus_input()

	def edit(self, fn):
		'''An edit of the view by the panel itself, which the listeners leave alone'''
		view = self.view
		read_only = view.is_read_only()
		self.restoring = True
		try:
			view.set_read_only(False)
			core.edit(view, fn)
		finally:
			view.set_read_only(read_only)
			self.restoring = False

	def placeholder(self) -> sublime.Region | None:
		'''Where the caption stands on the line, or None while something is typed'''
		regions = self.view.get_regions(self.PLACEHOLDER_REGION)
		return regions[0] if regions else None

	def input_end(self) -> int:
		'''Where typing goes: the end of the line, or in front of the caption standing on it'''
		placeholder = self.placeholder()
		return placeholder.begin() if placeholder else self.view.size()

	def input_text(self) -> str:
		full = self.view.substr(sublime.Region(0, self.view.size()))
		placeholder = self.placeholder()
		if placeholder:
			full = full[:placeholder.begin()] + full[placeholder.end():]
		return full[self.input_start:]

	def set_line(self, typed: str):
		'''The line as it should read for `typed`: the marker, the text, and the caption when there is none'''
		view = self.view
		wanted = self.prefix + typed
		caption = self.PLACEHOLDER_MARK + self.prompt_caption if not typed else ''
		full = view.substr(sublime.Region(0, view.size()))
		placeholder = self.placeholder()
		standing = view.substr(placeholder) if placeholder else ''
		if full != wanted + caption or standing != caption:
			self.edit(lambda edit: view.replace(edit, sublime.Region(0, view.size()), wanted + caption))
			if caption:
				view.add_regions(self.PLACEHOLDER_REGION, [sublime.Region(len(wanted), len(wanted) + len(caption))], flags=sublime.HIDDEN)
			else:
				view.erase_regions(self.PLACEHOLDER_REGION)
		self.focus_input()

	def focus_input(self):
		'''The caret where typing goes, ready'''
		view = self.view
		if not self.input_line or not view.is_valid():
			return
		end = self.input_end()
		sel = view.sel()
		sel.clear()
		sel.add(end)
		view.set_read_only(False)
		view.show(end, False)

	def open(self):
		super().open()
		self.focus_input()

	def enter(self):
		'''Enter on the Watch tab: the typed expression is added, or answers the pending prompt

		With the prompt in the strip the strip takes the text; enter on the view puts the caret there.
		'''
		if not self.input_line:
			if self.prompt_view:
				self.window.focus_view(self.prompt_view)
			return
		self._on_prompt_input(self.input_text())

	def set_prompt_text(self, text: str):
		if not self.input_line:
			super().set_prompt_text(text)
			return
		if self.view.is_valid():
			self.set_line(text)

	def update_prompt_hint(self):
		'''The caption on the line while nothing is typed; a changed caption replaces it'''
		if not self.input_line:
			super().update_prompt_hint()
			return
		if self.view.is_valid():
			self.set_line(self.input_text())

	def prompt(self, caption: str, initial: str, callback):
		if not self.input_line:
			super().prompt(caption, initial, callback)
			return
		self.prompt_callback = callback
		self.prompt_caption = caption
		self.set_prompt_text(initial)
		self.open()

	def cancel_prompt(self):
		if not self.input_line:
			super().cancel_prompt()
			return
		self.prompt_callback = None
		self.prompt_caption = self.DEFAULT_PROMPT
		self.set_prompt_text('')
		self.open()

	# -- keeping the line whole -----------------------------------------------------------------

	def on_selection_modified(self):
		'''The caret stays where typing goes: a click anywhere else lands there, a selection stops at the text'''
		if not self.input_line or not self.body or self.restoring:
			return
		view = self.view
		sel = view.sel()
		start, end = self.input_start, self.input_end()
		regions = list(sel)
		if not regions or all(region.empty() and not start <= region.a <= end for region in regions):
			self.focus_input()
			return
		clamped = [sublime.Region(min(max(region.a, start), end), min(max(region.b, start), end)) for region in regions]
		if any((region.a, region.b) != (kept.a, kept.b) for region, kept in zip(regions, clamped)):
			sel.clear()
			sel.add_all(clamped)
		view.set_read_only(False)

	def on_modified(self):
		'''The first keystroke takes the caption away; an edit into the marker or a pasted line break is put right

		The typed text is what is left once the caption's region is taken out and the longest part
		of the prefix still there is dropped, so backspace at the start of the line takes nothing
		and deleting the line leaves it empty, with the caption back on it.
		'''
		if not self.input_line or not self.body or self.restoring:
			return
		view = self.view
		full = view.substr(sublime.Region(0, view.size()))
		placeholder = self.placeholder()
		if placeholder:
			full = full[:placeholder.begin()] + full[placeholder.end():]
		prefix = self.prefix
		typed = full[len(prefix):] if full.startswith(prefix) else full[len(commonprefix([full, prefix])):]
		self.set_line(typed.replace('\n', ' '))

	def on_activated(self):
		if self.input_line and all(region.empty() for region in self.view.sel()):
			self.focus_input()

	def on_query_completions(self, prefix: str, locations: list[int]) -> Any:
		'''The completion popup of the input line: the language server's items for the expression so far'''
		if not self.input_line:
			return None
		view = self.view
		view.settings().set('auto_complete_triggers', self.completion_triggers(self.completion_session(), self.PROMPT_SCOPE))
		end = locations[0] if locations else view.size()
		text = view.substr(sublime.Region(self.input_start, max(self.input_start, end)))
		return self.language_server_completion_list(view, text)
