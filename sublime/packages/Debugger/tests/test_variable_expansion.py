from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path
import re
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Error(Exception):
	pass


class Literal:
	def __init__(self, value):
		self.value = value

	async def resolve(self):
		return self.value


class Counter:
	'''A variable that is asked for, and counts how often'''

	def __init__(self, *answers):
		self.answers = list(answers)
		self.asked = 0

	async def resolve(self):
		self.asked += 1
		return self.answers.pop(0)


def expanders():
	'''`async_expand_variables` and `async_expand_variables_and_platform`, compiled on their own'''
	module = ast.parse((ROOT / 'modules/dap/configuration.py').read_text())
	names = ('async_expand_variables', 'async_expand_variables_and_platform')
	functions = [node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
	namespace = {
		're': re, 'Error': Error, 'InputLiteral': Literal, 'cast': lambda _, value: value,
		'core': types.SimpleNamespace(platform=types.SimpleNamespace(osx=True, linux=False, windows=False)),
	}
	exec(compile(ast.fix_missing_locations(tree), 'configuration.py', 'exec'), namespace)
	return namespace['async_expand_variables'], namespace['async_expand_variables_and_platform']


expand, expand_configuration = expanders()


def configuration():
	return {
		'name': 'Run one test',
		'program': '${project_path}/main.py',
		'args': ['-k', '${input:test}', '--file', '${file}'],
		'env': {'MODE': '${input:mode}', 'NESTED': {'deep': ['${file}']}},
		'osx': {'cwd': '${project_path}/mac'},
	}


class ExpansionTests(unittest.TestCase):
	def test_variables_are_filled_in_at_every_depth(self):
		variables = {'project_path': Literal('/project'), 'file': Literal('/project/a.py'), 'input:test': Literal('test_login'), 'input:mode': Literal('fast')}
		_, expanded = asyncio.run(expand_configuration(configuration(), variables))
		self.assertEqual(expanded['program'], '/project/main.py')
		self.assertEqual(expanded['args'], ['-k', 'test_login', '--file', '/project/a.py'])
		self.assertEqual(expanded['env'], {'MODE': 'fast', 'NESTED': {'deep': ['/project/a.py']}})
		# what the platform sets is laid over the rest, and filled in like the rest
		self.assertEqual(expanded['cwd'], '/project/mac')

	def test_the_configuration_is_left_as_it_was_written(self):
		written = configuration()
		before = copy.deepcopy(written)
		variables = {'project_path': Literal('/project'), 'file': Literal('/project/a.py'), 'input:test': Literal('test_login'), 'input:mode': Literal('fast')}
		_, expanded = asyncio.run(expand_configuration(written, variables))

		self.assertEqual(written, before)
		# and nothing of the result is the configurations own: adding to it does not reach back
		expanded['args'].append('--added')
		expanded['env']['NESTED']['deep'].append('added')
		self.assertEqual(written, before)

	def test_the_second_start_asks_again_and_looks_the_file_up_again(self):
		written = configuration()
		test, mode = Counter('test_login', 'test_logout'), Counter('fast', 'slow')

		def variables(file):
			return {'project_path': Literal('/project'), 'file': Literal(file), 'input:test': test, 'input:mode': mode}

		_, first = asyncio.run(expand_configuration(written, variables('/project/a.py')))
		_, second = asyncio.run(expand_configuration(written, variables('/project/b.py')))

		self.assertEqual(first['args'], ['-k', 'test_login', '--file', '/project/a.py'])
		self.assertEqual(second['args'], ['-k', 'test_logout', '--file', '/project/b.py'])
		self.assertEqual(second['env']['MODE'], 'slow')
		self.assertEqual((test.asked, mode.asked), (2, 2))

	def test_a_variable_there_is_no_value_for_is_an_error_that_names_it(self):
		with self.assertRaises(Error) as raised:
			asyncio.run(expand({'args': ['${input:missing}']}, {'file': Literal('a.py')}))
		self.assertIn('${input:missing}', str(raised.exception))
		self.assertIn('${file}', str(raised.exception))

	def test_with_no_variables_at_all_nothing_is_looked_up(self):
		# the command of a terminal an adapter asked for: a `${...}` in it is the shells
		written = {'name': 'Terminal', 'cmd': ['sh', '-c', 'echo ${HOME}']}
		_, expanded = asyncio.run(expand_configuration(written, {}))
		self.assertEqual(expanded['cmd'], ['sh', '-c', 'echo ${HOME}'])
		self.assertIsNot(expanded['cmd'], written['cmd'])

	def test_variables_of_the_configuration_itself_are_used_and_taken_out(self):
		written = {'name': 'Example', 'program': '${project_path}/main.py', '$': {'project_path': '/examples/python'}}
		_, expanded = asyncio.run(expand_configuration(written, {'project_path': Literal('/project')}))
		self.assertEqual(expanded, {'name': 'Example', 'program': '/examples/python/main.py'})
		self.assertIn('$', written)
