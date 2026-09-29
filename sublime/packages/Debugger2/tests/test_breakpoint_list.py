from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class BreakpointListTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.nodes = []

		class Node:
			def __init__(self, *args, **kwargs):
				self.kwargs = kwargs
				cls.nodes.append(self)

			def html_tag_and_attrbutes(self):
				return 'a', 'href="toggle"'

		package = types.ModuleType('_breakpoint_list_test')
		package.__path__ = []
		views = types.ModuleType('_breakpoint_list_test.views')
		views.__path__ = []
		cls.ui = types.ModuleType('_breakpoint_list_test.ui')
		cls.ui.div = cls.ui.span = Node
		cls.ui.icon = Mock()
		cls.ui.text = Mock()
		cls.ui.spacer = Mock()
		cls.images = types.SimpleNamespace(**{name: object() for name in
			('dot', 'dot_disabled', 'dot_emtpy', 'dot_expr', 'dot_log')})
		cls.ui.Images = types.SimpleNamespace(shared=cls.images)
		cls.dap = types.ModuleType('_breakpoint_list_test.dap')
		for name in ('SourceBreakpoint', 'DataBreakpoint', 'FunctionBreakpoint', 'ExceptionBreakpointsFilter'):
			setattr(cls.dap, name, type(name, (), {}))
		cls.dap.SourceLocation = types.SimpleNamespace(from_path=Mock(return_value='location'))
		core = types.ModuleType('_breakpoint_list_test.core')
		core.Dispose = type('Dispose', (), {})
		core.run = lambda function: function
		css = types.ModuleType('_breakpoint_list_test.views.css')
		css.secondary, css.button = object(), object()
		cls.modules = patch.dict(sys.modules, {
			'_breakpoint_list_test': package,
			'_breakpoint_list_test.views': views,
			'_breakpoint_list_test.ui': cls.ui,
			'_breakpoint_list_test.dap': cls.dap,
			'_breakpoint_list_test.core': core,
			'_breakpoint_list_test.views.css': css,
		})
		cls.modules.start()
		path = Path(__file__).resolve().parents[1] / 'modules' / 'views' / 'breakpoints.py'
		spec = importlib.util.spec_from_file_location('_breakpoint_list_test.views.breakpoints', path)
		cls.view_module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = cls.view_module
		spec.loader.exec_module(cls.view_module)

	@classmethod
	def tearDownClass(cls):
		cls.modules.stop()

	def setUp(self):
		self.nodes.clear()
		self.ui.icon.reset_mock()
		self.ui.text.reset_mock()
		self.dap.SourceLocation.from_path.reset_mock()
		self.breakpoint = self.dap.SourceBreakpoint()
		self.breakpoint.enabled = True
		self.breakpoint.image = self.images.dot
		self.breakpoint.name = self.breakpoint.file = 'main.py'
		self.breakpoint.line = 37
		self.breakpoint.column = None
		self.breakpoint.tag = '37'
		self.manager = Mock()
		self.navigate = Mock()

	def render(self):
		view = self.view_module.BreakpointView(self.manager, self.breakpoint, self.navigate)
		view.render()
		return view

	def test_enabled_marker_uses_theme_red_text_not_png(self):
		self.render()
		self.ui.icon.assert_not_called()
		marker = next(node for node in self.nodes if isinstance(node, self.view_module.BreakpointGlyph))
		content = marker.html(100, 100)
		self.assertIn('var(--redish)', content)
		self.assertIn('&#9679;', content)
		self.assertNotIn('<img', content)
		self.assertEqual(marker.width, 3)
		marker.kwargs['on_click']()
		self.manager.source.toggle_enabled.assert_called_once_with(self.breakpoint)
		self.ui.text.call_args_list[0].kwargs['on_click']()
		self.dap.SourceLocation.from_path.assert_called_once_with('main.py', 37, None)
		self.navigate.assert_called_once_with('location')

	def test_enabled_glyphs_preserve_special_states(self):
		for image, entity in ((self.images.dot_emtpy, '&#9675;'), (self.images.dot_expr, '&#9673;'),
		                      (self.images.dot_log, '&#9670;')):
			with self.subTest(entity=entity):
				self.breakpoint.image = image
				marker = self.view_module.BreakpointGlyph(self.breakpoint, lambda: None)
				self.assertIn(entity, marker.html(100, 100))
				self.assertEqual(marker.width, 3)

	def test_disabled_marker_keeps_existing_image(self):
		self.breakpoint.enabled = False
		self.breakpoint.image = self.images.dot_disabled
		view = self.render()
		self.ui.icon.assert_called_once_with(self.images.dot_disabled, on_click=view._on_toggle)
		self.assertFalse(any(isinstance(node, self.view_module.BreakpointGlyph) for node in self.nodes))

	def test_exception_filter_uses_red_glyph_and_filter_toggle(self):
		filter = self.dap.ExceptionBreakpointsFilter()
		filter.enabled, filter.image, filter.name, filter.tag = True, self.images.dot, 'Uncaught Exceptions', None
		view = self.view_module.BreakpointView(self.manager, filter, self.navigate)
		view.render()
		marker = next(node for node in self.nodes if isinstance(node, self.view_module.BreakpointGlyph))
		self.assertIn('var(--redish)', marker.html(100, 100))
		marker.kwargs['on_click']()
		self.manager.filters.toggle_enabled.assert_called_once_with(filter)


if __name__ == '__main__':
	unittest.main()
