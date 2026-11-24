from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .. import dap
from ..views.breakpoints import BreakpointView
from .style import ACTION, CONTROL

if TYPE_CHECKING:
	from .panel import PanelUI


class BreakpointsPane:
	def __init__(self, ui: PanelUI):
		self.ui = ui

	def render(self, width):
		ui = self.ui
		breakpoints = ui.backend.breakpoints
		count = sum(1 for collection in (breakpoints.source, breakpoints.function, breakpoints.data) for _ in collection)
		# all of them at once: off and back on without losing them, and gone
		every = [item for collection in (breakpoints.source, breakpoints.function, breakpoints.data) for item in collection]
		# with none to act on it reads as what it will be once there is one
		any_enabled = any(item.enabled for item in every) or not every
		actions = ui.button('unchecked' if any_enabled else 'breakpoint',
			'Disable all breakpoints' if any_enabled else 'Enable all breakpoints',
			lambda: breakpoints.set_all_enabled(not any_enabled), bool(every))
		actions += ui.button('close', 'Remove all breakpoints', lambda: breakpoints.remove_all(), bool(every))
		rows = [ui.heading('Breakpoints', 'breakpoints', width, actions, 2, suffix=' ({})'.format(count))]
		if 'breakpoints' not in ui.state.expanded:
			return rows
		for group, collection in (('EXCEPTIONS', breakpoints.filters), ('FUNCTIONS', breakpoints.function), ('DATA', breakpoints.data), ('', breakpoints.source)):
			last_file = None
			items = list(collection)
			if items and group:
				rows.append(ui.row('<span class="group">{}</span>'.format(group)))
			for item in items:
				if isinstance(item, dap.SourceBreakpoint) and item.file != last_file:
					last_file = item.file
					rows.append(ui.row(ui.text(os.path.basename(item.file), width, 'muted')))
				actions = BreakpointView(breakpoints, item, ui.backend._on_navigate_to_source)
				mark = ui.button('breakpoint' if item.enabled else 'unchecked', 'Toggle breakpoint', actions._on_toggle,
					width=CONTROL, tone='danger' if item.enabled else 'faint')
				label = 'Line {}'.format(item.line) if isinstance(item, dap.SourceBreakpoint) else item.name
				if item.tag:
					label += ' · ' + item.tag
				content = mark + ui.link(ui.text(label, width - CONTROL - 2 * ACTION), actions._on_navigate, label)
				content += ui.button('edit', 'Edit breakpoint', actions.edit)
				content += ui.button('close', 'Remove breakpoint', actions.remove, actions.is_removeable())
				rows.append(ui.row(content))
		return rows
