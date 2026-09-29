from __future__ import annotations
from typing import TYPE_CHECKING

from .. import dap

if TYPE_CHECKING:
	from ..debugger import Debugger


def root_of(session: dap.Session) -> dap.Session:
	'''The session a configuration was started as, which is what a child was started from'''
	while session.parent:
		session = session.parent

	return session


class SessionScope:
	'''Which session a view renders

	A scope without a session follows the debuggers active session, which is what every view did back
	when there was only ever one place to render. A scope with a session renders that session whatever
	is active, which is what makes a session tab a container rather than a filter over a shared view.

	Child sessions belong to the scope of their parent. They are rendered nested by `CallstackView` and
	they are never given a tab of their own, so an event about a child has to reach the parents scope.
	'''

	def __init__(self, debugger: Debugger, session: dap.Session | None = None, active_only: bool = False) -> None:
		self.debugger = debugger
		self.session = session

		# render the selected session rather than every one at once, so picking a configuration out of the
		# dropdown changes what the callstack is about
		self.active_only = active_only

	@property
	def current(self) -> dap.Session | None:
		'''The session whose frame and variables should be shown'''
		if self.session:
			return self.session

		if self.active_only:
			from .. import configurations

			sessions = self.sessions
			current = self.debugger.session
			if current and root_of(current) in sessions:
				return current
			return configurations.selected(self.debugger) or (sessions[0] if sessions else None)

		return self.debugger.session

	@property
	def sessions(self) -> list[dap.Session]:
		'''The sessions to render, roots only, children are rendered by their parent'''
		if self.session:
			return [self.session]

		if self.active_only:
			from .. import configurations

			selection = self.debugger.project.configuration_or_compound
			if isinstance(selection, dap.ConfigurationCompound):
				return [session for session in self.debugger.sessions if not session.parent and session.configuration.name in selection.configurations]
			selected = configurations.selected(self.debugger)
			return [root_of(selected)] if selected else []

		return [session for session in self.debugger.sessions if not session.parent]

	def contains(self, session: dap.Session) -> bool:
		'''Whether an event about `session` is about something this scope renders'''
		if not self.session:
			return True

		current: dap.Session | None = session
		while current:
			if current is self.session:
				return True
			current = current.parent

		return False
