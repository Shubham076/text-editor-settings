from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Event:
	def __class_getitem__(cls, item):
		return cls

	def __call__(self, value):
		pass


class Terminal:
	created = []

	def __init__(self, debugger, task, is_terminal=False, show_panel=True):
		self.future = asyncio.get_event_loop().create_future()
		self.future.set_result(None)
		self.dispose = Mock()
		Terminal.created.append(self)

	async def wait(self):
		await self.future

	def is_finished(self):
		return self.future.done()


class Task(dict):
	def __init__(self, name, background, shell_cmd):
		super().__init__(shell_cmd=shell_cmd)
		self.name, self.background, self.type = name, background, 'shell'
		self.depends_on, self.depends_on_order, self.variables = None, None, {}
		self.ready_regex, self.ready_timeout = None, None


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
		core.run_in_executor = lambda function: (lambda *args: loop.run_in_executor(None, function, *args))
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

		# `tasks.py` and the files its runtimes are in, in the order they import each other
		for name in ('task_ready', 'task_runtimes', 'task_runtime_ready', 'tasks'):
			spec = importlib.util.spec_from_file_location(f'_bgt.modules.{name}', ROOT / 'modules' / f'{name}.py')
			module = importlib.util.module_from_spec(spec)
			sys.modules[spec.name] = module
			self.addCleanup(lambda name=spec.name: sys.modules.pop(name, None))
			spec.loader.exec_module(module)
		self.tasks = module.Tasks()

		self.folder = os.path.realpath(tempfile.mkdtemp())
		self.addCleanup(lambda: __import__('shutil').rmtree(self.folder, ignore_errors=True))
		self.debugger = types.SimpleNamespace(console=Mock(), window=types.SimpleNamespace(folders=lambda: [self.folder]))
		# whatever the users own shell is, a `shell_cmd` is not run by it
		environ = patch.dict(os.environ, {'SHELL': '/bin/zsh'})
		environ.start()
		self.addCleanup(environ.stop)

	def run_task(self, background, shell_cmd):
		async def scenario():
			await self.tasks.run(self.debugger, Task('clean up', background, shell_cmd))
			for _ in range(200):
				if all(task.is_finished() for task in self.tasks.tasks):
					break
				await asyncio.sleep(0.02)
			await asyncio.sleep(0.05)

		self.loop.set_exception_handler(lambda loop, context: None)
		self.loop.run_until_complete(scenario())

	def test_a_background_task_runs_in_the_project_without_a_terminal_and_leaves_nothing(self):
		open(os.path.join(self.folder, 'a.sublime-workspace'), 'w').close()

		self.run_task(True, 'rm -rf *.sublime-workspace')

		self.assertEqual(os.listdir(self.folder), [])
		# no panel was made, so there is none to open over what is being looked at or to take away again
		self.assertEqual(Terminal.created, [])
		self.assertEqual(self.tasks.tasks, [])
		self.debugger.console.error.assert_not_called()

	def test_a_pattern_that_matches_no_file_is_not_an_error(self):
		# what zsh makes of this is `no matches found` and exit code 1
		self.run_task(True, 'rm -rf *.sublime-workspace')

		self.debugger.console.error.assert_not_called()
		self.assertEqual(self.tasks.tasks, [])

	def test_a_background_task_that_fails_says_why_in_the_console(self):
		self.run_task(True, 'echo no such thing; exit 3')

		self.assertEqual(Terminal.created, [])
		self.debugger.console.error.assert_called_once_with('clean up ended with exit code 3\nno such thing')
		# kept among the tasks until the next start
		self.assertEqual(len(self.tasks.tasks), 1)

	def test_a_task_that_is_waited_for_still_gets_its_terminal(self):
		self.run_task(False, 'true')

		self.assertEqual(len(Terminal.created), 1)
		Terminal.created[0].dispose.assert_not_called()
		self.assertEqual(len(self.tasks.tasks), 1)


if __name__ == '__main__':
	unittest.main()
