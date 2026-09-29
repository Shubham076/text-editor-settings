from __future__ import annotations
from typing import TYPE_CHECKING

from dataclasses import dataclass
from functools import partial

from . import core
from . import dap

from .output_panel_console import ConsoleOutputPanel
from .settings import Settings

if TYPE_CHECKING:
	from .debugger import Debugger


@dataclass
class SessionPanels:
	'''The console of one configuration, which outlives any one run of it

	Keyed by the configuration rather than the session so that the output of a run is still there to read
	after it ends, and so that running the same thing again writes into the console that is already open
	instead of leaving a trail of dead ones.

	`session` is what is running right now, or None once it has finished.

	The callstack is shared. It already renders every session, nested where one started another, so a
	copy per configuration would be the same tree drawn twice.
	'''

	configuration_id: str
	console: ConsoleOutputPanel
	session: dap.Session | None = None
	configuration_name: str = ''
	console_visible: bool = False
	has_output: bool = False
	owns_console: bool = True

	def dispose(self) -> None:
		if self.owns_console:
			self.console.dispose()


class SessionPanelsRegistry(core.Dispose):
	'''A console per running configuration

	With one console for the whole window the output of two configurations interleaves with nothing but
	a session tag to tell them apart. One each is enough, and the existing tab strip already lists
	panels, so they need no new UI: the tabs read `Callstack`, `Test 1`, `Test 2`.

	Child sessions get no console. They log into their parents, which is the rule `SessionScope`
	follows for the callstack.
	'''

	def __init__(self, debugger: Debugger, console: ConsoleOutputPanel) -> None:
		super().__init__()

		self.debugger = debugger
		self.console = console
		self.panels: list[SessionPanels] = []

		self.dispose_add(
			debugger.on_session_added.add(self._on_session_added),
			debugger.on_session_removed.add(self._on_session_removed),
			debugger.on_session_output.add(self._on_session_output),
		)

	def is_enabled(self) -> bool:
		return Settings.session_panels

	def _on_session_added(self, session: dap.Session) -> None:
		if session.parent:
			return
		visible = session.configuration.get('console') not in ('integratedTerminal', 'externalTerminal')

		# the console of a previous run of this configuration, still open with its output in it. Reuse it
		# rather than leaving a trail of dead ones, emptied so the run being started is the only thing in
		# it. The output of a run is kept until the next run of the same thing, not forever
		if panels := self.panels_for_configuration(session.configuration.id_ish):
			panels.session = session
			panels.console_visible = visible
			panels.has_output = False
			if panels.owns_console:
				panels.console.session = session
				panels.console.clear()
			self.debugger.on_output_panels_updated()
			return

		owns_console = self.is_enabled()
		console = ConsoleOutputPanel(self.debugger, session, protocol=self.console.protocol, show_panel=False) if owns_console else self.console
		panels = SessionPanels(session.configuration.id_ish, console, session,
			configuration_name=session.configuration.name, console_visible=visible, owns_console=owns_console)
		self.panels.append(panels)
		self.debugger.on_output_panels_updated()
		if not owns_console:
			return

		# without these the panel is a place output arrives and nothing else: the expression it is typed
		# into goes nowhere and a source location in a stack trace does not open
		console.on_input.add(partial(self._on_input, panels))
		console.on_navigate.add(self.debugger._on_navigate_to_source)

	@core.run
	async def _on_input(self, panels: SessionPanels, command: str) -> None:
		'''Evaluates what was typed into a session console, in that session

		The debuggers own console evaluates in `current_session`, which is right when there is one console
		for everything. A console that belongs to a configuration evaluates in that configuration, whether
		or not it is the one selected.
		'''
		console = panels.console
		session = panels.session

		if not session:
			console.error('Not running')
			return

		try:
			result = await session.evaluate_expression(command, context='repl')
			console.write_evaluated(session, result)

		except dap.Error as e:
			console.error(f'{e}')

	def _on_session_removed(self, session: dap.Session) -> None:
		# the console stays, with what the run wrote in it. Only the session goes
		if panels := self.panels_for(session):
			if panels.session is session:
				panels.session = None
				self.debugger.on_output_panels_updated()

	def _on_session_output(self, session: dap.Session, event: dap.OutputEvent):
		if event.category != 'telemetry' and (event.output or event.variablesReference):
			self.reveal_console(session)

	def reveal_console(self, session: dap.Session):
		if panels := self.panels_for(session):
			panels.has_output = True
			if not panels.console_visible:
				panels.console_visible = True
				self.debugger.on_output_panels_updated()

	def on_terminal_request(self, session: dap.Session):
		if (panels := self.panels_for(session)) and panels.session:
			mode = panels.session.configuration.get('console')
			if not panels.has_output and mode not in ('internalConsole', 'integratedConsole'):
				panels.console_visible = False
				self.debugger.on_output_panels_updated()

	def visible_console_for(self, session: dap.Session):
		while session.parent:
			session = session.parent
		panels = self.panels_for_configuration(session.configuration.id_ish)
		return panels.console if panels and panels.console_visible else None

	def panels_for_configuration(self, configuration_id: str) -> SessionPanels | None:
		for panels in self.panels:
			if panels.configuration_id == configuration_id:
				return panels

		return None

	def panels_for(self, session: dap.Session | None) -> SessionPanels | None:
		'''The console a session belongs to, which for a child session is its parents'''
		while session:
			for panels in self.panels:
				if panels.session is session:
					return panels

			session = session.parent

		return None

	def running(self) -> bool:
		'''Whether any of these consoles belongs to something that is running'''
		return any(panels.session for panels in self.panels)

	def panels_for_console(self, console: ConsoleOutputPanel) -> SessionPanels | None:
		for panels in self.panels:
			if panels.console is console:
				return panels

		return None

	def close(self, panels: SessionPanels) -> bool:
		'''Closes a console. A console with something still writing to it is left alone'''
		shared = [item for item in self.panels if item.console is panels.console]
		if panels not in self.panels or any(item.session for item in shared):
			return False

		for item in shared:
			self.panels.remove(item)
			item.dispose()
		self.debugger.on_output_panels_updated()
		return True

	def console_for(self, session: dap.Session | None) -> ConsoleOutputPanel:
		if panels := self.panels_for(session):
			return panels.console

		return self.console

	def dispose(self) -> None:
		super().dispose()

		for panels in self.panels:
			panels.dispose()

		self.panels.clear()
