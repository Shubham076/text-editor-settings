from __future__ import annotations
from typing import TYPE_CHECKING, Any, Awaitable

from . import core
from . import dap
from . import ui

import os
import subprocess

from .output_panel import OutputPanel
from .output_panel_terminus import TerminusOutputPanel

if TYPE_CHECKING:
	from .debugger import Debugger

class TaskRuntime(core.Dispose):
	def __init__(self, task: dap.TaskExpanded):
		self.task:dap.TaskExpanded = task

	async def run(self): ...
	async def wait(self): ...

	def is_finished(self) -> bool: ...
	def cancel(self): ...
	def dispose(self): ...

	def get_panel(self) -> OutputPanel | None: ...

class ShellTaskRuntime(TaskRuntime):
	def __init__(self, debugger: Debugger, task: dap.TaskExpanded, is_terminal: bool = False):
		super().__init__(task)
		self.terminal = TerminusOutputPanel(debugger, task, is_terminal)

	async def wait(self):
		await self.terminal.wait()

	def is_finished(self) -> bool:
		return self.terminal.is_finished()

	def cancel(self):
		self.terminal.kill_process()

	def dispose(self):
		self.terminal.dispose()

	def get_panel(self) -> OutputPanel:
		return self.terminal

class BackgroundShellTaskRuntime(TaskRuntime):
	'''A shell task that nothing waits for, run as a plain process with no terminal

	`"background": true` is how a task says it is housekeeping: the `post_debug_task` that removes a
	file once a session has ended. In a terminal, every stop of a configuration opened a panel over
	the one being looked at to say that `rm` ended with code 0. Creating that panel and taking it
	away again is still the panel changing twice under a click on stop. So there is no panel: the
	output is kept, and is only said, in the debuggers console, when the task fails.
	'''

	def __init__(self, debugger: Debugger, task: dap.TaskExpanded):
		super().__init__(task)
		self.debugger = debugger
		self.process: subprocess.Popen[bytes] | None = None
		self.finished = False
		self.cancelled = False

		# where a task runs when it does not say: the project, which is where a terminal started it
		folders = debugger.window.folders()
		self.cwd = task.get('working_dir') or task.get('cwd') or (folders[0] if folders else None)

		self.done = self.run()

	@core.run
	async def run(self) -> None:
		try:
			code, output = await self.execute()
		except Exception as error:
			code, output = -1, str(error)
		finally:
			self.finished = True

		if code and not self.cancelled:
			message = f'{self.task.name} ended with exit code {code}'
			self.debugger.console.error(f'{message}\n{output.rstrip()}' if output.strip() else message)
			raise dap.Error(message)

	@core.run_in_executor
	def execute(self) -> tuple[int, str]:
		task = self.task
		command: Any = task.get('shell_cmd') or task.get('cmd')
		if not command:
			raise dap.Error(f'{task.name} has no `shell_cmd` or `cmd` to run')

		if isinstance(command, str) and os.name != 'nt':
			# bash, which is what a `shell_cmd` is written for: it is what Sublime runs the one of a
			# build system with. The users own shell may read it differently, zsh refuses
			# `rm -rf *.tmp` outright when there is no such file, where bash goes on
			command = ['/usr/bin/env', 'bash', '-c', command]

		env = {**os.environ, **{key: str(value) for key, value in (task.get('env') or {}).items() if value is not None}}

		self.process = subprocess.Popen(command, shell=isinstance(command, str), cwd=self.cwd, env=env,
			stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
		output, _ = self.process.communicate()

		return self.process.returncode, output.decode('utf-8', 'replace')

	async def wait(self):
		await self.done

	def is_finished(self) -> bool:
		return self.finished

	def cancel(self):
		self.cancelled = True
		if self.process and self.process.poll() is None:
			self.process.terminate()

	def dispose(self):
		self.cancel()

	def get_panel(self) -> OutputPanel | None:
		return None


class SublimeTaskRuntime(TaskRuntime):
	def __init__(self, debugger: Debugger, task: dap.TaskExpanded):
		super().__init__(task)
		self.command:str = task['command']
		self.arguments:Any | None = task.get('args')

		debugger.window.run_command(self.command, self.arguments)

	async def wait(self):
		pass

	def is_finished(self) -> bool:
		return True

	def cancel(self):
		pass

	def dispose(self):
		pass

	def get_panel(self) -> OutputPanel | None:
		return None

class Tasks(core.Dispose):
	def __init__(self) -> None:
		self.added = core.Event[TaskRuntime]()
		self.removed = core.Event[TaskRuntime]()
		self.updated = core.Event[TaskRuntime]()
		self.tasks: list[TaskRuntime] = []

	def is_active(self):
		for task in self.tasks:
			if not task.is_finished():
				return True
		return False

	@core.run
	async def run(self, debugger: Debugger, task: dap.TaskExpanded, is_terminal: bool = False):
		# if there is already an existing task we wait on it to finish and do not start a new task
		# this matches the behavior of vscode?
		for t in self.tasks:
			if t.task.name == task.name and not t.is_finished():
				debugger.console.info('This task has already been started')
				if not t.task.background:
					await t.wait()
				return

		depends_on = task.depends_on
		sequence = task.depends_on_order == 'sequence'
		type = task.type

		if isinstance(depends_on, str):
			depends_on = [depends_on]
		elif isinstance(depends_on, list):
			depends_on = depends_on
		else:
			depends_on = []

		try:
			if sequence:
				for depends_on_name in depends_on:
					depends_on_task = debugger.project.get_task(depends_on_name)
					depends_on_task_expanded = await depends_on_task.Expanded(task.variables)
					await self.run(debugger, depends_on_task_expanded)

			else:
				depends_on_tasks_expanded: list[Awaitable[None]] = []
				for depends_on_name in depends_on:
					depends_on_task = debugger.project.get_task(depends_on_name)
					depends_on_task_expanded = await depends_on_task.Expanded(task.variables)
					depends_on_tasks_expanded.append(self.run(debugger, depends_on_task_expanded))

				await core.gather(*depends_on_tasks_expanded)

		except dap.Error as error:
			raise dap.Error(f'Unable to resolve depends_on: {error}')

		if type == 'shell' and task.background and not is_terminal:
			runtime = BackgroundShellTaskRuntime(debugger, task)
		elif type == 'shell':
			runtime = ShellTaskRuntime(debugger, task, is_terminal)
			runtime.get_panel().on_opened_status = lambda: self.on_options(runtime)
		elif type == 'sublime':
			runtime = SublimeTaskRuntime(debugger, task)
		else:
			raise dap.Error('Unknown command type')

		self.tasks.append(runtime)
		self.added(runtime)

		@core.run
		async def update_when_done():
			succeeded = False
			try:
				await runtime.wait()
				succeeded = True
			except:
				raise
			finally:
				self.updated(runtime)

				# a background task that did what it was for is not kept either, one that failed is
				# until the next start so it can still be seen among the tasks
				if succeeded and task.background:
					self.cancel(runtime)

		update_when_done()

		if not task.background:
			await runtime.wait()

	def get_running(self) -> list[TaskRuntime]:
		return [task for task in self.tasks if not task.is_finished()]

	def on_options(self, task: TaskRuntime):
		if task.is_finished():
			self.cancel(task)
			return

		options = ui.InputList('Kill task?')[ui.InputListItem(lambda: self.cancel(task), 'Kill'),]
		options.run()

	def remove_finished(self):
		remove_tasks = []
		for task in self.tasks:
			if task.is_finished():
				remove_tasks.append(task)

		for task in remove_tasks:
			self.cancel(task)

		return False

	def cancel(self, task: TaskRuntime):
		try:
			self.tasks.remove(task)
		except ValueError:
			return

		# todo actually cancel...
		self.removed(task)
		task.dispose()

	def dispose(self):
		while self.tasks:
			task = self.tasks.pop()
			self.removed(task)
			task.dispose()

	def get_panels(self) -> list[OutputPanel]:
		panels = [task.get_panel() for task in self.tasks]
		return [panel for panel in panels if panel is not None]
