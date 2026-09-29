from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any
import unittest
from unittest.mock import Mock, patch

from test_ui_preview import load_preview

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path, modules):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, dict(modules, **{name: module})):
		spec.loader.exec_module(module)
	return module


@dataclass
class FakeInputListItem:
	"""`ui.InputListItem` without sublime: the fields a quick panel row is built from"""
	run: Any
	text: str
	name: Any = None
	annotation: str = ''
	details: Any = ''
	kind: tuple = (0, '', '')
	run_alt: Any = None
	preview: Any = None


class FakeInputList:
	"""`ui.InputList` without sublime: records what was shown instead of opening a quick panel"""
	shown: list = []

	def __init__(self, placeholder='', index=0):
		self.placeholder = placeholder
		self.index = index
		self.values = []

	def __getitem__(self, values):
		self.values = list(values)
		type(self).shown.append(self)
		return self


class MenuTests(unittest.TestCase):
	def setUp(self):
		self.preview = load_preview()
		self.sublime = self.preview.sublime
		self.sublime.KEEP_ON_SELECTION_MODIFIED = 1
		self.menu = load_module('_debugger_menu_test', ROOT / 'debugger_ui_menu.py', {'sublime': self.sublime})
		self.view = Mock()
		self.view.style.return_value = {'background': '#fafafa', 'foreground': '#606060', 'selection': '#d4cece', 'accent': '#343e5e'}
		self.options = [self.menu.Option('api', 'API <Server>', 'Python · launch', 'Launch', 'Paused', 'yellowish')]

	def test_group_description_badge_and_footer_are_escaped(self):
		html = self.menu.menu_html(self.view, self.options, 'api', 'Run configuration', 14, 'Edit configurations')
		for value in ('LAUNCH', 'API &lt;Server&gt;', 'Python · launch', 'Paused', 'Edit configurations', 'Esc to close', '#d4cece', '14px'):
			self.assertIn(value, html)
		self.assertNotIn('UIElements', html)
		# the footer action and the check mark are the plain text colour, bold; the accent is not used
		self.assertNotIn('#343e5e', html)
		self.assertIn('.action { font-weight: bold; color: #606060; }', html)
		self.assertIn('.mark { display: inline-block; width: 1.6rem; color: #606060; }', html)

	def test_action_closes_before_callback_and_ignores_stale_clicks(self):
		calls = []
		menu = self.menu.show(self.view, self.options, action=('Edit', lambda: calls.append(menu.closed)))
		menu._navigate('action')
		menu._navigate('action')
		self.assertEqual(calls, [True])

	def test_selection_and_replacement_lifecycle(self):
		selected = Mock()
		first = self.menu.show(self.view, self.options, on_select=selected)
		second = self.menu.show(self.view, self.options, on_select=selected)
		first._navigate('pick:0')
		selected.assert_not_called()
		second._navigate('pick:0')
		selected.assert_called_once_with('api')
		self.assertTrue(second.closed)

	def test_invalid_options_are_rejected(self):
		with self.assertRaises(ValueError):
			self.menu.show(self.view, self.options * 2)
		with self.assertRaises(ValueError):
			self.menu.show(self.view, self.options, selected='missing')

	def test_empty_menu_still_offers_edit_action(self):
		menu = self.menu.show(self.view, [], action=('Add configuration', Mock()))
		self.assertIsNotNone(menu)
		self.assertIn('Add configuration', self.view.show_popup.call_args[0][0])


class Event:
	def __init__(self):
		self.callbacks = []

	def __class_getitem__(cls, key):
		return cls

	def add(self, callback):
		self.callbacks.append(callback)
		return types.SimpleNamespace(dispose=lambda: self.callbacks.remove(callback))

	def __call__(self, *args):
		for callback in list(self.callbacks):
			callback(*args)


class Collection(list):
	def __init__(self, *args):
		super().__init__(*args)
		self.on_updated = Event()


class LiveTests(unittest.TestCase):
	def setUp(self):
		import asyncio
		self.asyncio = asyncio
		self.preview = load_preview()
		self.sublime = self.preview.sublime
		self.sublime.Region = lambda a, b=None: a if b is None else (a, b)
		self.sublime.KEEP_ON_SELECTION_MODIFIED = 1
		self.sublime.KIND_ID_AMBIGUOUS, self.sublime.KIND_ID_COLOR_YELLOWISH, self.sublime.KIND_ID_COLOR_GREENISH = 0, 14, 15
		package = types.ModuleType('_live_test')
		package.__path__ = []
		modules = types.ModuleType('_live_test.modules')
		modules.__path__ = []
		views = types.ModuleType('_live_test.modules.views')
		views.__path__ = []
		ui_package = types.ModuleType('_live_test.modules.ui')
		ui_package.__path__ = []
		ui_package.RawPhantom = Mock()
		ui_package.InputListItem = FakeInputListItem
		ui_package.InputList = type('InputList', (FakeInputList,), {'shown': []})
		self.core = types.SimpleNamespace(run=lambda fn: fn, edit=Mock(), Event=Event, platform=types.SimpleNamespace(unicode_checked_sigil='●'),
			CancelledError=asyncio.CancelledError, Dispose=type('Dispose', (), {'dispose_add': lambda *args: None}))
		self.dap = types.SimpleNamespace(ConfigurationCompound=type('Compound', (), {}), SourceBreakpoint=type('SourceBreakpoint', (), {}), Error=Exception,
			Variable=types.SimpleNamespace(from_evaluate=lambda session, name, response: types.SimpleNamespace(session=session, name=name, value=response.result)))
		self.settings = types.SimpleNamespace(font_size=None, font_face=None, line_padding=0, session_panels=True)
		self.console_class = type('ConsoleOutputPanel', (), {})
		self.terminal_class = type('TerminusOutputPanel', (), {})
		self.loaded = {
			'_live_test': package, '_live_test.modules': modules, '_live_test.modules.views': views,
			'_live_test.modules.ui': ui_package,
			'_live_test.debugger_ui_preview': self.preview, 'sublime': self.sublime,
			'_live_test.modules.core': self.core, '_live_test.modules.dap': self.dap,
			'_live_test.modules.settings': types.SimpleNamespace(Settings=self.settings),
			'_live_test.modules.output_panel_console': types.SimpleNamespace(ConsoleOutputPanel=self.console_class),
			'_live_test.modules.output_panel_terminus': types.SimpleNamespace(TerminusOutputPanel=self.terminal_class),
			'_live_test.modules.views.breakpoints': types.SimpleNamespace(BreakpointView=Mock()),
			'_live_test.modules.views.variable': types.SimpleNamespace(VariableView=Mock(), VariableViewState=Mock()),
		}
		for name, path in (('debugger_ui_menu', 'debugger_ui_menu.py'), ('modules.configurations', 'modules/configurations.py'),
			('modules.variable_format', 'modules/variable_format.py'), ('modules.views.session_scope', 'modules/views/session_scope.py'),
			('modules.watch', 'modules/watch.py'),
			*((f'modules.ui.{name}', f'modules/ui/{name}.py') for name in (
				'icons', 'style', 'renderer', 'view_settings', 'state', 'configuration_picker', 'breakpoints', 'callstack', 'variables', 'output_tabs', 'toolbar', 'panel')),
			('modules.live_ui', 'modules/live_ui.py')):
			self.loaded['_live_test.' + name] = load_module('_live_test.' + name, ROOT / path, self.loaded)
		self.patch = patch.dict(sys.modules, self.loaded)
		self.patch.start()
		self.addCleanup(self.patch.stop)
		self.module = self.loaded['_live_test.modules.live_ui']
		self.configuration = types.SimpleNamespace(name='Real service', id_ish='config-1')
		self.backend = types.SimpleNamespace(project=types.SimpleNamespace(name='Real service', compounds=[], configurations=[],
			configuration_or_compound=self.configuration, on_updated=Event()), sessions=[], session=None,
			output_panels=[], session_panels=None, watch=types.SimpleNamespace(expressions=[], on_updated=Event()),
			breakpoints=types.SimpleNamespace(**{name: Collection() for name in ('source', 'filters', 'function', 'data')}))
		for name in ('on_session_added', 'on_session_removed', 'on_session_updated', 'on_session_active', 'on_session_threads_updated',
			'on_session_variables_updated', 'on_session_thread_or_frame_updated', 'on_session_output', 'on_output_panels_updated', 'on_project_or_settings_updated'):
			setattr(self.backend, name, Event())
		self.view = Mock()
		self.view.style.return_value = {'background': '#fafafa', 'foreground': '#606060', 'selection': '#d4cece', 'accent': '#343e5e'}
		self.view.viewport_extent.return_value = (1200, 400)
		self.view.viewport_position.return_value = (0, 0)
		self.view.lines.return_value = []
		self.view.em_width.return_value = 1
		self.view.settings().get.side_effect = lambda key, default=None: default
		self.window = Mock()
		self.panel = self.console_class()
		self.panel.debugger = self.backend
		self.panel.view = self.view
		self.panel.window = self.window
		self.panel.is_open = lambda: True
		self.panel.open = Mock()
		self.panel.session = None
		self.panel.name = 'Console'
		self.backend.console = self.panel
		self.backend.output_panels = [self.panel]
		self.backend.callstack = types.SimpleNamespace(open=Mock())

		self.backend.breakpoints_panel = types.SimpleNamespace(open=Mock())
		self.backend.watch_panel = types.SimpleNamespace(open=Mock())

	def make_ui(self, body=False, header_view=None, layout='debugger'):
		return self.module.LiveUI(self.panel, self.view, body=body, header_view=header_view, layout=layout)

	def make_strip(self, height=22, font=12):
		'''A fake io panel input view: one text line tall, so only its font size changes its height'''
		strip = Mock()
		strip.is_valid.return_value = True
		strip.viewport_extent.return_value = (1000, height)
		strip.settings().get.return_value = font
		strip.style.return_value = self.view.style.return_value
		return strip

	def session(self, name='Real service', paused=True):
		return types.SimpleNamespace(configuration=types.SimpleNamespace(name=name), parent=None, children=[], threads=[], variables=[],
			is_paused=paused, is_running=not paused, is_stoppable=True, state=types.SimpleNamespace(status='Paused' if paused else 'Running'),
			selected_thread=None, selected_frame=None)

	def test_header_starts_with_only_debugger_and_no_sample_data(self):
		ui = self.make_ui()
		ui.render()
		html = ''.join(item[1] for item in ui.phantoms.update.call_args[0][0])
		for text in ('Real&nbsp;service', '>Call Stack / Variables</a>', 'Stopped'):
			self.assertIn(text, html)
		for text in ('API Server', 'Sample', 'preview', 'UIElements', '>Console</a>', '>Terminal</a>', '>Errors</a>'):
			self.assertNotIn(text, html)
		self.assertEqual([item[0] for item in ui.phantoms.update.call_args[0][0]], [0])

	def test_body_is_empty_when_selected_configuration_is_not_running(self):
		self.backend.sessions = [self.session('Other')]
		self.backend.session = self.backend.sessions[0]
		ui = self.make_ui(body=True)
		ui.render()
		html = ''.join(item[1] for item in ui.phantoms.update.call_args[0][0])
		self.assertIn('No active debug session', html)
		self.assertNotIn('Main thread', html)
		# brand, controls, tabs, then the two panes of the Debugger tab: call stack and variables
		self.assertEqual(len(ui.phantoms.update.call_args[0][0]), 5)
		self.view.viewport_extent.return_value = (500, 400)
		ui.render()
		self.assertEqual(len(ui.phantoms.update.call_args[0][0]), 4)

	def test_real_frames_and_source_labels_are_rendered(self):
		session = self.session()
		frame = types.SimpleNamespace(name='actual_handler', line=42, source=types.SimpleNamespace(name='service.py', path=None), instructionPointerReference=None)
		thread = types.SimpleNamespace(name='Thread 7', stopped=True, stopped_reason='Breakpoint', children=Mock())
		session.threads = [thread]
		session.selected_thread = thread
		session.selected_frame = frame
		self.backend.sessions = [session]
		self.backend.session = session
		ui = self.make_ui(body=True)
		ui.tree.cache[id(thread)] = [frame]
		ui.render()
		html = ''.join(item[1] for item in ui.phantoms.update.call_args[0][0])
		for text in ('actual_handler', 'service.py:42', 'Thread 7', 'frame selected'):
			self.assertIn(text, html)

	def test_invalidation_rejects_stale_clicks_and_disposal_removes_listeners(self):
		ui = self.make_ui()
		callback = Mock()
		ui.link('test', callback, 'test')
		generation = ui.generation
		ui.invalidate()
		ui.navigate(generation, '0')
		callback.assert_not_called()
		ui.dispose()
		self.assertFalse(self.backend.on_session_added.callbacks)
		self.assertFalse(self.backend.project.on_updated.callbacks)
		ui.render()
		ui.phantoms.update.assert_called_once_with([])

	def test_child_session_follows_selected_frame(self):
		parent = self.session()
		child = self.session('Child')
		child.parent = parent
		parent.children = [child]
		self.backend.sessions = [parent, child]
		self.backend.session = child
		ui = self.make_ui()
		self.assertIs(ui.active_session, child)

	def test_configuration_session_lookup_prefers_paused_child_over_running_root(self):
		root = self.session(paused=False)
		child = self.session('Child')
		child.parent = root
		root.children = [child]
		other = self.session('Other', paused=False)
		self.backend.sessions = [root, child, other]
		self.backend.session = other
		configurations = self.loaded['_live_test.modules.configurations']
		self.assertIs(configurations.session_for(self.backend, 'Real service'), child)
		self.backend.project.load_configuration = Mock()
		self.backend.open_session_output = Mock()
		configurations.select(self.backend, 'Real service')
		self.assertIs(self.backend.current_session, child)
		self.backend.open_session_output.assert_called_once_with(child)

	def test_step_targets_selected_session_not_last_active_other_session(self):
		from unittest.mock import AsyncMock
		selected, other = self.session(), self.session('Other')
		for name in ('step_over', 'step_in', 'step_out'):
			setattr(selected, name, AsyncMock())
		self.backend.sessions = [selected, other]
		self.backend.session = other
		self.backend.stepping_granularity = lambda: 'line'
		ui = self.make_ui()
		self.asyncio.run(ui.toolbar.step('step_over'))
		selected.step_over.assert_awaited_once_with(granularity='line')
		selected.is_paused = False
		self.asyncio.run(ui.toolbar.step('step_over'))
		self.assertEqual(selected.step_over.await_count, 1)

	def test_stale_async_children_are_discarded(self):
		ui = self.make_ui(body=True)
		async def children():
			ui.reset_data()
			return ['old frame']
		item = types.SimpleNamespace(children=children)
		self.asyncio.run(ui.tree.fetch(item, ui.tree.revision))
		self.assertNotIn(id(item), ui.tree.cache)

	def rows(self, select=None):
		return self.loaded['_live_test.modules.configurations'].items(self.backend, select or Mock())

	def test_picker_uses_metadata_and_status_without_exposing_environment(self):
		class Configuration(dict):
			name, id_ish, type, request = 'Actual API', 'id-api', 'python', 'launch'
		item = Configuration(program='app.py', presentation={'group': 'Services'}, env={'TOKEN': 'do-not-display'})
		self.backend.project.configurations = [item]
		self.backend.sessions = [self.session('Actual API')]
		rows, selected = self.rows()
		self.assertEqual(len(rows), 1)
		self.assertIsNone(selected)
		self.assertEqual(rows[0].text, 'Actual API')
		self.assertEqual(rows[0].details, 'python · launch')
		self.assertEqual(rows[0].annotation, 'Paused')
		self.assertEqual(rows[0].kind, (self.sublime.KIND_ID_COLOR_YELLOWISH, '\u2016', 'Paused'))
		self.assertNotIn('app.py', str(rows))
		self.assertNotIn('do-not-display', str(rows))

	def test_picker_marks_the_selection_in_its_status_colour_and_runs_the_callback_with_the_item(self):
		class Configuration(dict):
			name, id_ish, type, request = 'Actual API', 'id-api', 'python', 'launch'
		item = Configuration()
		self.backend.project.configurations = [item]
		self.backend.project.configuration_or_compound = item
		self.backend.sessions = [self.session('Actual API', paused=False)]
		select = Mock()
		rows, selected = self.rows(select)
		self.assertEqual(selected, 0)
		self.assertEqual(rows[0].kind, (self.sublime.KIND_ID_COLOR_GREENISH, '\u25cf', 'Running'))
		rows[0].run()
		select.assert_called_once_with(item)

	def test_picker_omits_run_targets_and_keeps_all_session_statuses(self):
		class Configuration(dict):
			type, request = 'debugpy', 'launch'
		items = []
		for index, name in enumerate(('Paused service', 'Running service', 'Unstarted service')):
			item = Configuration(program='${project_path}/' + 'long/path/' * 30 + 'main.py', module='pytest',
				url='https://example.invalid/private-path', args=['secret-argument'], shell_cmd='private-command')
			item.name, item.id_ish = name, str(index)
			items.append(item)
		self.backend.project.configurations = items
		self.backend.sessions = [self.session('Paused service'), self.session('Running service', paused=False)]
		rows, _ = self.rows()
		self.assertEqual([row.details for row in rows], ['debugpy · launch'] * 3)
		self.assertEqual([row.annotation for row in rows], ['Paused', 'Running', 'Stopped'])
		self.assertEqual([row.kind[0] for row in rows], [self.sublime.KIND_ID_COLOR_YELLOWISH, self.sublime.KIND_ID_COLOR_GREENISH, self.sublime.KIND_ID_AMBIGUOUS])
		self.assertEqual([row.kind[1] for row in rows], ['\u2016', '\u25b6', '\u25cb'])
		for text in ('project_path', 'main.py', 'pytest', 'private-path', 'secret-argument', 'private-command'):
			self.assertNotIn(text, str(rows))

	def test_picker_orders_paused_running_stopped_then_names_case_insensitively(self):
		class Configuration(dict):
			type, request = 'debugpy', 'launch'
		names = ('z stopped', 'Beta running', 'z paused', 'alpha stopped', 'alpha running', 'Alpha paused')
		items = []
		for index, name in enumerate(names):
			item = Configuration()
			item.name, item.id_ish = name, str(index)
			items.append(item)
		self.backend.project.configurations = items
		self.backend.sessions = [
			self.session('z paused'), self.session('Alpha paused'),
			self.session('Beta running', paused=False), self.session('alpha running', paused=False),
		]
		rows, _ = self.rows()
		self.assertEqual([row.text for row in rows], [
			'Alpha paused', 'z paused', 'alpha running', 'Beta running', 'alpha stopped', 'z stopped'])
		self.assertEqual([row.annotation for row in rows], ['Paused', 'Paused', 'Running', 'Running', 'Stopped', 'Stopped'])

	def test_compound_description_does_not_push_status_offscreen(self):
		compound = self.dap.ConfigurationCompound()
		compound.name, compound.id_ish = 'All services', 'compound-all'
		compound.configurations = ['A very long service name ' * 20, 'Another service']
		self.backend.project.compounds = [compound]
		rows, _ = self.rows()
		self.assertEqual(rows[0].details, '2 configurations')
		self.assertEqual(rows[0].annotation, 'Stopped')

	def test_watch_results_are_kept_per_session_and_errors_clear_old_values(self):
		watch_module = self.loaded['_live_test.modules.watch']
		expression = watch_module.WatchExpression('value')
		watch = watch_module.Watch(self.backend)
		first, second = Mock(), Mock()
		watch.expressions = [expression]
		watch.evaluated(first, expression, types.SimpleNamespace(result='first'))
		watch.evaluated(second, expression, types.SimpleNamespace(result='second'))
		self.assertEqual(expression.results[first].value, 'first')
		self.assertEqual(expression.results[second].value, 'second')
		watch.evaluated(first, expression, ValueError('unavailable'))
		self.assertIsNone(expression.evaluate_response)
		self.assertIsInstance(expression.results[first], ValueError)
		watch.clear_session_data(first)
		self.assertNotIn(first, expression.results)
		self.assertEqual(expression.results[second].value, 'second')

	def test_late_watch_result_cannot_overwrite_an_edited_expression(self):
		watch_module = self.loaded['_live_test.modules.watch']
		watch = watch_module.Watch(self.backend)
		expression = watch_module.WatchExpression('old')
		watch.expressions = [expression]
		session = Mock()
		frame = object()
		session.selected_frame = frame
		session.is_paused = True
		self.backend.sessions = [session]
		async def evaluate(value, context):
			expression.value = 'new'
			return types.SimpleNamespace(result='old result')
		async def gather(*items):
			return await self.asyncio.gather(*items)
		session.evaluate_expression = evaluate
		self.core.gather_results = gather
		self.asyncio.run(watch.evaluate(session, frame))
		self.assertEqual(expression.results, {})

	def test_restart_waits_for_all_compound_roots_before_starting(self):
		from unittest.mock import AsyncMock
		configurations = self.loaded['_live_test.modules.configurations']
		first, second = self.session('First'), self.session('Second')
		compound = self.dap.ConfigurationCompound()
		compound.name, compound.configurations = 'Both', ['First', 'Second']
		self.backend.project.compounds = [compound]
		self.backend.sessions = [first, second]
		async def stop(session):
			self.backend.sessions.remove(session)
		self.backend.stop = AsyncMock(side_effect=stop)
		self.backend.start = AsyncMock()
		self.asyncio.run(configurations.restart(self.backend, 'Both'))
		self.assertEqual(self.backend.stop.await_count, 2)
		self.backend.start.assert_awaited_once_with(args={'configuration': 'Both'})

	def test_preview_constructs_without_uielements(self):
		self.window.create_output_panel.return_value = self.view
		self.window.active_panel.return_value = 'output.debugger_ui_preview'
		self.view.size.return_value = 0
		self.view.settings.return_value.get.side_effect = lambda key, default=None: default
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		with patch.dict(sys.modules, {'UIElements': None}):
			module = load_module('_live_test.debugger_ui_preview', ROOT / 'debugger_ui_preview.py', dependencies)
			preview = module.DebuggerUiPreview(self.window)
			self.assertIs(preview.dropdown, self.loaded['_live_test.debugger_ui_menu'])
			preview.dispose()

	def test_variable_tree_escapes_values_and_pages_children(self):
		variable = types.SimpleNamespace(name='<root>', value='<Object>', type='Object', has_children=True,
			memoryReference=None, containerVariablesReference=1)
		children = [types.SimpleNamespace(name='child' + str(index), value='<script>', type=None, has_children=False,
			memoryReference=None, containerVariablesReference=1) for index in range(25)]
		ui = self.make_ui(body=True)
		ui.render()
		ui.tree.cache[id(variable)] = children
		ui.state.expanded.add('var:<root>')
		html = ''.join(ui.variables.variable_rows(variable, 35))
		self.assertIn('&lt;root&gt;', html)
		self.assertIn('&lt;script&gt;', html)
		self.assertNotIn('<script>', html)
		self.assertIn('5 more items', html)
		self.assertNotIn('child24', html)
		# clicking the row shows every remaining child at once, and the row goes away
		ui.variables.show_more('var:<root>')
		html = ''.join(ui.variables.variable_rows(variable, 35))
		self.assertNotIn('more items', html)
		self.assertIn('child24', html)
		# a step forgets the fetched children and the paging with them
		ui.reset_data()
		ui.tree.cache[id(variable)] = children
		html = ''.join(ui.variables.variable_rows(variable, 35))
		self.assertIn('5 more items', html)

	def test_debugpy_group_rows_follow_the_fields_and_open_without_a_value(self):
		def child(name, value, has_children=False):
			return types.SimpleNamespace(name=name, value=value, type=None, has_children=has_children, memoryReference=None, containerVariablesReference=1)
		variable = child('config', 'AgenticPluginConfig(...)', True)
		# as debugpy sends them: the groups first, then the fields
		children = [child('function variables', '', True), child('protected variables', '', True),
			child('api_key', "'5f30'"), child('timeout', '5000')]
		ui = self.make_ui(body=True)
		ui.render()
		ui.tree.cache[id(variable)] = children
		ui.state.expanded.add('var:config')
		html = ''.join(ui.variables.variable_rows(variable, 40))
		self.assertLess(html.index('api_key'), html.index('timeout'))
		self.assertLess(html.index('timeout'), html.index('function variables'))
		self.assertLess(html.index('function variables'), html.index('protected variables'))
		# a group is a muted name with a chevron, not an expression to inspect
		self.assertIn('<span title="protected variables">protected variables</span>', html)
		self.assertNotIn('protected variables = ', html)
		self.assertNotIn('Inspect / copy protected variables', html)
		self.assertIn('Expand / collapse protected variables', html)
		self.assertIn('Inspect / copy timeout', html)

	def test_locals_scope_opens_by_itself_and_keeps_its_state_across_steps(self):
		def scopes():
			return [types.SimpleNamespace(name=name, value='', type=None, has_children=True, memoryReference=None, containerVariablesReference=1)
				for name in ('Locals', 'Globals')]
		session = self.session()
		session.variables = scopes()
		self.backend.sessions, self.backend.session = [session], session
		ui = self.make_ui(body=True)
		ui.render()
		# the first scope opens on its own (its children are being fetched), the second stays shut
		html = ''.join(ui.variables.render(40))
		self.assertIn('scope:Locals', ui.state.expanded)
		self.assertNotIn('scope:Globals', ui.state.expanded)
		self.assertEqual(html.count('title="Loading…"'), 1)
		# a step: new variable objects, object keys dropped; the scope stays open
		session.variables = scopes()
		ui.reset_data()
		html = ''.join(ui.variables.render(40))
		self.assertIn('scope:Locals', ui.state.expanded)
		self.assertEqual(html.count('title="Loading…"'), 1)
		# the user folds it: that sticks across the next step too, and Globals is not opened instead
		ui.toggle('scope:Locals')
		session.variables = scopes()
		ui.reset_data()
		html = ''.join(ui.variables.render(40))
		self.assertNotIn('scope:Locals', ui.state.expanded)
		self.assertEqual(html.count('title="Loading…"'), 0)

	def test_rows_opened_below_a_scope_stay_open_across_steps_until_the_session_ends(self):
		def variable(name, has_children=True):
			return types.SimpleNamespace(name=name, value='', type=None, has_children=has_children, memoryReference=None, containerVariablesReference=1)
		def frame():
			# a fresh set of objects every time, as an adapter sends after each step
			locals_ = variable('Locals')
			settings = variable('settings')
			policy = variable('policy')
			return locals_, {id(locals_): [settings, variable('data')], id(settings): [policy, variable('timeout', False)], id(policy): [variable('release', False)]}
		session = self.session()
		self.backend.sessions, self.backend.session = [session], session
		ui = self.make_ui(body=True)
		ui.render()

		def render_frame():
			scope, children = frame()
			session.variables = [scope]
			ui.reset_data()
			ui.tree.cache.update(children)
			return ''.join(ui.variables.render(60))

		# Locals opens by itself; the user opens settings, then policy inside it
		html = render_frame()
		self.assertIn('settings', html)
		self.assertNotIn('policy', html)
		ui.toggle('scope:Locals/settings')
		html = render_frame()
		self.assertIn('policy', html)
		self.assertNotIn('release', html)
		ui.toggle('scope:Locals/settings/policy')
		# two steps later, with new objects each time, both are still open
		html = render_frame()
		html = render_frame()
		self.assertIn('release', html)
		# folding settings hides the lot, and stays folded on the next step; policy's own state is kept for when it is reopened
		ui.toggle('scope:Locals/settings')
		html = render_frame()
		self.assertNotIn('policy', html)
		self.assertIn('scope:Locals/settings/policy', ui.state.expanded)
		# the session ends: the paths are forgotten, the scope's default and the user's scope choice are not
		self.backend.sessions = []
		self.backend.on_session_removed(session)
		self.assertNotIn('scope:Locals/settings/policy', ui.state.expanded)
		self.assertIn('scope:Locals', ui.state.expanded)
		self.assertIn('variables', ui.state.expanded)

	def test_compound_scope_contains_only_its_roots(self):
		first, second, other = self.session('First'), self.session('Second'), self.session('Other')
		selection = self.dap.ConfigurationCompound()
		selection.configurations = ['First', 'Second']
		self.backend.project.configuration_or_compound = selection
		self.backend.sessions = [first, second, other]
		self.backend.session = second
		ui = self.make_ui()
		self.assertEqual(ui.scope.sessions, [first, second])
		self.assertIs(ui.active_session, second)


if __name__ == '__main__':
	unittest.main()
