from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def source_breakpoints_methods(*names):
	'''The named methods of `SourceBreakpoints`, compiled on their own with `ui` as the only global'''
	module = ast.parse((ROOT / 'modules/dap/breakpoint_source.py').read_text())
	owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'SourceBreakpoints')
	methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in names]
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *methods], type_ignores=[])
	namespace = {'ui': types.SimpleNamespace(InputText=Mock())}
	exec(compile(ast.fix_missing_locations(tree), 'breakpoint_source.py', 'exec'), namespace)
	return namespace


class Breakpoints:
	'''Lines of a file with breakpoints on them, the way `SourceBreakpoints` keeps them'''

	def __init__(self, namespace):
		self.breakpoints = []
		self.updated = Mock()
		self.set_logpoint = lambda *args: namespace['set_logpoint'](self, *args)
		self.add_logpoint = lambda *args: namespace['add_logpoint'](self, *args)

	def get_breakpoints_on_line(self, file, line):
		return [item for item in self.breakpoints if item.file == file and item.line == line]

	def add_breakpoint(self, file, line):
		self.breakpoints.append(types.SimpleNamespace(file=file, line=line, dap=types.SimpleNamespace(logMessage=None)))


class AddLogpointTests(unittest.TestCase):
	def setUp(self):
		self.namespace = source_breakpoints_methods('set_logpoint', 'add_logpoint')
		self.input = self.namespace['ui'].InputText
		self.breakpoints = Breakpoints(self.namespace)

	def test_a_line_becomes_a_logpoint_once_there_is_a_message(self):
		self.breakpoints.add_logpoint('/src/main.go', 12)

		# asked first: a line is not given a breakpoint for a question that may be given up on
		self.assertEqual(self.breakpoints.breakpoints, [])
		callback, placeholder, initial = self.input.call_args.args
		self.assertIn('{}', placeholder)
		self.assertIsNone(initial)
		self.input.return_value.run.assert_called_once()

		callback('  user is {name}  ')
		(breakpoint,) = self.breakpoints.breakpoints
		self.assertEqual((breakpoint.line, breakpoint.dap.logMessage), (12, 'user is {name}'))
		self.breakpoints.updated.assert_called_once_with(breakpoint)

	def test_an_empty_message_changes_nothing(self):
		self.breakpoints.add_logpoint('/src/main.go', 12)
		self.input.call_args.args[0]('   ')

		self.assertEqual(self.breakpoints.breakpoints, [])
		self.breakpoints.updated.assert_not_called()

	def test_a_breakpoint_that_is_already_on_the_line_becomes_the_logpoint(self):
		self.breakpoints.add_breakpoint('/src/main.go', 12)
		self.breakpoints.breakpoints[0].dap.logMessage = 'old'

		self.breakpoints.add_logpoint('/src/main.go', 12)
		callback, _, initial = self.input.call_args.args
		# what it prints now is what is there to be changed
		self.assertEqual(initial, 'old')

		callback('new')
		self.assertEqual([item.dap.logMessage for item in self.breakpoints.breakpoints], ['new'])


if __name__ == '__main__':
	unittest.main()
