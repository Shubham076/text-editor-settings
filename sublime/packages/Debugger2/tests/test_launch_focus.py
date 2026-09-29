from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import AsyncMock, Mock

from test_open_ui import debugger_method


class Session:
	def __init__(self, configuration=None, parent=None, **kwargs):
		self.configuration = configuration or {}
		self.parent = parent
		self.is_paused = False


class LaunchFocusTests(unittest.TestCase):
	def setUp(self):
		self.console, self.terminal, self.dashboard = Mock(), Mock(), Mock()
		self.debugger = types.SimpleNamespace(
			integrated_terminals={}, external_terminals={}, output_panels=[], sessions=[],
			session_panels=types.SimpleNamespace(visible_console_for=Mock(return_value=self.console), on_terminal_request=Mock()),
			callstack=self.dashboard, console=Mock(),
		)
		self.debugger.open_session_output = types.MethodType(debugger_method('open_session_output'), self.debugger)

	def test_internal_console_is_focused_before_adapter_launch_begins(self):
		order = []
		class StartingSession(Session):
			async def launch(self):
				order.append('adapter-launch')
		self.console.open.side_effect = lambda: order.append('console-focused')
		for event in ('on_session_modules_updated', 'on_session_sources_updated', 'on_session_threads_updated',
			'on_session_variables_updated', 'on_session_updated', 'on_session_output', 'on_session_thread_or_frame_updated',
			'on_session_added', 'on_session_active', 'session_terminal_request', 'session_task_request'):
			setattr(self.debugger, event, Mock())
		method = debugger_method('launch', {'dap': types.SimpleNamespace(Session=StartingSession)})
		asyncio.run(method(self.debugger, Mock(), {'console': 'internalConsole'}))
		self.assertEqual(order, ['console-focused', 'adapter-launch'])

	def test_integrated_terminal_is_focused_as_soon_as_it_is_registered(self):
		order = []
		class Terminal:
			def __init__(terminal, owner, task, **kwargs):
				terminal.arguments = kwargs
				self.debugger.output_panels.append(terminal)
				order.append('terminal-created')
			def open(terminal):
				self.assertIs(terminal.session, session)
				self.assertIn(terminal, self.debugger.integrated_terminals[session])
				order.append('terminal-focused')
		configuration = {'console': 'integratedTerminal'}
		class Configuration(dict):
			name = 'App'
		session = Session(Configuration(configuration))
		self.debugger.on_output_panels_updated = Mock()
		dap = types.SimpleNamespace(
			Task=lambda data: types.SimpleNamespace(Expanded=AsyncMock(return_value=data)),
			RunInTerminalResponse=lambda **kwargs: kwargs,
		)
		method = debugger_method('_on_session_run_terminal_requested', {'dap': dap, 'TerminusOutputPanel': Terminal})
		request = types.SimpleNamespace(title='App', kind='integrated', env={}, cwd='.', args=['not-executed'])
		asyncio.run(method(self.debugger, session, request))
		self.assertEqual(order, ['terminal-created', 'terminal-focused'])
		self.assertFalse(self.debugger.integrated_terminals[session][0].arguments['show_panel'])
		self.console.open.assert_not_called()

	def test_ending_the_last_session_leaves_the_open_panel_alone(self):
		session = Session()
		session.dispose, session.stopped_unexpectedly, session.threads = Mock(), False, []
		self.debugger.memory_views, self.debugger.sessions, self.debugger.session = [], [session], session
		self.debugger.on_session_removed, self.debugger.on_session_active = Mock(), Mock()
		self.debugger.console.protocol.logs = []
		self.debugger.open_session_output = Mock()
		self.dashboard.is_open.return_value = True
		core = types.SimpleNamespace(remove_and_dispose=Mock())
		method = debugger_method('remove_session', {'core': core, 'dap': types.SimpleNamespace(TransportOutputLog=type('TransportOutputLog', (), {}))})
		method(self.debugger, session)
		self.assertEqual(self.debugger.sessions, [])
		self.assertIsNone(self.debugger.session)
		self.debugger.console.info.assert_called_once_with('Debugging ended')
		# whichever tab was open stays: no console, terminal or dashboard is opened on stop
		self.debugger.open_session_output.assert_not_called()
		self.console.open.assert_not_called()
		self.dashboard.open.assert_not_called()

	def test_explicit_internal_console_wins_over_auxiliary_terminal(self):
		session = Session({'console': 'internalConsole'})
		self.debugger.integrated_terminals[session] = [self.terminal]
		self.debugger.output_panels.append(self.terminal)
		self.debugger.open_session_output(session)
		self.console.open.assert_called_once()
		self.terminal.open.assert_not_called()

	def test_waiting_for_integrated_terminal_does_not_focus_diagnostic_console(self):
		session = Session({'console': 'integratedTerminal'})
		self.debugger.open_session_output(session)
		self.console.open.assert_not_called()

	def test_external_terminal_does_not_lose_focus_to_diagnostic_console(self):
		session = Session({'console': 'externalTerminal'})
		self.debugger.external_terminals[session] = [Mock()]
		self.debugger.open_session_output(session)
		self.console.open.assert_not_called()
		self.dashboard.open.assert_not_called()

	def test_adapter_chosen_external_terminal_keeps_focus_without_console_setting(self):
		session = Session()
		self.debugger.external_terminals[session] = [Mock()]
		self.debugger.open_session_output(session)
		self.console.open.assert_not_called()

	def test_pause_still_focuses_debugger_for_inspection(self):
		session = Session({'console': 'internalConsole'})
		session.is_paused = True
		self.debugger.open_session_output(session)
		self.dashboard.open.assert_called_once()
		self.console.open.assert_not_called()


if __name__ == '__main__':
	unittest.main()
