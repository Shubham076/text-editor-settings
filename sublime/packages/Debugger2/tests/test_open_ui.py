from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

from test_live_ui import load_module


ROOT = Path(__file__).resolve().parents[1]


def debugger_method(name, globals_=None):
	path = ROOT / 'modules/debugger.py'
	module = ast.parse(path.read_text())
	debugger = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Debugger')
	method = deepcopy(next(node for node in debugger.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name))
	method.decorator_list = []
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
	namespace = dict(globals_ or {})
	exec(compile(ast.fix_missing_locations(tree), str(path), 'exec'), namespace)
	return namespace[name]


class OpenUiTests(unittest.TestCase):
	def test_open_shows_dashboard_not_startup_console(self):
		debugger = types.SimpleNamespace(console=Mock(), callstack=Mock())
		debugger_method('open')(debugger)
		debugger.callstack.open.assert_called_once_with()
		debugger.console.open.assert_not_called()

	def test_initialization_finishes_by_showing_default_dashboard(self):
		tree = ast.parse((ROOT / 'modules/debugger.py').read_text())
		debugger = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Debugger')
		initializer = next(node for node in debugger.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
		last = initializer.body[-1]
		self.assertIsInstance(last, ast.Expr)
		self.assertEqual(ast.dump(last.value), ast.dump(ast.parse('self.open()', mode='eval').body))

	def test_a_gutter_click_changes_a_breakpoint_without_opening_a_panel(self):
		tree = ast.parse((ROOT / 'start.py').read_text())
		handler = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'on_view_gutter_clicked')
		calls = [node.func.attr for node in ast.walk(handler) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
		self.assertIn('toggle_file_line', calls)
		self.assertIn('edit_breakpoints', calls)
		# adding, removing or editing a breakpoint leaves whatever panel is open where it is
		self.assertNotIn('open', calls)
		self.assertNotIn('open_status', calls)

	def test_debug_console_carries_no_welcome_text_and_is_not_cleared_with_a_project_open(self):
		package = types.ModuleType('_open_ui_test')
		package.__path__ = []
		modules = types.ModuleType('_open_ui_test.modules')
		modules.__path__ = []
		commands = types.ModuleType('_open_ui_test.modules.commands')
		commands.__path__ = []
		example_action = types.SimpleNamespace(key='example_projects')
		dependencies = {
			'_open_ui_test': package, '_open_ui_test.modules': modules,
			'_open_ui_test.modules.commands': commands,
			'_open_ui_test.modules.commands.commands': types.SimpleNamespace(ExampleProjects=example_action),
			'_open_ui_test.modules.settings': types.SimpleNamespace(SettingsRegistery=types.SimpleNamespace(is_package_installed=lambda name: True)),
			'_open_ui_test.modules.core': types.SimpleNamespace(Dispose=type('Dispose', (), {'dispose_add': lambda *args: None}),
				platform=types.SimpleNamespace(unicode_checked_sigil='*')),
			'_open_ui_test.modules.ui': types.SimpleNamespace(Html=lambda html, callback: types.SimpleNamespace(html=html, callback=callback)),
			'sublime': types.SimpleNamespace(run_command=Mock()),
		}
		module = load_module('_open_ui_test.modules.suggestions', ROOT / 'modules/suggestions.py', dependencies)
		debugger = Mock()
		debugger.console.debugger = debugger
		suggestions = module.Suggestions(debugger)
		# with a project open nothing is written and the console keeps whatever is in it
		debugger.console.window.project_file_name.return_value = '/project/demo.sublime-project'
		suggestions.refresh()
		debugger.console.log.assert_not_called()
		debugger.console.error.assert_not_called()
		debugger.console.clear.assert_not_called()
		# without a project the warning is written once, and cleared again once a project appears
		debugger.console.window.project_file_name.return_value = None
		suggestions.refresh()
		debugger.console.clear.assert_called_once()
		debugger.console.error.assert_called_once()
		messages = '\n'.join(str(call.args[1]) for call in debugger.console.log.call_args_list)
		self.assertIn('Sublime Project', messages)
		for text in ('Getting Started', 'Example Projects', 'Suggested Packages', 'Terminus'):
			self.assertNotIn(text, messages)
		debugger.console.window.project_file_name.return_value = '/project/demo.sublime-project'
		suggestions.refresh()
		self.assertEqual(debugger.console.clear.call_count, 2)
		suggestions.refresh()
		self.assertEqual(debugger.console.clear.call_count, 2)


if __name__ == '__main__':
	unittest.main()
