from __future__ import annotations
from typing import ClassVar

import base64
import re

import sublime
import sublime_plugin

from . import configurations
from . import core
from . import ui

from .settings import Settings
from .ui.view import lightness_from_color

# how big the icon is drawn, in the views own font size so it matches the line it sits on
ICON_SIZE = '1.1rem'

ACTION_SETTINGS = 'settings'
ACTION_RUN = 'run'
ACTION_STOP = 'stop'

# the phantom key `ui.RawPhantom` adds its phantoms under
PHANTOM_KEY = 'debugger'


class ProjectButtons(core.Dispose):
	'''Clickable icons on the configurations of a `.sublime-project` file

	The configurations are written down in a file the user has open, one object each with a name. An
	icon beside each is the shortest path there is from wanting to run one to running it, and it is
	where the eye already is when adding one.

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
		# (phantom, icon file, href) for each icon on the file, in file order
		self.phantoms: list[tuple[ui.RawPhantom, str, str]] = []
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
		for phantom, _, _ in self.phantoms:
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

		wanted: list[tuple[int, str, str]] = []
		targets: list[str] = []

		if region := self.view.find(r'"\s*debugger_configurations\s*"', 0):
			wanted.append((self.view.line(region).begin(), self.file(ui.Images.shared.settings), ACTION_SETTINGS))

		running = configurations.running(debugger)

		for name in configurations.names(debugger):
			# located by name rather than by parsing, the names come from the project the file was loaded
			# into so they are the ones that would actually start
			region = self.view.find(r'"\s*name\s*"\s*:\s*"' + re.escape(name) + r'"', 0)
			if not region:
				continue

			is_running = name in running
			image = ui.Images.shared.stop if is_running else ui.Images.shared.play

			# the href carries an index into `targets` rather than the name itself: a name can hold
			# spaces or quotes, which an html attribute would not survive
			wanted.append((self.view.line(region).begin(), self.file(image), f'{ACTION_STOP if is_running else ACTION_RUN}:{len(targets)}'))
			targets.append(name)

		if wanted == self.current() and targets == self.targets:
			return

		self.clear()
		self.targets = targets

		for at, file, href in wanted:
			self.add(at, file, href)

	def current(self) -> list[tuple[int, str, str]] | None:
		'''What is drawn right now, in the same shape as `render()` wants it, or None if any icon is gone'''
		items: list[tuple[int, str, str]] = []

		for phantom, file, href in self.phantoms:
			regions = self.view.query_phantom(phantom.pid)
			if not regions:
				return None

			items.append((regions[0].a, file, href))

		return items

	def add(self, at: int, file: str, href: str) -> None:
		# at the head of the line rather than on the match, so every icon lines up down the left edge
		html = f'<body><a href="{href}"><img style="width:{ICON_SIZE};height:{ICON_SIZE}" src="{self.data(file)}"></a></body>'

		self.phantoms.append((ui.RawPhantom(self.view, sublime.Region(at), html, on_navigate=self.navigate), file, href))

	def file(self, image: ui.Image) -> str:
		'''The icon file for this views background

		`Image.data()` picks between the two by the luminocity of a layout and a phantom has none, so
		make the same choice against the background the view is actually drawn on.
		'''
		style = self.view.style()
		background = style.get('background') if style else None

		return image.file_light if lightness_from_color(background) < 0.5 else image.file_dark

	def data(self, file: str) -> str:
		png = sublime.load_binary_resource(file)

		return f'data:image/png;base64,{base64.b64encode(png).decode("ascii")}'

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
			configurations.start(debugger, name)

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
		ProjectButtons.refresh(view)

	def on_close(self, view: sublime.View) -> None:
		if buttons := ProjectButtons.views.get(view.id()):
			buttons.dispose()
