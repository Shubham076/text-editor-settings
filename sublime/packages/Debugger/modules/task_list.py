'''The tasks of a project as the rows of a quick panel, for the tasks button of the bar and `Run Task`

The same shape as the list of configurations (`configurations.items`): what is running comes
first with a green badge, each row says what it runs, and the list opens on the task that was
run last, so running it again is the button and enter.
'''

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable

from . import configurations
from . import ui

if TYPE_CHECKING:
	from .debugger import Debugger

RUNNING = 'Running'
STOPPED = 'Stopped'


def runtime_of(debugger: Debugger, name: str) -> Any:
	'''What a task is running as right now, `None` when it is not running'''
	for runtime in debugger.tasks.tasks:
		if runtime.task.name == name and not runtime.is_finished():
			return runtime
	return None


def description_of(task: Any) -> str:
	'''What a task runs, on the line under its name'''
	if task.get('type') == 'sublime':
		return str(task.get('command') or '')

	command = task.get('shell_cmd') or task.get('cmd') or ''
	if isinstance(command, list):
		command = ' '.join(str(part) for part in command)

	notes = []
	if task.get('ready_regex'):
		notes.append('waits until ready')
	elif task.get('background'):
		notes.append('background')

	return ' · '.join([str(command), *notes]) if command else ' · '.join(notes)


def ordered(debugger: Debugger, tasks: list[Any]) -> list[tuple[Any, str]]:
	'''The tasks with what each is doing, the running ones first and otherwise as the project lists them

	A task that is listed twice, in the project and in the settings, is the first of the two:
	that is the one a `pre_debug_task` of that name would run.
	'''
	seen: set[str] = set()
	rows: list[tuple[Any, str]] = []
	for task in tasks:
		if task.name in seen:
			continue
		seen.add(task.name)
		rows.append((task, RUNNING if runtime_of(debugger, task.name) else STOPPED))

	return [row for row in rows if row[1] == RUNNING] + [row for row in rows if row[1] != RUNNING]


def items(debugger: Debugger, tasks: list[Any], run: Callable[[Any], Any], last: str | None = None) -> tuple[list[ui.InputListItem], int]:
	'''The rows, and the index the list opens on: the task that was run last

	`run` is called with a task that is not running. One that is running is shown instead, in the
	tab it runs in: starting it a second time would only say it has already been started, and its
	tab is where it is stopped from. Alt-enter opens the task where it is defined.
	'''
	rows: list[ui.InputListItem] = []
	index = 0

	for task, status in ordered(debugger, tasks):
		if task.name == last:
			index = len(rows)

		def pick(task: Any = task):
			runtime = runtime_of(debugger, task.name)
			panel = runtime.get_panel() if runtime else None
			if panel:
				panel.open()
			elif not runtime:
				run(task)

		rows.append(ui.InputListItem(
			pick,
			task.name,
			annotation=status,
			details=description_of(task),
			kind=configurations.status_kind(status, False),
			run_alt=lambda task=task: task.source and task.source.open_file(),
		))

	return rows, index
