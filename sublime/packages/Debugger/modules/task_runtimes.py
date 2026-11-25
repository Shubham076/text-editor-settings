'''What a task is run as: in a terminal, as a plain process, or as a command of the editor

`Tasks` (`tasks.py`) decides which and keeps the list, a task that says when it is ready has a
runtime of its own (`task_runtime_ready.py`).
'''

from __future__ import annotations
from typing import TYPE_CHECKING, Any

from . import core
from . import dap

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
