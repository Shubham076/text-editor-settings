from __future__ import annotations
from typing import TYPE_CHECKING, Any, Awaitable

from . import core
from . import dap
from . import ui

from .output_panel import OutputPanel
from .task_runtimes import TaskRuntime, ShellTaskRuntime, BackgroundShellTaskRuntime, SublimeTaskRuntime
from .task_runtime_ready import ReadyShellTaskRuntime

if TYPE_CHECKING:
	from .debugger import Debugger

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
	async def run(self, debugger: Debugger, task: dap.TaskExpanded, is_terminal: bool = False, owner: Any = None):
		'''Runs a task and returns when whoever asked can go on: at its end, at once for a background
		task, and at its ready signal for one that has a `ready_regex`

		`owner` is the session it is run for. A task with a ready signal is kept running for its
		owners and stopped when the last of them is gone, see `release`.
		'''
		# if there is already an existing task we wait on it to finish and do not start a new task
		# this matches the behavior of vscode?
		for t in list(self.tasks):
			if t.task.name != task.name:
				continue

			if isinstance(t, ReadyShellTaskRuntime):
				# one that was stopped, or ended by itself, is in the way of the one about to start:
				# its tab has the name the new one is about to take
				if t.released or t.is_finished():
					self.cancel(t)
					continue

				# already up, for another session: this one waits for the same signal and shares it
				if owner is not None:
					t.owners.add(owner)
				console = self.console_of(debugger, owner)
				console.info(f'{task.name} is already running, waiting for it to be ready')
				await t.wait_ready()
				console.info(f'{task.name} is ready: {t.ready_line}')
				return

			if not t.is_finished():
				debugger.console.info('This task has already been started')
				if not t.task.background:
					await t.wait()
				return

			# one that ended is in the way of the one about to start, as above: its tab is taken
			# away so the task has one tab, the one of its last run, and not one for every run
			self.cancel(t)

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
					await self.run(debugger, depends_on_task_expanded, owner=owner)

			else:
				depends_on_tasks_expanded: list[Awaitable[None]] = []
				for depends_on_name in depends_on:
					depends_on_task = debugger.project.get_task(depends_on_name)
					depends_on_task_expanded = await depends_on_task.Expanded(task.variables)
					depends_on_tasks_expanded.append(self.run(debugger, depends_on_task_expanded, owner=owner))

				await core.gather(*depends_on_tasks_expanded)

		except dap.Error as error:
			raise dap.Error(f'Unable to resolve depends_on: {error}')

		ready: ReadyShellTaskRuntime | None = None

		if type == 'shell' and task.ready_regex and not is_terminal:
			runtime = ready = ReadyShellTaskRuntime(debugger, task)
			if owner is not None:
				ready.owners.add(owner)
			ready.get_panel().on_opened_status = lambda: self.on_options(runtime)
		elif type == 'shell' and task.background and not is_terminal:
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
			except BaseException:
				# one with a ready signal ends by being stopped, at the end of every session it was
				# started for. Its own runtime says so when that was not meant (`watch_end`)
				if not ready:
					raise
			finally:
				self.updated(runtime)

				# a background task that did what it was for is not kept either, one that failed is
				# until the next start so it can still be seen among the tasks. One with a ready
				# signal has a tab that is still worth reading, however it ended
				if succeeded and task.background and not ready:
					self.cancel(runtime)

		update_when_done()

		if ready:
			console = self.console_of(debugger, owner)
			console.info(f'Waiting for {task.name} to be ready: a line of its output matching {task.ready_regex!r}')
			await ready.wait_ready()
			console.info(f'{task.name} is ready: {ready.ready_line}')
		elif not task.background:
			await runtime.wait()

	def console_of(self, debugger: Debugger, owner: Any) -> Any:
		'''Where what happens to a task is said: the console of the session it runs for, else the debuggers'''
		return getattr(owner, 'console', None) or debugger.console

	def release(self, owner: Any) -> None:
		'''A session has ended: the tasks that were only running for it are stopped

		Only those with a ready signal have owners. A server started as the `pre_debug_task` of two
		configurations of a compound goes on for as long as either of them is running.
		'''
		for task in self.tasks:
			if not isinstance(task, ReadyShellTaskRuntime) or owner not in task.owners:
				continue

			task.owners.discard(owner)
			if task.owners and not task.is_finished():
				# said where it was said to be ready, so that console does not end on a task that
				# is neither stopped nor accounted for
				others = ', '.join(sorted(str(getattr(other, 'name', other)) for other in task.owners))
				if console := getattr(owner, 'console', None):
					console.info(f'{task.task.name} keeps running for {others}')
			if not task.owners:
				# in the console of the session that ended, which is the one being looked at
				name = getattr(owner, 'name', None) or 'the session it was started for'
				task.stop(f'{name} ended', getattr(owner, 'console', None))
				self.updated(task)

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
