from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class Error(Exception):
	pass


def restart_natively():
	'''`configurations._restart_natively`, compiled on its own'''
	module = ast.parse((ROOT / 'modules/configurations.py').read_text())
	function = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_restart_natively')
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), function], type_ignores=[])
	namespace = {'dap': types.SimpleNamespace(Error=Error), 'core': Mock()}
	exec(compile(ast.fix_missing_locations(tree), 'configurations.py', 'exec'), namespace)
	return namespace['_restart_natively']


class Session:
	def __init__(self, name, can=True, no_debug=False, fails=False):
		self.configuration = types.SimpleNamespace(name=name)
		self.can_restart_natively = can
		self.no_debug = no_debug
		self.fails = fails
		self.restarted = 0
		self.console = Mock()

	async def restart_natively(self):
		if self.fails:
			raise Error('not this time')
		self.restarted += 1


def run(sessions, names, no_debug=False):
	return asyncio.run(restart_natively()(Mock(), sessions, names, no_debug))


class NativeRestartTests(unittest.TestCase):
	def test_an_adapter_that_can_is_asked_to(self):
		session = Session('Server')
		self.assertTrue(run([session], ['Server']))
		self.assertEqual(session.restarted, 1)

	def test_an_adapter_that_cannot_is_stopped_and_started(self):
		session = Session('Server', can=False)
		self.assertFalse(run([session], ['Server']))
		self.assertEqual(session.restarted, 0)

	def test_nothing_running_is_a_start(self):
		self.assertFalse(run([], ['Server']))

	def test_changing_between_run_and_debug_is_a_new_launch(self):
		session = Session('Server', no_debug=True)
		self.assertFalse(run([session], ['Server'], no_debug=False))
		self.assertEqual(session.restarted, 0)

	def test_a_compound_is_all_or_none(self):
		one, two = Session('One'), Session('Two', can=False)
		self.assertFalse(run([one, two], ['One', 'Two']))
		self.assertEqual(one.restarted, 0)

		# one of its configurations is not running at all
		self.assertFalse(run([one], ['One', 'Two']))
		self.assertEqual(one.restarted, 0)

		two = Session('Two')
		self.assertTrue(run([one, two], ['One', 'Two']))
		self.assertEqual((one.restarted, two.restarted), (1, 1))

	def test_a_request_that_fails_falls_back(self):
		self.assertFalse(run([Session('Server', fails=True)], ['Server']))
