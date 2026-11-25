from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

from test_live_ui import ROOT, load_module


@unittest.skipIf(os.name == 'nt', 'process trees are read with ps')
class ExitCleanupTests(unittest.TestCase):
	"""Quitting Sublime ends what the debugger started, not just the adapters"""

	def setUp(self):
		package = types.ModuleType('_exit_test')
		package.__path__ = []
		modules = types.ModuleType('_exit_test.modules')
		modules.__path__ = []
		self.core = types.SimpleNamespace(exception=Mock())
		self.loaded = {'_exit_test': package, '_exit_test.modules': modules, '_exit_test.modules.core': self.core}
		self.module = load_module('_exit_test.modules.exit_cleanup', ROOT / 'modules/exit_cleanup.py', self.loaded)
		self.loaded['_exit_test.modules.exit_cleanup'] = self.module
		self.started = []
		# no log file and no detached killers left behind by the tests; each has a test of its own
		self.module.LOG = os.path.join(tempfile.mkdtemp(), 'processes.log')
		self.backstop = self.module.backstop
		self.module.backstop = Mock()

	def tearDown(self):
		for process in self.started:
			if process.poll() is None:
				process.kill()

	def spawn_tree(self, ignore_term=False):
		"""An "adapter" that starts a "program" and waits on it; returns (adapter, pid of the program)"""
		trap = "trap '' TERM; " if ignore_term else ''
		adapter = subprocess.Popen(['sh', '-c', trap + 'sh -c "' + trap + 'sleep 60" & echo $!; wait'], stdout=subprocess.PIPE)
		self.started.append(adapter)
		return adapter, int(adapter.stdout.readline())

	def running(self, pid):
		try:
			os.kill(pid, 0)
		except ProcessLookupError:
			return False
		return True

	def test_trees_are_the_roots_and_everything_beneath_them_deepest_first(self):
		children = {1: [10, 20], 10: [11, 12], 11: [13], 20: [21], 99: [100]}
		self.assertEqual(self.module.process_trees([10], children), [13, 11, 12, 10])
		# a process reached twice is ended once
		self.assertEqual(self.module.process_trees([10, 11, 20], children), [13, 11, 12, 10, 21, 20])
		self.assertEqual(self.module.process_trees([], children), [])

	def test_the_program_an_adapter_started_ends_with_the_adapter(self):
		adapter, program = self.spawn_tree()
		self.assertTrue(self.running(program))
		ended = self.module.end_process_trees([adapter.pid])
		self.assertIn(program, ended)
		self.assertIn(adapter.pid, ended)
		adapter.wait(2)
		deadline = time.monotonic() + 2
		while self.running(program) and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertFalse(self.running(program))

	def test_a_program_that_ignores_the_request_is_killed_after_the_grace_period(self):
		adapter, program = self.spawn_tree(ignore_term=True)
		started = time.monotonic()
		self.module.end_process_trees([adapter.pid], grace=0.3)
		self.assertGreaterEqual(time.monotonic() - started, 0.3)
		adapter.wait(2)
		deadline = time.monotonic() + 2
		while self.running(program) and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertFalse(self.running(program))

	def test_nothing_to_end_reads_no_process_table_and_never_ends_itself(self):
		with patch.object(self.module.subprocess, 'check_output', side_effect=AssertionError('no need to look')):
			self.assertEqual(self.module.end_process_trees([]), [])
			self.assertEqual(self.module.end_process_trees([os.getpid()]), [])

	def test_only_the_debuggers_own_terminals_are_ended(self):
		terminal_class = type('TerminusOutputPanel', (), {})
		mine = terminal_class()
		mine.output_panel_name = 'output.prisma:generate-types'
		debugger = types.SimpleNamespace(output_panels=[mine, types.SimpleNamespace(output_panel_name='output.Debugger')])
		self.loaded['_exit_test.modules.debugger'] = types.SimpleNamespace(Debugger=types.SimpleNamespace(debuggers=lambda: [debugger]))
		self.loaded['_exit_test.modules.output_panel_terminus'] = types.SimpleNamespace(TerminusOutputPanel=terminal_class)
		terminus = types.ModuleType('Terminus.terminus.terminal')
		terminus.Terminal = types.SimpleNamespace(
			_terminals={1: types.SimpleNamespace(tag='output.prisma:generate-types', process=types.SimpleNamespace(pid=4242)),
				2: types.SimpleNamespace(tag=None, process=types.SimpleNamespace(pid=5555))},
			_detached_terminals=[types.SimpleNamespace(tag='output.Debugger', process=types.SimpleNamespace(pid=6666))])
		with patch.dict(sys.modules, dict(self.loaded, **{'Terminus.terminus.terminal': terminus})):
			# the user's own Terminus tab and a terminal on a panel that is not a terminal's are left alone
			self.assertEqual(self.module.terminal_pids(), [4242])

	def test_a_failure_while_quitting_is_logged_not_raised(self):
		with patch.object(self.module, 'adapter_pids', side_effect=RuntimeError('gone')):
			self.assertEqual(self.module.end_everything(), [])
		self.core.exception.assert_called_once()


	def test_what_is_left_is_killed_by_a_process_that_outlives_the_plugin_host(self):
		adapter, program = self.spawn_tree(ignore_term=True)
		self.module.BACKSTOP = 0.3
		self.backstop([adapter.pid, program])
		adapter.wait(3)
		deadline = time.monotonic() + 3
		while self.running(program) and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertFalse(self.running(program))
		# and it is armed before anything is asked to stop
		self.module.backstop = Mock(side_effect=lambda pids: self.assertTrue(all(self.running(pid) for pid in pids)))
		adapter, program = self.spawn_tree()
		self.module.end_process_trees([adapter.pid])
		self.module.backstop.assert_called_once()

	def test_what_was_ended_is_written_down(self):
		adapter, program = self.spawn_tree()
		self.module.end_process_trees([adapter.pid], reason='sublime exit')
		self.module.end_process_trees([], reason='sublime exit')
		text = open(self.module.LOG).read()
		self.assertIn('sublime exit: roots [{}]'.format(adapter.pid), text)
		self.assertIn(str(program), text)
		self.assertIn('sublime exit: all stopped when asked', text)
		self.assertIn('sublime exit: nothing running', text)

	def test_disposing_an_adapter_ends_the_program_it_launched(self):
		"""What closing a window does to each session, and so what quitting Sublime does first"""
		dap = types.ModuleType('_exit_test.modules.dap')
		dap.__path__ = []
		names = ('Transport', 'TransportListener', 'TransportOutputLog', 'TransportConnectionError', 'TransportStream')
		transport = types.SimpleNamespace(**{name: type(name, (Exception,) if 'Error' in name else (), {}) for name in names})
		self.core.run_in_executor = lambda fn: fn
		self.core.info = self.core.error = Mock()
		loaded = dict(self.loaded, **{'_exit_test.modules.dap': dap, '_exit_test.modules.dap.transport': transport})
		module = load_module('_exit_test.modules.dap.transports', ROOT / 'modules/dap/transports.py', loaded)
		adapter, program = self.spawn_tree()
		process = module.Process.__new__(module.Process)
		process.process = adapter
		with patch.dict(sys.modules, loaded):
			process.dispose()
		self.assertTrue(process.closed)
		self.core.exception.assert_not_called()
		adapter.wait(2)
		deadline = time.monotonic() + 2
		while self.running(program) and time.monotonic() < deadline:
			time.sleep(0.02)
		self.assertFalse(self.running(program))
		# an adapter that already exited is left alone: its pid may be someone else's by now
		with patch.dict(sys.modules, loaded), patch.object(self.module, 'end_process_trees', side_effect=AssertionError('already gone')):
			process.dispose()


if __name__ == '__main__':
	unittest.main()
