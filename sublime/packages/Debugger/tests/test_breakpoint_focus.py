from __future__ import annotations

import types
import unittest
from unittest.mock import Mock

from test_open_ui import debugger_method


class State(str):
	"""A session state as the debugger reads it: comparable, and knowing the state before it"""
	previous = None


RUNNING, PAUSED = State('running'), State('paused')


class Compound:
	def __init__(self, name, configurations):
		self.name, self.configurations = name, configurations


class Session:
	def __init__(self, name, parent=None):
		self.configuration = types.SimpleNamespace(name=name)
		self.parent = parent
		self._state = RUNNING
		self.stepping = False

	@property
	def state(self):
		return self._state

	@state.setter
	def state(self, value):
		value = State(value)
		value.previous = self._state
		self._state = value

	@property
	def is_paused(self):
		return self.state == PAUSED


class BreakpointFocusTests(unittest.TestCase):
	"""A session that stops at a breakpoint becomes the one the debugger shows"""

	def setUp(self):
		dap = types.SimpleNamespace(Session=types.SimpleNamespace(State=types.SimpleNamespace(PAUSED=PAUSED, RUNNING=RUNNING)), ConfigurationCompound=Compound)
		self.gateway, self.backend, self.agentic = Session('gateway'), Session('backend'), Session('agentic')
		project = types.SimpleNamespace(name='gateway', configuration_or_compound=types.SimpleNamespace(name='gateway'))

		def load_configuration(name):
			project.name = name
			project.configuration_or_compound = types.SimpleNamespace(name=name)
		project.load_configuration = Mock(side_effect=load_configuration)
		self.project = project
		self.debugger = types.SimpleNamespace(
			sessions=[self.gateway, self.backend, self.agentic], session=self.gateway, paused_sessions=set(),
			project=project, callstack=Mock(), on_session_active=Mock(), open_session_output=Mock(),
			output_panels=[], panel_terminals={}, session_panels=None, session_tabs={}, console=Mock(), watch_panel=Mock(), breakpoints_panel=Mock())
		self.debugger.callstack.is_open.return_value = False
		self.debugger.output_panels.append(self.debugger.callstack)
		for name in ('_on_session_updated', 'focus_paused_session', 'shown_panel', 'tab_of', 'open_tab'):
			setattr(self.debugger, name, types.MethodType(debugger_method(name, {'dap': dap}), self.debugger))

	def pause(self, session):
		session.state = PAUSED
		self.debugger._on_session_updated(session)

	def resume(self, session):
		session.state = RUNNING
		self.debugger._on_session_updated(session)

	def panel(self):
		"""A panel of the debugger, not showing until `show`"""
		panel = Mock()
		panel.is_open.return_value = False
		self.debugger.output_panels.append(panel)
		return panel

	def show(self, panel):
		for other in self.debugger.output_panels:
			other.is_open.return_value = other is panel

	def consoles(self):
		"""A console for gateway and one for backend, as the session panels keep them"""
		gateway, backend = self.panel(), self.panel()
		owners = {id(gateway): 'gateway', id(backend): 'backend'}
		self.debugger.session_panels = types.SimpleNamespace(
			panels_for_console=lambda console: owners.get(id(console)),
			visible_console_for=lambda session: {'gateway': gateway, 'backend': backend}.get(session.configuration.name))
		return gateway, backend

	def test_on_the_console_a_breakpoint_and_a_continue_leave_the_console_showing(self):
		gateway, _ = self.consoles()
		self.show(gateway)
		self.pause(self.gateway)
		self.debugger.callstack.open.assert_not_called()
		gateway.open.assert_not_called()
		# the many updates of a session at a breakpoint do not take it either
		self.debugger._on_session_updated(self.gateway)
		self.debugger.callstack.open.assert_not_called()
		self.resume(self.gateway)
		self.debugger.open_session_output.assert_not_called()
		self.debugger.callstack.open.assert_not_called()
		# and the next breakpoint
		self.pause(self.gateway)
		self.debugger.callstack.open.assert_not_called()

	def test_on_the_call_stack_it_stays_the_call_stack(self):
		self.show(self.debugger.callstack)
		self.pause(self.gateway)
		self.resume(self.gateway)
		self.debugger.callstack.open.assert_not_called()
		self.debugger.open_session_output.assert_not_called()

	def test_with_no_panel_showing_a_breakpoint_opens_the_call_stack_once(self):
		self.pause(self.gateway)
		self.debugger._on_session_updated(self.gateway)
		self.debugger.callstack.open.assert_called_once()
		self.resume(self.gateway)
		self.debugger.open_session_output.assert_called_once_with(self.gateway)

	def test_a_breakpoint_in_another_configuration_shows_its_console_when_a_console_was_showing(self):
		gateway, backend = self.consoles()
		self.show(gateway)
		self.pause(self.backend)
		self.project.load_configuration.assert_called_once_with('backend')
		self.assertIs(self.debugger.session, self.backend)
		backend.open.assert_called_once()
		self.debugger.callstack.open.assert_not_called()

	def test_a_breakpoint_in_another_configuration_shows_its_terminal_when_a_terminal_was_showing(self):
		gateway, backend = self.panel(), self.panel()
		self.debugger.panel_terminals = {self.gateway: [gateway], self.backend: [backend]}
		self.show(gateway)
		self.pause(self.backend)
		backend.open.assert_called_once()
		self.debugger.callstack.open.assert_not_called()

	def test_a_breakpoint_in_another_configuration_selects_it_and_opens_its_call_stack(self):
		self.pause(self.backend)
		self.project.load_configuration.assert_called_once_with('backend')
		self.assertIs(self.debugger.session, self.backend)
		self.debugger.on_session_active.assert_called_once_with(self.backend)
		self.debugger.callstack.open.assert_called_once()

	def test_a_second_breakpoint_does_not_take_the_panel_from_the_one_being_read(self):
		self.pause(self.backend)
		self.project.load_configuration.reset_mock()
		self.debugger.callstack.open.reset_mock()
		self.pause(self.agentic)
		self.project.load_configuration.assert_not_called()
		self.assertIs(self.debugger.session, self.backend)
		self.debugger.callstack.open.assert_not_called()

	def test_later_updates_of_a_paused_session_do_not_take_the_focus_back(self):
		self.pause(self.backend)
		# the user moves to another configuration while backend sits at its breakpoint
		self.project.load_configuration('gateway')
		self.debugger.session = self.gateway
		self.project.load_configuration.reset_mock()
		self.debugger._on_session_updated(self.backend)
		self.project.load_configuration.assert_not_called()
		self.assertIs(self.debugger.session, self.gateway)
		# once it has run again, its next breakpoint counts as new
		self.backend.state = RUNNING
		self.debugger._on_session_updated(self.backend)
		self.pause(self.backend)
		self.project.load_configuration.assert_called_once_with('backend')

	def test_a_step_does_not_refocus(self):
		self.backend.stepping = True
		self.pause(self.backend)
		self.project.load_configuration.assert_not_called()
		self.assertIs(self.debugger.session, self.gateway)

	def test_a_child_session_selects_the_configuration_it_was_started_from(self):
		child = Session('pwa-node child', parent=self.backend)
		self.debugger.sessions.append(child)
		self.pause(child)
		self.project.load_configuration.assert_called_once_with('backend')
		self.assertIs(self.debugger.session, child)

	def test_inside_a_selected_compound_the_paused_member_becomes_current_without_changing_the_selection(self):
		self.project.configuration_or_compound = Compound('all', ['gateway', 'backend'])
		self.project.name = 'all'
		self.pause(self.backend)
		self.project.load_configuration.assert_not_called()
		self.assertIs(self.debugger.session, self.backend)
		self.debugger.callstack.open.assert_called_once()

	def test_a_breakpoint_shows_the_configuration_on_the_tab_it_was_last_looked_at_on(self):
		gateway, backend = self.consoles()
		# backend was last looked at on its console, gateway is being read on the call stack
		self.debugger.session_tabs['backend'] = 'console'
		self.show(self.debugger.callstack)
		self.pause(self.backend)
		backend.open.assert_called_once()
		self.assertEqual(self.debugger.session_tabs['gateway'], 'debugger')
		# and back: gateway was left on the call stack
		self.show(backend)
		self.backend.state = RUNNING
		self.debugger._on_session_updated(self.backend)
		self.pause(self.gateway)
		self.assertEqual(self.debugger.session_tabs['backend'], 'console')
		self.debugger.callstack.open.assert_called_once()
		gateway.open.assert_not_called()

	def test_a_remembered_console_tab_of_a_configuration_with_no_console_leaves_the_tab_as_it_is(self):
		self.debugger.session_panels = types.SimpleNamespace(panels_for_console=lambda console: None, visible_console_for=lambda session: None)
		self.debugger.session_tabs['backend'] = 'console'
		self.show(self.debugger.callstack)
		self.pause(self.backend)
		self.debugger.callstack.open.assert_not_called()


if __name__ == '__main__':
	unittest.main()
