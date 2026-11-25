from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_live_ui as fixtures
from test_live_ui import ROOT, load_module


class SizedView:
	"""A panel's view, sized by `SizedWindow` when its panel is first shown"""

	def __init__(self, padding=0, strip=False):
		self.values = {'font_size': 16}
		self.padding = padding
		self.is_strip = strip
		self.height = None
		settings = Mock()
		settings.get.side_effect = lambda key, default=None: self.values.get(key, default)
		settings.set.side_effect = self.values.__setitem__
		self.settings = Mock(return_value=settings)
		for name in ('assign_syntax', 'set_read_only', 'sel', 'run_command', 'set_viewport_position'):
			setattr(self, name, Mock())

	def line_height(self):
		return 22 if self.is_strip else 1.2 * self.values['font_size'] + 2 * self.padding

	def viewport_extent(self):
		return (1000, 23 if self.is_strip else self.height or 0)

	def is_valid(self):
		return True


class SizedWindow:
	"""Sublime's panel sizing, as measured: a height once, at first show, and the workspace's say first

	A name with a height in the workspace gets that height back, strip included, whatever the
	font. Any other gets six lines of its font plus six pixels for the output, with the strip on
	top. Destroying a panel forgets a height given this session and keeps the workspace's.
	"""

	def __init__(self, saved=None, padding=0):
		self.saved = dict(saved or {})
		self.padding = padding
		self.panels = {}
		self.created = []
		self.active = None
		self.bring_to_front = Mock()
		self.focus_view = Mock()

	def is_valid(self):
		return True

	def active_panel(self):
		return self.active

	def find_output_panel(self, name):
		return self.panels.get(name, (None, None))[0]

	def create_output_panel(self, name, unlisted=False):
		self.panels[name] = (SizedView(self.padding), None)
		self.created.append(name)
		return self.panels[name][0]

	def create_io_panel(self, name, on_input, unlisted=False):
		self.panels[name] = (SizedView(self.padding), SizedView(strip=True))
		self.created.append(name)
		return self.panels[name]

	def destroy_output_panel(self, name):
		self.panels.pop(name, None)
		if self.active == 'output.' + name:
			self.active = None

	def run_command(self, command, args=None):
		if command == 'hide_panel':
			self.active = None
		elif command == 'show_panel':
			self.active = args['panel']
			view, strip = self.panels[args['panel'][len('output.'):]]
			if view.height is None:
				saved = self.saved.get(args['panel'][len('output.'):])
				view.height = saved - (23 if strip else 0) if saved else 6 * view.line_height() + 6


class PanelHeightTests(unittest.TestCase):
	setUp = fixtures.LiveTests.setUp

	def make_panel(self, name, io=False, padding=0):
		dependencies = dict(self.loaded, sublime_plugin=self.stubs.sublime_plugin)
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=Mock())
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		self.settings.console_minimum_height = 20
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.window.padding = padding
		panel = module.OutputPanel.__new__(module.OutputPanel)
		panel.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			module.OutputPanel.__init__(panel, self.backend, name, bottom_bar=io)
		return panel

	def test_the_first_panel_sets_the_height_and_later_ones_match_it_whatever_their_padding(self):
		self.window = SizedWindow()
		first = self.make_panel('Console', padding=5)
		# `console_minimum_height` lines by the scaling the debugger has always used
		self.assertAlmostEqual(first.total_height(), 6 * (1.2 * 16 * 21.75 / 5 + 10) + 6)
		self.assertAlmostEqual(self.backend.panel_height, first.total_height())
		# a dashboard has no line padding and a terminal its own: the same height all the same
		for name, padding in (('Dashboard', 0), ('Terminal', 8)):
			self.assertAlmostEqual(self.make_panel(name, padding=padding).total_height(), first.total_height())
		self.assertAlmostEqual(self.backend.panel_height, first.total_height())

	def test_the_strip_of_an_io_panel_counts_towards_the_height(self):
		self.window = SizedWindow()
		self.backend.panel_height = 500
		panel = self.make_panel('Console', io=True)
		self.assertAlmostEqual(panel.view.viewport_extent()[1] + 23, 500)
		self.assertAlmostEqual(panel.total_height(), 500)

	def test_a_name_with_a_stale_height_in_the_workspace_is_passed_over(self):
		# what a workspace looks like after a few weeks: every name dragged to a height of its own
		self.window = SizedWindow(saved={'Console': 469, 'Console 1': 431, 'Terminal': 622})
		self.backend.panel_height = 500
		console = self.make_panel('Console', io=True)
		self.assertEqual(console.panel_name, 'Console 2')
		self.assertAlmostEqual(console.total_height(), 500)
		terminal = self.make_panel('Terminal', io=True)
		self.assertEqual(terminal.panel_name, 'Terminal 1')
		self.assertAlmostEqual(terminal.total_height(), 500)
		# the throwaway panels the names were tried with are gone, and what was open is open again
		self.assertEqual(sorted(self.window.panels), ['Console 2', 'Terminal 1'])

	def test_a_name_whose_saved_height_is_the_one_wanted_is_used_again(self):
		self.window = SizedWindow(saved={'Console': 500})
		self.backend.panel_height = 500
		console = self.make_panel('Console', io=True)
		self.assertEqual(console.panel_name, 'Console')
		self.assertAlmostEqual(console.total_height(), 500)

	def test_with_no_height_to_match_the_first_panel_takes_a_fresh_name_not_a_remembered_height(self):
		self.window = SizedWindow(saved={'Console': 469})
		console = self.make_panel('Console')
		self.assertEqual(console.panel_name, 'Console 1')
		self.assertAlmostEqual(self.backend.panel_height, 6 * (1.2 * 16 * 21.75 / 5) + 6)

	def test_a_name_in_use_is_skipped_and_the_open_panel_is_shown_again_afterwards(self):
		self.window = SizedWindow()
		self.backend.panel_height = 500
		self.make_panel('Console')
		self.window.active = 'output.Console'
		second = self.make_panel('Console')
		self.assertEqual(second.panel_name, 'Console 1')

	def test_a_drag_sets_the_height_of_the_panels_created_after_it_and_a_tall_panel_does_not(self):
		self.window = SizedWindow()
		self.backend.save_data = Mock()
		panel = self.make_panel('Console')
		height = self.backend.panel_height
		# looked at and unchanged: nothing
		panel.track_height()
		self.assertEqual(self.backend.panel_height, height)
		# a panel that is taller than the rest without having been dragged keeps that to itself
		other = self.make_panel('Terminal')
		other.view.height = height + 200
		other.seen_height = other.view.height
		other.track_height()
		self.assertEqual(self.backend.panel_height, height)
		self.backend.save_data.assert_not_called()
		# the edge is dragged: the next panel is created at the new height, and it is kept
		panel.view.height = height - 120
		panel.track_height()
		self.assertAlmostEqual(self.backend.panel_height, height - 120)
		self.backend.save_data.assert_called_once()
		self.assertAlmostEqual(self.make_panel('Later', padding=3).total_height(), height - 120)


if __name__ == '__main__':
	unittest.main()
