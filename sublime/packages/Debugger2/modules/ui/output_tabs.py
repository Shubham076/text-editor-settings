from __future__ import annotations

from .. import dap
from ..views.session_scope import root_of


def selected_names(debugger):
	selection = debugger.project.configuration_or_compound
	return selection.configurations if isinstance(selection, dap.ConfigurationCompound) else [debugger.project.name]


def console_panels(debugger):
	registry = debugger.session_panels
	if not registry:
		return []
	names = selected_names(debugger)
	panels = []
	for record in registry.panels:
		if record.configuration_name in names and record.console_visible and record.console in debugger.output_panels and record.console not in panels:
			panels.append(record.console)
	return panels


def terminal_panels(debugger):
	from ..output_panel_terminus import TerminusOutputPanel
	names = selected_names(debugger)
	return [panel for panel in debugger.output_panels if isinstance(panel, TerminusOutputPanel)
		and (not panel.session or root_of(panel.session).configuration.name in names)]
