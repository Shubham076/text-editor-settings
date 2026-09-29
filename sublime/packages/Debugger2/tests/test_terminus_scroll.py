from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path, modules):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, dict(modules, **{name: module})):
		spec.loader.exec_module(module)
	return module


class TerminusScrollTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		package = types.ModuleType('_terminus_scroll_test')
		package.__path__ = []
		modules = types.ModuleType('_terminus_scroll_test.modules')
		modules.__path__ = []
		sublime = types.ModuleType('sublime')
		cls.scheduled = []
		sublime.set_timeout = lambda callback, delay=0: cls.scheduled.append((callback, delay))
		sublime_plugin = types.ModuleType('sublime_plugin')
		sublime_plugin.TextCommand = type('TextCommand', (), {})

		class OutputPanel:
			def on_show_panel(self):
				self.base_show_called = True

		dependencies = {
			'_terminus_scroll_test': package,
			'_terminus_scroll_test.modules': modules,
			'_terminus_scroll_test.modules.core': types.SimpleNamespace(run=lambda fn: fn),
			'_terminus_scroll_test.modules.dap': types.SimpleNamespace(Error=Exception),
			'_terminus_scroll_test.modules.ui': types.SimpleNamespace(),
			'_terminus_scroll_test.modules.output_panel': types.SimpleNamespace(OutputPanel=OutputPanel),
			'sublime': sublime,
			'sublime_plugin': sublime_plugin,
		}
		cls.module = load_module(
			'_terminus_scroll_test.modules.output_panel_terminus',
			ROOT / 'modules/output_panel_terminus.py',
			dependencies,
		)

	def setUp(self):
		self.scheduled.clear()
		self.panel = self.module.TerminusOutputPanel.__new__(self.module.TerminusOutputPanel)
		self.panel.closed = False
		self.panel._follow_scroll_scheduled = False
		self.panel.view = Mock()
		self.panel.view.is_valid.return_value = True
		self.panel.is_open = Mock(return_value=True)

	def test_live_terminal_scrolls_directly_to_layout_bottom_after_output(self):
		self.panel.view.layout_extent.return_value = (1000, 1000)
		self.panel.view.viewport_position.return_value = (0, 600)
		self.panel.on_modified()
		self.assertEqual(len(self.scheduled), 1)
		self.panel.view.set_viewport_position.assert_not_called()
		self.scheduled[0][0]()
		self.panel.view.set_viewport_position.assert_called_once_with((0, 1000), False)
		self.panel.view.settings().set.assert_called_once_with('terminus_view.viewport_y', 600)

	def test_disposed_terminal_ignores_pending_scroll(self):
		self.panel.view.layout_extent.return_value = (1000, 1000)
		self.panel.view.viewport_position.return_value = (0, 600)
		self.panel.on_modified()
		self.panel.closed = True
		self.scheduled[0][0]()
		self.panel.view.set_viewport_position.assert_not_called()

	def test_hidden_terminal_keeps_following_and_scrolls_when_shown(self):
		self.panel.is_open.return_value = False
		self.panel.view.layout_extent.return_value = (1000, 1000)
		self.panel.view.viewport_position.return_value = (0, 0)
		self.panel.on_modified()
		self.assertEqual(self.scheduled, [])
		self.panel.is_open.return_value = True
		self.panel.on_show_panel()
		self.assertTrue(self.panel.base_show_called)
		self.scheduled[0][0]()
		self.panel.view.set_viewport_position.assert_called_once_with((0, 1000), False)

	def test_terminal_buffer_updates_schedule_one_follow_after_layout(self):
		self.panel.view.layout_extent.return_value = (1000, 1000)
		self.panel.view.viewport_position.return_value = (0, 600)
		self.panel.on_modified()
		self.panel.on_modified()
		self.assertEqual(len(self.scheduled), 1)
		self.scheduled[0][0]()
		self.panel.view.set_viewport_position.assert_called_once()


if __name__ == '__main__':
	unittest.main()
