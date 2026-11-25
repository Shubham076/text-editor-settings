from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class Item:
	def __init__(self, run, text, annotation='', details='', kind=None):
		self.run, self.text, self.annotation, self.details = run, text, annotation, details


def options():
	'''`ChangeConfiguration.options`, compiled on its own'''
	module = ast.parse((ROOT / 'modules/commands/commands_configurations.py').read_text())
	owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'ChangeConfiguration')
	method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == 'options')
	method.decorator_list = []
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
	named = lambda name: types.SimpleNamespace(name=name)
	namespace = {
		'ui': types.SimpleNamespace(InputListItem=Item), 'sublime': types.SimpleNamespace(KIND_ID_AMBIGUOUS=0),
		'EditConfiguration': named('Edit Configuration File'), 'AddConfiguration': named('Add Configuration'),
		'InstallAdapters': named('Install Adapters'),
	}
	exec(compile(ast.fix_missing_locations(tree), 'commands_configurations.py', 'exec'), namespace)
	return namespace['options']


class OptionsMenuTests(unittest.TestCase):
	def test_the_gear_lists_the_options_and_no_configuration(self):
		debugger = types.SimpleNamespace(run_action=Mock(), project=types.SimpleNamespace(project_file_name='exploit.sublime-project',
			configurations=[types.SimpleNamespace(name='Run Server')], compounds=[]))
		rows = options()(debugger, Mock(), Mock(), types.SimpleNamespace(name='Add Function Breakpoint'), object())

		self.assertEqual([row.text for row in rows], [
			'Edit Configuration File', 'Add Configuration', 'Install Adapters', 'Debugger Settings',
			'Add Function Breakpoint', 'Report Issue', 'About/Getting Started',
		])
		self.assertEqual(rows[0].annotation, 'exploit.sublime-project')
		# one line each: a row with a second line makes every row of the list as tall as it
		self.assertTrue(all(not row.details for row in rows))


if __name__ == '__main__':
	unittest.main()
