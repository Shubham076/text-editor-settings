from __future__ import annotations

from typing import TYPE_CHECKING

from .. import configurations, core, dap
from ..ui import InputList, InputListItem

if TYPE_CHECKING:
	from .panel import PanelUI


class ConfigurationPicker:
	"""The toolbar's configuration picker: Sublime's quick panel

	The same rows as the gear's list (`configurations.items`): paused first, then running, then
	stopped, the status as the coloured badge and the annotation, opened on the selection. Choosing
	one also restores the tab remembered for it.
	"""

	def __init__(self, ui: PanelUI):
		self.ui = ui

	def show(self):
		backend = self.ui.backend
		rows, selected = configurations.items(backend, lambda item: self.select(item.id_ish))
		rows.append(InputListItem(self.edit, 'Edit Configuration File', annotation=backend.project.project_file_name))
		core.run(InputList('Run configuration', selected or 0)[rows])

	def select(self, value):
		ui = self.ui
		if ui.closed:
			return
		for item in (*ui.backend.project.compounds, *ui.backend.project.configurations):
			if item.id_ish == value:
				# A configuration gets a remembered tab only from an explicit tab click. Untouched
				# configurations start independently on Call Stack / Variables rather than inheriting
				# whichever tab the previously selected configuration left visible. A paused selection
				# must remain on its call stack; this automatic focus does not overwrite its preference.
				tabs = getattr(ui.backend.project, 'configuration_tabs', {})
				if isinstance(item, dap.ConfigurationCompound):
					session = configurations.session_for_names(ui.backend, item.configurations)
				else:
					session = configurations.session_for(ui.backend, item.name)
				paused = bool(session and session.is_paused)
				tab = 'debugger' if paused else tabs.get(item.id_ish, 'debugger')
				# Older versions stored the global Breakpoints view per configuration. Do not restore
				# that stale value now that Breakpoints has moved out of the session tab row.
				if tab == 'breakpoints':
					tab = 'debugger'
				configurations.select(ui.backend, item.name)
				ui.toolbar.select_tab(tab, remember=False)
				return

	def edit(self):
		self.ui.run_command('edit_configurations')
