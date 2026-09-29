from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable

import sublime

from . import core
from . import dap
from . import ui

if TYPE_CHECKING:
	from .debugger import Debugger


def names(debugger: Debugger) -> list[str]:
	'''Every configuration and compound that can be started, in the order the project lists them'''
	project = debugger.project

	return [item.name for item in (*project.compounds, *project.configurations)]


def running(debugger: Debugger) -> set[str]:
	return {_root(session).configuration.name for session in debugger.sessions}


def _root(session: dap.Session) -> dap.Session:
	while getattr(session, 'parent', None):
		session = session.parent
	return session


def session_for_names(debugger: Debugger, names) -> dap.Session | None:
	'''The best session in the trees started by these configurations

	Adapters such as js-debug can create child sessions. The root can keep reporting Running while a
	child is paused at a breakpoint, so selecting the first name match discards the stopped frame.
	Prefer the current paused child, then any paused session in the matching trees, then the current
	matching session, and finally a root.
	'''
	names = set(names)
	sessions = [session for session in debugger.sessions if _root(session).configuration.name in names]
	current = debugger.session
	if current in sessions and current.is_paused:
		return current
	if paused := next((session for session in sessions if session.is_paused), None):
		return paused
	if current in sessions:
		return current
	return next((session for session in sessions if not getattr(session, 'parent', None)), None) or (sessions[0] if sessions else None)


def session_for(debugger: Debugger, name: str) -> dap.Session | None:
	'''The active or paused session in a configuration's session tree, if it is running'''
	return session_for_names(debugger, (name,))


def selected(debugger: Debugger) -> dap.Session | None:
	'''The session of the selected configuration, or None when it is not running

	What the whole ui is about. The debugger keeps an active session, which is whichever one started or
	stopped last, and that is not the same question: selecting a configuration that is not running has to
	mean an empty callstack rather than somebody else's.
	'''
	selection = debugger.project.configuration_or_compound
	if isinstance(selection, dap.ConfigurationCompound):
		return session_for_names(debugger, selection.configurations)
	return session_for(debugger, debugger.project.name)


def selected_console(debugger: Debugger):
	'''The console of the selected configuration, or the debuggers own when it has never run

	Keyed by the configuration rather than by its session, so the output of the last run is still what
	is shown after it has ended.
	'''
	selection = debugger.project.configuration_or_compound

	if selection and debugger.session_panels:
		if panels := debugger.session_panels.panels_for_configuration(selection.id_ish):
			return panels.console

	return debugger.console


def select(debugger: Debugger, name: str) -> None:
	'''Makes a configuration the one the debugger bar is about

	The bar runs, restarts and stops whichever configuration is selected, so selecting is the whole job
	here. If that configuration is running, the callstack, the variables and its console follow, which
	is what makes picking one out of the list mean something while several are going at once.
	'''
	debugger.project.load_configuration(name)

	if session := selected(debugger):
		debugger.current_session = session
		debugger.open_session_output(session)


STATUS_ORDER = {'Paused': 0, 'Running': 1, 'Stopped': 2}


def status_of(debugger: Debugger, item: dap.Configuration | dap.ConfigurationCompound) -> str:
	'''Paused, Running or Stopped: what the sessions a configuration started are doing

	A starting session counts as Running: the list has only these three bands.
	'''
	if isinstance(item, dap.ConfigurationCompound):
		session = session_for_names(debugger, item.configurations)
	else:
		session = session_for(debugger, item.name)

	if not session:
		return 'Stopped'
	return 'Paused' if session.is_paused else 'Running'


def description_of(item: dap.Configuration | dap.ConfigurationCompound) -> str:
	'''The line under a configuration's name in a list

	Only the adapter type and request: program paths, modules, urls and arguments make the rows very
	wide and can carry private details, so they stay out of the list.
	'''
	if isinstance(item, dap.ConfigurationCompound):
		count = len(item.configurations)
		return '{} configuration{}'.format(count, '' if count == 1 else 's')
	return ' · '.join(str(value) for value in (item.type, item.request) if value)


def ordered(debugger: Debugger) -> list[tuple[dap.Configuration | dap.ConfigurationCompound, str]]:
	'''Every compound and configuration with its status: paused first, then running, then stopped, then by name'''
	rows = [(item, status_of(debugger, item)) for item in (*debugger.project.compounds, *debugger.project.configurations)]
	return sorted(rows, key=lambda row: (STATUS_ORDER[row[1]], row[0].name.casefold(), row[0].name))


def status_kind(status: str, selected: bool) -> tuple[int, str, str]:
	'''The badge of a quick panel row: the only colour a row can carry

	A letter in a coloured square, drawn by sublime from a `kind`: yellow while paused, green while
	running, plain otherwise. The selected configuration shows the checked sigil in that same colour
	so the status is never hidden by the selection mark. It cannot be pressed, which is why stopping
	and restarting stay on the bar where there are real buttons.
	'''
	colors = {'Paused': sublime.KIND_ID_COLOR_YELLOWISH, 'Running': sublime.KIND_ID_COLOR_GREENISH}
	letters = {'Paused': '\u2016', 'Running': '\u25b6'}
	letter = core.platform.unicode_checked_sigil if selected else letters.get(status, '\u25cb')
	return (colors.get(status, sublime.KIND_ID_AMBIGUOUS), letter, status)


def items(debugger: Debugger, select: Callable[[Any], Any]) -> tuple[list[ui.InputListItem], int | None]:
	'''The configuration rows of a quick panel, and the index of the selected one

	`select` is called with the compound or configuration that was picked. The status is the badge
	and the annotation, the adapter type and request the detail line; alt-enter opens the source.
	Only to choose: running, restarting and stopping are buttons on the debugger bar, and a list that
	also did those would be a second place to do the same things with no way to tell which one is in
	charge.
	'''
	selection = debugger.project.configuration_or_compound
	# `is not None`: a configuration is a dict, and an empty one is still a selection
	selected_id = selection.id_ish if selection is not None else None
	rows: list[ui.InputListItem] = []
	index = None
	for item, status in ordered(debugger):
		selected = item.id_ish == selected_id
		if selected:
			index = len(rows)
		rows.append(ui.InputListItem(
			lambda item=item: select(item),
			item.name,
			annotation=status,
			details=description_of(item),
			kind=status_kind(status, selected),
			run_alt=lambda item=item: item.source and item.source.open_file(),
		))
	return rows, index


# how long to wait for a session to actually end before starting it again, and how often to look
RESTART_TIMEOUT = 5.0
RESTART_POLL = 0.05


@core.run
async def restart(debugger: Debugger, name: str) -> None:
	'''Stops what a configuration is running as, then starts it again

	`Session.stop()` asks the adapter to end, `Debugger.remove_session()` is what takes the session off
	the list, and those are not the same moment. Starting again in between is refused as running the same
	configuration twice, so wait for the list rather than for the request.
	'''
	try:
		compound = next((item for item in debugger.project.compounds if item.name == name), None)
		names = compound.configurations if compound else [name]
		sessions = [session for session in debugger.sessions if not session.parent and session.configuration.name in names]
		for session in sessions:
			await debugger.stop(session)

		for _ in range(int(RESTART_TIMEOUT / RESTART_POLL)):
			if not any(session in debugger.sessions for session in sessions):
				break
			await core.delay(RESTART_POLL)
		else:
			raise dap.Error('Timed out waiting for the previous session to stop')

		await debugger.start(args={'configuration': name})

	except dap.Error as e:
		debugger.console.error(f'Unable to restart {name}: {e}')


@core.run
async def start(debugger: Debugger, name: str) -> None:
	'''Starts a configuration by name without changing which one the run button starts'''
	try:
		await debugger.start(args={'configuration': name})
	except dap.Error as e:
		debugger.console.error(f'Unable to start {name}: {e}')
