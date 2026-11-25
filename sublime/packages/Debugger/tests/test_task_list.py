from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Item:
	def __init__(self, run, text, annotation='', details='', kind=None, run_alt=None):
		self.run, self.text, self.annotation, self.details, self.kind, self.run_alt = run, text, annotation, details, kind, run_alt


class Task(dict):
	def __init__(self, name, **keys):
		super().__init__(keys)
		self.name = name
		self.source = types.SimpleNamespace(open_file=Mock())


class Runtime:
	def __init__(self, name, finished=False, panel=True):
		self.task = types.SimpleNamespace(name=name)
		self.finished = finished
		self.panel = types.SimpleNamespace(open=Mock()) if panel else None

	def is_finished(self):
		return self.finished

	def get_panel(self):
		return self.panel


class TaskListTests(unittest.TestCase):
	def setUp(self):
		package = types.ModuleType('_tasklist')
		package.__path__ = []
		modules = {
			'_tasklist': package,
			'_tasklist.ui': types.SimpleNamespace(InputListItem=Item),
			'_tasklist.configurations': types.SimpleNamespace(status_kind=lambda status, selected: ('kind', status)),
		}
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)
		spec = importlib.util.spec_from_file_location('_tasklist.task_list', ROOT / 'modules' / 'task_list.py')
		self.module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(self.module)

		self.tasks = [
			Task('build', shell_cmd='make build'),
			Task('api server', shell_cmd='npm run dev', ready_regex='Listening'),
			Task('clean', cmd=['rm', '-rf', 'out'], background=True),
			Task('format', type='sublime', command='lsp_format_document'),
		]
		self.debugger = types.SimpleNamespace(tasks=types.SimpleNamespace(tasks=[]))
		self.run = Mock()

	def rows(self, last=None):
		return self.module.items(self.debugger, self.tasks, self.run, last)

	def test_every_task_is_a_row_that_says_what_it_runs(self):
		rows, index = self.rows()
		self.assertEqual([row.text for row in rows], ['build', 'api server', 'clean', 'format'])
		self.assertEqual([row.details for row in rows], [
			'make build', 'npm run dev · waits until ready', 'rm -rf out · background', 'lsp_format_document'])
		self.assertEqual({row.annotation for row in rows}, {'Stopped'})
		self.assertEqual(index, 0)

	def test_what_is_running_comes_first_and_says_so(self):
		self.debugger.tasks.tasks = [Runtime('api server'), Runtime('build', finished=True)]
		rows, _ = self.rows()
		self.assertEqual([(row.text, row.annotation) for row in rows], [
			('api server', 'Running'), ('build', 'Stopped'), ('clean', 'Stopped'), ('format', 'Stopped')])
		self.assertEqual(rows[0].kind, ('kind', 'Running'))

	def test_the_list_opens_on_the_task_that_was_run_last(self):
		self.assertEqual(self.rows('clean')[1], 2)
		# wherever being first for running has put it
		self.debugger.tasks.tasks = [Runtime('clean')]
		self.assertEqual(self.rows('clean')[1], 0)
		self.assertEqual(self.rows('build')[1], 1)
		# and on the first row when that task is gone
		self.assertEqual(self.rows('deleted')[1], 0)

	def test_picking_a_task_runs_it(self):
		rows, _ = self.rows()
		rows[1].run()
		self.run.assert_called_once_with(self.tasks[1])

	def test_picking_one_that_is_running_shows_it_and_does_not_start_another(self):
		runtime = Runtime('api server')
		self.debugger.tasks.tasks = [runtime]
		rows, _ = self.rows()
		rows[0].run()
		runtime.panel.open.assert_called_once()
		self.run.assert_not_called()

		# one that runs without a tab has nothing to show, and is still not started twice
		self.debugger.tasks.tasks = [Runtime('clean', panel=False)]
		self.rows()[0][0].run()
		self.run.assert_not_called()

	def test_it_is_looked_up_when_it_is_picked_not_when_the_list_was_made(self):
		rows, _ = self.rows()
		runtime = Runtime('build')
		self.debugger.tasks.tasks = [runtime]
		rows[0].run()
		runtime.panel.open.assert_called_once()
		self.run.assert_not_called()

	def test_alt_enter_opens_where_the_task_is_defined(self):
		rows, _ = self.rows()
		rows[2].run_alt()
		self.tasks[2].source.open_file.assert_called_once()

	def test_a_task_listed_twice_is_one_row(self):
		self.tasks.append(Task('build', shell_cmd='make all'))
		rows, _ = self.rows()
		self.assertEqual([row.text for row in rows].count('build'), 1)
		self.assertEqual(rows[0].details, 'make build')


class TasksButtonTests(unittest.TestCase):
	'''The button on the bar: `Toolbar.tasks_tool` and what pressing it does'''

	def toolbar(self, backend):
		import ast
		module = ast.parse((ROOT / 'modules/ui/toolbar.py').read_text())
		owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Toolbar')
		members = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('tasks_tool', 'run_task')]
		body = ast.ClassDef(name='Toolbar', bases=[], keywords=[], body=members, decorator_list=[])
		namespace = {}
		exec(compile(ast.fix_missing_locations(ast.Module(body=[body], type_ignores=[])), 'toolbar.py', 'exec'), namespace)
		toolbar = namespace['Toolbar']()
		toolbar.ui = types.SimpleNamespace(backend=backend, tool=Mock(return_value='<tool>'), run_command=Mock())
		return toolbar

	def test_it_opens_the_list_of_tasks(self):
		toolbar = self.toolbar(types.SimpleNamespace(tasks=types.SimpleNamespace(get_running=lambda: [])))
		self.assertEqual(toolbar.tasks_tool(), '<tool>')
		name, title, callback = toolbar.ui.tool.call_args[0]
		self.assertEqual((name, title), ('tasks', 'Run a task'))
		self.assertEqual(toolbar.ui.tool.call_args[1], {'css': ''})

		callback()
		toolbar.ui.run_command.assert_called_once_with('select_and_run_task')

	def test_it_is_lit_while_a_task_is_running(self):
		toolbar = self.toolbar(types.SimpleNamespace(tasks=types.SimpleNamespace(get_running=lambda: [object()])))
		toolbar.tasks_tool()
		self.assertEqual(toolbar.ui.tool.call_args[0][1], 'Run a task · one is running')
		self.assertEqual(toolbar.ui.tool.call_args[1], {'css': 'active'})

	def test_a_debugger_that_is_still_being_built_has_a_button_too(self):
		toolbar = self.toolbar(types.SimpleNamespace())
		toolbar.tasks_tool()
		self.assertEqual(toolbar.ui.tool.call_args[1], {'css': ''})


class IconTests(unittest.TestCase):
	def test_the_tasks_icon_is_drawn_like_the_others(self):
		spec = importlib.util.spec_from_file_location('_icons_test', ROOT / 'modules/ui/icons.py')
		icons = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(icons)
		self.assertIn('tasks', icons.ICONS)
		self.assertEqual(icons.ICON_SIZES['tasks'], icons.ICON_SIZES['settings'])
