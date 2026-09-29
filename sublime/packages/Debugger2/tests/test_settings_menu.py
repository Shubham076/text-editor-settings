from __future__ import annotations

import types
import unittest
from unittest.mock import Mock

import test_live_ui as fixtures


class SettingsMenuTests(unittest.TestCase):
	setUp = fixtures.LiveTests.setUp
	make_ui = fixtures.LiveTests.make_ui
	make_strip = fixtures.LiveTests.make_strip
	session = fixtures.LiveTests.session

	def test_gear_opens_the_configuration_quick_panel_without_touching_the_layout(self):
		for body in (True, False):
			with self.subTest(body=body):
				self.window.run_command.reset_mock()
				self.view.show_popup.reset_mock()
				ui = self.make_ui(body=body)
				ui.render()
				before = [item[1] for item in ui.phantoms.update.call_args.args[0]]
				ui.toolbar.settings()
				ui.render()
				after = [item[1] for item in ui.phantoms.update.call_args.args[0]]
				self.assertEqual(before, after)
				# the same quick panel the project file's settings icon and the palette entry open
				self.window.run_command.assert_called_once_with('debugger', {'action': 'change_configuration'})
				self.view.show_popup.assert_not_called()
				ui.dispose()

	def two_configurations(self):
		api = types.SimpleNamespace(name='api', id_ish='config-1', type='node', request='launch')
		worker = types.SimpleNamespace(name='worker', id_ish='config-2', type='node', request='launch')
		self.backend.project.configurations = [api, worker]
		self.backend.project.project_file_name = 'ps-platform.sublime-project'
		return api, worker

	def shown(self):
		return self.loaded['_live_test.modules.ui'].InputList.shown[-1]

	def test_picker_opens_the_native_list_with_status_badges_on_the_selection(self):
		self.two_configurations()
		self.backend.sessions = [self.session('worker', paused=False)]
		ui = self.make_ui(body=True)
		ui.render()
		ui.toolbar.picker.show()
		shown = self.shown()
		self.assertEqual(shown.placeholder, 'Run configuration')
		# running before stopped; the selected `api` is stopped and the list opens on it
		self.assertEqual([row.text for row in shown.values], ['worker', 'api', 'Edit Configuration File'])
		self.assertEqual([row.annotation for row in shown.values], ['Running', 'Stopped', 'ps-platform.sublime-project'])
		self.assertEqual(shown.values[0].kind, (self.sublime.KIND_ID_COLOR_GREENISH, '\u25b6', 'Running'))
		self.assertEqual(shown.values[1].kind, (self.sublime.KIND_ID_AMBIGUOUS, '\u25cf', 'Stopped'))
		self.assertEqual([row.details for row in shown.values[:2]], ['node · launch'] * 2)
		self.assertEqual(shown.index, 1)
		# no html popup any more
		self.view.show_popup.assert_not_called()

	def test_picker_opens_at_the_top_when_nothing_is_selected(self):
		self.two_configurations()
		self.backend.project.configuration_or_compound = None
		ui = self.make_ui(body=True)
		ui.render()
		ui.toolbar.picker.show()
		self.assertEqual(self.shown().index, 0)

	def test_picking_a_row_selects_that_configuration_and_restores_its_tab(self):
		api, worker = self.two_configurations()
		self.backend.project.configuration_tabs = {'config-2': 'console'}
		picker_module = self.loaded['_live_test.modules.ui.configuration_picker']
		picker_module.configurations.select = Mock()
		ui = self.make_ui(body=True)
		ui.toolbar.select_tab = Mock()
		ui.toolbar.picker.show()
		next(row for row in self.shown().values if row.text == 'worker').run()
		picker_module.configurations.select.assert_called_once_with(self.backend, 'worker')
		ui.toolbar.select_tab.assert_called_once_with('console', remember=False)

	def test_edit_row_opens_the_project_configurations(self):
		self.two_configurations()
		ui = self.make_ui(body=True)
		ui.toolbar.picker.show()
		self.shown().values[-1].run()
		self.window.run_command.assert_called_once_with('debugger', {'action': 'edit_configurations'})

	def test_picker_does_not_modify_output_buffer(self):
		self.two_configurations()
		ui = self.make_ui()
		ui.render()
		ui.toolbar.picker.show()
		ui.render()
		self.core.edit.assert_not_called()
		self.view.set_read_only.assert_not_called()
		self.view.sel.assert_not_called()


if __name__ == '__main__':
	unittest.main()
