from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Any, ClassVar, cast
import sublime
import sublime_plugin


from . import core
from . import ui

from .settings import Settings

if TYPE_CHECKING:
	from .debugger import Debugger


class OutputPanel(core.Dispose):
	on_opened: Callable[[], Any] | None = None
	on_opened_status: Callable[[], Any] | None = None

	# set by `ConsoleOutputPanel` when the panel belongs to one session. Declared here so that every
	# panel answers the question: the tab strip asks it of all of them to tell a session console from a
	# panel of the debuggers own
	session: Any | None = None

	from_view: ClassVar[dict[sublime.View, OutputPanel]] = {}
	from_input_view: ClassVar[dict[sublime.View, OutputPanel]] = {}
	from_output_panel_name: ClassVar[dict[str, OutputPanel]] = {}

	def __init__(
		self,
		debugger: Debugger,
		panel_name: str,
		name: str | None = None,
		show_panel=True,
		show_tabs=True,
		show_tabs_top=False,
		remove_last_newline=False,
		create=True,
		lock_selection=False,
		unlisted=False,
		dashboard=False,
		bottom_bar=False,
		prompt_strip=False,
		layout='debugger',
	):
		super().__init__()
		self.panel_name = self._clean_output_panel_name(debugger, panel_name, bottom_bar or prompt_strip) if create else panel_name
		self.output_panel_name = f'output.{self.panel_name}'
		self.name = name or panel_name

		self.window = debugger.window
		self.create = create
		self.show_tabs = show_tabs
		self.show_tabs_top = show_tabs_top
		self.remove_last_newline = remove_last_newline
		self.debugger = debugger
		self.lock_selection = lock_selection
		self.live_view_settings = None

		self.status: ui.Image | None = None

		self.removed_newline: int | None = None

		previous_panel = self.window.active_panel()

		from .output_panel_tabs import OutputPanelTabsPhantom

		self.input_view = None
		self.prompt_view = None
		self.prompt_callback = None
		self.prompt_caption = self.DEFAULT_PROMPT
		self.prompt_hint = None
		if create and bottom_bar:
			# An io panel: the output above scrolls, the one-line input strip below it does not. The
			# header is drawn into that strip, so the toolbar and tabs stay put however long the
			# output gets. The strip never takes input; see `configure_bar_view`.
			self.view, self.input_view = self.window.create_io_panel(self.panel_name, lambda text: None, unlisted=unlisted)
			self.configure_bar_view(self.input_view)
		elif create and prompt_strip:
			# An io panel whose input strip is a prompt line: Sublime shows one panel at a time, so
			# `show_input_panel` would replace this panel while typing. The strip stays below the
			# output, adds a watch expression on enter, and hosts other prompts (`prompt`).
			self.view, self.input_view = self.window.create_io_panel(self.panel_name, self._on_prompt_input, unlisted=unlisted)
			self.prompt_view = self.input_view
			self.configure_prompt_view(self.input_view)
		else:
			self.view = self.window.create_output_panel(self.panel_name, unlisted=unlisted) if create else self.window.find_output_panel(self.panel_name)
		assert self.view
		self.tabs_phantom = OutputPanelTabsPhantom(self, self.view, body=dashboard, header_view=self.input_view if bottom_bar else None, layout=layout)

		settings = self.view.settings()
		settings.set('debugger', id(debugger))
		settings.set('debugger.output', True)
		settings.set('debugger.output.' + self.name.lower(), True)

		if create:
			settings.set('draw_unicode_white_space', 'none')
			settings.set('context_menu', 'DebuggerWidget.sublime-menu')
			settings.set('is_widget', True)
			settings.set('rulers', [])

		OutputPanel.from_view[self.view] = self
		OutputPanel.from_output_panel_name[self.output_panel_name] = self

		if self.input_view:
			OutputPanel.from_input_view[self.input_view] = self

		settings.set('scroll_past_end', False)
		settings.set('gutter', False)

		self.update_settings()
		self.open_at_shared_height()
		self.update_settings()

		if not show_panel:
			if previous_panel:
				self.window.run_command('show_panel', {'panel': previous_panel})
			else:
				self.window.run_command('hide_panel')

		self.debugger.add_output_panel(self)
		self.dispose_add(
			self.tabs_phantom,
			self.dispose_live_settings,
			lambda: self.debugger.remove_output_panel(self),
		)

	# -- height ------------------------------------------------------------------------------
	#
	# Sublime has no way to set the height of a panel. It gives a panel its height once, the first
	# time it is shown: `PANEL_LINES` lines of the view's font plus `PANEL_EXTRA` pixels for the
	# output, and the input strip of an io panel on top of that. From then on the height belongs to
	# that panel alone: dragging the edge changes the one panel that is showing. The height is
	# also written to the workspace under the panel's name, and a panel created under a name found
	# there gets that height back whatever its font is. Destroying the panel does not clear it,
	# hidden or shown, at once or later (all of this measured, not documented).
	#
	# Each tab of the debugger is a panel of its own, so left to itself every tab ends up a
	# different height: the one it was last dragged to, weeks ago. Two things keep them the same.
	# A panel is created under a name that either has no height saved or has the right one
	# (`_clean_output_panel_name`), and it is first shown with a font picked to come out at the
	# height the other tabs have: `Debugger.panel_height`, the output and its strip together.
	# That height follows a drag of whichever tab is showing and is kept with the project's data,
	# so panels created after the drag, and after a restart, match it. The panels that already
	# exist cannot be made to follow: there is nothing to resize them with.
	PANEL_LINES = 6
	PANEL_EXTRA = 6
	# how far, in pixels, a panel has to move from the height it was last seen at to count as dragged
	DRAG_TOLERANCE = 4
	# how close a height has to be to the one wanted, or to a fresh panel's, to be taken for it
	HEIGHT_TOLERANCE = 3
	# the font a name is tried out with: small, so a fresh panel's height is one no drag leaves behind
	PROBE_FONT = 7
	# names tried before settling for one with the wrong height
	NAME_ATTEMPTS = 40

	def _clean_output_panel_name(self, debugger: Debugger, name: str, io: bool) -> str:
		'''The first free name whose panel will come out at the height the others have

		Each candidate is tried with a throwaway panel of the same kind, shown and destroyed on the
		spot: it either gets a fresh panel's height (nothing is saved under the name, so the real
		panel can be given any height) or the saved one (usable only if it is the height wanted).
		A name that has been through a drag is skipped from then on; the workspace keeps its entry,
		which is a line of json. Without a height to match yet, only a fresh name will do, so the
		first panel sets the height from the settings rather than from whatever its name remembers.
		'''
		window = debugger.window
		wanted = self._pixels(getattr(debugger, 'panel_height', None))
		previous = window.active_panel()
		chosen = None
		first_free = None
		index = 0
		for _ in range(self.NAME_ATTEMPTS):
			candidate = name if not index else f'{name} {index}'
			index += 1
			if window.find_output_panel(candidate):
				continue
			first_free = first_free or candidate
			if io:
				view, strip = window.create_io_panel(candidate, lambda text: None, unlisted=True)
			else:
				view, strip = window.create_output_panel(candidate, unlisted=True), None
			view.settings().set('font_size', self.PROBE_FONT)
			fresh = self._pixels(view.line_height())
			window.run_command('show_panel', {'panel': f'output.{candidate}'})
			try:
				height = self._pixels(view.viewport_extent()[1])
				total = height + (self._pixels(strip.viewport_extent()[1]) or 0 if strip else 0) if height else None
			except (TypeError, IndexError):
				height = total = None
			window.destroy_output_panel(candidate)
			if not fresh or not height:
				# nothing to measure with (no layout yet): the name is as good as any
				chosen = candidate
				break
			if abs(height - (self.PANEL_LINES * fresh + self.PANEL_EXTRA)) <= self.HEIGHT_TOLERANCE:
				chosen = candidate
				break
			if wanted and total and abs(total - wanted) <= self.HEIGHT_TOLERANCE:
				chosen = candidate
				break

		if previous:
			window.run_command('show_panel', {'panel': previous})
		else:
			window.run_command('hide_panel')
		return chosen or first_free or self._get_free_output_panel_name(window, name)

	@staticmethod
	def _pixels(value) -> float | None:
		return float(value) if isinstance(value, (int, float)) and value > 0 else None

	def total_height(self) -> float | None:
		'''The height of the panel on screen: the output and, for an io panel, its strip'''
		try:
			height = self._pixels(self.view.viewport_extent()[1])
			strip = self._pixels(self.input_view.viewport_extent()[1]) if self.input_view else 0
		except (TypeError, IndexError):
			return None
		return height + strip if height and strip is not None else None

	def font_for_line_height(self, line_height: float) -> float | None:
		'''The font size at which a line of this view is `line_height` pixels tall

		Line height is a straight line in the font size, offset by the view's line padding, so two
		readings give it. Read from this view rather than worked out, because the face and the
		padding differ between a console, a terminal and a dashboard.
		'''
		settings = self.view.settings()
		low, high = 20, 60
		settings.set('font_size', low)
		at_low = self._pixels(self.view.line_height())
		settings.set('font_size', high)
		at_high = self._pixels(self.view.line_height())
		if not at_low or not at_high or at_high <= at_low:
			return None
		return max(1.0, low + (line_height - at_low) * (high - low) / (at_high - at_low))

	def open_at_shared_height(self):
		'''Shows the panel for the first time, at the height the debugger's other panels have

		With no height to match yet, the first panel of a window sets it: `console_minimum_height`
		lines, by the scaling the debugger has always used. The font set here is only there for the
		moment the panel is sized; `update_settings` puts the real one back right after.
		'''
		settings = self.view.settings()
		shared = self._pixels(getattr(self.debugger, 'panel_height', None)) if self.create else None
		font = None
		if shared:
			# the strip is one line of its own font tall, plus a pixel of border
			strip = (self._pixels(self.input_view.line_height()) or 0) + 1 if self.input_view else 0
			font = self.font_for_line_height((shared - strip - self.PANEL_EXTRA) / self.PANEL_LINES)
		if not font:
			font_size = cast(float, settings.get('font_size') or 12)
			font = font_size * (Settings.console_minimum_height + 1.75) / 5
		settings.set('font_size', font)
		self.open()
		# the extents are right as soon as the panel is shown
		self.seen_height = self.total_height()
		if self.create and not shared and self.seen_height:
			self.debugger.panel_height = self.seen_height

	def track_height(self):
		'''Called while the panel is showing: a change in its height is the user dragging its edge

		Only a change counts. A panel that is simply taller or shorter than the rest (one Terminus
		recreated, one from before a drag) must not pass its height on to the panels made after it.
		'''
		height = self.total_height()
		if not height:
			return
		seen = getattr(self, 'seen_height', None)
		if seen and abs(height - seen) > self.DRAG_TOLERANCE:
			self.debugger.panel_height = height
			# kept with the project's data, so the height is the same after a restart
			if save := getattr(self.debugger, 'save_data', None):
				save()
		self.seen_height = height

	DEFAULT_PROMPT = 'Expression to watch'

	@property
	def has_prompt(self) -> bool:
		'''Whether the panel can ask for a line of text itself (`prompt`) and so stay on screen while it is typed'''
		return self.prompt_view is not None

	def configure_prompt_view(self, view: sublime.View):
		'''The input strip of an io panel as a one-line prompt below the output

		It completes like the console's input line: a scope of its own for the trigger characters
		to hang on, and only the language server's items (`on_prompt_query_completions`).
		'''
		view.assign_syntax(core.package_path_relative('contributes/Syntax/DebuggerPrompt.sublime-syntax'))
		settings = view.settings()
		for key, value in {
			'gutter': False, 'line_numbers': False, 'margin': 8, 'draw_indent_guides': False, 'draw_white_space': 'none',
			'scroll_past_end': False, 'word_wrap': False, 'highlight_line': False, 'is_widget': True, 'rulers': [],
			'debugger.prompt': True,
			'auto_complete': True, 'auto_complete_selector': self.PROMPT_SCOPE, 'auto_complete_include_snippets': False,
			'auto_complete_include_snippets_when_typing': False, 'auto_complete_use_history': False,
			'auto_complete_triggers': self.completion_triggers(None, self.PROMPT_SCOPE),
		}.items():
			settings.set(key, value)
		self.update_prompt_hint()

	PROMPT_SCOPE = 'debugger.prompt'

	def on_prompt_query_completions(self, prefix: str, locations: list[int]) -> Any:
		'''The completion popup of the prompt strip: the language server's items for the expression typed so far'''
		view = self.prompt_view
		if not view:
			return None
		view.settings().set('auto_complete_triggers', self.completion_triggers(self.completion_session(), self.PROMPT_SCOPE))
		text = view.substr(sublime.Region(0, locations[0] if locations else view.size()))
		return self.language_server_completion_list(view, text)

	# -- completions from the language server ---------------------------------------------------

	COMPLETION_TRIGGERS = '.['

	def completion_triggers(self, session: Any, selector: str) -> list[dict[str, str]]:
		'''An `auto_complete_triggers` value: the adapter's trigger characters once a session names them, else `.` and `[`'''
		characters = ''.join(session.capabilities.completionTriggerCharacters or '') if session else ''
		return [{'selector': selector, 'characters': characters or self.COMPLETION_TRIGGERS}]

	def completion_session(self) -> Any:
		'''The session whose frame the language server is asked about

		A configuration's console asks in its own session; every other panel in the current one.
		When nothing is running they fall back to the selected configuration's last run: its console
		keeps the session, and the frame it was last paused in is what expressions typed after the
		run are about, exactly as in that console itself.
		'''
		if self.session or self.debugger.session:
			return self.session or self.debugger.session
		from .ui.output_tabs import console_panels
		for console in console_panels(self.debugger):
			if console.session and console.session.selected_frame:
				return console.session
		return None

	def language_server_completion_list(self, view: sublime.View, text: str) -> Any:
		'''A completion list for the expression `text`, typed in `view`, from the language server

		Only the server's items: Sublime's buffer words and snippets are inhibited. With nothing to
		ask, no session with a frame, the empty list goes back at once with its flags, so no popup
		opens: a list that only resolves to nothing later does not stop Sublime from showing the
		words of the buffer in the meantime, and that popup then stays.
		'''
		from . import lsp_completions
		session = self.completion_session()
		flags = sublime.INHIBIT_EXPLICIT_COMPLETIONS | sublime.INHIBIT_REORDER | sublime.INHIBIT_WORD_COMPLETIONS
		if not session:
			return sublime.CompletionList([], flags)
		completions = sublime.CompletionList(None, flags)

		def on_items(response: list[dict]):
			items: list[sublime.CompletionItem] = []
			seen: set[str] = set()
			for item in response:
				label = item.get('label', '')
				if label in seen:
					continue
				seen.add(label)
				items.append(sublime.CompletionItem.command_completion(
					trigger=label,
					annotation=item.get('detail') or '',
					kind=lsp_completions.kind_for(item.get('kind')),
					command='insert',
					args={'characters': lsp_completions.insert_text_of(item)},
				))
			completions.set_completions(items, flags)
			if not items:
				# resolved empty: the words popup Sublime opened while waiting would stay, see above
				sublime.set_timeout(lambda: view.run_command('hide_auto_complete'))

		# `request` calls back on the main thread, or declines when there is no frame, LSP or server
		if not lsp_completions.request(self.debugger, session, text, on_items):
			on_items([])
		return completions

	def prompt(self, caption: str, initial: str, callback: Callable[[str], Any]):
		'''Asks for a line of text in the prompt strip, keeping the panel on screen

		`callback` gets the stripped text on enter. Escape (`debugger_prompt_cancel`) drops it.
		'''
		view = self.prompt_view
		if not view:
			return
		self.prompt_callback = callback
		self.prompt_caption = caption
		self.set_prompt_text(initial)
		self.window.focus_view(view)

	def cancel_prompt(self):
		self.prompt_callback = None
		self.prompt_caption = self.DEFAULT_PROMPT
		self.set_prompt_text('')
		# `open` rather than a bare focus: should Sublime have hidden the panel on enter or escape
		# the way it does for `show_input_panel`, this brings it back
		self.open()

	def set_prompt_text(self, text: str):
		view = self.prompt_view
		if not view or not view.is_valid():
			return
		core.edit(view, lambda edit: view.replace(edit, sublime.Region(0, view.size()), text))
		view.sel().clear()
		view.sel().add(view.size())
		self.update_prompt_hint()

	def update_prompt_hint(self):
		'''Shows the caption as placeholder text while the strip is empty'''
		view = self.prompt_view
		if not view or not view.is_valid():
			return
		if self.prompt_hint:
			self.prompt_hint.dispose()
			self.prompt_hint = None
		if view.size() == 0:
			html = '<body><span style="color: color(var(--foreground) alpha(0.45));">{}</span></body>'.format(self.prompt_caption)
			self.prompt_hint = ui.RawPhantom(view, sublime.Region(0), html)

	def _on_prompt_input(self, text: str):
		'''Enter in the prompt strip: hands the text to the pending prompt, or adds it as a watch'''
		callback, self.prompt_callback = self.prompt_callback, None
		value = text.strip()
		self.prompt_caption = self.DEFAULT_PROMPT
		self.set_prompt_text('')
		if callback:
			callback(value)
		elif value:
			self.debugger.watch.add(value)
		elif self.debugger.console is not self:
			# an empty enter goes to the debug console with its prompt ready, as enter on the call stack does
			console = self.debugger.console
			console.open()
			console.enable_input_mode()
			console.scroll_to_end()
			return
		self.open()

	def configure_bar_view(self, view: sublime.View):
		'''The input strip of an io panel, turned into a bare canvas for the header phantom

		Read only and without gutter, margins or padding, so the phantom is all there is. The live ui
		sets its font size: the strip is one text line tall and that is the only handle on its height.
		Focus is bounced back to the output by `OutputPanelEventListener.on_activated`.
		'''
		settings = view.settings()
		for key, value in {
			'gutter': False, 'line_numbers': False, 'margin': 0, 'line_padding_top': 0, 'line_padding_bottom': 0,
			'draw_indent_guides': False, 'draw_white_space': 'none', 'scroll_past_end': False, 'word_wrap': False,
			'highlight_line': False, 'is_widget': True, 'rulers': [], 'auto_complete': False, 'debugger.bar': True,
		}.items():
			settings.set(key, value)
		view.set_read_only(True)

	def dispose_live_settings(self):
		if self.live_view_settings:
			self.live_view_settings.dispose()
			self.live_view_settings = None

	def update_settings(self):
		# these settings control the size of the ui calculated in ui/layout
		settings = self.view.settings()
		if Settings.font_size:
			settings['font_size'] = Settings.font_size
		else:
			settings.erase('font_size')

		if self.create:
			# The text of created panels (console, terminal) follows the `console_*` settings, which
			# are separate from the `font_*` settings of the debugger ui drawn above it. The font
			# face is left to the editor's preferences unless set. Re-applied whenever a value
			# changes, restoring what the view had before for anything dropped.
			from .ui.view_settings import ViewSettings
			padding = Settings.console_line_padding
			values = {'margin': 14, 'line_padding_top': padding, 'line_padding_bottom': padding}
			if Settings.console_font_face:
				values['font_face'] = Settings.console_font_face
			if not self.live_view_settings or self.live_view_settings.values != values:
				if self.live_view_settings:
					self.live_view_settings.dispose()
				self.live_view_settings = ViewSettings(self.view, values)
			editor_font = sublime.load_settings('Preferences.sublime-settings').get('font_size', 12) or 12
			settings.set('font_size', max(10, round(Settings.console_font_size or Settings.font_size or editor_font * 0.875)))
		self.tabs_phantom.invalidated_layout()

	def set_status(self, status: ui.Image):
		if self.status == status:
			return

		self.status = status
		self.debugger.on_output_panels_updated()

	def dispose(self):
		super().dispose()

		view = self.view
		input_view = self.input_view
		output_panel_name = self.output_panel_name

		# remove debugger markers we added
		if not self.create:
			settings = view.settings()
			del settings['debugger']
			del settings['debugger.output']
			del settings['debugger.output.' + self.name.lower()]


		# we want to make sure we can run dispose multiple times
		if view in OutputPanel.from_view:
			del OutputPanel.from_view[view]
		if output_panel_name in OutputPanel.from_output_panel_name:
			del OutputPanel.from_output_panel_name[output_panel_name]
		if input_view in OutputPanel.from_input_view:
			del OutputPanel.from_input_view[input_view]

		if self.create:
			self.window.destroy_output_panel(self.panel_name)

	def _get_free_output_panel_name(self, window: sublime.Window, name: str) -> str:
		id = 1
		result = name
		while True:
			if not window.find_output_panel(result):
				return result

			result = f'{name} {id}'
			id += 1

	def open(self):
		# disposed
		if self.view not in OutputPanel.from_view:
			return

		# lost?
		if not self.view.is_valid():
			self.dispose()
			return

		self.window.bring_to_front()
		self.window.run_command('show_panel', {'panel': self.output_panel_name})
		self.window.focus_view(self.view)

	def open_status(self):
		if on_opened_status := self.on_opened_status:
			on_opened_status()
		else:
			self.open()

	def is_open(self) -> bool:
		return self.window.active_panel() == self.output_panel_name

	def on_show_panel(self):
		if self.on_opened:
			self.on_opened()

		self.tabs_phantom.invalidated_layout()

	def scroll_to_end(self):
		sel = self.view.sel()
		core.edit(
			self.view,
			lambda edit: (
				sel.clear(),
				sel.add(self.view.size()),
			),
		)

		if self.show_tabs_top:
			self.view.set_viewport_position((0, 0), False)
		else:
			height = self.view.layout_extent()[1]
			self.view.set_viewport_position((0, height), False)

		if self.window.active_view() == self.input_view:
			self.window.focus_view(self.view)

		if input_view := self.input_view:
			sublime.set_timeout(lambda: input_view.set_viewport_position((0, 0), False))

	def at(self):
		return self.view.size()

	def on_selection_modified(self): ...
	def on_modified(self): ...
	def on_activated(self): ...
	def on_deactivated(self): ...
	def on_text_command(self, command_name: str, args: Any): ...
	def on_post_text_command(self, command_name: str, args: Any): ...
	def on_query_context(self, key: str, operator: int, operand: Any, match_all: bool) -> bool | None: ...
	def on_query_completions(self, prefix: str, locations: list[int]) -> Any: ...


class OutputPanelEventListener(sublime_plugin.EventListener):
	def on_modified(self, view: sublime.View):
		if panel := OutputPanel.from_input_view.get(view):
			# `==`, not `is`: Sublime hands listeners a fresh View object for the same view
			if panel.prompt_view == view:
				panel.update_prompt_hint()
			return
		panel = OutputPanel.from_view.get(view)
		# a header or tab row drawn above the output rides on its first line and has to be
		# re-anchored after edits; the dashboards draw into a buffer that never changes
		if panel and not panel.tabs_phantom.live.body:
			panel.tabs_phantom.invalidated_layout()
		if panel:
			# A terminal follows only after the header reflow above has been queued, so its final
			# viewport calculation sees the completed layout.
			panel.on_modified()

	def on_selection_modified(self, view: sublime.View) -> None:
		panel = OutputPanel.from_view.get(view)
		if not panel:
			return

		# the view is locked so we do not allow changing the selection.
		# This allows the view to be scrolled to the bottom without issues when the selection is changed.
		if panel.lock_selection:
			view.sel().clear()

		panel.on_selection_modified()

	def on_activated(self, view: sublime.View):
		if panel := OutputPanel.from_input_view.get(view):
			# a strip holding the toolbar never takes focus (it would recolour and shift); a prompt strip does
			if panel.prompt_view != view:
				panel.window.focus_view(panel.view)
				# changing viewport has to be done the next cycle or it does not change
				sublime.set_timeout(lambda: view.set_viewport_position((0, 0), False))
			return

		if panel := OutputPanel.from_view.get(view):
			panel.on_activated()

	def on_deactivated(self, view: sublime.View):
		if panel := OutputPanel.from_view.get(view):
			panel.on_deactivated()

	def on_text_command(self, view: sublime.View, command_name: str, args: Any):
		if panel := OutputPanel.from_view.get(view):
			return panel.on_text_command(command_name, args)

	def on_post_text_command(self, view: sublime.View, command_name: str, args: Any):
		if panel := OutputPanel.from_view.get(view):
			if command_name in ('terminus_show_cursor', 'terminus_render'):
				sublime.set_timeout(panel.tabs_phantom.live.keep_header_visible)
			return panel.on_post_text_command(command_name, args)

	def on_query_context(self, view: sublime.View, key: str, operator: int, operand: Any, match_all: bool) -> bool | None:
		if not key.startswith('debugger.'):
			return None

		if panel := OutputPanel.from_view.get(view):
			return panel.on_query_context(key, operator, operand, match_all)

		return None

	def on_query_completions(self, view: sublime.View, prefix: str, locations: list[int]) -> Any:
		if panel := OutputPanel.from_input_view.get(view):
			# the prompt strip completes an expression; the strip holding a toolbar never takes input
			return panel.on_prompt_query_completions(prefix, locations) if panel.prompt_view == view else None
		if panel := OutputPanel.from_view.get(view):
			return panel.on_query_completions(prefix, locations)


class DebuggerPromptCancelCommand(sublime_plugin.TextCommand):
	'''Escape in a prompt strip, or on the Watch panel's input line: drops the pending prompt and returns focus to the output'''

	def run(self, edit: sublime.Edit):
		if panel := OutputPanel.from_input_view.get(self.view) or OutputPanel.from_view.get(self.view):
			panel.cancel_prompt()
