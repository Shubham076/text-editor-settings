from __future__ import annotations

import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_live_ui as fixtures
from test_live_ui import ROOT, load_module


class DashboardLayoutTests(unittest.TestCase):
	setUp = fixtures.LiveTests.setUp
	make_ui = fixtures.LiveTests.make_ui
	make_strip = fixtures.LiveTests.make_strip

	def test_call_stack_and_breakpoints_keep_the_toolbar_in_the_strip_below_the_panes(self):
		strip_set, view_set = Mock(), Mock()
		self.sublime.PhantomSet = Mock(side_effect=[strip_set, view_set])
		strip = self.make_strip()
		self.view.size.return_value = 6
		ui = self.make_ui(body=True, header_view=strip, layout='debugger')
		ui.render()
		# the strip: one toolbar row, laid out at the strip's width, without the tab row
		toolbar = strip_set.update.call_args.args[0]
		self.assertEqual(len(toolbar), 1)
		point, html, _, layout = toolbar[0]
		self.assertEqual((point, layout), (0, self.sublime.LAYOUT_INLINE))
		self.assertIn('toolbar joined strip', html)
		self.assertIn('Select run configuration', html)
		self.assertIn('class="breakpoints-control"', html)
		self.assertNotIn('class="tabs"', html)
		# the call stack is where the back arrow leads, so its strip carries the brand mark instead
		self.assertNotIn('Back to call stack', html)
		self.assertIn('<span class="brand" title="Debugger"><img class="icon ', html)
		self.assertLess(html.index('class="brand"'), html.index('Select run configuration'))
		self.assertAlmostEqual(ui.header_height, ui.font * 3.8 + 2)
		# the view: tabs at the tab anchor, then the two panes; the toolbar anchors stay empty
		content = view_set.update.call_args.args[0]
		self.assertEqual([item[0] for item in content], [2, 3, 4])
		self.assertIn('class="tabs"', content[0][1])
		self.assertIn('Call stack', content[1][1])
		self.assertIn('Variables', content[2][1])
		self.assertTrue(all(item[3] == self.sublime.LAYOUT_INLINE for item in content))
		# the breakpoints tab keeps the back arrow, and one pane
		self.sublime.PhantomSet = Mock(side_effect=[Mock(), Mock()])
		ui = self.make_ui(body=True, header_view=strip, layout='breakpoints')
		ui.render()
		strip_html = ui.phantoms.update.call_args.args[0][0][1]
		self.assertIn('Back to call stack', strip_html)
		self.assertIn('class="breakpoints-control active"', strip_html)
		self.assertEqual([item[0] for item in ui.view_phantoms.update.call_args.args[0]], [2, 3])

	def test_dashboard_renders_toolbar_tabs_then_call_stack_beside_variables(self):
		ui = self.make_ui(body=True)
		ui.render()
		phantoms = ui.phantoms.update.call_args.args[0]
		self.assertEqual([item[0] for item in phantoms], [0, 1, 2, 3, 4])
		self.assertIn('class="toolbar brand-cell"', phantoms[0][1])
		self.assertIn('class="toolbar controls-cell"', phantoms[1][1])
		# the brand cell is the bug icon with the package name as its tooltip, not a text label
		self.assertIn('<span class="brand" title="Debugger"><img class="icon ', phantoms[0][1])
		self.assertNotIn('>Debugger</span>', phantoms[0][1])
		# the tab row contains the session views, with the global Breakpoints control in the toolbar
		tabs = phantoms[2][1]
		self.assertIn('>Call Stack / Variables</a>', tabs)
		self.assertIn('>Watch</a>', tabs)
		self.assertLess(tabs.index('>Call Stack / Variables</a>'), tabs.index('>Watch</a>'))
		self.assertNotIn('Breakpoints', tabs)
		self.assertIn('class="breakpoints-control"', phantoms[1][1])
		self.assertIn('class="tab active"', tabs.split('>Call Stack / Variables</a>')[0].rsplit('<a', 1)[1])
		self.assertNotIn('>Console</a>', tabs)
		self.assertNotIn('>Terminal</a>', tabs)
		# two panes: call stack and variables; breakpoints and watch have tabs of their own
		self.assertIn('Call stack', phantoms[3][1])
		self.assertIn('pane columns first', phantoms[3][1])
		self.assertIn('Variables', phantoms[4][1])
		self.assertIn('pane columns last', phantoms[4][1])
		body = phantoms[3][1] + phantoms[4][1]
		self.assertNotIn('>Breakpoints (', body)
		self.assertNotIn('>Watch (', body)
		# the call stack takes a fifth of the width, the variables the rest
		style = self.loaded['_live_test.modules.ui.style']
		widths = [int(re.search(r'class="pane columns[^"]*" style="width:(\d+)px', item).group(1)) for item in (phantoms[3][1], phantoms[4][1])]
		stack = max(ui.total * style.STACK_SHARE, style.STACK_MIN)
		self.assertEqual(widths[0], ui.px(stack - 2 * style.PANE_PAD - 0.15))
		self.assertGreater(widths[1], 2 * widths[0])
		# a wide panel: the floor no longer applies and the split is the plain share
		self.view.viewport_extent.return_value = (2400, 400)
		ui.render()
		wide = ui.phantoms.update.call_args.args[0][3][1]
		width = int(re.search(r'class="pane columns[^"]*" style="width:(\d+)px', wide).group(1))
		self.assertEqual(width, ui.px(ui.total * style.STACK_SHARE - 2 * style.PANE_PAD - 0.15))

	def test_lone_pane_spans_the_panel_but_keeps_its_rows_narrow(self):
		style = self.loaded['_live_test.modules.ui.style']
		ui = self.make_ui(body=True, layout='breakpoints')
		ui.render()
		pane = ui.phantoms.update.call_args.args[0][3][1]
		self.assertGreater(ui.total, style.PANE_CONTENT)
		# the pane box is as wide as the panel...
		self.assertIn('style="width:{}px;'.format(ui.px(ui.total - 2 * style.PANE_PAD - 0.15)), pane)
		# ...its heading row is capped, so the icons at the end of each row stay near the text
		self.assertIn('style="width:{}px;"'.format(ui.px(style.PANE_CONTENT)), pane)

	def test_breakpoints_control_is_global_and_marks_the_bottom_control_active(self):
		ui = self.make_ui(body=True, layout='breakpoints')
		ui.render()
		phantoms = ui.phantoms.update.call_args.args[0]
		self.assertEqual([item[0] for item in phantoms], [0, 1, 2, 3])
		self.assertEqual(ui.state.tab, 'breakpoints')
		tabs = phantoms[2][1]
		self.assertNotIn('Breakpoints', tabs)
		self.assertIn('class="breakpoints-control active"', phantoms[1][1])
		pane = phantoms[3][1]
		self.assertIn('Breakpoints (0)', pane)
		self.assertIn('pane columns first last', pane)
		self.assertNotIn('Call stack', pane)
		self.assertNotIn('Watch', pane)

	def test_watch_tab_is_one_pane_without_variables(self):
		ui = self.make_ui(body=True, layout='watch')
		ui.render()
		phantoms = ui.phantoms.update.call_args.args[0]
		self.assertEqual([item[0] for item in phantoms], [0, 1, 2, 3])
		self.assertEqual(ui.state.tab, 'watch')
		pane = phantoms[3][1]
		self.assertIn('Watch (0)', pane)
		self.assertIn('Type an expression below and press enter', pane)
		self.assertNotIn('Variables', pane)
		self.assertNotIn('Call stack', pane)

	def test_tabs_open_the_panel_they_name(self):
		ui = self.make_ui(body=True)
		ui.toolbar.select_tab('breakpoints')
		self.backend.breakpoints_panel.open.assert_called_once_with()
		ui.toolbar.select_tab('watch')
		self.backend.watch_panel.open.assert_called_once_with()
		ui.toolbar.select_tab('debugger')
		self.backend.callstack.open.assert_called_once_with()

	def test_explicit_session_tabs_are_remembered_but_global_breakpoints_are_not(self):
		self.backend.project.configuration_tabs = {}
		self.backend.save_data = Mock()
		ui = self.make_ui(body=True)
		ui.toolbar.select_tab('debugger')
		self.assertEqual(self.backend.project.configuration_tabs, {})
		ui.toolbar.select_tab('breakpoints')
		self.assertEqual(self.backend.project.configuration_tabs, {})
		second = types.SimpleNamespace(name='Second', id_ish='config-2')
		self.backend.project.configuration_or_compound = second
		ui.toolbar.select_tab('watch')
		self.assertEqual(self.backend.project.configuration_tabs, {'config-2': 'watch'})
		ui.toolbar.select_tab('debugger', remember=False)
		self.assertEqual(self.backend.project.configuration_tabs['config-2'], 'watch')
		self.assertEqual(self.backend.save_data.call_count, 1)

	def test_configuration_switch_restores_each_saved_tab_or_uses_call_stack(self):
		first = types.SimpleNamespace(name='First', id_ish='config-1')
		second = types.SimpleNamespace(name='Second', id_ish='config-2')
		third = types.SimpleNamespace(name='Third', id_ish='config-3')
		self.backend.project.configurations = [first, second, third]
		self.backend.project.configuration_tabs = {'config-1': 'console', 'config-3': 'breakpoints'}
		picker_module = self.loaded['_live_test.modules.ui.configuration_picker']
		picker_module.configurations.select = Mock()
		ui = self.make_ui(body=True)
		ui.toolbar.select_tab = Mock()
		ui.state.tab = 'console'
		ui.toolbar.picker.select('config-1')
		ui.toolbar.select_tab.assert_called_once_with('console', remember=False)
		ui.toolbar.select_tab.reset_mock()
		ui.toolbar.picker.select('config-2')
		ui.toolbar.select_tab.assert_called_once_with('debugger', remember=False)
		ui.toolbar.select_tab.reset_mock()
		ui.toolbar.picker.select('config-3')
		ui.toolbar.select_tab.assert_called_once_with('debugger', remember=False)

	def test_switching_to_paused_configuration_keeps_its_call_stack_visible(self):
		first = types.SimpleNamespace(name='First', id_ish='config-1')
		second = types.SimpleNamespace(name='Second', id_ish='config-2')
		self.backend.project.configurations = [first, second]
		self.backend.project.configuration_or_compound = second
		self.backend.project.configuration_tabs = {'config-1': 'console', 'config-2': 'breakpoints'}
		self.backend.sessions = [
			types.SimpleNamespace(configuration=types.SimpleNamespace(name='First'), is_paused=True),
			types.SimpleNamespace(configuration=types.SimpleNamespace(name='Second'), is_paused=False),
		]
		picker_module = self.loaded['_live_test.modules.ui.configuration_picker']
		picker_module.configurations.select = Mock()
		ui = self.make_ui(body=True)
		ui.toolbar.select_tab = Mock()
		ui.toolbar.picker.select('config-1')
		ui.toolbar.select_tab.assert_called_once_with('debugger', remember=False)
		self.assertEqual(self.backend.project.configuration_tabs['config-1'], 'console')

	def test_watch_with_the_toolbar_in_the_strip_ends_in_a_line_of_input(self):
		strip_set, view_set = Mock(), Mock()
		self.sublime.PhantomSet = Mock(side_effect=[strip_set, view_set])
		self.sublime.LAYOUT_BELOW = 'below'
		strip = self.make_strip()
		self.view.size.return_value = 0
		ui = self.make_ui(body=True, header_view=strip, layout='watch')
		self.assertTrue(ui.input_line)
		# one anchor line per phantom, so the view can keep a legible font for the typed text
		callback = self.core.edit.call_args.args[1]
		callback(object())
		self.assertEqual(self.view.replace.call_args.args[-1], ' \n \n')
		self.assertEqual(ui.anchor_text, ' \n \n')
		applied = [call.args for call in self.view.settings().set.call_args_list]
		self.assertNotIn(('font_size', 2), applied)
		self.assertNotIn(('auto_complete', False), applied)
		self.assertIn(('margin', 0), applied)
		ui.render()
		# the toolbar in the strip, as on the other tabs, with the back arrow
		self.assertIn('Back to call stack', strip_set.update.call_args.args[0][0][1])
		# the view: the tab row, then the one pane, then a spacer under the pane's line and one
		# under the input line, so the input has air above and below it
		content = view_set.update.call_args.args[0]
		inline = self.sublime.LAYOUT_INLINE
		self.assertEqual([(item[0], item[3]) for item in content], [(0, inline), (2, inline), (3, 'below'), (4, 'below')])
		self.assertIn('class="tabs"', content[0][1])
		pane = content[1][1]
		self.assertIn('Watch (0)', pane)
		self.assertIn('Type an expression below and press enter', pane)
		self.assertIn('class="gap-large"', content[2][1])
		self.assertIn('height:{}px'.format(round(1.6 * ui.font)), content[3][1])
		# the pane is as tall as its rows, not the viewport and not an estimate of the rows either:
		# the input line follows right under the last row
		self.assertNotIn('height:', pane.split('</style>')[-1].split('>')[0])
		# the other dashboards keep filling the viewport
		self.sublime.PhantomSet = Mock(side_effect=[Mock(), Mock()])
		ui = self.make_ui(body=True, header_view=strip, layout='breakpoints')
		self.assertFalse(ui.input_line)
		ui.render()
		content = ui.view_phantoms.update.call_args.args[0]
		self.assertEqual([item[0] for item in content], [2, 3])
		self.assertGreater(int(re.search(r'height:(\d+)px', content[1][1]).group(1)), 300)

	def test_dashboard_anchors_use_separate_header_and_content_rows(self):
		self.view.size.return_value = 0
		self.make_ui(body=True)
		callback = self.core.edit.call_args.args[1]
		callback(object())
		self.assertEqual(self.view.replace.call_args.args[-1], ' \n\n  \n')

	def test_pane_height_reserves_room_for_header(self):
		ui = self.make_ui(body=True)
		ui.panes = Mock(return_value=[])
		ui.render()
		available = ui.panes.call_args.args[0]
		style = self.loaded['_live_test.modules.ui.style']
		self.assertLessEqual(available, 400 - ui.font * (style.TOOLBAR + style.TABS_HEIGHT))

	def test_narrow_dashboard_keeps_header_above_stacked_panes(self):
		self.view.viewport_extent.return_value = (500, 400)
		ui = self.make_ui(body=True)
		ui.render()
		phantoms = ui.phantoms.update.call_args.args[0]
		self.assertEqual([item[0] for item in phantoms], [0, 1, 2, 3])
		self.assertIn('pane stacked', phantoms[3][1])

	def test_dashboard_uses_output_panel_without_native_input_strip(self):
		tabs = Mock()
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=tabs)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		self.settings.console_minimum_height = 20
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.window.panels.return_value = []
		self.window.find_output_panel.return_value = None
		self.window.active_panel.return_value = None
		self.window.create_output_panel.return_value = self.view
		self.view.settings.return_value.get.side_effect = lambda key, default=None: 12 if key == 'font_size' else default
		panel = module.OutputPanel.__new__(module.OutputPanel)
		panel.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			module.OutputPanel.__init__(panel, self.backend, 'Dashboard', dashboard=True, unlisted=True)
		self.window.create_io_panel.assert_not_called()
		self.window.create_output_panel.assert_called_once_with('Dashboard', unlisted=True)
		self.assertIsNone(panel.input_view)
		tabs.assert_called_once_with(panel, self.view, body=True, header_view=None, layout='debugger')
		self.window.find_output_panel.side_effect = [self.view, None]
		self.assertEqual(panel._get_free_output_panel_name(self.window, 'Dashboard'), 'Dashboard 1')


if __name__ == '__main__':
	unittest.main()
