from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path, modules):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, dict(modules, **{name: module})):
		spec.loader.exec_module(module)
	return module


class ConsoleBatchingTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		package = types.ModuleType('_console_batch_test')
		package.__path__ = []
		modules = types.ModuleType('_console_batch_test.modules')
		modules.__path__ = []
		views = types.ModuleType('_console_batch_test.modules.views')
		views.__path__ = []
		sublime = types.ModuleType('sublime')
		cls.scheduled = []
		sublime.set_timeout = lambda callback, delay=0: cls.scheduled.append((callback, delay))
		sublime.Region = lambda a, b=None: (a, a if b is None else b)

		class Dispose:
			def dispose_add(self, *items): ...
			def dispose(self): ...

		class OutputPanel: ...
		class Console: ...

		json_logs = load_module('_console_batch_test.modules.json_logs', ROOT / 'modules/json_logs.py', {})
		dependencies = {
			'_console_batch_test.modules.json_logs': json_logs,
			'_console_batch_test': package,
			'_console_batch_test.modules': modules,
			'_console_batch_test.modules.views': views,
			'_console_batch_test.modules.core': types.SimpleNamespace(
				CancelledError=Exception,
				Dispose=Dispose,
				Event=Mock,
				platform=types.SimpleNamespace(unicode_unchecked_sigil='?', unicode_checked_sigil='!'),
				run=lambda fn: fn,
			),
			'_console_batch_test.modules.ui': types.SimpleNamespace(),
			'_console_batch_test.modules.dap': types.SimpleNamespace(Console=Console, Error=Exception),
			'_console_batch_test.modules.settings': types.SimpleNamespace(Settings=types.SimpleNamespace()),
			'_console_batch_test.modules.variable_format': types.SimpleNamespace(value_summary=lambda variable: variable.value),
			'_console_batch_test.modules.views.variable': types.SimpleNamespace(VariableView=object),
			'_console_batch_test.modules.ansi': types.SimpleNamespace(ansi_colorize=lambda text, *args: text,
				stderr_runs=lambda text, unfinished=None: ([(text, 'red')], None)),
			'_console_batch_test.modules.output_window_protocol': types.SimpleNamespace(ProtocolConsoleWindow=object),
			'_console_batch_test.modules.output_panel': types.SimpleNamespace(OutputPanel=OutputPanel),
			'sublime': sublime,
		}
		cls.module = load_module(
			'_console_batch_test.modules.output_panel_console',
			ROOT / 'modules/output_panel_console.py',
			dependencies,
		)

	def setUp(self):
		self.scheduled.clear()
		self.console = self.module.ConsoleOutputPanel.__new__(self.module.ConsoleOutputPanel)
		self.console._last_output_event = None
		self.console._program_output_batch = []
		self.console._program_output_batch_color = None
		self.console._program_output_batch_revision = 0
		self.console._program_output_batch_scheduled = False
		self.console.indent = ''
		self.console.forced_indent = ''
		self.console._write = Mock()

	def output(self, text, category='stdout', group=None):
		return types.SimpleNamespace(
			output=text,
			category=category,
			group=group,
			variablesReference=None,
			source=None,
		)

	def test_what_a_logpoint_prints_says_that_it_is_one_and_where(self):
		logpoint = types.SimpleNamespace(dap=types.SimpleNamespace(logMessage='reached here'))
		plain = types.SimpleNamespace(dap=types.SimpleNamespace(logMessage=None))
		on_line = {('/src/graph/graph.go', 118): [logpoint], ('/src/graph/graph.go', 20): [plain]}
		self.console.debugger = types.SimpleNamespace(breakpoints=types.SimpleNamespace(source=types.SimpleNamespace(
			get_breakpoints_on_line=lambda file, line: on_line.get((file, line), []))))
		self.console.phantoms = []
		self.console.view = Mock()
		self.console.on_navigate = Mock()
		self.console.at = Mock(return_value=10)

		def event(text, line):
			return types.SimpleNamespace(output=text, category='stdout', group=None, variablesReference=None,
				source=types.SimpleNamespace(path='/src/graph/graph.go'), line=line)

		with patch.object(self.module, 'RegionAnnotation', Mock()), patch.object(self.module.dap, 'SourceLocation', Mock(), create=True):
			self.console.program_output(Mock(), event('> [Go 40]: reached here\n', 118))
			# output that only comes from a line, with no logpoint on it, is the programs own
			self.console.program_output(Mock(), event('plain\n', 20))

		written = [call.args[0] for call in self.console._write.call_args_list]
		self.assertEqual(written, ['logpoint graph.go:118: [Go 40]: reached here\n', 'plain\n'])

	def test_stderr_that_is_a_report_is_drawn_as_output(self):
		session = Mock()
		self.console.debugger = types.SimpleNamespace(stderr_is_output=lambda asked: asked is session)

		self.console.program_output(session, self.output('PASS src/x.test.ts\n', category='stderr'))
		self.console.program_output(Mock(), self.output('panic\n', category='stderr'))
		self.console.flush_program_output()

		self.assertEqual([(call.args[0], call.args[1]) for call in self.console._write.call_args_list],
			[('PASS src/x.test.ts\n', 'foreground'), ('panic\n', 'red')])

	def test_plain_program_output_is_combined_into_one_ui_write(self):
		self.console.program_output(Mock(), self.output('first\n'))
		self.console.program_output(Mock(), self.output('second\n'))
		self.console._write.assert_not_called()
		self.assertEqual(len(self.scheduled), 1)
		callback, delay = self.scheduled[0]
		self.assertEqual(delay, self.module.PROGRAM_OUTPUT_BATCH_DELAY_MS)
		callback()
		self.console._write.assert_called_once_with('first\nsecond\n', 'foreground', ignore_indent=False)

	def test_structured_output_flushes_the_plain_output_before_it(self):
		writes = []
		self.console._write.side_effect = lambda text, color, *args, **kwargs: writes.append((text, color, self.console.indent))
		self.console.program_output(Mock(), self.output('before\n'))
		self.console.program_output(Mock(), self.output('group\n', group='start'))
		self.console.program_output(Mock(), self.output('inside\n'))
		self.console.program_output(Mock(), self.output('', group='end'))
		self.assertEqual(writes, [
			('before\n', 'foreground', ''),
			('group\n', 'foreground', ''),
			('inside\n', 'foreground', '\t'),
		])
		self.assertEqual(self.console.indent, '')

	def test_color_change_finishes_the_old_batch_and_ignores_its_stale_callback(self):
		self.console.program_output(Mock(), self.output('normal\n'))
		self.console.program_output(Mock(), self.output('error\n', category='stderr'))
		self.console._write.assert_called_once_with('normal\n', 'foreground', ignore_indent=False)
		self.assertEqual(len(self.scheduled), 2)
		self.scheduled[0][0]()
		self.console._write.assert_called_once()
		self.scheduled[1][0]()
		self.assertEqual([call.args[:2] for call in self.console._write.call_args_list], [
			('normal\n', 'foreground'),
			('error\n', 'red'),
		])

	def test_clearing_console_discards_a_scheduled_output_batch(self):
		self.console.program_output(Mock(), self.output('old run\n'))
		callback = self.scheduled[0][0]
		self.console.edit = Mock()
		self.console.dispose_phantoms = Mock()
		self.console.owns_protocol = False
		self.console.view = Mock()
		self.console.clear()
		callback()
		self.console._write.assert_not_called()

	def json_logs(self, mode):
		settings = self.module.Settings
		settings.json_logs = mode
		self.addCleanup(lambda: delattr(settings, 'json_logs'))

	def written(self):
		self.console.flush_program_output()
		return [(call.args[0], call.args[1]) for call in self.console._write.call_args_list]

	def test_a_json_log_is_formatted_and_takes_its_own_colours_even_on_stderr(self):
		self.json_logs('compact')
		self.console.program_output(None, self.output('boom\n{"level":"info","msg":"listening","port":3000}\n', 'stderr'))
		(plain, plain_color), (log, log_color) = self.written()
		self.assertEqual((plain, plain_color), ('boom\n', 'red'))
		self.assertEqual(log_color, 'foreground')
		self.assertIn('listening', log)
		self.assertNotIn('{', log)

	def test_a_configuration_can_show_json_logs_its_own_way_or_not_at_all(self):
		self.json_logs('compact')
		session = types.SimpleNamespace(configuration={'json_logs': 'off'})
		self.console.program_output(session, self.output('{"msg":"as it is"}\n'))
		self.assertEqual(self.written(), [('{"msg":"as it is"}\n', 'foreground')])

	def test_the_start_of_a_json_log_waits_for_its_end_and_is_shown_as_it_is_when_none_comes(self):
		self.json_logs('compact')
		self.console.program_output(None, self.output('{"msg":"he'))
		self.assertEqual(self.written(), [])
		self.console.program_output(None, self.output('llo"}\n{ waiting'))
		self.assertEqual(self.written(), [('hello\n', 'foreground')])
		# the timer of the piece still held
		callback, delay = [item for item in self.scheduled if item[1] == self.module.JSON_LOG_PARTIAL_DELAY_MS][-1]
		callback()
		self.assertEqual(self.written()[-1], ('{ waiting', 'foreground'))

	def test_what_the_adapters_process_printed_is_formatted_too(self):
		# delve: the program's output is the output of the adapter's process, not output events
		self.json_logs('compact')
		self.console.protocol = Mock()
		self.console.session = None
		self.console.debugger = types.SimpleNamespace(session_panels=None)
		self.console.log('stdout', 'Building main.go\n{"level":"info","msg":"started"}\n')
		self.console.log('stderr', '2026/11/26 loading config\n{"level":"fatal","msg":"no database","error":"refused"}\n')
		written = [(call.args[0], call.args[1]) for call in self.console._write.call_args_list]
		self.assertEqual([(text if '{' in text or 'config' in text or 'Building' in text else 'formatted', color) for text, color in written], [
			('Building main.go\n', None), ('formatted', None), ('2026/11/26 loading config\n', 'red'), ('formatted', None)])
		self.assertIn('started', written[1][0])
		self.assertIn('no database', written[3][0])
		self.assertIn('refused', written[3][0])

	def progress_console(self):
		'''The console over a buffer that is a string, with the regions a view keeps'''
		console = self.console
		buffer = ['\u200b']
		regions = {}

		class View:
			def insert(self, edit, at, text):
				buffer[0] = buffer[0][:at] + text + buffer[0][at:]
				# a region after the insertion moves with the text, as a view's does
				for key, (a, b) in list(regions.items()):
					if a >= at:
						regions[key] = (a + len(text), b + len(text))
				return len(text)

			def replace(self, edit, region, text):
				buffer[0] = buffer[0][:region[0]] + text + buffer[0][region[1]:]

			def add_regions(self, key, values):
				regions[key] = values[0]

			def get_regions(self, key):
				return [types.SimpleNamespace(a=regions[key][0], size=lambda: regions[key][1] - regions[key][0])] if key in regions else []

			def erase_regions(self, key):
				regions.pop(key, None)

		console.view = View()
		console.at = lambda: len(buffer[0]) - 1
		console.edit = lambda fn: fn(None)

		def write(text, color, ensure_new_line=False, **_):
			at = console.at()
			if ensure_new_line and at and buffer[0][at - 1] != '\n':
				text = '\n' + text
			console.view.insert(None, at, text)

		console.write = write
		return console, buffer, regions

	def ticks(self):
		return [callback for callback, delay in self.scheduled if delay == self.module.PROGRESS_INTERVAL_MS]

	def test_the_mark_of_a_progress_line_spins_and_then_says_how_it_ended(self):
		console, buffer, regions = self.progress_console()
		console.write('before', None)
		done = console.progress('Building main.go')
		frames = self.module.PROGRESS_FRAMES
		self.assertEqual(buffer[0], 'before\n' + frames[0] + ' Building main.go\u200b')

		self.ticks()[-1]()
		self.assertIn(frames[1] + ' Building main.go', buffer[0])
		# output written below does not move the mark off its line
		console.write('program output\n', None, ensure_new_line=True)
		self.ticks()[-1]()
		self.assertIn(frames[2] + ' Building main.go\nprogram output', buffer[0])

		done(True)
		self.assertRegex(buffer[0], '^before\n' + self.module.PROGRESS_DONE + r' Building main\.go · \d+\.\ds\nprogram output\n\u200b$')
		self.assertEqual(regions, {})
		# the timer that was still waiting does nothing more
		before = buffer[0]
		self.ticks()[-1]()
		self.assertEqual(buffer[0], before)

	def test_a_failed_progress_line_is_marked_and_a_cleared_one_stops(self):
		console, buffer, regions = self.progress_console()
		console.progress('Building a')(False)
		self.assertTrue(buffer[0].startswith(self.module.PROGRESS_FAILED + ' Building a · '))

		done = console.progress('Building b')
		# the console was cleared: the text and its regions are gone
		buffer[0] = '\u200b'
		regions.clear()
		scheduled = len(self.scheduled)
		self.ticks()[-1]()
		done(True)
		self.assertEqual(buffer[0], '\u200b')
		self.assertEqual(len(self.scheduled), scheduled)

	def test_what_the_debugger_says_is_marked_for_what_it_is_and_what_the_program_prints_is_not(self):
		self.console.protocol = Mock()
		self.console.session = None
		self.console.debugger = types.SimpleNamespace(session_panels=None)
		self.console.open = Mock()
		self.console.phantoms = []
		written = []
		self.console.write = lambda text, color, **_: written.append((text, color))
		self.console.log('error', 'no adapter\nsecond line\n')
		self.console.log('error-no-open', 'quiet')
		self.console.log('warn', 'careful')
		self.console.log('success', 'done')
		self.console.log('comment', 'just saying')
		self.console.log('error', '● has a mark already')
		self.console.log('stderr', 'the program failed\n')
		self.assertEqual(written, [
			('✗ no adapter\nsecond line', 'red'), ('✗ quiet', 'red'), ('⚠ careful', 'yellow'), ('✓ done', 'green'),
			('just saying', 'blue'), ('● has a mark already', 'red'), ('the program failed\n', 'red')])


if __name__ == '__main__':
	unittest.main()
