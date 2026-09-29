from __future__ import annotations
import sys

for module in list(filter(lambda module: module.startswith(f'{__package__}.') and module != __name__, sys.modules.keys())):
	del sys.modules[module]

from typing import Any, Set, cast
import sublime
import sublime_plugin

from .modules.core import asyncio


if sublime.version() < '4199':
	raise Exception('Debugger only supports Sublime Text version 4199 and later')

# remove old modules for this package so that they are reloaded when this module is reloaded


# import all the commands so that sublime sees them
from .modules.core.sublime import DebuggerEditCommand
from .modules.command import DebuggerCommand, DebuggerTextCommand, DebuggerInputCommand

from .modules.output_panel import OutputPanelEventListener, DebuggerPromptCancelCommand
from .modules.output_panel_terminus import DebuggerTerminusPostViewHooks
from .modules.project_buttons import DebuggerProjectFileListener, ProjectButtons

from .modules.ui.input import CommandPaletteInputCommand

from .modules import core
from .modules import ui
from .modules import dap
from .modules.project import Project

from .modules.debugger import Debugger
from .modules import hover
from .modules.hover import DebuggerShowHoverPopupCommand
from .modules.output_panel import OutputPanel
from .modules.memory_view import DebuggerMemoryInput, DebuggerMemoryViewListener

from .modules.commands.commands import *  # import all the action classes
from .modules.adapters import *  # import all the adapters so Adapters.initialize() will see them
from .modules.settings import SettingsRegistery, Settings

from .modules.dap.schema import initialize_lsp_json_schema

was_opened_at_startup: Set[int] = set()


def plugin_loaded() -> None:
	# do this first since we need to configure logging right away
	SettingsRegistery.initialize(on_updated=updated_settings)
	core.log_configure(
		log_info=Settings.development,
		log_errors=True,
		log_exceptions=True,
	)

	core.info('[startup]')

	ui.startup(Settings.development)

	def open_in_windows():
		for window in sublime.windows():
			open_debugger_in_window_or_view(window)

	# this is working around an issue where output panels not showing during plugin_loaded for some reason
	sublime.set_timeout(open_in_windows)

	initialize_lsp_json_schema()

	hover.startup()

	core.info('[finished]')


def plugin_unloaded() -> None:
	core.info('[shutdown]')

	for debugger in list(Debugger.debuggers()):
		core.info('Disposing Debugger')
		try:
			debugger.dispose()
		except Exception:
			core.exception()

	try:
		hover.shutdown()
	except Exception:
		core.exception()

	# the icons on project files are not owned by a debugger, so they are taken down here; otherwise
	# a reload draws a second set on top of them
	try:
		ProjectButtons.dispose_all()
	except Exception:
		core.exception()

	try:
		ui.shutdown()
	except Exception:
		core.exception()


	core.info('[finished]')


def open_debugger_in_window_or_view(window_or_view: sublime.View | sublime.Window):
	if isinstance(window_or_view, sublime.View):
		window = window_or_view.window()
	else:
		window = window_or_view

	if not window:
		return

	id = window.id()
	if id in was_opened_at_startup:
		return

	was_opened_at_startup.add(id)

	if not Settings.open_at_startup and not window.settings().get('debugger.open_at_startup'):
		return

	project_data: Any = window.project_data()
	if not project_data or 'debugger_configurations' not in project_data:
		return

	Debugger.get(window, create=True)


def updated_settings():
	core.log_configure(
		log_info=Settings.development,
		log_errors=True,
		log_exceptions=True,
	)

	ui.update_and_render()

	for debugger in Debugger.debuggers():
		debugger.project_or_settings_updated()


class EventListener(sublime_plugin.EventListener):
	def on_new_window(self, window: sublime.Window):
		open_debugger_in_window_or_view(window)

	def on_pre_close_window(self, window: sublime.Window):
		if debugger := Debugger.get(window):
			debugger.dispose()

	def on_exit(self):
		core.info('saving project data: {}'.format(Debugger.debuggers()))
		for debugger in Debugger.debuggers():
			debugger.save_data()

	def on_post_save(self, view: sublime.View):
		if debugger := Debugger.get(view):
			if file := debugger.project.source_file(view):
				for session in debugger.sessions:
					session.adapter.on_saved_source_file(session, file)

	# is on_new_project bugged? this gets called when creating a new project so use it instead
	def on_pre_save_project(self, window: sublime.Window):
		if debugger := Debugger.get(window):
			debugger.project_or_settings_updated()

	def on_load_project(self, window: sublime.Window):
		if debugger := Debugger.get(window):
			debugger.project_or_settings_updated()

	def on_pre_close_project(self, window: sublime.Window):
		if debugger := Debugger.get(window):
			sublime.set_timeout(lambda: debugger.project_or_settings_updated(), 0)

	def on_hover(self, view: sublime.View, point: int, hover_zone: int):
		if hover_zone != sublime.HOVER_TEXT:
			return

		# when the information is contributed to the LSP popup showing our own popup here would just
		# result in two popups fighting over the same hover point
		if hover.is_active():
			return

		hover.show_popup(view, point)

	def on_text_command(self, view: sublime.View, cmd: str, args: dict[str, Any] | None) -> Any:
		debugger = Debugger.get(view)
		if not debugger:
			return

		if (cmd == 'drag_select' or cmd == 'context_menu') and args and 'event' in args:
			# close the input on drag select or context menu since these menus are accessable from clicking the debugger ui
			CommandPaletteInputCommand.cancel_running_command()

			event = args['event']
			x: int = event['x']
			y: int = event['y']

			view_x, _ = view.layout_to_window(view.viewport_position())  # type: ignore

			margin = cast(float, view.settings().get('margin') or 0)
			offset = x - view_x  # type: ignore

			if offset < -30 - margin:
				pt = view.window_to_text((x, y))
				line = view.rowcol(pt)[0]

				# only rewrite this command if someone actually consumed it
				# otherwise let sublime do its thing
				if self.on_view_gutter_clicked(view, line, event['button']):
					return 'noop'

	def on_window_command(self, window: sublime.Window, cmd: str, args: dict[str, Any] | None) -> Any:
		if cmd == 'show_panel' and args:
			debugger = Debugger.get(window)
			if not debugger:
				return

			debugger._refresh_none_debugger_output_panel(args['panel'])

	def on_post_window_command(self, window: sublime.Window, cmd: str, args: Any):
		if cmd == 'show_panel':
			if panel := OutputPanel.from_output_panel_name.get(window.active_panel() or ''):
				panel.on_show_panel()

			debugger = Debugger.get(window)
			if debugger and Settings.always_keep_visible and window.active_panel() is None:
				debugger.open()

		if cmd == 'hide_panel':
			debugger = Debugger.get(window)
			if debugger and Settings.always_keep_visible and window.active_panel() is None:
				debugger.open()

	def on_view_gutter_clicked(self, view: sublime.View, line: int, button: int) -> bool:
		line += 1  # convert to 1 based lines
		debugger = Debugger.get(view)
		if not debugger:
			return False

		breakpoints = debugger.breakpoints
		file = view.file_name()
		if not file:
			return False

		if window := view.window():
			window.focus_view(view)

		# a click in the gutter is about the file: it adds, removes or edits a breakpoint and leaves
		# whatever panel is open alone, the marker in the gutter being the feedback
		source_breakpoints = breakpoints.source.get_breakpoints_on_line(file, line)
		if button == 1 or (not source_breakpoints and button == 2):
			debugger.breakpoints.source.toggle_file_line(file, line)

		elif source_breakpoints and button == 2:
			debugger.breakpoints.source.edit_breakpoints(source_breakpoints)

		return True

	def on_query_context(self, view: sublime.View, key: str, operator: int, operand: Any, match_all: bool) -> bool | None:
		if not key.startswith('debugger'):
			return None

		def apply_operator(value: Any):
			if operator == sublime.OP_EQUAL:
				return value == operand
			elif operator == sublime.OP_NOT_EQUAL:
				return value != operand

		if key == 'debugger':
			debugger = Debugger.get(view)
			return apply_operator(bool(debugger))

		if key == 'debugger.visible':
			debugger = Debugger.get(view)
			return apply_operator(debugger.is_open()) if debugger else apply_operator(False)

		if key == 'debugger.active':
			debugger = Debugger.get(view)
			return apply_operator(bool(debugger.session)) if debugger else apply_operator(False)

		if key.startswith('debugger.'):
			settings_key = key[len('debugger.') :]
			if SettingsRegistery.settings.has(settings_key):
				return apply_operator(SettingsRegistery.settings.get(settings_key))
			else:
				return apply_operator(view.settings().get(key))

		return None

	def on_load(self, view: sublime.View):
		core.on_view_load(view)
		for debugger in Debugger.debuggers():
			debugger.breakpoints.source.sync_from_breakpoints(view)

	def on_activated(self, view: sublime.View):
		for debugger in Debugger.debuggers():
			debugger.breakpoints.source.sync_from_breakpoints(view)

	def on_modified(self, view: sublime.View) -> None:
		for debugger in Debugger.debuggers():
			debugger.breakpoints.source.invalidate(view)
