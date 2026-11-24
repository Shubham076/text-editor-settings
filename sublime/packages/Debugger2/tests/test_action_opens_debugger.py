from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def action_run():
	'''`Action._run`, compiled on its own against a debugger that is handed to it'''
	module = ast.parse((ROOT / 'modules/command.py').read_text())
	action = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Action')
	method = next(node for node in action.body if isinstance(node, ast.FunctionDef) and node.name == '_run')
	# the import of the debugger module is replaced by the global of the same name
	method.body = [node for node in method.body if not isinstance(node, ast.ImportFrom)]
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
	namespace = {}
	exec(compile(ast.fix_missing_locations(tree), 'command.py', 'exec'), namespace)
	return namespace


def flags():
	'''`opens_debugger` of every action class in commands.py that sets it, by its key'''
	module = ast.parse((ROOT / 'modules/commands/commands.py').read_text())
	found = {}
	for node in module.body:
		if not isinstance(node, ast.ClassDef):
			continue
		values = {target.id: ast.literal_eval(item.value) for item in node.body if isinstance(item, ast.Assign)
			for target in item.targets if isinstance(target, ast.Name) and isinstance(item.value, ast.Constant)}
		if 'opens_debugger' in values:
			found[values.get('key')] = values['opens_debugger']
	return found


class ActionOpensDebuggerTests(unittest.TestCase):
	def run_action(self, opens_debugger):
		namespace = action_run()
		debugger = types.SimpleNamespace(is_open=Mock(return_value=False), open=Mock())
		namespace['Debugger'] = types.SimpleNamespace(get=Mock(return_value=debugger))
		action = types.SimpleNamespace(create_debugger=True, opens_debugger=opens_debugger,
			action_raw=Mock(), action=Mock(), action_with_args=Mock())
		namespace['_run'](action, Mock())
		action.action.assert_called_once_with(debugger)
		self.get = namespace['Debugger'].get
		return debugger

	def test_an_action_about_the_panel_brings_it_up(self):
		self.run_action(True).open.assert_called_once()

	def test_an_action_about_a_line_of_the_file_leaves_the_panel_closed(self):
		self.run_action(False).open.assert_not_called()
		# asked for as it is: asking for it to be made is what brings the panel of one that exists up
		self.assertEqual(self.get.call_args.kwargs, {})

	def test_the_actions_about_a_line_are_the_breakpoints_and_the_logpoint(self):
		self.assertEqual(flags(), {'toggle_breakpoint': False, 'toggle_column_breakpoint': False, 'add_logpoint': False})


if __name__ == '__main__':
	unittest.main()
