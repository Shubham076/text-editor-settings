import sublime
import sublime_plugin


class ToggleDebuggerPanelCommand(sublime_plugin.WindowCommand):
	"""
	A command to toggle the SublimeDebugger panel on/off.

	Usage:
	- Add to your keybindings: {"keys": ["ctrl+shift+d"], "command": "toggle_debugger_panel"}
	- Or run via Command Palette: "Toggle Debugger Panel"
	"""

	def run(self):
		"""Toggle the debugger panel - open if closed, close if open."""
		# Check if any debugger panel is currently active
		if self._is_debugger_panel_open():
			# Hide the panel without stopping debug sessions
			self.window.run_command('hide_panel')
		else:
			# Open the debugger by running the open action
			self.window.run_command('debugger', {'action': 'open'})

	def _is_debugger_panel_open(self):
		"""Whether the panel that is open belongs to the debugger

		Asked of the panel's view rather than of its name: the debugger marks every panel it
		creates (console, call stack, breakpoints, watch, terminals) with the `debugger.output`
		setting, while the names vary (`Debugger Callstack 1`, a task's own name, ...).
		"""
		active_panel = self.window.active_panel()

		if not active_panel or not active_panel.startswith('output.'):
			return False

		view = self.window.find_output_panel(active_panel[len('output.'):])
		return bool(view and view.settings().get('debugger.output'))

	def is_enabled(self):
		"""Enable the command only if we have a valid window."""
		return self.window is not None

	def description(self):
		"""Description shown in Command Palette."""
		return "Toggle Debugger Panel"
