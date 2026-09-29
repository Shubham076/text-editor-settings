from __future__ import annotations

from functools import partial
from html import escape
from typing import TYPE_CHECKING

from .. import configurations, core, dap
from ..views.session_scope import root_of
from .configuration_picker import ConfigurationPicker
from .output_tabs import console_panels, terminal_panels
from .state import session_status
from .style import ACTION, CH, DASHBOARDS, PAD, TAB_PAD, TABS, TOOL, ZW

if TYPE_CHECKING:
	from .panel import PanelUI


class Toolbar:
	def __init__(self, ui: PanelUI):
		self.ui = ui
		self.picker = ConfigurationPicker(ui)

	def render(self):
		ui = self.ui
		session = ui.active_session
		status = session_status(session)
		action = 'pause' if session and session.is_running else 'continue' if session and session.is_paused else 'start'
		enabled = not session or session.is_running or session.is_paused
		controls = ui.tool('pause' if action == 'pause' else 'play', action.title(), partial(self.transport, action), enabled, primary=True)
		for icon, label, method in (('over', 'Step over', 'step_over'), ('into', 'Step into', 'step_in'), ('out', 'Step out', 'step_out')):
			controls += ui.tool(icon, label, partial(self.step, method), bool(session and session.is_paused))
		restart_enabled = bool(ui.backend.project.configuration_or_compound) and (not session or session.is_stoppable)
		controls += ui.separator() + ui.tool('restart', 'Restart', partial(self.transport, 'restart'), restart_enabled)
		controls += ui.tool('stop', 'Stop', partial(self.transport, 'stop'), bool(session and session.is_stoppable), css='stop')
		gear = ui.tool('settings', 'Debugger settings', self.settings)
		breakpoints, breakpoints_width = self.breakpoints_control()
		name = ui.backend.project.name or 'Select configuration'
		if ui.header_view:
			# the fixed strip: one row, no brand label or tab row (the tabs are above the panel's
			# content). A back arrow at the very left, in front of the picker, returns to the call
			# stack; on the call stack itself the brand mark holds that slot instead, so the picker
			# sits at the same place on every tab
			if ui.body and ui.layout == 'debugger':
				lead = ui.slot('<span class="brand" title="Debugger">{}</span>'.format(ui.icon('bug', 'muted')), TOOL, 'center')
			else:
				lead = ui.tool('back', 'Back to call stack', partial(self.select_tab, 'debugger'))
			return ui.toolbar_layout(name, status, self.picker.show, controls, gear, split=False, brand=False,
				lead=lead + ui.slot('', 0.4), lead_width=TOOL + 0.4, extra=breakpoints,
				extra_width=breakpoints_width, css='strip')
		return ui.toolbar_layout(name, status, self.picker.show, controls, gear, split=ui.body,
			extra=breakpoints, extra_width=breakpoints_width)

	def breakpoints_control(self):
		"""The global Breakpoints view belongs beside the global settings control, not session tabs."""
		ui = self.ui
		width = len('Breakpoints') * CH + 1.7
		active = ui.state.tab == 'breakpoints'
		button = ui.link('Breakpoints', partial(self.select_tab, 'breakpoints', False), 'Show breakpoints',
			'breakpoints-control' + (' active' if active else ''))
		return ui.slot(button, width, 'center'), width

	def panel_tab(self):
		from ..output_panel_console import ConsoleOutputPanel
		from ..output_panel_terminus import TerminusOutputPanel
		panel = self.ui.panel
		if isinstance(panel, ConsoleOutputPanel):
			# the debugger's own console (adapter messages, install output, evaluation in the current
			# session) is its own tab whenever the configurations have consoles of their own
			return 'debugger_console' if self.is_debugger_console(panel) else 'console'
		if isinstance(panel, TerminusOutputPanel):
			return 'terminal'
		for tab, dashboard in self.dashboards().items():
			if panel is dashboard:
				return tab
		return panel.output_panel_name

	def dashboards(self):
		"""Tab key to panel for the dashboards the debugger has built so far, in tab order"""
		backend = self.ui.backend
		return {tab: panel for tab, attribute in DASHBOARDS if (panel := getattr(backend, attribute, None))}

	def terminals(self):
		return terminal_panels(self.ui.backend)

	def is_debugger_console(self, panel):
		backend = self.ui.backend
		return panel is getattr(backend, 'console', None) and panel not in console_panels(backend)

	def select_tab(self, tab, remember=True):
		ui = self.ui
		selected_tab = tab
		if tab in ('console', 'terminal'):
			panels = console_panels(ui.backend) if tab == 'console' else self.terminals()
			if panels:
				panels[0].open()
			else:
				ui.backend.callstack.open()
				selected_tab = 'debugger'
		elif dashboard := self.dashboards().get(tab):
			dashboard.open()
		elif tab == 'debugger_console':
			# same as enter on the call stack: the debug console with its input prompt ready
			console = ui.backend.console
			console.open()
			console.enable_input_mode()
			console.scroll_to_end()
		else:
			for panel in ui.backend.output_panels:
				if panel.output_panel_name == tab:
					panel.open()
					break
		# Breakpoints are shared by every configuration. Opening that global view must not replace a
		# configuration's remembered session tab.
		if remember and selected_tab != 'breakpoints' and selected_tab != ui.state.tab:
			selection = ui.backend.project.configuration_or_compound
			if selection:
				tabs = getattr(ui.backend.project, 'configuration_tabs', None)
				if tabs is None:
					tabs = {}
					ui.backend.project.configuration_tabs = tabs
				tabs[selection.id_ish] = selected_tab
				if save := getattr(ui.backend, 'save_data', None):
					save()

	def tab_items(self):
		from ..output_panel_console import ConsoleOutputPanel
		from ..output_panel_terminus import TerminusOutputPanel
		ui = self.ui
		# the three dashboards are always there; a still unbuilt one (the debugger is being
		# constructed) is listed too, it is built before anything can be clicked
		available = {tab for tab, _ in DASHBOARDS}
		if console_panels(ui.backend):
			available.add('console')
		if self.terminals():
			available.add('terminal')
		if getattr(ui.backend, 'console', None) and self.is_debugger_console(ui.backend.console):
			available.add('debugger_console')
		items = [(key, label) for key, label, _ in TABS if key in available]
		dashboards = list(self.dashboards().values())
		items += [(panel.output_panel_name, panel.name) for panel in ui.backend.output_panels
			if not any(panel is dashboard for dashboard in dashboards) and not isinstance(panel, (ConsoleOutputPanel, TerminusOutputPanel))]
		return items

	def closable_console(self):
		"""The console record whose close button the console tab shows, if no session owns it."""
		ui = self.ui
		outputs = console_panels(ui.backend)
		if not outputs:
			return None
		target = ui.panel if ui.panel in outputs else outputs[0]
		records = [item for item in ui.backend.session_panels.panels if item.console is target]
		if records and not any(item.session for item in records):
			return records[0]
		return None

	def tabs(self):
		ui = self.ui
		items = self.tab_items()
		row, offset, underline = ZW, 0.0, (0.0, 0.0)
		for key, label in items:
			width = len(label) * CH + 2 * TAB_PAD
			active = key == ui.state.tab
			row += ui.link(escape(label), partial(self.select_tab, key), label, 'tab' + (' active' if active else ''))
			if key == 'console' and (record := self.closable_console()):
				row += ui.button('close', 'Close console output', partial(self.close_console, record))
				width += ACTION
			if key == 'terminal' and (terminal := self.closable_terminal()):
				row += ui.button('close', 'Close finished terminal', terminal.dispose)
				width += ACTION
			if active:
				underline = offset, width
			offset += width
		return '<div class="tabs" style="width:{}px;"><div class="tabrow">{}</div><div class="underline" style="margin-left:{}px;width:{}px;"></div></div>'.format(
			ui.px(ui.total - 2 * PAD), row, ui.px(underline[0]), ui.px(underline[1]))

	def closable_terminal(self):
		"""The terminal whose close button the terminal tab shows: the one open, or the selection's first, once its process has ended

		Like the console tab's close button. There is no bar of terminal chips: the tab is the
		terminal, and a further one is opened from the command palette (`New Terminal`).
		"""
		terminals = self.terminals()
		if not terminals:
			return None
		target = self.ui.panel if self.ui.panel in terminals else terminals[0]
		return target if target.is_finished() else None

	def close_console(self, record):
		if self.ui.backend.session_panels.close(record):
			self.ui.backend.callstack.open()

	@core.run
	async def transport(self, action):
		ui = self.ui
		session = ui.active_session
		try:
			if action == 'start' and not session:
				await ui.backend.start()
			elif action == 'restart':
				await configurations.restart(ui.backend, ui.backend.project.name)
			elif action == 'stop' and session and session.is_stoppable:
				selection = ui.backend.project.configuration_or_compound
				roots = ui.scope.sessions if isinstance(selection, dap.ConfigurationCompound) else [root_of(session)]
				for root in roots:
					await ui.backend.stop(root)
			elif action == 'continue' and session and session.is_paused:
				await session.resume()
			elif action == 'pause' and session and session.is_running:
				await session.pause()
		except dap.Error as error:
			ui.backend.console.error(str(error))

	@core.run
	async def step(self, method):
		ui = self.ui
		session = ui.active_session
		if not session or not session.is_paused or method not in ('step_over', 'step_in', 'step_out'):
			return
		try:
			await getattr(session, method)(granularity=ui.backend.stepping_granularity())
		except dap.Error as error:
			ui.backend.console.error(str(error))

	def settings(self):
		"""The gear opens Sublime's quick panel with the debugger's actions and the configurations

		The same list the settings icon in the project file and the command palette entry open
		(`ChangeConfiguration`), so there is one place to look.
		"""
		self.ui.run_command('change_configuration')
