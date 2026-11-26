from __future__ import annotations

from functools import partial
from html import escape
from typing import TYPE_CHECKING

from .. import configurations, core, dap
from ..views.session_scope import root_of
from .configuration_picker import ConfigurationPicker
from .output_tabs import console_panels, terminal_panels
from .state import session_status
from .style import CH, CHIP_DOT_GAP, CHIP_GAP, CHIP_NAME, CHIP_PAD, CHIP_SHORT, DASHBOARDS, PAD, TAB_NAME, TABS, TOOL, ZW

if TYPE_CHECKING:
	from .panel import PanelUI


def short_names(names):
	"""The names with the words they all start with taken off: `ps-backend`, `ps-agentic` to `backend`, `agentic`

	Configurations of one project tend to share a prefix, which says nothing on a chip beside the
	others and costs the room of a whole chip. Only whole words go (the cut is after a separator),
	and nothing is cut when that would leave a name empty.
	"""
	names = list(names)
	if len(names) < 2:
		return names
	prefix = names[0]
	for name in names[1:]:
		while not name.startswith(prefix):
			prefix = prefix[:-1]
	cut = max(prefix.rfind(separator) for separator in '-_ /.:') + 1
	if not cut or any(len(name) <= cut for name in names):
		return names
	return [name[cut:] for name in names]


class Toolbar:
	def __init__(self, ui: PanelUI):
		self.ui = ui
		self.picker = ConfigurationPicker(ui)

	def render(self):
		ui = self.ui
		if ui.header_view:
			return self.strip(), ''
		session = ui.active_session
		status = session_status(session)
		controls, start_width = self.start_controls(session)
		for icon, label, method in (('over', 'Step over', 'step_over'), ('into', 'Step into', 'step_in'), ('out', 'Step out', 'step_out')):
			controls += ui.tool(icon, label, partial(self.step, method), bool(session and session.is_paused))
		restart_enabled = bool(ui.backend.project.configuration_or_compound) and (not session or session.is_stoppable)
		controls += ui.separator() + ui.tool('restart', 'Restart', partial(self.transport, 'restart'), restart_enabled)
		controls += ui.tool('stop', 'Stop', partial(self.transport, 'stop'), bool(session and session.is_stoppable), css='stop')
		gear = self.tasks_tool() + ui.tool('settings', 'Debugger settings', self.settings)
		breakpoints, breakpoints_width = self.breakpoints_control()
		name = ui.backend.project.name or 'Select configuration'
		return ui.toolbar_layout(name, status, self.picker.show, controls, gear, split=ui.body,
			extra=breakpoints, extra_width=breakpoints_width, tools=6 + round(start_width / TOOL))

	# -- the fixed strip -------------------------------------------------------------------

	def strip(self):
		"""The toolbar in the fixed strip under the output: one row, no brand label or tab row

		Left to right: a back arrow to the call stack (on the call stack itself the brand mark holds
		that slot, so the chips start at the same place on every tab), a chip for every configuration
		that is running, the controls of the selected one, and at the far end the breakpoints view
		and the settings.

		The chips are what the picker and the status badge were: with several configurations running
		each is one click away, and the dot of a chip is its status. The strip is one line and cannot
		grow, so everything that is not usable right now stays off it: the step buttons while nothing
		is paused, restart and stop while nothing runs.
		"""
		ui = self.ui
		if ui.body and ui.layout == 'debugger':
			lead = ui.slot('<span class="brand" title="Debugger">{}</span>'.format(ui.icon('bug', 'muted')), TOOL, 'center')
		else:
			lead = ui.tool('back', 'Back to call stack', partial(self.select_tab, 'debugger'))
		lead += ui.slot('', 0.4)
		lead_width = TOOL + 0.4
		controls, controls_width = self.strip_controls()
		tail = self.tasks_tool()
		tail += ui.tool('breakpoints', 'Show breakpoints', partial(self.select_tab, 'breakpoints'), primary=ui.state.tab == 'breakpoints')
		tail += ui.tool('settings', 'Debugger settings', self.settings)
		tail_width = 3 * TOOL + 0.6
		width = ui.total - 2 * PAD
		cell = 'toolbar joined strip'
		style = 'style="width:{}px;"'.format(ui.px(width))
		room = width - lead_width - 1.5 - controls_width - tail_width
		chips, chips_width = self.chips(room)
		if chips_width <= room:
			return '<div class="{}" {}>{}{}{}{}{}{}</div>'.format(
				cell, style, lead, chips, ui.separator(), controls, ui.slot('', room - chips_width), tail)
		# too narrow even for the selected chip alone: the chips get a row to themselves
		chips, _ = self.chips(width - lead_width)
		gap = max(0, width - controls_width - tail_width)
		return '<div class="{}" {}>{}{}</div><div class="{} continued" {}>{}{}{}</div>'.format(
			cell, style, lead, chips, cell, style, controls, ui.slot('', gap), tail)

	def tasks_tool(self):
		"""The button that lists the tasks of the project, to run one

		What the picker is for configurations: the list is Sublime's quick panel, with what is
		running first. Lit while a task is running, which is the one thing about tasks the bar
		says without being asked.
		"""
		running = bool(getattr(self.ui.backend, 'tasks', None) and self.ui.backend.tasks.get_running())
		return self.ui.tool('tasks', 'Run a task' + (' · one is running' if running else ''), self.run_task, css='active' if running else '')

	def run_task(self):
		self.ui.run_command('select_and_run_task')

	def start_controls(self, session):
		"""What starts the selected configuration and, while it is debugged, pauses and continues it, and the width in rem

		Two buttons that are always there: play runs it without the debugger, the bug runs it under the
		debugger. Which of the two it was started with is chosen each time it is started, so the same
		configuration can be run once to see it work and debugged the next time. While it runs the one
		it was started with is green, which is how the bar says whether breakpoints will be hit. The
		other one then starts it again the other way.
		"""
		ui = self.ui
		mode = self.mode(session)
		# its own icon: beside the continue of a paused session, two of the same were two plays
		controls = ui.tool('run', 'Run without the debugger', partial(self.transport, 'run'), css='active' if mode == 'run' else '')
		controls += ui.tool('bug', 'Debug', partial(self.transport, 'start'), css='active' if mode == 'start' else '')
		width = 2 * TOOL
		# only what is being debugged can be paused
		if mode == 'start':
			action = 'pause' if session.is_running else 'continue'
			controls += ui.tool('pause' if action == 'pause' else 'play', action.title(), partial(self.transport, action), session.is_running or session.is_paused)
			width += TOOL
		return controls, width

	@staticmethod
	def mode(session):
		"""How the selected configuration is running: 'run' without the debugger, 'start' under it, None when it is not"""
		if not session:
			return None
		return 'run' if getattr(root_of(session), 'no_debug', False) else 'start'

	def strip_controls(self):
		"""The transport buttons of the selected configuration that can be pressed right now, and their width in rem"""
		ui = self.ui
		session = ui.active_session
		controls, width = self.start_controls(session)
		if session and session.is_paused:
			for icon, label, method in (('over', 'Step over', 'step_over'), ('into', 'Step into', 'step_in'), ('out', 'Step out', 'step_out')):
				controls += ui.tool(icon, label, partial(self.step, method))
			controls += ui.separator()
			width += 3 * TOOL + 1.5
		if session:
			controls += ui.tool('restart', 'Restart', partial(self.transport, 'restart'), session.is_stoppable)
			controls += ui.tool('stop', 'Stop', partial(self.transport, 'stop'), session.is_stoppable, css='stop')
			width += 2 * TOOL
		if self.console():
			# after stop, set off from the buttons that act on the program: this one only empties
			# the output on screen. It is there on a console tab alone, the only thing it clears
			controls += ui.separator() + ui.tool('trash', 'Clear console', self.clear_console)
			width += TOOL + 1.5
		return controls, width

	def console(self):
		"""The console this bar is drawn under, `None` under any other panel"""
		from ..output_panel_console import ConsoleOutputPanel
		panel = self.ui.panel
		return panel if isinstance(panel, ConsoleOutputPanel) else None

	def clear_console(self):
		"""Empties the console that is open, and no other: the program and its session go on as they were"""
		console = self.console()
		if not console:
			return
		# clearing takes the prompt with the output, a console that was being typed into gets it back
		typing = bool(console.input_region())
		console.clear()
		if typing:
			console.enable_input_mode()

	def chip_items(self):
		"""(item, status, selected) for each chip, in the order the project lists them

		A chip for each configuration that is running or paused, and one for the selection whatever
		it is doing, so the controls always have a name beside them. A compound is only a chip while
		it is the selection: what it started are chips of their own.
		"""
		backend = self.ui.backend
		selection = backend.project.configuration_or_compound
		# `is not None`: a configuration is a dict, and an empty one is still a selection
		selected_id = selection.id_ish if selection is not None else None
		rows = []
		for item in (*backend.project.compounds, *backend.project.configurations):
			selected = item.id_ish == selected_id
			status = configurations.status_of(backend, item)
			if selected or (status != 'Stopped' and item not in backend.project.compounds):
				rows.append((item, status, selected))
		if selection is not None and not any(selected for _, _, selected in rows):
			# a selection the project no longer lists still names what the controls act on
			rows.append((selection, configurations.status_of(backend, selection), True))
		return rows

	def chips(self, room):
		"""The chips and the list button that fit in `room` rem, and the width they take

		The selected chip is always drawn, under its whole name; the others drop the words all the
		names start with. When they do not all fit, chips go from the far end and the list button
		counts them (`+2`): the list has every configuration. A selected chip too long for the room
		is clipped, and when even that is too wide the caller wraps the strip.
		"""
		ui = self.ui
		rows = self.chip_items()
		short = short_names([item.name for item, _, _ in rows])
		entries = [(item, status, selected, self.chip_label(item.name if selected else name, CHIP_NAME if selected else CHIP_SHORT))
			for (item, status, selected), name in zip(rows, short)]

		def chip_width(label):
			return 2 * CHIP_PAD + CH + CHIP_DOT_GAP + len(label) * CH + 0.15 + CHIP_GAP

		def more_label(hidden):
			return '+{}'.format(hidden) if hidden else '' if entries else 'Select configuration'

		def more_width(hidden):
			label = more_label(hidden)
			return 2 * CHIP_PAD + 0.8 + (len(label) * CH + CHIP_DOT_GAP if label else 0) + 0.15

		def total(hidden):
			return sum(chip_width(entry[3]) for entry in entries) + more_width(hidden)

		hidden = 0
		while total(hidden) > room and any(not entry[2] for entry in entries):
			entries.pop(max(index for index, entry in enumerate(entries) if not entry[2]))
			hidden += 1
		if entries and total(hidden) > room:
			item, status, selected, label = entries[0]
			keep = max(4, len(label) - int((total(hidden) - room) / CH) - 1)
			entries[0] = (item, status, selected, self.chip_label(label, keep))

		html = ''
		for item, status, selected, label in entries:
			# The dot is a glyph coloured by the stylesheet, as the status badge it replaces was, so
			# it is the very green and yellow the rest of the debugger uses: `var(--greenish)` held
			# to a readable contrast by minihtml. A rasterised icon would have to resolve that colour
			# itself, and what `view.style()` reports for it is not what the stylesheet draws.
			kind = {'Paused': 'warnish', 'Running': 'infoish'}.get(status, 'faint')
			dot = '<span class="{}">{}</span>'.format(kind, '&#9679;' if kind != 'faint' else '&#9675;')
			content = dot + ui.slot('', CHIP_DOT_GAP) + escape(label).replace(' ', '&nbsp;')
			# the selected chip opens the list, as the picker it replaces did
			callback = self.picker.show if selected else partial(self.picker.select, item.id_ish)
			html += ui.link(content, callback, '{} · {}'.format(item.name, status), 'cfg' + (' active' if selected else ''))
			html += ui.slot('', CHIP_GAP)
		label = more_label(hidden)
		# the zero-width text gives a chip holding nothing but the chevron the line box, and so the
		# height, of the chips with a name
		# the chevron in the full text colour and the border of the selected chip: a small arrow in a
		# faint box, dimmed like the names of the chips that are not selected, was hard to make out
		content = ZW + (escape(label).replace(' ', '&nbsp;') + ui.slot('', CHIP_DOT_GAP) if label else '') + ui.icon('down', 'primary')
		html += ui.link(content, self.picker.show, 'Select run configuration', 'cfg more')
		return html, total(hidden)

	@staticmethod
	def chip_label(name, length):
		return name if len(name) <= length else name[:max(1, length - 1)] + '…'

	def breakpoints_control(self):
		"""The global Breakpoints view belongs beside the global settings control, not session tabs."""
		ui = self.ui
		width = len('Breakpoints') * CH + 1.7
		active = ui.state.tab == 'breakpoints'
		button = ui.link('Breakpoints', partial(self.select_tab, 'breakpoints'), 'Show breakpoints',
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

	def select_tab(self, tab):
		ui = self.ui
		group, _, index = tab.partition(':')
		if group in ('console', 'terminal'):
			panels = self.tab_panels(group)
			# `console:1` is the tab of one console among several, `console` the only one there is
			position = int(index) if index.isdigit() else 0
			if position < len(panels):
				panels[position].open()
			elif panels:
				panels[0].open()
			else:
				ui.backend.callstack.open()
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

	def tab_panels(self, tab):
		"""The panels behind the console or the terminal tab, in the order they are gone through"""
		return console_panels(self.ui.backend) if tab == 'console' else self.terminals()

	def tab_name(self, panel, label):
		"""What the tab of one console or terminal among several reads: whose it is

		A console is named after its configuration and a terminal after its task. The terminal a
		program was started in is named `configuration<tab>Terminal`, for the title of its panel.
		"""
		name = ' '.join(str(getattr(panel, 'name', '') or label).split())
		return self.chip_label(name, TAB_NAME)

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
		items = []
		for key, label, _ in TABS:
			if key not in available:
				continue
			panels = self.tab_panels(key) if key in ('console', 'terminal') else []
			if len(panels) < 2:
				items.append((key, label))
				continue
			# several behind one name: the consoles of a compound, the terminals of two tasks. Each
			# is a tab of its own under the name of what it belongs to, one tab for all of them
			# shows one and leaves the others to be found
			items += [('{}:{}'.format(key, index), self.tab_name(panel, label)) for index, panel in enumerate(panels)]
		dashboards = list(self.dashboards().values())
		items += [(panel.output_panel_name, panel.name) for panel in ui.backend.output_panels
			if not any(panel is dashboard for dashboard in dashboards) and not isinstance(panel, (ConsoleOutputPanel, TerminusOutputPanel))]
		return items

	def tab_panel(self, key):
		"""The panel a console or terminal tab is the tab of, `None` for every other tab

		With one tab for the consoles it is the one that is open, or the first when the row is
		drawn in some other panel.
		"""
		group, _, index = key.partition(':')
		if group not in ('console', 'terminal'):
			return None
		panels = self.tab_panels(group)
		if index.isdigit():
			return panels[int(index)] if int(index) < len(panels) else None
		for panel in panels:
			if panel is self.ui.panel:
				return panel
		return panels[0] if panels else None

	def closable_console(self, target=None):
		"""The console record whose close button a console tab shows, if no session owns it."""
		target = target or self.tab_panel('console')
		if not target:
			return None
		records = [item for item in self.ui.backend.session_panels.panels if item.console is target]
		if records and not any(item.session for item in records):
			return records[0]
		return None

	def tabs(self):
		"""The tab row, the open tab underlined

		The underline is the open tab's own bottom border, so it is exactly as wide as the tab
		whatever the font. It used to be a bar of its own, placed by adding up the widths of the
		tabs before it from an assumed character width; with a font narrower than that assumption
		it drifted to the right, further with every tab, until it sat between two of them. A tab's
		padding reaches down to the bottom of the row (inline padding paints without taking room),
		which puts the border on the spacer that keeps the row the height it had with the bar.
		"""
		ui = self.ui
		row = ZW
		for key, label in self.tab_items():
			group = key.partition(':')[0]
			panel = self.tab_panel(key)
			# one of several consoles is the open tab when it is the panel this row is drawn in
			active = key == ui.state.tab or (group != key and group == ui.state.tab and panel is ui.panel)
			row += ui.link(escape(label), partial(self.select_tab, key), str(getattr(panel, 'name', '') or label) if group != key else label,
				'tab' + (' active' if active else ''))
			if group == 'console' and (record := self.closable_console(panel)):
				row += ui.button('close', 'Close console output', partial(self.close_console, record))
			if group == 'terminal' and (terminal := self.closable_terminal(panel)):
				row += ui.button('close', 'Close finished terminal', terminal.dispose)
		return '<div class="tabs" style="width:{}px;"><div class="tabrow">{}</div><div class="underline"></div></div>'.format(
			ui.px(ui.total - 2 * PAD), row)

	def closable_terminal(self, target=None):
		"""The terminal whose close button a terminal tab shows: its own, once its process has ended

		Like the console tab's close button. There is no bar of terminal chips: the tab is the
		terminal, and a further one is opened from the command palette (`New Terminal`).
		"""
		target = target or self.tab_panel('terminal')
		return target if target and target.is_finished() else None

	def close_console(self, record):
		if self.ui.backend.session_panels.close(record):
			self.ui.backend.callstack.open()

	@core.run
	async def transport(self, action):
		ui = self.ui
		session = ui.active_session
		try:
			if action in ('start', 'run') and not session:
				await ui.backend.start(no_debug=action == 'run')
			elif action in ('start', 'run'):
				# the one it is running as is only a light, the other one is a way to change over
				if action != self.mode(session):
					await configurations.restart(ui.backend, ui.backend.project.name, no_debug=action == 'run')
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
		"""The gear opens Sublime's quick panel with the debugger's options

		The same list the settings icon in the project file and the command palette entry open
		(`ChangeConfiguration`), so there is one place to look.
		"""
		self.ui.run_command('change_configuration')
