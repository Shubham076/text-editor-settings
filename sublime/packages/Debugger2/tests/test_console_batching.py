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

		dependencies = {
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
			'_console_batch_test.modules.ansi': types.SimpleNamespace(ansi_colorize=lambda text, *args: text),
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


if __name__ == '__main__':
	unittest.main()
