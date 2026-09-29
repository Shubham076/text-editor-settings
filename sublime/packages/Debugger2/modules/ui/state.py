from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

import sublime

from .. import core, dap

if TYPE_CHECKING:
	from .panel import PanelUI


@dataclass
class ViewState:
	# the sections, the top-level scopes (`scope:Locals`) and the variable rows the user opened, by
	# name path (`scope:Locals/settings/policy`, `watch:expr/field`), so they survive a step; see
	# `VariablesPane.scope_key` for when the paths are forgotten
	expanded: set[str | int] = field(default_factory=lambda: {'breakpoints', 'thread', 'watch', 'variables'})
	# scopes that have been given their default expansion once (`VariablesPane.scope_key`)
	scopes_seen: set[str] = field(default_factory=set)
	compact: bool = False
	tab: str = 'console'


def session_status(session):
	if not session:
		return 'Stopped'
	if session.is_paused:
		return 'Paused'
	if session.is_running:
		return 'Running'
	return session.state.status or 'Starting'


class TreeData:
	def __init__(self, ui: PanelUI):
		self.ui = ui
		self.revision = 0
		self.cache: dict[int, list[Any] | str] = {}
		self.pending: set[int] = set()
		self.owners: dict[int, Any] = {}

	def reset(self):
		self.revision += 1
		self.cache.clear()
		self.pending.clear()
		self.owners.clear()

	def get(self, item):
		key = id(item)
		self.owners[key] = item
		if key not in self.cache and key not in self.pending:
			self.pending.add(key)
			sublime.set_timeout(partial(self.fetch, item, self.revision))
		return self.cache.get(key)

	@core.run
	async def fetch(self, item, revision):
		if self.ui.closed or revision != self.revision:
			return
		try:
			result = await item.children()
		except (dap.Error, core.CancelledError) as error:
			result = str(error) or 'No longer available'
		if not self.ui.closed and revision == self.revision:
			self.cache[id(item)] = result
			self.pending.discard(id(item))
			self.ui.invalidate()
