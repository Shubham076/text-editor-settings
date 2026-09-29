from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def python_sources():
	return [*ROOT.glob('*.py'), *(path for path in (ROOT / 'modules').rglob('*.py') if 'libs' not in path.parts)]


def command_name(name):
	result = name[0].lower()
	last_upper = False
	for char in name[1:]:
		result += ('_' + char.lower()) if char.isupper() and not last_upper else char
		last_upper = char.isupper()
	return result[:-8] if result.endswith('_command') else result


def registered_commands():
	commands = {}
	for path in python_sources():
		for node in ast.walk(ast.parse(path.read_text())):
			if isinstance(node, ast.ClassDef) and any(isinstance(base, ast.Attribute) and base.attr in ('WindowCommand', 'TextCommand', 'ApplicationCommand') for base in node.bases):
				commands[command_name(node.name)] = (path, node.name)
	return commands


class PackageIsolationTests(unittest.TestCase):
	'''The package lives in a directory called Debugger2 but presents itself as Debugger

	Commands, settings, view setting keys, markers and the LSP provider all carry the plain
	`debugger` name, the same one the original Debugger package used, so the two cannot be
	enabled at once (the original sits in `ignored_packages`). Only what is derived from the
	directory keeps the `2`: the package path and the storage folder under Package Storage.
	'''

	def test_all_registered_commands_use_the_debugger_namespace(self):
		commands = registered_commands()
		self.assertIn('debugger', commands)
		self.assertIn('debugger_edit', commands)
		self.assertIn('debugger_text', commands)
		self.assertIn('debugger_memory_input', commands)
		self.assertTrue(all(name.startswith('debugger') for name in commands), commands)
		self.assertFalse(any('debugger2' in name for name in commands), commands)

	def test_internal_commands_are_exported_by_plugin_entrypoint(self):
		exports = {alias.name for node in ast.walk(ast.parse((ROOT / 'start.py').read_text())) if isinstance(node, ast.ImportFrom) for alias in node.names}
		for path, name in registered_commands().values():
			if path.parent != ROOT:
				self.assertIn(name, exports)

	def test_palette_commands_and_actions_exist(self):
		commands = registered_commands()
		actions = {node.value.value for path in python_sources() for node in ast.walk(ast.parse(path.read_text()))
			if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
			and any(isinstance(target, ast.Name) and target.id == 'key' for target in node.targets)}
		def check(items):
			for item in items:
				if 'children' in item:
					check(item['children'])
				if 'command' in item:
					self.assertIn(item['command'], commands)
					if 'action' in item.get('args', {}):
						self.assertIn(item['args']['action'], actions)
		for pattern in ('*.sublime-commands', '*.sublime-menu'):
			for path in (ROOT / 'contributes/Commands').glob(pattern):
				with self.subTest(path=path.name):
					check(json.loads(path.read_text()))

	def test_old_dashboard_and_switch_setting_are_absent(self):
		for name in ('legacy_panel', 'output_panel_tabs', 'callstack', 'debugger', 'variables', 'tabbed'):
			self.assertFalse((ROOT / 'modules/views' / (name + '.py')).exists())
		for path in python_sources():
			self.assertNotIn('legacy_ui', path.read_text(), str(path))
		self.assertFalse((ROOT / 'Debugger2.sublime-settings').exists())
		self.assertTrue((ROOT / 'Debugger.sublime-settings').exists())
		self.assertTrue((ROOT / 'contributes/Commands/DebuggerWidget.sublime-menu').exists())

	def test_no_debugger2_name_is_left_except_the_package_directory(self):
		'''Only `${packages}/Debugger2/...` paths keep the directory name; all other text says Debugger'''
		for path in [*python_sources(), *(ROOT / 'contributes').rglob('*.sublime-*'), ROOT / 'Debugger.sublime-settings']:
			for number, line in enumerate(path.read_text().splitlines(), 1):
				if 'debugger2' in line.lower():
					self.assertIn('${packages}/Debugger2/', line, (str(path), number, line.strip()))

	def test_commands_and_settings_use_the_debugger_names(self):
		settings_files, commands = set(), set()
		for path in python_sources():
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
					arg = node.args[0]
					if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
						if node.func.attr in ('run_command', 'command_url') and arg.value.startswith('debugger'):
							commands.add(arg.value)
						if node.func.attr in ('load_settings', 'save_settings') and 'ebugger' in arg.value:
							settings_files.add(arg.value)
		self.assertIn('debugger', commands)
		self.assertEqual(settings_files, {'Debugger.sublime-settings'})

	def test_new_picker_uses_registered_configuration_editor_action(self):
		text = (ROOT / 'modules/ui/configuration_picker.py').read_text()
		self.assertIn("run_command('edit_configurations')", text)

	def test_python38_and_no_imports_of_removed_dashboard(self):
		removed = {'views.legacy_panel', 'views.output_panel_tabs', 'views.callstack', 'views.debugger', 'views.variables', 'views.tabbed'}
		for path in python_sources():
			with self.subTest(path=str(path.relative_to(ROOT))):
				tree = ast.parse(path.read_text(), feature_version=(3, 8))
				for node in ast.walk(tree):
					if isinstance(node, ast.ImportFrom):
						self.assertNotIn(node.module, removed)

	def test_storage_follows_the_directory_and_markers_use_the_debugger_names(self):
		self.assertIn('os.path.join(package_storage_path, _current_package)', (ROOT / 'modules/core/util.py').read_text())
		self.assertIn("LSP_PROVIDER_NAME = 'Debugger'", (ROOT / 'modules/hover.py').read_text())
		self.assertIn("'debugger_settings'", (ROOT / 'modules/settings.py').read_text())
		self.assertIn("'debugger.bp{}'", (ROOT / 'modules/dap/breakpoint_source.py').read_text())


if __name__ == '__main__':
	unittest.main()
