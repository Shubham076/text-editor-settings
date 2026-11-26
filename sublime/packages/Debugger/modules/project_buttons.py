from __future__ import annotations
from typing import ClassVar, Tuple

import re

import sublime
import sublime_plugin

from . import configurations
from . import core
from . import ui

from .settings import Settings
from .ui.icons import icon_data_uri
from .ui.view import lightness_from_color

# how big the icon is drawn, in the views own font size so it matches the line it sits on
ICON_SIZE = '1.1rem'

ACTION_SETTINGS = 'settings'
ACTION_RUN = 'run'
ACTION_STOP = 'stop'

# The icons are drawn, in the colour the text of the file is. They were files once, a black shape
# and a white one to choose between, and black on a scheme whose text is a soft grey-green is the
# loudest thing on the line. An icon is named `name:colour`, which is also what says it has to be
# drawn again when the scheme changes
DRAWN_SIZE = 48
# when a scheme does not say what colour its text is in a way that can be read
DRAWN_ON_DARK = '#ffffff'
DRAWN_ON_LIGHT = '#000000'

# an icon and what a click on it does
Icon = Tuple[str, str]

# the phantom key `ui.RawPhantom` adds its phantoms under
PHANTOM_KEY = 'debugger'


class ProjectButtons(core.Dispose):
	'''Clickable icons on the configurations of a `.sublime-project` file

	The configurations are written down in a file the user has open, one object each with a name. An
	icon beside each is the shortest path there is from wanting to run one to running it, and it is
	where the eye already is when adding one.

	Play runs a configuration without the debugger, which is the quick way to see it work, and makes
	it the selection of the bar, where the bug debugs it. While it runs the icon is a stop.

	They are phantoms rather than gutter icons. A gutter icon is what this wants to be and Sublime will
	draw one, `add_regions(icon=...)`, but there is no event for a click on the gutter, so it could only
	ever be decoration. A phantom sits at the head of the line instead, which shifts the line right by
	the width of the icon and is the closest thing to a gutter that can be pressed.

	A click on a phantom reaches the plugin as two events: the view is activated first, then the link
	navigates. Redrawing on activation used to erase the phantom that was clicked before its navigate
	arrived, and Sublime drops a navigate for a phantom that no longer exists, so the first click into
	the file did nothing. `render()` therefore only touches the phantoms when what they show changed.
	'''

	views: ClassVar[dict[int, ProjectButtons]] = {}

	@staticmethod
	def refresh(view: sublime.View) -> None:
		file = view.file_name()
		if not file or not file.endswith('.sublime-project'):
			return

		buttons = ProjectButtons.views.get(view.id()) or ProjectButtons(view)
		buttons.render()

	@staticmethod
	def reload_found_project(view: sublime.View) -> None:
		'''Reads a saved project file again when it is one the debugger found in a folder

		Sublime says when the project a window has open was saved. It says nothing of a project file
		that is only in a folder of the window, so a save of that one is noticed here.
		'''
		from .debugger import Debugger

		file = view.file_name()
		window = view.window()
		if not file or not window or not file.endswith('.sublime-project') or window.project_file_name():
			return

		debugger = Debugger.get(window)
		if debugger and debugger.project.location == file:
			debugger.project_or_settings_updated()

	@staticmethod
	def refresh_all() -> None:
		'''Redraws every open project file, an icon shows whether its configuration is running'''
		for window in sublime.windows():
			for view in window.views():
				ProjectButtons.refresh(view)

	@staticmethod
	def dispose_all() -> None:
		'''Takes every icon off every file, for when the plugin unloads'''
		for buttons in list(ProjectButtons.views.values()):
			buttons.dispose()

	def __init__(self, view: sublime.View) -> None:
		super().__init__()
		self.view = view
		# (phantom, its icons) for each place on the file that has icons, in file order
		self.phantoms: list[tuple[ui.RawPhantom, tuple[Icon, ...]]] = []
		# the configuration a run/stop href points at, by the index carried in the href
		self.targets: list[str] = []

		# icons a previous instance of the plugin left behind (a reload without an unload hook, or a
		# crash) would otherwise stack up under the new ones; the file has no other debugger phantoms
		view.erase_phantoms(PHANTOM_KEY)

		ProjectButtons.views[view.id()] = self

	def dispose(self) -> None:
		super().dispose()
		self.clear()
		ProjectButtons.views.pop(self.view.id(), None)

	def clear(self) -> None:
		for phantom, _ in self.phantoms:
			phantom.dispose()

		self.phantoms.clear()
		self.targets.clear()

	def render(self) -> None:
		from .debugger import Debugger

		window = self.view.window()
		debugger = Debugger.get(window) if window else None

		if not debugger or not Settings.project_file_buttons:
			self.clear()
			return

		wanted: list[tuple[int, tuple[Icon, ...]]] = []
		targets: list[str] = []

		if region := self.view.find(r'"\s*debugger_configurations\s*"', 0):
			wanted.append((self.view.line(region).begin(), ((self.drawn('settings'), ACTION_SETTINGS),)))

		running = configurations.running(debugger)

		for name in configurations.names(debugger):
			# located by name rather than by parsing, the names come from the project the file was loaded
			# into so they are the ones that would actually start
			region = self.view.find(r'"\s*name\s*"\s*:\s*"' + re.escape(name) + r'"', 0)
			if not region:
				continue

			# the href carries an index into `targets` rather than the name itself: a name can hold
			# spaces or quotes, which an html attribute would not survive
			wanted.append((self.view.line(region).begin(), self.icons(name in running, len(targets))))
			targets.append(name)

		if wanted == self.current() and targets == self.targets:
			return

		self.clear()
		self.targets = targets

		for at, icons in wanted:
			self.add(at, icons)

	def icons(self, is_running: bool, index: int) -> tuple[Icon, ...]:
		'''The icon of the thing `targets[index]` starts: a stop while it runs, otherwise a play'''
		if is_running:
			return ((self.drawn('stop-filled'), f'{ACTION_STOP}:{index}'),)

		return ((self.drawn('run-filled'), f'{ACTION_RUN}:{index}'),)

	def current(self) -> list[tuple[int, tuple[Icon, ...]]] | None:
		'''What is drawn right now, in the same shape as `render()` wants it, or None if any icon is gone'''
		items: list[tuple[int, tuple[Icon, ...]]] = []

		for phantom, icons in self.phantoms:
			regions = self.view.query_phantom(phantom.pid)
			if not regions:
				return None

			items.append((regions[0].a, icons))

		return items

	def add(self, at: int, icons: tuple[Icon, ...]) -> None:
		# at the head of the line rather than on the match, so every icon lines up down the left edge
		links = ''.join(
			f'<a href="{href}"><img style="width:{ICON_SIZE};height:{ICON_SIZE}" src="{self.data(file)}"></a>'
			for file, href in icons)

		self.phantoms.append((ui.RawPhantom(self.view, sublime.Region(at), f'<body>{links}</body>', on_navigate=self.navigate), icons))

	def colour(self) -> str:
		'''The colour of the text of this view, as `#rrggbb`'''
		style = self.view.style() or {}
		foreground = str(style.get('foreground') or '')

		# `#rrggbb`, or `#rrggbbaa` with an opacity that an icon this small is better off without
		if re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?', foreground):
			return foreground[:7].lower()

		return DRAWN_ON_DARK if lightness_from_color(style.get('background')) < 0.5 else DRAWN_ON_LIGHT

	def drawn(self, name: str) -> str:
		'''An icon by name, in the colour of the text of this view'''
		return f'{name}:{self.colour()}'

	def data(self, icon: str) -> str:
		name, _, colour = icon.partition(':')
		return icon_data_uri(name, colour, DRAWN_SIZE)

	@core.run
	async def navigate(self, href: str) -> None:
		from .commands.commands import ChangeConfiguration
		from .debugger import Debugger

		window = self.view.window()
		debugger = Debugger.get(window) if window else None
		if not debugger:
			return

		action, _, index = href.partition(':')

		if action == ACTION_SETTINGS:
			# the quick panel with the configurations and the debugger's actions; the toolbar gear
			# opens the same one
			debugger.run_action(ChangeConfiguration)
			return

		if not index.isdigit() or int(index) >= len(self.targets):
			return

		name = self.targets[int(index)]

		if action == ACTION_RUN:
			configurations.start(debugger, name, no_debug=True)

		elif action == ACTION_STOP:
			if session := configurations.session_for(debugger, name):
				await debugger.stop(session)


def refresh_all() -> None:
	ProjectButtons.refresh_all()


class DebuggerProjectFileListener(sublime_plugin.EventListener):
	def on_load(self, view: sublime.View) -> None:
		ProjectButtons.refresh(view)

	def on_activated(self, view: sublime.View) -> None:
		# a click into the file activates it first; render() leaves unchanged icons alone so the
		# clicked one is still there when its navigate arrives
		ProjectButtons.refresh(view)

	def on_post_save(self, view: sublime.View) -> None:
		ProjectButtons.reload_found_project(view)
		ProjectButtons.refresh(view)

	def on_close(self, view: sublime.View) -> None:
		if buttons := ProjectButtons.views.get(view.id()):
			buttons.dispose()
