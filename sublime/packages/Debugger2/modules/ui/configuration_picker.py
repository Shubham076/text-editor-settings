from __future__ import annotations

from typing import TYPE_CHECKING

from .. import configurations, core
from ..ui import InputList, InputListItem

if TYPE_CHECKING:
	from .panel import PanelUI


class ConfigurationPicker:
	"""The toolbar's configuration picker: Sublime's quick panel

	The same rows as the gear's list (`configurations.items`): paused first, then running, then
	stopped, the status as the coloured badge and the annotation, opened on the selection. Choosing
	one keeps the tab that is open, now about that configuration.
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
				# The tab stays the one that is open: on the console, picking another configuration shows
				# that one's console, on the call stack its frames. Read before the selection changes,
				# which can open a panel of its own. A tab the new selection has nothing for (a console
				# before its first run) falls back to the call stack in `select_tab`.
				tab = ui.state.tab
				configurations.select(ui.backend, item.name)
				ui.toolbar.select_tab(tab)
				return

	def edit(self):
		self.ui.run_command('edit_configurations')
