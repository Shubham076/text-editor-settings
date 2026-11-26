from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class FakeSettings(dict):
	'''What `sublime.load_settings` gives: the user's file laid over the package's, a top level key at a time'''

	def set(self, key, value):
		self[key] = value


def load_settings_module():
	package = types.ModuleType('_settings_test')
	package.__path__ = []
	modules = {'_settings_test': package, '_settings_test.core': types.ModuleType('_settings_test.core'), 'sublime': types.ModuleType('sublime')}
	spec = importlib.util.spec_from_file_location('_settings_test.settings', ROOT / 'modules/settings.py')
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, dict(modules, **{'_settings_test.settings': module})):
		spec.loader.exec_module(module)
	return module


def package_file():
	text = (ROOT / 'Debugger.sublime-settings').read_text()
	text = re.sub(r'^\s*//.*$', '', text, flags=re.M)
	return json.loads(re.sub(r',(\s*[}\]])', r'\1', text))


class SettingsTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.module = load_settings_module()

	def setUp(self):
		self.stored = FakeSettings()
		self.module.SettingsRegistery.settings = self.stored
		self.module.SettingsRegistery.save = staticmethod(lambda: None)
		self.settings = self.module.Settings

	def test_a_setting_of_a_group_is_read_from_its_object(self):
		self.stored['console'] = {'font_size': 17, 'json_logs': 'compact'}
		self.assertEqual(self.settings.console_font_size, 17)
		self.assertEqual(self.settings.json_logs, 'compact')

	def test_the_keys_a_user_left_out_of_a_group_keep_their_defaults(self):
		# the user's object replaces the package's whole object, it is not merged into it
		self.stored['console'] = {'font_size': 17}
		self.assertEqual(self.settings.console_line_padding, 2)
		self.assertEqual(self.settings.console_scrollback_limit, 2000)
		self.assertEqual(self.settings.external_terminal, 'terminus')

	def test_a_group_that_is_missing_or_not_an_object_is_all_defaults(self):
		self.assertEqual(self.settings.font_size, None)
		self.stored['ui'] = 'nonsense'
		self.assertEqual(self.settings.console_bar_position, 'bottom')
		self.assertIs(self.settings.inline_values, True)

	def test_a_value_set_to_null_or_false_is_that_not_the_default(self):
		self.stored['inline_values'] = {'enabled': False}
		self.stored['console'] = {'line_padding': 0}
		self.assertIs(self.settings.inline_values, False)
		self.assertEqual(self.settings.console_line_padding, 0)

	def test_setting_one_key_keeps_the_rest_of_its_object(self):
		self.stored['console'] = {'font_size': 17}
		self.settings.json_logs = 'pretty'
		self.assertEqual(self.stored['console'], {'font_size': 17, 'json_logs': 'pretty'})

	def test_a_setting_outside_any_group_is_a_key_of_its_own(self):
		self.assertIs(self.settings.session_panels, True)
		self.stored['session_panels'] = False
		self.assertIs(self.settings.session_panels, False)

	def test_the_flat_keys_of_before_are_no_longer_read(self):
		self.stored['console_font_size'] = 17
		self.assertEqual(self.settings.console_font_size, None)

	def test_the_packages_file_has_every_visible_setting_at_its_default(self):
		file = package_file()
		for setting in self.module.Setting.all:
			if not setting.visible:
				continue
			holder = file[setting.group] if setting.group else file
			self.assertIn(setting.name, holder, setting.key)
			self.assertEqual(holder[setting.name], setting.default, setting.key)

	def test_the_packages_file_has_no_setting_the_code_does_not_know(self):
		# the adapters define theirs where they are used, in modules that need Sublime to import
		elsewhere = {'adapters.go_dlv', 'adapters.go_build_cache', 'adapters.go_build_cache_hours', 'adapters.lldb_library', 'adapters.github_personal_access_token'}
		known = {setting.key for setting in self.module.Setting.all} | elsewhere
		for key, value in package_file().items():
			names = [f'{key}.{name}' for name in value] if key in self.module.GROUPS else [key]
			for name in names:
				self.assertIn(name, known)

	def test_the_adapters_settings_are_defined_under_the_names_the_file_has(self):
		for path, key in (('modules/adapters/go.py', 'adapters.go_dlv'), ('modules/adapters/lldb.py', 'adapters.lldb_library'),
				('modules/adapters/util/adapter_installer_git.py', 'adapters.github_personal_access_token')):
			self.assertIn(f"key='{key}'", (ROOT / path).read_text())

	def test_the_schema_nests_a_group_as_an_object(self):
		schema = self.module.settings_schema()
		console = schema['properties']['console']
		self.assertEqual(console['type'], 'object')
		self.assertEqual(console['properties']['json_logs']['type'], 'string')
		self.assertEqual(schema['properties']['session_panels']['type'], 'boolean')


if __name__ == '__main__':
	unittest.main()
