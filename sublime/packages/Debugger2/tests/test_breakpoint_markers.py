from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch


class BreakpointMarkerTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		package = types.ModuleType('_breakpoint_marker_test')
		package.__path__ = []
		dap = types.ModuleType('_breakpoint_marker_test.dap')
		dap.__path__ = []
		session = types.ModuleType('_breakpoint_marker_test.dap.session')
		session.Session = type('Session', (), {})
		api = types.ModuleType('_breakpoint_marker_test.dap.api')
		api.SourceBreakpoint = lambda line, column, condition, hit, log: types.SimpleNamespace(
			line=line, column=column, condition=condition, hitCondition=hit, logMessage=log)
		core = types.ModuleType('_breakpoint_marker_test.core')
		core.run = lambda function: function
		core.wait_for_view_to_load = AsyncMock()
		core.JSON = dict
		ui = types.ModuleType('_breakpoint_marker_test.ui')
		cls.images = types.SimpleNamespace(**{
			name: types.SimpleNamespace(file=name + '.png')
			for name in ('dot', 'dot_disabled', 'dot_emtpy', 'dot_expr', 'dot_log')
		})
		ui.Images = types.SimpleNamespace(shared=cls.images)
		sublime = types.ModuleType('sublime')
		sublime.Region = lambda point: point
		sublime.HIDDEN = 1
		cls.modules = patch.dict(sys.modules, {
			'_breakpoint_marker_test': package,
			'_breakpoint_marker_test.dap': dap,
			'_breakpoint_marker_test.dap.session': session,
			'_breakpoint_marker_test.dap.api': api,
			'_breakpoint_marker_test.core': core,
			'_breakpoint_marker_test.ui': ui,
			'sublime': sublime,
		})
		cls.modules.start()
		root = Path(__file__).resolve().parents[1] / 'modules' / 'dap'
		for name in ('breakpoint', 'breakpoint_source'):
			spec = importlib.util.spec_from_file_location('_breakpoint_marker_test.dap.' + name, root / (name + '.py'))
			module = importlib.util.module_from_spec(spec)
			sys.modules[spec.name] = module
			spec.loader.exec_module(module)
		cls.source = module

	@classmethod
	def tearDownClass(cls):
		cls.modules.stop()

	def setUp(self):
		self.breakpoint = self.source.SourceBreakpoint(Mock(), 'sample.py', 5, None, True)

	def test_normal_breakpoint_uses_native_circle(self):
		self.assertEqual(self.breakpoint.gutter_icon, 'circle')
		self.assertEqual(self.breakpoint.scope(), 'region.redish.debugger')

	def test_disabled_breakpoint_is_circle_and_muted(self):
		self.breakpoint.enabled = False
		self.assertEqual(self.breakpoint.gutter_icon, 'circle')
		self.assertEqual(self.breakpoint.scope(), 'comment')

	def test_unverified_breakpoint_matches_enabled_size(self):
		enabled_icon = self.breakpoint.gutter_icon
		self.breakpoint._result = types.SimpleNamespace(verified=False, line=None, column=None)
		self.assertEqual(self.breakpoint.gutter_icon, enabled_icon)
		self.assertEqual(self.breakpoint.gutter_icon, 'circle')
		self.assertEqual(self.breakpoint.scope(), 'region.redish.debugger')

	def test_conditional_and_log_points_have_special_native_marker(self):
		for attribute in ('condition', 'hitCondition', 'logMessage'):
			with self.subTest(attribute=attribute):
				setattr(self.breakpoint.dap, attribute, 'value')
				self.assertEqual(self.breakpoint.gutter_icon, 'bookmark')
				self.assertEqual(self.breakpoint.scope(), 'region.redish.debugger')
				setattr(self.breakpoint.dap, attribute, None)

	def test_render_uses_native_icon_without_loading_png(self):
		view = Mock()
		view.text_point.return_value = 42
		marker = object.__new__(self.source.SourceBreakpointGutterPhantom)
		marker.breakpoint = self.breakpoint
		marker.view = view
		marker.disposed = False
		marker.column_phantom = None
		asyncio.run(marker.render())
		view.text_point.assert_called_once_with(4, 0)
		view.add_regions.assert_called_once_with(
			self.breakpoint.region_name, [42], scope='region.redish.debugger', icon='circle', flags=1)
		view.erase_regions.assert_called_once_with(self.breakpoint.region_name)

	def test_column_marker_is_the_gutter_shape_in_the_schemes_live_colour(self):
		self.source.ui.RawPhantom = Mock()
		view = Mock()
		view.text_point.side_effect = lambda row, column: row * 100 + column
		view.line_height.return_value = 30
		breakpoint = self.source.SourceBreakpoint(Mock(), 'sample.py', 5, 9, True)
		marker = object.__new__(self.source.SourceBreakpointGutterPhantom)
		marker.breakpoint, marker.view, marker.disposed, marker.column_phantom = breakpoint, view, False, None
		marker.on_click_inline = Mock()
		asyncio.run(marker.render())
		# the gutter marker as before, and the inline marker at the column
		view.add_regions.assert_called_once_with(breakpoint.region_name, [400], scope='region.redish.debugger', icon='circle', flags=1)
		phantom_view, region, html = self.source.ui.RawPhantom.call_args.args
		self.assertEqual((phantom_view, region), (view, 408))
		# a disc in the scheme's own variable, so it recolours with the scheme like the gutter icon;
		# no colour is read and baked in at draw time
		self.assertIn('color: var(--redish);', html)
		self.assertIn('>●</a>', html)
		self.assertIn('font-size: 15px;', html)
		view.style_for_scope.assert_not_called()
		# a conditional point takes a diamond for the gutter's bookmark, an unverified one a ring,
		# a disabled one the disc dimmed like the gutter's comment-coloured icon
		breakpoint.dap.condition = 'x > 1'
		self.assertIn('>◆</a>', marker.column_html())
		breakpoint.dap.condition = None
		breakpoint._result = types.SimpleNamespace(verified=False, line=None, column=None)
		self.assertIn('>○</a>', marker.column_html())
		breakpoint._result = None
		breakpoint.enabled = False
		html = marker.column_html()
		self.assertIn('>●</a>', html)
		self.assertIn('color: color(var(--foreground) alpha(0.45));', html)
		self.assertNotIn('--redish', html)

	def test_image_models_are_unchanged(self):
		self.assertIs(self.breakpoint.image, self.images.dot)
		self.breakpoint.dap.logMessage = 'value'
		self.assertIs(self.breakpoint.image, self.images.dot_log)
		self.breakpoint.enabled = False
		self.assertIs(self.breakpoint.image, self.images.dot_disabled)


if __name__ == '__main__':
	unittest.main()
