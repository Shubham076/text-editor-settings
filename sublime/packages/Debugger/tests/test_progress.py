from __future__ import annotations

import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def session_class():
	'''`Session.on_progress_event` and `Session.progress_text`, compiled on their own'''
	module = ast.parse((ROOT / 'modules/dap/session.py').read_text())
	owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Session')
	members = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('on_progress_event', 'progress_text')]
	constant = next(node for node in module.body if isinstance(node, ast.Assign) and node.targets[0].id == 'PROGRESS_LENGTH')
	body = ast.ClassDef(name='Session', bases=[], keywords=[], body=members, decorator_list=[])
	tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), constant, body], type_ignores=[])
	namespace = {}
	exec(compile(ast.fix_missing_locations(tree), 'session.py', 'exec'), namespace)
	return namespace['Session'], namespace['PROGRESS_LENGTH']


class ProgressTests(unittest.TestCase):
	def setUp(self):
		Session, self.length = session_class()
		self.session = Session()
		self.session.progress = {}
		self.session.on_updated = Mock()

	def event(self, name, **body):
		self.session.on_progress_event(name, body)

	def test_what_the_adapter_is_busy_with_is_said_and_the_ui_is_told(self):
		self.assertEqual(self.session.progress_text, '')
		self.event('progressStart', progressId='1', title='Loading symbols')
		self.assertEqual(self.session.progress_text, 'Loading symbols')
		self.session.on_updated.assert_called_once_with(self.session)

	def test_an_update_changes_the_message_and_keeps_the_title(self):
		self.event('progressStart', progressId='1', title='Building')
		self.event('progressUpdate', progressId='1', message='main.go', percentage=40)
		self.assertEqual(self.session.progress_text, 'Building: main.go 40%')
		# one without a message keeps the message before it
		self.event('progressUpdate', progressId='1', percentage=75.4)
		self.assertEqual(self.session.progress_text, 'Building: main.go 75%')

	def test_it_is_gone_when_the_adapter_says_it_is_done(self):
		self.event('progressStart', progressId='1', title='Attaching')
		self.event('progressEnd', progressId='1')
		self.assertEqual(self.session.progress_text, '')
		# one that was never started ends without a fuss
		self.event('progressEnd', progressId='7')

	def test_the_latest_of_two_is_the_one_shown_until_it_ends(self):
		self.event('progressStart', progressId='1', title='Attaching')
		self.event('progressStart', progressId='2', title='Loading symbols')
		self.assertEqual(self.session.progress_text, 'Loading symbols')
		self.event('progressEnd', progressId='2')
		self.assertEqual(self.session.progress_text, 'Attaching')

	def test_a_long_one_is_cut_and_a_percentage_is_kept_in_range(self):
		self.event('progressStart', progressId='1', title='Loading symbols for a library with a very long name indeed', percentage=250)
		text = self.session.progress_text
		self.assertTrue(text.endswith('… 100%'))
		self.assertLessEqual(len(text), self.length + len(' 100%'))

	def test_an_event_without_an_id_is_passed_over(self):
		self.event('progressStart', title='Loading')
		self.assertEqual(self.session.progress_text, '')
		self.session.on_updated.assert_not_called()


class StatusTests(unittest.TestCase):
	def setUp(self):
		import importlib.util
		spec = importlib.util.spec_from_file_location('_state_test', ROOT / 'modules/ui/state.py')
		source = (ROOT / 'modules/ui/state.py').read_text()
		function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'session_status')
		namespace = {}
		exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), 'state.py', 'exec'), namespace)
		self.status = namespace['session_status']

	def session(self, paused=False, running=False, progress='', status=''):
		return types.SimpleNamespace(is_paused=paused, is_running=running, progress_text=progress, state=types.SimpleNamespace(status=status))

	def test_progress_is_what_a_session_that_is_starting_or_running_says(self):
		self.assertEqual(self.status(self.session(status='Starting', progress='Loading symbols 40%')), 'Loading symbols 40%')
		self.assertEqual(self.status(self.session(running=True, progress='Attaching')), 'Attaching')

	def test_paused_is_paused_whatever_else_is_going_on(self):
		self.assertEqual(self.status(self.session(paused=True, progress='Loading symbols')), 'Paused')

	def test_without_progress_it_is_what_it_was(self):
		self.assertEqual(self.status(None), 'Stopped')
		self.assertEqual(self.status(self.session(running=True)), 'Running')
		self.assertEqual(self.status(self.session(status='Running pre debug task')), 'Running pre debug task')
		self.assertEqual(self.status(self.session()), 'Starting')
