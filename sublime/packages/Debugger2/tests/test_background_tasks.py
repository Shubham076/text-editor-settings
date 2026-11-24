from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Event:
	def __init__(self):
		self.calls = []

	def __class_getitem__(cls, item):
		return cls

	def __call__(self, value):
		self.calls.append(value)


class Terminal:
	created = []

	def __init__(self, debugger, task, is_terminal=False, show_panel=True):
		self.show_panel = show_panel
		self.future = asyncio.get_event_loop().create_future()
		self.dispose = Mock()
		Terminal.created.append(self)

	async def wait(self):
		await self.future

	def is_finished(self):
		return self.future.done()


class Task(dict):
	def __init__(self, name, background):
		super().__init__()
		self.name, self.background, self.type = name, background, 'shell'
		self.depends_on, self.depends_on_order, self.variables = None, None, {}


class BackgroundTaskTests(unittest.TestCase):
	def setUp(self):
		Terminal.created = []
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		self.addCleanup(loop.close)
		self.loop = loop

		async def gather(*values):
			return await asyncio.gather(*values)

		core = types.ModuleType('_bgt.modules.core')
		core.Dispose = object
		core.Event = Event
		core.run = lambda function: (lambda *args, **kwargs: loop.create_task(function(*args, **kwargs)))
		core.gather = gather
		dap = types.ModuleType('_bgt.modules.dap')
		dap.Error = RuntimeError
		modules = {
			'_bgt': types.ModuleType('_bgt'), '_bgt.modules': types.ModuleType('_bgt.modules'),
			'_bgt.modules.core': core, '_bgt.modules.dap': dap, '_bgt.modules.ui': types.ModuleType('_bgt.modules.ui'),
			'_bgt.modules.output_panel': types.SimpleNamespace(OutputPanel=object),
			'_bgt.modules.output_panel_terminus': types.SimpleNamespace(TerminusOutputPanel=Terminal),
		}
		modules['_bgt'].__path__ = []
		modules['_bgt.modules'].__path__ = []
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)

		spec = importlib.util.spec_from_file_location('_bgt.modules.tasks', ROOT / 'modules' / 'tasks.py')
		module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = module
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		spec.loader.exec_module(module)
		self.tasks = module.Tasks()

	def run_task(self, background, error=None):
		async def scenario():
			running = self.tasks.run(Mock(), Task('clean up', background))
			await asyncio.sleep(0)
			terminal = Terminal.created[-1]
			if error:
				terminal.future.set_exception(error)
			else:
				terminal.future.set_result(None)
			try:
				await running
			except RuntimeError:
				pass
			await asyncio.sleep(0)
			await asyncio.sleep(0)
			return terminal

		return self.loop.run_until_complete(scenario())

	def test_a_background_task_that_succeeds_leaves_no_terminal_behind(self):
		terminal = self.run_task(background=True)

		# it never took the panel, and it is gone
		self.assertFalse(terminal.show_panel)
		self.assertTrue(terminal.in_background)
		terminal.dispose.assert_called_once()
		self.assertEqual(self.tasks.tasks, [])

	def test_a_background_task_that_fails_stays_to_be_read(self):
		terminal = self.run_task(background=True, error=RuntimeError('process is terminated with return code 1.'))

		terminal.dispose.assert_not_called()
		self.assertEqual(len(self.tasks.tasks), 1)

	def test_a_task_that_is_waited_for_keeps_its_terminal(self):
		terminal = self.run_task(background=False)

		self.assertTrue(terminal.show_panel)
		self.assertFalse(terminal.in_background)
		terminal.dispose.assert_not_called()
		self.assertEqual(len(self.tasks.tasks), 1)


if __name__ == '__main__':
	unittest.main()
