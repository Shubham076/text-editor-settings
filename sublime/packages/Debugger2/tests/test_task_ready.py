from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_task_ready_test', ROOT / 'modules' / 'task_ready.py')
task_ready = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_ready)


class ReadySignalTests(unittest.TestCase):
	def test_the_first_line_the_pattern_is_found_in(self):
		pattern = task_ready.compile_pattern(r'Listening on port \d+')
		self.assertIsNone(task_ready.ready_line(pattern, 'starting\ncompiling\n'))
		self.assertEqual(task_ready.ready_line(pattern, 'starting\n[api] Listening on port 8080 (http)\nmore\n'), '[api] Listening on port 8080 (http)')

	def test_colours_and_carriage_returns_are_not_part_of_a_line(self):
		pattern = task_ready.compile_pattern(r'^ready in \d+ms$')
		self.assertEqual(task_ready.ready_line(pattern, 'building\r\n\x1b[32mready\x1b[0m in \x1b[1m120ms\x1b[0m\r\n'), 'ready in 120ms')
		# a progress line redrawn in place is a line each time it is drawn
		self.assertEqual(task_ready.ready_line(pattern, 'ready in ...\rready in 9ms'), 'ready in 9ms')

	def test_a_pattern_does_not_match_across_lines(self):
		self.assertIsNone(task_ready.ready_line(task_ready.compile_pattern('server up'), 'server\nup\n'))

	def test_a_line_the_terminal_wrapped_is_matched_as_the_line_it_was(self):
		pattern = task_ready.compile_pattern(r'Server listening on http://localhost:\d+')
		# 20 columns: the line goes over three rows, the last of them short
		rows = 'Compiled in 3ms\n[api] Server listeni\nng on http://localho\nst:8080\nnext line\n'
		self.assertEqual([len(row) for row in rows.split('\n')[1:3]], [20, 20])

		self.assertIsNone(task_ready.ready_line(pattern, rows))
		self.assertEqual(task_ready.ready_line(pattern, rows, [20]), '[api] Server listening on http://localhost:8080')

	def test_rows_keep_the_width_they_were_drawn_at_when_the_terminal_is_resized(self):
		pattern = task_ready.compile_pattern('ready to accept')
		rows = 'server is ready to a\nccept connections\n'
		self.assertIsNone(task_ready.ready_line(pattern, rows, [80]))
		self.assertEqual(task_ready.ready_line(pattern, rows, [80, 20]), 'server is ready to accept connections')

	def test_only_a_row_as_wide_as_the_terminal_goes_on_in_the_next(self):
		self.assertEqual(task_ready.unwrapped(['abcd', 'efgh', 'ij', 'kl', ''], [4]), ['abcdefghij', 'kl', ''])
		self.assertEqual(task_ready.unwrapped(['abcd', 'ef'], []), ['abcd', 'ef'])
		self.assertEqual(task_ready.unwrapped(['abcd', 'ef'], [0, None]), ['abcd', 'ef'])
		# two lines that end are never put together
		self.assertIsNone(task_ready.ready_line(task_ready.compile_pattern('server up'), 'server\nup\n', [20]))

	def test_a_pattern_that_is_not_one_is_refused(self):
		for pattern in ('(', '', None, 5):
			with self.assertRaises(task_ready.ReadyError):
				task_ready.compile_pattern(pattern)

	def test_how_long_it_is_given(self):
		self.assertEqual(task_ready.timeout_of(None), task_ready.DEFAULT_TIMEOUT)
		self.assertEqual(task_ready.timeout_of('soon'), task_ready.DEFAULT_TIMEOUT)
		self.assertEqual(task_ready.timeout_of(True), task_ready.DEFAULT_TIMEOUT)
		self.assertEqual(task_ready.timeout_of(5), 5.0)
		self.assertEqual(task_ready.timeout_of(0.5), 0.5)
		self.assertIsNone(task_ready.timeout_of(0))


class Event:
	def __class_getitem__(cls, item):
		return cls

	def __init__(self):
		self.calls = []

	def __call__(self, value):
		self.calls.append(value)


class Terminal:
	'''What a task runtime uses of `TerminusOutputPanel`: a terminal that is written to and ends'''

	created = []

	def __init__(self, debugger, task, is_terminal=False, show_panel=True):
		self.task = task
		self.future = asyncio.get_event_loop().create_future()
		self.on_text_changed = None
		self.on_opened_status = None
		self.written = ''
		self.width = 80
		self.killed = False
		self.dispose = Mock()
		Terminal.created.append(self)

	def write(self, text):
		self.written += text
		if self.on_text_changed:
			self.on_text_changed()

	def end(self, error=None):
		if error:
			self.future.set_exception(RuntimeError(error))
		else:
			self.future.set_result(None)

	def text(self):
		return self.written

	def columns(self):
		return self.width

	async def wait(self):
		await self.future

	def is_finished(self):
		return self.future.done()

	def kill_process(self):
		self.killed = True
		if not self.future.done():
			self.future.set_exception(RuntimeError('[Cancelled]'))


class Task(dict):
	def __init__(self, name, ready_regex=None, ready_timeout=None, background=False):
		super().__init__(shell_cmd='serve')
		self.name, self.type, self.source = name, 'shell', None
		self.ready_regex, self.ready_timeout = ready_regex, ready_timeout
		self.background = background or bool(ready_regex)
		self.depends_on, self.depends_on_order, self.variables = None, None, {}


class ReadyTaskTests(unittest.TestCase):
	def setUp(self):
		Terminal.created = []
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		self.addCleanup(loop.close)
		self.loop = loop

		async def gather(*values):
			return await asyncio.gather(*values)

		class Error(Exception):
			def __init__(self, message, source=None):
				super().__init__(message)

		core = types.ModuleType('_rt.modules.core')
		core.Dispose = object
		core.Event = Event
		core.Future = lambda: loop.create_future()
		core.CancelledError = asyncio.CancelledError
		core.run = lambda function: (lambda *args, **kwargs: loop.create_task(function(*args, **kwargs)))
		core.run_in_executor = lambda function: (lambda *args: loop.run_in_executor(None, function, *args))
		core.gather = gather
		core.delay = asyncio.sleep
		dap = types.ModuleType('_rt.modules.dap')
		dap.Error = Error
		self.Error = Error
		modules = {
			'_rt': types.ModuleType('_rt'), '_rt.modules': types.ModuleType('_rt.modules'),
			'_rt.modules.core': core, '_rt.modules.dap': dap, '_rt.modules.ui': types.ModuleType('_rt.modules.ui'),
			'_rt.modules.output_panel': types.SimpleNamespace(OutputPanel=object),
			'_rt.modules.output_panel_terminus': types.SimpleNamespace(TerminusOutputPanel=Terminal),
		}
		modules['_rt'].__path__ = []
		modules['_rt.modules'].__path__ = []
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)

		for name in ('task_ready', 'task_runtimes', 'task_runtime_ready', 'tasks'):
			spec = importlib.util.spec_from_file_location(f'_rt.modules.{name}', ROOT / 'modules' / f'{name}.py')
			module = importlib.util.module_from_spec(spec)
			sys.modules[spec.name] = module
			self.addCleanup(lambda name=spec.name: sys.modules.pop(name, None))
			spec.loader.exec_module(module)

		self.tasks = module.Tasks()
		self.debugger = types.SimpleNamespace(console=Mock(), window=types.SimpleNamespace(folders=lambda: []))

	def scenario(self, coroutine):
		return self.loop.run_until_complete(coroutine)

	async def settle(self):
		for _ in range(5):
			await asyncio.sleep(0)

	def start(self, task, owner=None):
		return self.tasks.run(self.debugger, task, owner=owner)

	def test_whoever_started_it_goes_on_at_the_signal_and_it_keeps_running(self):
		async def scenario():
			run = self.start(Task('server', r'Listening on \d+'), owner='session')
			await self.settle()
			terminal = Terminal.created[0]

			terminal.write('compiling\n')
			await self.settle()
			self.assertFalse(run.done())

			terminal.write('Listening on 8080\n')
			await self.settle()
			self.assertTrue(run.done())
			self.assertIsNone(run.exception())

			# up and still running, with its tab
			self.assertFalse(terminal.is_finished())
			self.assertFalse(terminal.killed)
			self.assertEqual(len(self.tasks.tasks), 1)
			terminal.dispose.assert_not_called()
			# it stops being read once it has said it
			self.assertIsNone(terminal.on_text_changed)

		self.scenario(scenario())

	def test_a_signal_the_terminal_wrapped_is_still_the_signal(self):
		async def scenario():
			run = self.start(Task('server', r'Listening on port \d+'), owner='session')
			await self.settle()
			terminal = Terminal.created[0]
			terminal.width = 12

			terminal.write('Listening on\n')
			await self.settle()
			self.assertFalse(run.done())

			terminal.write(' port 8080\n')
			await self.settle()
			self.assertTrue(run.done())

		self.scenario(scenario())

	def test_it_is_stopped_when_the_session_it_was_started_for_ends_and_its_tab_stays(self):
		async def scenario():
			run = self.start(Task('server', 'ready'), owner='session')
			await self.settle()
			terminal = Terminal.created[0]
			terminal.write('ready\n')
			await run

			self.tasks.release('another session')
			self.assertFalse(terminal.killed)

			self.tasks.release('session')
			await self.settle()
			self.assertTrue(terminal.killed)
			terminal.dispose.assert_not_called()
			self.assertEqual(len(self.tasks.tasks), 1)
			# stopped on purpose is not something to report
			self.debugger.console.error.assert_not_called()

		self.scenario(scenario())

	def test_two_sessions_share_it_and_the_last_one_to_end_stops_it(self):
		async def scenario():
			first = self.start(Task('server', 'ready'), owner='one')
			await self.settle()
			second = self.start(Task('server', 'ready'), owner='two')
			await self.settle()
			self.assertEqual(len(Terminal.created), 1)
			self.assertFalse(second.done())

			terminal = Terminal.created[0]
			terminal.write('ready\n')
			await first
			await second

			self.tasks.release('one')
			self.assertFalse(terminal.killed)
			self.tasks.release('two')
			self.assertTrue(terminal.killed)

		self.scenario(scenario())

	def test_starting_it_again_after_it_was_stopped_is_a_new_one_in_place_of_the_old(self):
		async def scenario():
			run = self.start(Task('server', 'ready'), owner='session')
			await self.settle()
			Terminal.created[0].write('ready\n')
			await run
			self.tasks.release('session')

			again = self.start(Task('server', 'ready'), owner='next session')
			await self.settle()
			self.assertEqual(len(Terminal.created), 2)
			# the old tab made way for the new one, the signal is waited for again
			Terminal.created[0].dispose.assert_called_once()
			self.assertEqual(len(self.tasks.tasks), 1)
			self.assertFalse(again.done())

			Terminal.created[1].write('ready\n')
			await again

		self.scenario(scenario())

	def test_ending_before_the_signal_fails_the_start(self):
		async def scenario():
			run = self.start(Task('server', 'ready'), owner='session')
			await self.settle()
			Terminal.created[0].write('port 8080 is in use\n')
			Terminal.created[0].end('process is terminated with return code 1.')
			await self.settle()

			with self.assertRaises(self.Error) as raised:
				await run
			self.assertIn('server ended before it was ready', str(raised.exception))
			self.assertIn("'ready'", str(raised.exception))

		self.scenario(scenario())

	def test_no_signal_in_time_fails_the_start_and_stops_it(self):
		async def scenario():
			run = self.start(Task('server', 'ready', ready_timeout=0.05), owner='session')
			await self.settle()
			Terminal.created[0].write('still compiling\n')

			with self.assertRaises(self.Error) as raised:
				await run
			self.assertIn('was not ready after 0.05s', str(raised.exception))
			self.assertTrue(Terminal.created[0].killed)

		self.scenario(scenario())

	def test_stopping_the_session_while_it_waits_ends_the_wait_and_the_task(self):
		async def scenario():
			run = self.start(Task('server', 'ready'), owner='session')
			await self.settle()

			self.tasks.release('session')
			await self.settle()
			self.assertTrue(Terminal.created[0].killed)
			self.assertTrue(run.cancelled())

		self.scenario(scenario())

	def test_a_pattern_that_is_not_one_fails_the_start_before_anything_runs(self):
		async def scenario():
			with self.assertRaises(self.Error) as raised:
				await self.start(Task('server', '('), owner='session')
			self.assertIn('ready_regex', str(raised.exception))
			self.assertEqual(Terminal.created, [])
			self.assertEqual(self.tasks.tasks, [])

		self.scenario(scenario())

	def test_ending_while_a_session_still_needs_it_is_said_in_the_console(self):
		async def scenario():
			run = self.start(Task('server', 'ready'), owner='session')
			await self.settle()
			Terminal.created[0].write('ready\n')
			await run

			Terminal.created[0].end('process is terminated with return code 137.')
			await self.settle()
			self.debugger.console.error.assert_called_once()
			self.assertIn('server ended while it was still needed', self.debugger.console.error.call_args[0][0])

		self.scenario(scenario())

	def test_a_task_without_a_signal_is_waited_for_to_its_end_as_before(self):
		async def scenario():
			run = self.start(Task('build'), owner='session')
			await self.settle()
			self.assertFalse(run.done())
			Terminal.created[0].end()
			await run

			# it has no owner to be stopped with
			self.tasks.release('session')
			self.assertFalse(Terminal.created[0].killed)

		self.scenario(scenario())
