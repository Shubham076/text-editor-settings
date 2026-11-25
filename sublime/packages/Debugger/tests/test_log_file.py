from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from test_open_ui import debugger_method

ROOT = Path(__file__).resolve().parents[1]


def load(name):
	spec = importlib.util.spec_from_file_location(f'_log_test_{name}', ROOT / 'modules' / f'{name}.py')
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


log_file = load('log_file')


class OptionsTests(unittest.TestCase):
	def test_a_configuration_that_does_not_log(self):
		self.assertIsNone(log_file.options(None, '/project'))
		self.assertIsNone(log_file.options(False, '/project'))

	def test_a_file_and_whether_it_is_added_to(self):
		self.assertEqual(log_file.options({'file': '/tmp/api.log'}, '/project'), ('/tmp/api.log', False))
		self.assertEqual(log_file.options({'file': '/tmp/api.log', 'append': True}, '/project'), ('/tmp/api.log', True))

	def test_a_relative_path_is_from_the_folder_of_the_configuration(self):
		self.assertEqual(log_file.options({'file': 'logs/api.log'}, '/project'), ('/project/logs/api.log', False))
		self.assertEqual(log_file.options({'file': './logs/../api.log'}, '/project'), ('/project/api.log', False))

	def test_what_is_not_a_log_is_refused_by_what_is_wrong_with_it(self):
		for value, said in (
			('logs/api.log', 'has to be an object'),
			({}, 'needs a `file`'),
			({'file': ''}, 'needs a `file`'),
			({'file': 'a.log', 'append': 'yes'}, 'true or false'),
			({'file': 'a.log', 'stdout': 'b.log'}, 'has no `stdout`'),
		):
			with self.assertRaises(log_file.LogError) as raised:
				log_file.options(value, '/project')
			self.assertIn(said, str(raised.exception))


class LogFileTests(unittest.TestCase):
	def setUp(self):
		self.directory = tempfile.TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / 'logs' / 'deep' / 'api.log'

	def log(self, append=False):
		log = log_file.LogFile(str(self.path), append)
		self.addCleanup(log.close)
		return log

	def test_the_folder_is_made_and_output_is_there_as_soon_as_it_is_written(self):
		log = self.log()
		log.write('starting\n')
		log.write('listening\n')
		# without closing it: a log is read while the program runs
		self.assertEqual(self.path.read_text(), 'starting\nlistening\n')

	def test_colours_and_carriage_returns_are_not_written(self):
		log = self.log()
		log.write('\x1b[32mready\x1b[0m in 9ms\r\n')
		self.assertEqual(self.path.read_text(), 'ready in 9ms\n')

	def test_every_run_starts_the_file_again(self):
		self.log().write('first run\n')
		self.log().write('second run\n')
		self.assertEqual(self.path.read_text(), 'second run\n')

	def test_append_keeps_what_was_there(self):
		self.log().write('first run\n')
		self.log(append=True).write('second run\n')
		self.assertEqual(self.path.read_text(), 'first run\nsecond run\n')

	def test_a_run_added_after_one_that_did_not_end_its_line_starts_on_its_own(self):
		self.log().write('cut off')
		self.log(append=True).write('second run\n')
		self.assertEqual(self.path.read_text(), 'cut off\nsecond run\n')

	def test_the_text_of_a_terminal_is_written_whole_each_time(self):
		log = self.log()
		log.replace('starting')
		log.replace('starting\nlistening on 8080')
		self.assertEqual(self.path.read_text(), 'starting\nlistening on 8080\n')
		# a terminal that was cleared is a shorter file, not the old one with a new start
		log.replace('cleared')
		self.assertEqual(self.path.read_text(), 'cleared\n')

	def test_the_text_of_a_terminal_goes_after_what_append_kept(self):
		self.log().write('first run\n')
		log = self.log(append=True)
		log.replace('second')
		log.replace('second run\nmore')
		self.assertEqual(self.path.read_text(), 'first run\nsecond run\nmore\n')

	def test_a_file_that_cannot_be_written_is_an_error_that_names_it(self):
		blocker = Path(self.directory.name) / 'file'
		blocker.write_text('')
		with self.assertRaises(log_file.LogError) as raised:
			log_file.LogFile(str(blocker / 'api.log'))
		self.assertIn('api.log', str(raised.exception))

	def test_nothing_is_written_once_it_is_closed(self):
		log = self.log()
		log.write('one\n')
		log.close()
		log.write('two\n')
		log.replace('three')
		self.assertEqual(self.path.read_text(), 'one\n')


class View:
	def __init__(self):
		self.text, self.changes, self.valid = '', 0, True

	def write(self, text):
		self.text += text
		self.changes += 1

	def is_valid(self):
		return self.valid

	def change_count(self):
		return self.changes

	def size(self):
		return len(self.text)

	def substr(self, region):
		return self.text[region[0]:region[1]]


class TerminalLogTests(unittest.TestCase):
	def setUp(self):
		self.timeouts = []
		sublime = types.ModuleType('sublime')
		sublime.Region = lambda a, b: (a, b)
		sublime.set_timeout = lambda callback, delay=0: self.timeouts.append(callback)
		package = types.ModuleType('_tl')
		package.__path__ = []
		modules = {'sublime': sublime, '_tl': package, '_tl.task_ready': load('task_ready'), '_tl.log_file': log_file}
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)
		spec = importlib.util.spec_from_file_location('_tl.terminal_log', ROOT / 'modules' / 'terminal_log.py')
		self.module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(self.module)

		self.directory = tempfile.TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / 'terminal.log'
		self.log = log_file.LogFile(str(self.path))
		self.addCleanup(self.log.close)
		self.view = View()
		self.width = 20

	def follow(self):
		return self.module.TerminalLog(self.log, lambda: self.view, lambda: self.width)

	def tick(self):
		pending, self.timeouts = self.timeouts, []
		for callback in pending:
			callback()

	def test_the_log_follows_what_the_terminal_shows(self):
		self.follow()
		self.assertTrue(self.log.terminal)
		self.view.write('starting\n')
		self.tick()
		self.assertEqual(self.path.read_text(), 'starting\n')
		self.view.write('listening\n')
		self.tick()
		self.assertEqual(self.path.read_text(), 'starting\nlistening\n')

	def test_a_line_the_terminal_wrapped_is_one_line_in_the_log(self):
		self.follow()
		self.view.write('[api] Server listeni\nng on http://localho\nst:8080\nnext\n')
		self.tick()
		self.assertEqual(self.path.read_text(), '[api] Server listening on http://localhost:8080\nnext\n')

	def test_a_terminal_that_has_not_changed_is_not_read_again(self):
		self.follow()
		self.view.write('one\n')
		self.tick()
		self.log.replace = Mock()
		self.tick()
		self.tick()
		self.log.replace.assert_not_called()

	def test_closing_writes_the_last_of_it_and_stops_reading(self):
		follower = self.follow()
		self.view.write('one\n')
		self.tick()
		self.view.write('two\n')
		follower.close()
		self.assertEqual(self.path.read_text(), 'one\ntwo\n')

		self.view.write('three\n')
		self.tick()
		self.assertEqual(self.path.read_text(), 'one\ntwo\n')
		self.assertEqual(self.timeouts, [])

	def test_a_terminal_that_is_not_there_yet_or_was_closed_is_waited_for(self):
		view, self.view = self.view, None
		self.follow()
		self.tick()
		self.view = view
		self.view.write('late\n')
		self.tick()
		self.assertEqual(self.path.read_text(), 'late\n')
		self.view.valid = False
		self.view.write('gone\n')
		self.tick()
		self.assertEqual(self.path.read_text(), 'late\n')


class DebuggerLogTests(unittest.TestCase):
	def debugger(self, **logs):
		console = Mock()
		debugger = types.SimpleNamespace(logs=dict(logs), console_for=Mock(return_value=console))
		debugger.log_of = lambda session: debugger_method('log_of')(debugger, session)
		return debugger

	def test_what_the_program_wrote_goes_to_the_log_of_its_configuration(self):
		root = types.SimpleNamespace(parent=None)
		child = types.SimpleNamespace(parent=root)
		log = types.SimpleNamespace(terminal=False, write=Mock())
		debugger = self.debugger()
		# the log is kept under the session a configuration was started as, a child writes to its parents
		debugger.logs = types.SimpleNamespace(get=lambda session: log if session is root else None)

		output = debugger_method('_on_session_output')
		output(debugger, root, types.SimpleNamespace(category='stdout', output='out\n'))
		output(debugger, child, types.SimpleNamespace(category='stderr', output='err\n'))
		# what the adapter says about the program is not what the program printed
		output(debugger, root, types.SimpleNamespace(category='console', output='adapter chatter\n'))
		output(debugger, root, types.SimpleNamespace(category=None, output='no category\n'))
		self.assertEqual([call[0][0] for call in log.write.call_args_list], ['out\n', 'err\n'])

	def test_a_program_in_a_terminal_is_logged_from_the_terminal_only(self):
		root = types.SimpleNamespace(parent=None)
		log = types.SimpleNamespace(terminal=True, write=Mock())
		debugger = self.debugger()
		debugger.logs = types.SimpleNamespace(get=lambda session: log)
		debugger_method('_on_session_output')(debugger, root, types.SimpleNamespace(category='stdout', output='out\n'))
		log.write.assert_not_called()

	def test_a_configuration_without_a_log_writes_nothing(self):
		debugger = self.debugger()
		debugger.logs = types.SimpleNamespace(get=lambda session: None)
		debugger_method('_on_session_output')(debugger, types.SimpleNamespace(parent=None), types.SimpleNamespace(category='stdout', output='out\n'))
