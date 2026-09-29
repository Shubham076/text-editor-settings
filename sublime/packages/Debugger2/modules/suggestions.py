from __future__ import annotations
from typing import TYPE_CHECKING

from . import core
from . import ui

if TYPE_CHECKING:
	from .debugger import Debugger


class Suggestions(core.Dispose):
	'''Warns in the debug console when Debugger runs without a Sublime project

	That is the one situation where something the user needs to know is not visible anywhere else.
	The old "Getting Started" and "Suggested Packages" groups are gone: the debug console is where
	expressions are evaluated and adapter messages land, and a help text sitting above the prompt read
	as noise. Example projects and the setup guide remain in the command palette.
	'''

	def __init__(self, debugger: Debugger) -> None:
		self.debugger = debugger
		self.warned = False
		self.dispose_add(debugger.on_project_or_settings_updated.add(self.refresh))

	def refresh(self):
		console = self.debugger.console

		if console.window.project_file_name():
			# the warning, if it was written, is stale now that a project is open
			if self.warned:
				self.warned = False
				console.clear()
			return

		console.clear()
		self.warned = True
		console.error(f'{core.platform.unicode_checked_sigil} Beware using Debugger outside of a Sublime project has limited functionality')

		console.log(
			'warn',
			'\t- Would you like to create a Sublime Project? ',
			html=ui.Html('<a href="">[Save As Project]</a>', lambda _: (console.window.run_command('save_project_and_workspace_as'), console.debugger.project_or_settings_updated())),
		)
		console.log(
			'warn',
			'\t- Or open an existing project? ',
			html=ui.Html('<a href="">[Open Project]</a>', lambda _: console.window.run_command('prompt_open_project_or_workspace')),
		)
		console.info('\n')
