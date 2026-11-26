from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent


class ProjectFileTests(unittest.TestCase):
	'''A window that has a folder open, and not its project, reads the project file in that folder'''

	def setUp(self):
		root = types.ModuleType('_pft')
		root.__path__ = []
		package = types.ModuleType('_pft.modules')
		package.__path__ = []
		core = types.SimpleNamespace(Event=lambda: Mock(), info=Mock(), run=lambda function: function)
		core.Event = type('Event', (), {'__class_getitem__': classmethod(lambda cls, item: Mock)})
		dap = types.SimpleNamespace(Configuration=Mock(), ConfigurationCompound=Mock(), Task=Mock(), InputLiteral=lambda value: value)
		sublime = types.ModuleType('sublime')
		sublime.decode_value = json.loads
		self.modules = patch.dict(sys.modules, {
			'_pft': root, '_pft.modules': package, '_pft.modules.core': core, '_pft.modules.dap': dap,
			'_pft.modules.inputs': types.SimpleNamespace(SelectProcess=Mock(), PromptInput=Mock()),
			'_pft.modules.input_prompts': types.SimpleNamespace(),
			'_pft.modules.settings': types.SimpleNamespace(Settings=types.SimpleNamespace()),
			'sublime': sublime,
		})
		self.modules.start()
		self.addCleanup(self.modules.stop)
		package.core = core
		package.dap = dap
		package.input_prompts = sys.modules['_pft.modules.input_prompts']
		spec = importlib.util.spec_from_file_location('_pft.modules.project', ROOT / 'modules' / 'project.py')
		self.module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = self.module
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		spec.loader.exec_module(self.module)

		directory = tempfile.TemporaryDirectory()
		self.addCleanup(directory.cleanup)
		self.folder = os.path.join(os.path.realpath(directory.name), 'demo')
		os.mkdir(self.folder)
		self.window = Mock()
		self.window.project_file_name.return_value = None
		self.window.folders.return_value = [self.folder]
		self.window.project_data.return_value = {'folders': [{'path': self.folder}]}
		self.window.extract_variables.return_value = {'folder': self.folder}

	def write(self, name, data, sub=''):
		directory = os.path.join(self.folder, sub)
		os.makedirs(directory, exist_ok=True)
		path = os.path.join(directory, name)
		with open(path, 'w') as file:
			json.dump(data, file)
		return path

	def test_a_window_with_a_project_open_reads_that_project(self):
		self.write('demo.sublime-project', {'debugger_configurations': [{'name': 'in the folder'}]})
		self.window.project_file_name.return_value = '/elsewhere/other.sublime-project'
		self.window.project_data.return_value = {'debugger_configurations': [{'name': 'open'}]}
		self.assertEqual(self.module.find_project_file(self.window), '/elsewhere/other.sublime-project')
		self.assertEqual(self.module.read_project_data(self.window), {'debugger_configurations': [{'name': 'open'}]})

	def test_a_folder_window_reads_the_project_file_in_the_folder(self):
		path = self.write('demo.sublime-project', {'debugger_configurations': [{'name': 'backend'}]})
		self.assertEqual(self.module.find_project_file(self.window), path)
		self.assertEqual(self.module.read_project_data(self.window), {'debugger_configurations': [{'name': 'backend'}]})

	def test_the_one_named_after_the_folder_is_taken_of_several(self):
		self.write('another.sublime-project', {})
		path = self.write('demo.sublime-project', {})
		self.assertEqual(self.module.find_project_file(self.window), path)

	def test_a_project_file_in_dot_sublime_is_found(self):
		path = self.write('wt.sublime-project', {}, sub='.sublime')
		self.assertEqual(self.module.find_project_file(self.window), path)

	def test_a_folder_with_no_project_file_has_what_the_window_has(self):
		self.assertIsNone(self.module.find_project_file(self.window))
		self.assertEqual(self.module.read_project_data(self.window), {'folders': [{'path': self.folder}]})

	def test_a_project_file_that_does_not_parse_has_what_the_window_has(self):
		with open(os.path.join(self.folder, 'demo.sublime-project'), 'w') as file:
			file.write('{ not json')
		self.assertEqual(self.module.read_project_data(self.window), {'folders': [{'path': self.folder}]})

	def test_the_variables_of_a_found_project_file_are_those_of_an_open_one(self):
		path = self.write('demo.sublime-project', {})
		project = self.module.Project(self.window)
		variables = project.variables()
		self.assertEqual(variables['project'], path)
		self.assertEqual(variables['project_path'], self.folder)
		self.assertEqual(variables['project_name'], 'demo.sublime-project')
		self.assertEqual(variables['project_base_name'], 'demo')
		self.assertEqual(variables['project_extension'], 'sublime-project')
		self.assertEqual(project.location, path)
		self.assertEqual(project.project_file_name, 'demo.sublime-project')


if __name__ == '__main__':
	unittest.main()
