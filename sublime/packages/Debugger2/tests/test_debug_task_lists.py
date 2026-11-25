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


def compiled(path, names, owner=None, namespace=None):
	'''Functions of a module, or methods of one of its classes, compiled on their own'''
	module = ast.parse((ROOT / path).read_text())
	body = module.body
	if owner:
		body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == owner).body
	functions = [node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
	namespace = dict(namespace or {})
	exec(compile(ast.fix_missing_locations(tree), path, 'exec'), namespace)
	return [namespace[name] for name in names]


task_names, = compiled('modules/dap/configuration.py', ['task_names'], namespace={'Error': Error})


class TaskNamesTests(unittest.TestCase):
	def test_one_name_or_a_list_of_them_in_the_order_written(self):
		self.assertEqual(task_names('build'), ['build'])
		self.assertEqual(task_names(['build', 'api server']), ['build', 'api server'])

	def test_nothing_named_is_no_tasks(self):
		for value in (None, '', []):
			self.assertEqual(task_names(value), [])

	def test_anything_else_is_refused_by_the_name_of_the_key(self):
		for value in ({'name': 'build'}, ['build', 5], ['build', ''], 7):
			with self.assertRaises(Error) as raised:
				task_names(value, 'post_debug_task')
			self.assertIn('post_debug_task', str(raised.exception))


class SessionTaskOrderTests(unittest.TestCase):
	def session(self, pre=(), post=(), failing=()):
		ran = []

		async def run_task(name, task):
			ran.append((name, task))
			return task not in failing

		session = types.SimpleNamespace(
			configuration=types.SimpleNamespace(pre_debug_tasks=list(pre), post_debug_tasks=list(post)),
			_change_state_status=Mock(), run_task=run_task)
		return session, ran

	def setUp(self):
		self.pre, self.post = compiled('modules/dap/session.py', ['run_pre_debug_task', 'run_post_debug_task'], owner='Session')

	def test_the_tasks_before_run_in_order_one_after_the_other(self):
		session, ran = self.session(pre=['build', 'database', 'api server'])
		self.assertTrue(asyncio.run(self.pre(session)))
		self.assertEqual(ran, [('pre_debug_task', 'build'), ('pre_debug_task', 'database'), ('pre_debug_task', 'api server')])

	def test_the_first_that_fails_stops_the_rest_and_the_start(self):
		session, ran = self.session(pre=['build', 'database', 'api server'], failing=['database'])
		self.assertFalse(asyncio.run(self.pre(session)))
		self.assertEqual([task for _, task in ran], ['build', 'database'])

	def test_no_tasks_goes_straight_on(self):
		session, ran = self.session()
		self.assertTrue(asyncio.run(self.pre(session)))
		self.assertTrue(asyncio.run(self.post(session)))
		self.assertEqual(ran, [])

	def test_the_tasks_after_all_run_even_when_one_fails(self):
		session, ran = self.session(post=['stop database', 'remove files'], failing=['stop database'])
		self.assertFalse(asyncio.run(self.post(session)))
		self.assertEqual([task for _, task in ran], ['stop database', 'remove files'])
