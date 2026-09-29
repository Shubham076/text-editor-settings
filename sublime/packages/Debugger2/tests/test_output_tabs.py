from __future__ import annotations

import types
import unittest
from unittest.mock import Mock, patch

import test_live_ui as fixtures
from test_live_ui import Event, ROOT, load_module
from test_open_ui import debugger_method


class Configuration(dict):
	def __init__(self, name='Real service', console='internalConsole'):
		super().__init__(console=console)
		self.name = name
		self.id_ish = 'configuration_' + name


class OutputTabsTests(unittest.TestCase):
	setUp = fixtures.LiveTests.setUp
	make_ui = fixtures.LiveTests.make_ui

	def tab_html(self):
		ui = self.make_ui()
		ui.render()
		return ui, ui.phantoms.update.call_args.args[0][0][1].split('</style>', 1)[1]

	def record(self, console='internalConsole'):
		configuration = Configuration(console=console)
		self.backend.project.configuration_or_compound = configuration
		session = types.SimpleNamespace(configuration=configuration, parent=None)
		panel = self.console_class()
		panel.session = session
		panel.open = Mock()
		panel.name = configuration.name
		self.backend.output_panels.append(panel)
		record = types.SimpleNamespace(configuration_id=configuration.id_ish, configuration_name=configuration.name,
			console=panel, session=session, console_visible=console == 'internalConsole')
		self.backend.session_panels = types.SimpleNamespace(panels=[record])
		return record

	def terminal(self, session):
		panel = self.terminal_class()
		panel.session = session
		panel.name = 'Real terminal'
		panel.open = Mock()
		panel.dispose = Mock()
		panel.is_finished = lambda: False
		self.backend.output_panels.append(panel)
		return panel

	def test_console_has_no_filter_chips_or_extra_bar(self):
		record = self.record()
		record.console = self.panel
		self.backend.session_panels.panels_for_console = lambda console: record
		ui = self.make_ui()
		ui.render()
		html = ui.phantoms.update.call_args.args[0][0][1]
		for label in ('All', 'Errors', 'Warnings', 'Info'):
			self.assertNotIn('>{}</a>'.format(label), html)
		self.assertNotIn('class="bar"', html)
		record.session = None
		ui.render()
		html = ui.phantoms.update.call_args.args[0][0][1]
		self.assertIn('Close console output', html)
		self.assertNotIn('class="bar"', html)

	def test_terminal_tab_has_no_chip_bar_and_closes_a_finished_terminal_from_the_tab(self):
		record = self.record()
		terminal = self.terminal(record.session)
		ui = self.make_ui()
		ui.render()  # sizes and palette; then the tab row as the terminal panel would draw it
		ui.state.tab = 'terminal'
		ui.panel = terminal
		tabs = ui.toolbar.tabs()
		self.assertIn('>Terminal</a>', tabs)
		# no bar of terminal chips, no new-terminal button; and no close button while it runs
		self.assertNotIn('class="bar"', tabs)
		self.assertNotIn('class="chip', tabs)
		self.assertNotIn('New terminal', tabs)
		self.assertNotIn('Close finished terminal', tabs)
		# once the process has ended the terminal tab carries the close button, like the console tab
		terminal.is_finished = lambda: True
		tabs = ui.toolbar.tabs()
		self.assertIn('Close finished terminal', tabs)
		self.assertLess(tabs.index('>Terminal</a>'), tabs.index('Close finished terminal'))
		self.assertLess(tabs.index('Close finished terminal'), tabs.index('>Debug Console</a>'))
		self.assertFalse(hasattr(ui.toolbar, 'subbar'))

	def test_initial_ui_contains_the_dashboards_and_debug_console_tabs_only(self):
		ui, html = self.tab_html()
		labels = ('>Call Stack / Variables</a>', '>Debug Console</a>', '>Watch</a>')
		for label in labels:
			self.assertIn(label, html)
		self.assertIn('class="breakpoints-control" title="Show breakpoints">Breakpoints</a>', html)
		self.assertNotIn('class="tab" title="Breakpoints"', html)
		self.assertNotIn('>Console</a>', html)
		self.assertNotIn('>Terminal</a>', html)
		self.assertEqual([html.index(label) for label in labels], sorted(html.index(label) for label in labels))
		# the debugger's own console is the panel under test here, so its tab is the active one
		self.assertEqual(ui.state.tab, 'debugger_console')

	def test_debug_console_tab_opens_the_debuggers_own_console_with_its_prompt(self):
		record = self.record()
		ui, html = self.tab_html()
		self.assertIn('>Console</a>', html)
		self.assertIn('>Debug Console</a>', html)
		console = self.backend.console
		console.open, console.enable_input_mode, console.scroll_to_end = Mock(), Mock(), Mock()
		ui.toolbar.select_tab('debugger_console')
		console.open.assert_called_once()
		console.enable_input_mode.assert_called_once()
		console.scroll_to_end.assert_called_once()
		record.console.open.assert_not_called()

	def test_debug_console_tab_is_absent_when_the_console_is_shared(self):
		record = self.record()
		record.console = self.panel
		self.backend.session_panels.panels_for_console = lambda console: record
		ui, html = self.tab_html()
		self.assertIn('>Console</a>', html)
		self.assertNotIn('>Debug Console</a>', html)
		self.assertEqual(ui.state.tab, 'console')

	def test_internal_console_appears_and_remains_after_session_stops(self):
		record = self.record()
		_, html = self.tab_html()
		self.assertIn('>Console</a>', html)
		self.assertNotIn('>Terminal</a>', html)
		record.session = None
		ui, html = self.tab_html()
		self.assertIn('>Console</a>', html)
		ui.toolbar.select_tab('console')
		record.console.open.assert_called_once()

	def test_integrated_terminal_requires_an_actual_panel(self):
		record = self.record('integratedTerminal')
		_, html = self.tab_html()
		self.assertNotIn('>Console</a>', html)
		self.assertNotIn('>Terminal</a>', html)
		terminal = self.terminal(record.session)
		record.session = None
		ui, html = self.tab_html()
		self.assertIn('>Terminal</a>', html)
		self.assertNotIn('>Console</a>', html)
		ui.toolbar.select_tab('terminal')
		terminal.open.assert_called_once()

	def test_external_terminal_does_not_create_an_integrated_tab(self):
		self.record('externalTerminal')
		_, html = self.tab_html()
		self.assertNotIn('>Console</a>', html)
		self.assertNotIn('>Terminal</a>', html)

	def test_unrun_configuration_does_not_inherit_previous_output_tabs(self):
		record = self.record()
		self.terminal(record.session)
		self.backend.project.name = 'Never run'
		self.backend.project.configuration_or_compound = Configuration('Never run')
		_, html = self.tab_html()
		self.assertNotIn('>Console</a>', html)
		self.assertNotIn('>Terminal</a>', html)

	def test_unavailable_terminal_tab_never_spawns_a_shell(self):
		ui, _ = self.tab_html()
		ui.toolbar.select_tab('terminal')
		self.window.run_command.assert_not_called()
		self.backend.callstack.open.assert_called_once()

	def registry(self):
		self.panel.protocol = Mock()
		def create_console(debugger, session, **kwargs):
			console = self.console_class()
			console.session = session
			console.clear = Mock()
			console.dispose = Mock()
			console.on_input, console.on_navigate = Event(), Event()
			debugger.output_panels.append(console)
			return console
		dependencies = dict(self.loaded)
		dependencies['_live_test.modules.output_panel_console'] = types.SimpleNamespace(ConsoleOutputPanel=create_console)
		module = load_module('_live_test.modules.session_panels', ROOT / 'modules/session_panels.py', dependencies)
		self.backend._on_navigate_to_source = Mock()
		registry = module.SessionPanelsRegistry(self.backend, self.panel)
		self.backend.session_panels = registry
		return registry

	def test_registry_hides_terminal_console_until_dap_output_arrives(self):
		registry = self.registry()
		session = types.SimpleNamespace(configuration=Configuration(console='integratedTerminal'), parent=None)
		registry._on_session_added(session)
		entry = registry.panels[0]
		self.assertFalse(entry.console_visible)
		registry._on_session_output(session, types.SimpleNamespace(category='telemetry', output='stats', variablesReference=0))
		self.assertFalse(entry.console_visible)
		registry._on_session_output(session, types.SimpleNamespace(category='console', output='diagnostic', variablesReference=0))
		self.assertTrue(entry.console_visible)
		registry._on_session_removed(session)
		self.assertIsNone(entry.session)
		self.assertTrue(entry.console_visible)
		entry.console.dispose.assert_not_called()

	def test_dap_terminal_request_corrects_unspecified_console_mode(self):
		registry = self.registry()
		configuration = Configuration()
		configuration.pop('console')
		session = types.SimpleNamespace(configuration=configuration, parent=None)
		registry._on_session_added(session)
		self.assertTrue(registry.panels[0].console_visible)
		registry.on_terminal_request(session)
		self.assertFalse(registry.panels[0].console_visible)

	def test_auxiliary_terminal_keeps_explicit_internal_console_visible(self):
		registry = self.registry()
		session = types.SimpleNamespace(configuration=Configuration(console='internalConsole'), parent=None)
		registry._on_session_added(session)
		registry.on_terminal_request(session)
		self.assertTrue(registry.panels[0].console_visible)

	def test_restarting_configuration_reuses_its_output_record(self):
		registry = self.registry()
		configuration = Configuration()
		first = types.SimpleNamespace(configuration=configuration, parent=None)
		registry._on_session_added(first)
		registry._on_session_removed(first)
		second = types.SimpleNamespace(configuration=configuration, parent=None)
		registry._on_session_added(second)
		self.assertEqual(len(registry.panels), 1)
		self.assertIs(registry.panels[0].console.session, second)
		self.assertTrue(registry.panels[0].console_visible)
		registry.panels[0].console.clear.assert_called_once()

	def test_shared_console_is_hidden_until_a_run_and_is_not_destroyed_on_close(self):
		self.settings.session_panels = False
		registry = self.registry()
		self.panel.dispose = Mock()
		self.assertFalse(registry.panels)
		session = types.SimpleNamespace(configuration=Configuration(), parent=None)
		registry._on_session_added(session)
		record = registry.panels[0]
		self.assertIs(record.console, self.panel)
		self.assertTrue(record.console_visible)
		self.assertFalse(registry.close(record))
		registry._on_session_removed(session)
		self.assertTrue(registry.close(record))
		self.panel.dispose.assert_not_called()

	def test_closing_shared_console_removes_all_stopped_output_records(self):
		self.settings.session_panels = False
		registry = self.registry()
		self.panel.dispose = Mock()
		for name in ('First', 'Second'):
			session = types.SimpleNamespace(configuration=Configuration(name), parent=None)
			registry._on_session_added(session)
			registry._on_session_removed(session)
		self.assertEqual(len(registry.panels), 2)
		self.assertTrue(registry.close(registry.panels[0]))
		self.assertFalse(registry.panels)
		self.panel.dispose.assert_not_called()

	def test_child_exit_does_not_mark_root_console_stopped(self):
		registry = self.registry()
		root = types.SimpleNamespace(configuration=Configuration(), parent=None)
		registry._on_session_added(root)
		child = types.SimpleNamespace(configuration=root.configuration, parent=root)
		registry._on_session_removed(child)
		self.assertIs(registry.panels[0].session, root)

	def test_automatic_cleanup_keeps_finished_terminal_output(self):
		terminal = Mock()
		debugger = types.SimpleNamespace(integrated_terminals={object(): [terminal]}, external_terminals={}, tasks=Mock())
		debugger_method('dispose_terminals')(debugger, unused_only=True)
		terminal.dispose.assert_not_called()
		debugger.tasks.remove_finished.assert_not_called()
		self.assertTrue(debugger.integrated_terminals)
		debugger_method('dispose_terminals')(debugger)
		terminal.dispose.assert_called_once()
		self.assertFalse(debugger.integrated_terminals)

	def test_run_focus_uses_terminal_and_never_opens_hidden_console(self):
		session = Mock()
		session.parent = None
		session.is_paused = False
		session.configuration = {}
		terminal = Mock()
		console = Mock()
		debugger = types.SimpleNamespace(integrated_terminals={session: [terminal]}, external_terminals={}, output_panels=[terminal],
			session_panels=types.SimpleNamespace(visible_console_for=Mock(return_value=console)), callstack=Mock())
		debugger_method('open_session_output')(debugger, session)
		terminal.open.assert_called_once()
		console.open.assert_not_called()
		debugger.integrated_terminals.clear()
		debugger.session_panels.visible_console_for.return_value = None
		debugger_method('open_session_output')(debugger, session)
		debugger.callstack.open.assert_called_once()

	def test_expanded_configuration_preserves_identity(self):
		module = load_module('_live_test.modules.dap.configuration', ROOT / 'modules/dap/configuration.py', self.loaded)
		configuration = module.Configuration('App', 2, 'python', 'launch', {})
		expanded = module.ConfigurationExpanded(configuration, {}, {})
		self.assertEqual(expanded.id_ish, configuration.id_ish)


if __name__ == '__main__':
	unittest.main()
