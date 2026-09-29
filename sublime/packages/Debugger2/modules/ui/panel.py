from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import sublime

from .. import core
from ..settings import Settings
from ..views.session_scope import SessionScope
from .breakpoints import BreakpointsPane
from .callstack import CallstackPane
from .renderer import Renderer
from .state import TreeData, ViewState
from .style import PANE_CONTENT, PANE_PAD, STACK_MIN, STACK_SHARE, TABS_HEIGHT, TOOLBAR
from .toolbar import Toolbar
from .variables import VariablesPane
from .view_settings import ViewSettings

if TYPE_CHECKING:
	from ..output_panel import OutputPanel


ABOVE_LINE = 3

# The buffer a dashboard draws its phantoms into, one anchor point per phantom: the toolbar's two
# cells at 0 and 1 (one line), the tab row at 2, the panes at 3 and 4 (one line, side by side)
ANCHORS = ' \n\n  \n'
# The same with the toolbar in the strip below and a line of input after the panes (Watch): the tab
# row at 0, the pane at 2, and the input line, which the panel appends, from 4 on. The lines carry
# nothing but their phantoms, so the view can keep a readable font for the typed text
INPUT_ANCHORS = ' \n \n'
# the air under the input line, in rem
INPUT_AIR = 1.6


class PanelUI(Renderer):
	def __init__(self, panel: OutputPanel, view: sublime.View, body=False, header_view: sublime.View | None = None, layout='debugger'):
		self.panel = panel
		self.backend = panel.debugger
		self.window = panel.window
		self.view = view
		self.body = body
		# Which dashboard a body panel draws, and the tab it answers to: `debugger` (call stack
		# beside variables), `breakpoints` or `watch`. Ignored for output panels.
		self.layout = layout
		# When set, the header is drawn into this fixed strip (an io panel's input view) below the
		# output instead of above the output's first line, so it stays put while the output scrolls.
		self.header_view = header_view
		# A dashboard that ends in a line of typed input: the Watch panel with its toolbar in the
		# strip, so the strip is not free to be the prompt. The panel owns the input line; the
		# ui only leaves the buffer after the anchors alone and stops its pane short of it
		self.input_line = body and header_view is not None and layout == 'watch'
		self.anchor_text = INPUT_ANCHORS if self.input_line else ANCHORS
		self.tabs_anchor, self.panes_anchor = (0, 2) if self.input_line else (2, 3)
		self.header_height = 0
		self.closed = False
		self.handlers = {}
		self.generation = 0
		self.signature = None
		self.queued = False
		self.state = ViewState(tab=layout if body else 'console')
		self.scope = SessionScope(self.backend, active_only=Settings.session_panels)
		self.tree = TreeData(self)
		self.toolbar = Toolbar(self)
		self.breakpoints = BreakpointsPane(self)
		self.callstack = CallstackPane(self)
		self.variables = VariablesPane(self)
		self.handles = []
		settings = {
			'font_size': 2, 'margin': 0, 'gutter': False, 'line_numbers': False,
			'word_wrap': False, 'draw_white_space': 'none', 'draw_unicode_white_space': 'none',
			'draw_indent_guides': False, 'highlight_line': False, 'scroll_past_end': False,
			'line_padding_top': 0, 'line_padding_bottom': 0, 'auto_complete': False,
		} if body else {}
		if self.input_line:
			# the typed text has to be legible, and it completes; the panel sets both up
			del settings['font_size'], settings['auto_complete']
		self.view_settings = ViewSettings(view, settings)
		if body:
			view.set_read_only(False)
			core.edit(view, lambda edit: view.replace(edit, sublime.Region(0, view.size()), self.anchor_text))
			view.set_read_only(True)
			view.sel().clear()
		self.phantoms = sublime.PhantomSet(header_view or view, 'debugger.live_ui')
		# With the toolbar in the strip below, what goes on the view itself, the tab row above the
		# output or a dashboard's tab row and panes, has a phantom set of its own
		self.view_phantoms = sublime.PhantomSet(view, 'debugger.live_ui.view') if header_view else None
		data_events = (self.backend.on_session_added, self.backend.on_session_removed,
			self.backend.on_session_updated, self.backend.on_session_active,
			self.backend.on_session_threads_updated, self.backend.on_session_variables_updated,
			self.backend.on_session_thread_or_frame_updated, self.backend.project.on_updated)
		for event in data_events:
			self.handles.append(event.add(self.reset_data if body else self.invalidate))
		if body:
			self.handles.append(self.backend.on_session_removed.add(self.forget_expanded_variables))
		for event in (self.backend.on_output_panels_updated, self.backend.on_project_or_settings_updated, self.backend.watch.on_updated,
			self.backend.breakpoints.source.on_updated, self.backend.breakpoints.filters.on_updated,
			self.backend.breakpoints.function.on_updated, self.backend.breakpoints.data.on_updated):
			self.handles.append(event.add(self.invalidate))
		self.invalidate()
		sublime.set_timeout(self.poll, 250)

	@property
	def active_session(self):
		return self.scope.current

	def reset_data(self, *args):
		"""A step or a frame change: fetched children and per-object state go, what the user opened stays (by name path)"""
		self.tree.reset()
		self.variables.reset()
		self.callstack.collapsed_threads.clear()
		self.state.expanded = {key for key in self.state.expanded if isinstance(key, str)}
		self.invalidate()

	def forget_expanded_variables(self, *args):
		"""When the last session ends, the variable rows opened during it are forgotten

		The sections and the scopes keep their state: level one is the user's standing preference,
		the paths beneath it were about one run's values.
		"""
		if self.backend.sessions:
			return
		self.state.expanded = {key for key in self.state.expanded
			if not isinstance(key, str) or not ('/' in key or key.startswith(('var:', 'watch:')))}
		self.invalidate()

	def invalidate(self, *args):
		if self.closed:
			return
		self.generation += 1
		self.handlers.clear()
		if not self.queued:
			self.queued = True
			sublime.set_timeout(self.render)

	def poll(self):
		if self.closed:
			return
		if not self.view.is_valid() or not self.window.is_valid():
			self.dispose()
			return
		if self.panel.is_open():
			preferences = sublime.load_settings('Preferences.sublime-settings')
			signature = (self.panel.view.viewport_extent(), str(self.view.style()), Settings.font_size, Settings.font_face, Settings.line_padding,
				preferences.get('font_size'), preferences.get('font_face'),
				self.header_view.viewport_extent()[0] if self.header_view else None,
				None if self.body or self.header_view else self.view.change_count())
			if signature != self.signature:
				self.signature = signature
				self.invalidate()
			elif self.header_view:
				self.fit_header()
		sublime.set_timeout(self.poll, 250)

	def dispose(self):
		if self.closed:
			return
		self.closed = True
		for handle in self.handles:
			handle.dispose()
		self.handles.clear()
		self.handlers.clear()
		self.tree.reset()
		self.variables.reset()
		if (self.header_view or self.view).is_valid():
			self.phantoms.update([])
		if self.view_phantoms and self.view.is_valid():
			self.view_phantoms.update([])
		self.view_settings.dispose()

	def fit_header(self):
		"""Sizes the fixed strip to the header.

		An io panel's input view is one text line tall and grows with nothing but its font size, so
		the font size is scaled by the ratio of wanted to current height. Each pass gets closer; the
		poll keeps calling until the strip is within two pixels.
		"""
		view = self.header_view
		if self.closed or not view or not view.is_valid() or not self.header_height:
			return
		current = view.viewport_extent()[1]
		if current <= 0 or abs(current - self.header_height) <= 2:
			return
		settings = view.settings()
		size = settings.get('font_size') or 12
		settings.set('font_size', max(6, min(200, round(size * self.header_height / current, 1))))

	def keep_header_visible(self):
		if self.closed or self.body or self.header_view or not self.view.is_valid():
			return
		if self.view.layout_extent()[1] <= self.view.viewport_extent()[1]:
			x, y = self.view.viewport_position()
			if y:
				self.view.set_viewport_position((x, 0), False)
				if self.view.settings().get('terminus_view'):
					self.view.settings().set('terminus_view.viewport_y', 0)

	def run_command(self, action):
		self.window.run_command('debugger', {'action': action})

	def prompt(self, caption, initial, callback):
		def done(value):
			if not self.closed and self.view.is_valid():
				callback(value.strip())
		if getattr(self.panel, 'has_prompt', False):
			# the panel has a prompt line of its own, so it stays on screen while typing
			self.panel.prompt(caption, initial, done)
			return

		def done_and_show(value):
			done(value)
			self.show()
		# Sublime shows one panel at a time: the input panel replaces this one, which `show` reopens
		self.window.show_input_panel(caption, initial, done_and_show, None, lambda: None if self.closed else self.show())

	def show(self):
		self.panel.open()
		self.invalidate()

	def render(self):
		self.queued = False
		if self.closed or not self.view.is_valid():
			return
		self.scope.active_only = Settings.session_panels
		self.generation += 1
		self.handlers = {}
		style = self.view.style()
		self.palette = {key: style.get(key) or default for key, default in (
			('foreground', '#606060'), ('background', '#ffffff'), ('bluish', '#343e5e'), ('redish', '#9b362b'))}
		self.palette['accent'] = style.get('accent') or self.palette['bluish']
		self.palette['selection'] = style.get('selection') or style.get('line_highlight') or 'color(var(--foreground) alpha(0.1))'
		preferences = sublime.load_settings('Preferences.sublime-settings')
		editor_font = preferences.get('font_size', 12) or 12
		self.font = max(10, round(Settings.font_size or editor_font * 0.875))
		self.font_face = Settings.font_face or preferences.get('font_face') or None
		self.line_padding = max(0, int(Settings.line_padding or 0))
		width, height = self.panel.view.viewport_extent()
		margin = 0 if self.body else self.view.settings().get('margin', 0) or 0
		# the strip's own width, less the history arrow Sublime draws at its right end
		strip_width = max(320, int(self.header_view.viewport_extent()[0] - 40)) if self.header_view else 0
		self.width = strip_width if self.header_view and not self.body else max(320, int(width - 2 * margin - 20))
		self.total = (self.width - 2) / self.font
		self.space = (self.view.em_width() or 1) / self.font if self.body else 0
		navigate = partial(self.navigate, self.generation)
		self.state.tab = self.layout if self.body else self.toolbar.panel_tab()
		if self.body and self.header_view:
			# the toolbar in the strip, laid out at the strip's width; the tab row and the panes on
			# the view, at its own
			self.total = (strip_width - 2) / self.font
			phantoms = [self.strip_phantom(navigate)]
			self.total = (self.width - 2) / self.font
			content = [(self.tabs_anchor, self.toolbar.tabs(), sublime.LAYOUT_INLINE)]
			# the pane fills the viewport under the tab row, unless a line of input follows it: then
			# it ends with its rows so the input sits right under them, not at the bottom of the panel
			fill = 0 if self.input_line else max(0, height - self.font * TABS_HEIGHT - 6)
			content.extend((self.panes_anchor + index, pane, sublime.LAYOUT_INLINE) for index, pane in enumerate(self.panes(fill)))
			if self.input_line:
				# air around the input line: a spacer under the pane's line and a taller one under
				# the line itself, drawn rather than typed so the buffer stays the anchors and the input
				content.append((len(self.anchor_text) - 1, '<div class="gap-large"></div>', sublime.LAYOUT_BELOW))
				content.append((len(self.anchor_text), '<div style="height:{}px;"></div>'.format(self.px(INPUT_AIR)), sublime.LAYOUT_BELOW))
			self.view_phantoms.update([sublime.Phantom(sublime.Region(at), self.document(html), layout, navigate) for at, html, layout in content])
		elif self.body:
			brand, rest = self.toolbar.render()
			content = [(0, brand), (1, rest), (2, self.toolbar.tabs())]
			header_height = self.font * (TOOLBAR * (2 if 'continued' in rest else 1) + TABS_HEIGHT) + 6
			content.extend((3 + index, pane) for index, pane in enumerate(self.panes(max(0, height - header_height))))
			phantoms = [sublime.Phantom(sublime.Region(at), self.document(html), sublime.LAYOUT_INLINE, navigate) for at, html in content]
		elif self.header_view:
			# the toolbar in the strip; the tab row above the output's first line, as on the other
			# panels. It rides on that line, so `on_modified` re-anchors it after edits
			phantoms = [self.strip_phantom(navigate)]
			tabs = self.toolbar.tabs() + '<div class="gap-large"></div>'
			self.view_phantoms.update([sublime.Phantom(sublime.Region(0), self.document(tabs), ABOVE_LINE, navigate)])
		else:
			# a little air between the tab underline and the first line of output beneath it
			brand, rest = self.toolbar.render()
			header = brand + rest + self.toolbar.tabs() + '<div class="gap-large"></div>'
			phantoms = [sublime.Phantom(sublime.Region(0), self.document(header), ABOVE_LINE, navigate)]
		self.phantoms.update(phantoms)
		if self.header_view:
			sublime.set_timeout(self.fit_header)
		elif not self.body:
			sublime.set_timeout(self.keep_header_visible)

	def strip_phantom(self, navigate):
		"""The toolbar row (see Toolbar.render) inline at the fixed strip's only point

		The strip is then sized to `header_height` (`fit_header`); a toolbar wrapped onto a second
		row doubles it.
		"""
		brand, rest = self.toolbar.render()
		header = brand + rest
		self.header_height = self.font * TOOLBAR * (2 if 'continued' in header else 1) + 2
		return sublime.Phantom(sublime.Region(0), self.document(header), sublime.LAYOUT_INLINE, navigate)

	def panes(self, viewport_height):
		"""The panes of this dashboard's `layout`, filling the viewport below the header

		Breakpoints and Watch are one pane across the panel. The Debugger tab puts the call stack
		in a narrow column (`STACK_SHARE` of the width) beside the variables, which get the rest,
		or stacks them when the panel is too narrow for two columns.
		"""
		fill = viewport_height / self.font - 1.8
		if self.layout == 'breakpoints':
			return [self.single_pane(self.breakpoints.render, fill)]
		if self.layout == 'watch':
			return [self.single_pane(self.variables.watch, fill)]
		if self.total < 68:
			width = self.total - 2 * PANE_PAD
			stack, _ = self.callstack.render(width)
			rows = stack + ['<div class="gap-large"></div>'] + self.variables.render(width)
			return ['<div class="pane stacked first last" style="width:{}px;padding-bottom:0.8rem;">{}</div>'.format(self.px(width), ''.join(rows))]
		outer = [max(self.total * STACK_SHARE, STACK_MIN)]
		outer.append(self.total - outer[0])
		inner = [width - (self.space if index else 0) - 2 * PANE_PAD - 0.15 for index, width in enumerate(outer)]
		variables = self.variables.render(inner[1])
		_, stack_height = self.callstack.render(inner[0])
		height = max(self.rows_height(variables), stack_height, fill)
		stack, _ = self.callstack.render(inner[0], height)
		return ['<div class="pane columns{}" style="width:{}px;height:{}px;">{}</div>'.format(
			' first' if index == 0 else ' last', self.px(width), self.px(height), ''.join(rows))
			for index, (width, rows) in enumerate(zip(inner, (stack, variables)))]

	def single_pane(self, render, fill):
		"""One pane the width of the panel, at least as tall as the space under the header

		The rows inside are no wider than `PANE_CONTENT`: a row ends in its action icons, and on a
		wide panel a full-width row would put them at the far edge, away from the text they act on.
		With a line of input under the pane (`fill` 0) the pane is as tall as its rows and no
		taller: `rows_height` is an estimate, and over a long list the difference between it and
		what minihtml draws would open up as blank space between the last row and the input. The
		air between them is a spacer of its own (`render`).
		"""
		width = self.total - 2 * PANE_PAD - 0.15
		rows = render(min(width, PANE_CONTENT))
		if fill <= 0:
			return '<div class="pane columns first last" style="width:{}px;">{}</div>'.format(self.px(width), ''.join(rows))
		height = max(self.rows_height(rows), fill)
		return '<div class="pane columns first last" style="width:{}px;height:{}px;">{}</div>'.format(self.px(width), self.px(height), ''.join(rows))
