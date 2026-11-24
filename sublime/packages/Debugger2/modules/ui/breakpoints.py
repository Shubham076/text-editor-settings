from __future__ import annotations

from html import escape
import os
from typing import TYPE_CHECKING

from .. import dap
from ..views.breakpoints import BreakpointView
from .style import ACTION, CH, CONTROL

if TYPE_CHECKING:
	from .panel import PanelUI


def is_logpoint(item) -> bool:
	'''A breakpoint that prints a message and goes on, instead of stopping there'''
	return bool(getattr(getattr(item, 'dap', None), 'logMessage', None))


class BreakpointsPane:
	'''The Breakpoints tab: what stops the program on the left, what only prints on the right

	A logpoint is a breakpoint to the adapter and to the gutter, but not to whoever is looking for
	where the program will stop: in one list they are a row with a different dot among rows that
	stop. So they have a column of their own, with the message each one prints.
	'''

	def __init__(self, ui: PanelUI):
		self.ui = ui

	def every(self):
		breakpoints = self.ui.backend.breakpoints
		return [item for collection in (breakpoints.source, breakpoints.function, breakpoints.data) for item in collection]

	def text_button(self, label, title, callback, enabled):
		"""A button that says what it does, and its width in rem

		Two icons at the end of the heading were not seen as buttons at all: these are the two things
		done to every breakpoint at once, and an icon for either would have to be learned.
		"""
		ui = self.ui
		width = len(label) * CH + 2.1
		text = escape(label).replace(' ', '&nbsp;')
		if enabled:
			inner = ui.link(text, callback, title, 'cfg small')
		else:
			inner = '<span class="cfg small faint" title="{}">{}</span>'.format(escape(title + ' · unavailable', quote=True), text)
		return ui.slot(inner, width, 'center'), width

	def render(self, width):
		ui = self.ui
		breakpoints = ui.backend.breakpoints
		# The ones of this column. A logpoint is in the other one, and `all` over a list that does
		# not show it is not what was pressed: it took the logpoints with it
		stops = lambda item: not is_logpoint(item)
		every = [item for item in self.every() if stops(item)]
		count = len(every)

		# all of them at once: off and back on without losing them, and gone.
		# With none to act on, the first reads as what it will be once there is one
		any_enabled = any(item.enabled for item in every) or not every
		toggle, toggle_width = self.text_button('Disable all' if any_enabled else 'Enable all',
			'Disable all breakpoints' if any_enabled else 'Enable all breakpoints',
			lambda: breakpoints.set_all_enabled(not any_enabled, stops), bool(every))
		remove, remove_width = self.text_button('Remove all', 'Remove all breakpoints', lambda: breakpoints.remove_only(stops), bool(every))

		rows = [ui.heading('Breakpoints', 'breakpoints', width, toggle + remove, (toggle_width + remove_width) / ACTION, suffix=' ({})'.format(count))]
		if 'breakpoints' not in ui.state.expanded:
			return rows

		for group, collection in (('EXCEPTIONS', breakpoints.filters), ('FUNCTIONS', breakpoints.function), ('DATA', breakpoints.data), ('', breakpoints.source)):
			items = [item for item in collection if not is_logpoint(item)]
			if items and group:
				rows.append(ui.row('<span class="group">{}</span>'.format(group)))
			rows.extend(self.rows(items, width))
		return rows

	def logpoints(self, width):
		ui = self.ui
		items = [item for item in ui.backend.breakpoints.source if is_logpoint(item)]
		# at the line the cursor is on in the file being edited, as the menu entry of the same name
		add, add_width = self.text_button('Add logpoint', 'Add a logpoint at the line of the cursor', lambda: ui.run_command('add_logpoint'), True)
		rows = [ui.heading('Logpoints', 'logpoints', width, add, add_width / ACTION, suffix=' ({})'.format(len(items)))]
		if 'logpoints' not in ui.state.expanded:
			return rows
		if not items:
			rows.append(ui.row(ui.text('Prints a message at a line and goes on. Put the cursor on the line, then Add logpoint', width, 'faint')))
		rows.extend(self.rows(items, width))
		return rows

	def rows(self, items, width):
		"""A row for each breakpoint, under the name of its file when it is a line of one"""
		ui = self.ui
		breakpoints = ui.backend.breakpoints
		rows = []
		last_file = None
		for item in items:
			if isinstance(item, dap.SourceBreakpoint) and item.file != last_file:
				last_file = item.file
				rows.append(ui.row(ui.text(os.path.basename(item.file), width, 'muted')))
			actions = BreakpointView(breakpoints, item, ui.backend._on_navigate_to_source)
			mark = ui.button('breakpoint' if item.enabled else 'unchecked', 'Toggle breakpoint', actions._on_toggle,
				width=CONTROL, tone='danger' if item.enabled else 'faint')
			label = 'Line {}'.format(item.line) if isinstance(item, dap.SourceBreakpoint) else item.name
			if is_logpoint(item):
				# what it prints is what tells one logpoint from the next
				label += ' · ' + str(item.dap.logMessage)
			elif item.tag:
				label += ' · ' + item.tag
			content = mark + ui.link(ui.text(label, width - CONTROL - 2 * ACTION), actions._on_navigate, label)
			content += ui.button('edit', 'Edit breakpoint', actions.edit)
			content += ui.button('close', 'Remove breakpoint', actions.remove, actions.is_removeable())
			rows.append(ui.row(content))
		return rows
