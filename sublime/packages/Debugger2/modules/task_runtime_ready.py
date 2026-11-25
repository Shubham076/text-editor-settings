'''A background task that says when it is ready, see `task_ready`

It runs in a terminal of its own, a tab of the debugger like any other task, because what a
server prints is read long after it started. Whoever started it waits for the signal rather than
for the end, and it is stopped when the last session that started it is gone.
'''

from __future__ import annotations
from typing import TYPE_CHECKING, Any

from . import core
from . import dap
from . import task_ready

from .output_panel import OutputPanel
from .output_panel_terminus import TerminusOutputPanel
from .task_runtimes import TaskRuntime

if TYPE_CHECKING:
	from .debugger import Debugger


class ReadyShellTaskRuntime(TaskRuntime):
	def __init__(self, debugger: Debugger, task: dap.TaskExpanded):
		super().__init__(task)
		self.debugger = debugger

		try:
			self.pattern = task_ready.compile_pattern(task.ready_regex)
		except task_ready.ReadyError as error:
			raise dap.Error(f'{task.name}: {error}', source=task.source)

		self.timeout = task_ready.timeout_of(task.ready_timeout)

		# the sessions it was started for, it is stopped when the last of them ends (`Tasks.release`)
		self.owners: set[Any] = set()
		# stopped because nothing needs it any more: what it prints from here on is not an error,
		# and the next start of the task is a new one rather than this one found still running
		self.released = False

		self.ready: core.Future[None] = core.Future()

		# every width the terminal has had while it was read, which is what tells a row that was
		# wrapped from one that ended (`task_ready.unwrapped`)
		self.widths: set[int] = set()

		self.terminal = TerminusOutputPanel(debugger, task)
		self.terminal.on_text_changed = self.check

		self.watch_end()
		if self.timeout:
			self.watch_timeout(self.timeout)

	def check(self) -> None:
		'''Looks for the signal in what the terminal shows, called as it is written to'''
		if self.ready.done():
			return

		if columns := self.terminal.columns():
			self.widths.add(columns)

		if task_ready.ready_line(self.pattern, self.terminal.text(), self.widths) is None:
			return

		# nothing more to look for, and a terminal is written to for as long as the task runs
		self.terminal.on_text_changed = None
		self.ready.set_result(None)

	def fail(self, reason: str) -> None:
		if not self.ready.done():
			self.ready.set_exception(dap.Error(task_ready.not_ready(self.task.name, self.pattern, reason)))

	@core.run
	async def watch_end(self) -> None:
		error = ''
		try:
			await self.terminal.wait()
		except core.CancelledError:
			error = 'was cancelled'
		except Exception as e:
			error = str(e)

		if not self.ready.done():
			# the last thing it wrote may be the signal: a task that says it is ready and ends is ready
			self.check()
			self.fail('ended before it was ready')

		elif error and not self.released:
			# up, and then gone while something was still relying on it
			self.debugger.console.error(f'{self.task.name} ended while it was still needed: {error}')

	@core.run
	async def watch_timeout(self, timeout: float) -> None:
		await core.delay(timeout)
		if self.ready.done():
			return

		self.fail(f'was not ready after {timeout:g}s')
		self.terminal.kill_process()

	async def wait_ready(self) -> None:
		await self.ready

	async def wait(self) -> None:
		await self.terminal.wait()

	def is_finished(self) -> bool:
		return bool(self.terminal.is_finished())

	def stop(self) -> None:
		'''Nothing needs it any more: its process is ended, its tab stays to be read'''
		self.released = True
		self.terminal.on_text_changed = None

		# whoever is still waiting for the signal is told to stop waiting, not that it failed
		if not self.ready.done():
			self.ready.cancel()

		if not self.is_finished():
			self.terminal.kill_process()

	def cancel(self) -> None:
		self.stop()

	def dispose(self) -> None:
		self.terminal.on_text_changed = None
		if not self.ready.done():
			self.ready.cancel()
		self.terminal.dispose()

	def get_panel(self) -> OutputPanel:
		return self.terminal
