from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def session_class():
	'''`Session.start_progress` and `Session.end_start_progress`, compiled on their own'''
	module = ast.parse((ROOT / 'modules/dap/session.py').read_text())
	owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Session')
	members = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('start_progress', 'end_start_progress')]
	body = ast.ClassDef(name='Session', bases=[], keywords=[], body=members, decorator_list=[])
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), body], type_ignores=[])
	namespace = {}
	exec(compile(ast.fix_missing_locations(tree), 'session.py', 'exec'), namespace)
	return namespace['Session']


class StartProgressTests(unittest.TestCase):
	def session(self, request='launch', no_debug=False, parent=None):
		session = session_class()()
		session.parent = parent
		session.no_debug = no_debug
		session.name = 'server'
		session.configuration = types.SimpleNamespace(request=request)
		self.done = Mock()
		session.console = types.SimpleNamespace(progress=Mock(return_value=self.done))
		return session

	def test_the_line_says_what_is_being_done_and_ends_once(self):
		for request, no_debug, text in (('launch', False, 'Starting server'), ('launch', True, 'Running server'), ('attach', False, 'Attaching to server')):
			session = self.session(request, no_debug)
			session.start_progress()
			session.console.progress.assert_called_once_with(text)
			session.end_start_progress(True)
			# a session that is stopped later does not end the line a second time
			session.end_start_progress(False)
			self.done.assert_called_once_with(True)

	def test_a_start_that_fails_is_marked_so(self):
		session = self.session()
		session.start_progress()
		session.end_start_progress(False)
		self.done.assert_called_once_with(False)

	def test_a_session_inside_another_and_a_second_start_have_no_line_of_their_own(self):
		child = self.session(parent=object())
		child.start_progress()
		child.console.progress.assert_not_called()

		session = self.session()
		session.start_progress()
		session.start_progress()
		session.console.progress.assert_called_once()

	def test_a_console_that_has_no_progress_and_an_end_without_a_start_are_fine(self):
		session = self.session()
		session.console = types.SimpleNamespace()
		session.start_progress()
		session.end_start_progress(True)


if __name__ == '__main__':
	unittest.main()
