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
		"""Check if any debugger panel is currently open using Sublime's panel system."""
		active_panel = self.window.active_panel()

		if not active_panel:
			return False

		# Check for known debugger panel names
		debugger_panels = [
			'output.Debugger',           # Console panel
			'output.Debugger Callstack', # Callstack panel
		]

		# Also check for numbered variants (e.g., 'output.Debugger2', 'output.Debugger3')
		# since the debugger creates numbered panels for multiple instances
		if active_panel in debugger_panels:
			return True

		# Check for numbered variants
		for panel_base in ['output.Debugger', 'output.Debugger Callstack']:
			if active_panel.startswith(panel_base):
				# Check if it's a numbered variant (e.g., 'output.Debugger2')
				suffix = active_panel[len(panel_base):]
				if suffix == '' or (suffix.isdigit() and len(suffix) <= 2):
					return True

		return False

	def is_enabled(self):
		"""Enable the command only if we have a valid window."""
		return self.window is not None

	def description(self):
		"""Description shown in Command Palette."""
		return "Toggle Debugger Panel"
