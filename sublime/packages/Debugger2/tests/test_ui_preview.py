from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


def load_preview():
	sublime = types.ModuleType('sublime')
	sublime_plugin = types.ModuleType('sublime_plugin')
	sublime_plugin.WindowCommand = type('WindowCommand', (), {})
	sublime_plugin.EventListener = type('EventListener', (), {})
	sublime_plugin.TextCommand = type('TextCommand', (), {})
	sublime.Region = lambda point: point
	sublime.LAYOUT_BLOCK = 1
	sublime.LAYOUT_INLINE = 0
	sublime.Phantom = lambda region, content, layout, navigate: (region, content, navigate, layout)
	sublime.PhantomSet = lambda *args: Mock()
	sublime.set_timeout = Mock()
	sublime.load_settings = lambda name: types.SimpleNamespace(get=lambda key, default=None: 16 if key == 'font_size' else default)
	path = Path(__file__).resolve().parents[1] / 'debugger_ui_preview.py'
	package = types.ModuleType('_debugger_ui_preview_test')
	package.__path__ = [str(path.parent)]
	ui_package = types.ModuleType('_debugger_ui_preview_test.modules.ui')
	ui_package.__path__ = [str(path.parent / 'modules' / 'ui')]
	spec = importlib.util.spec_from_file_location('_debugger_ui_preview_test.debugger_ui_preview', path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, {'sublime': sublime, 'sublime_plugin': sublime_plugin, package.__name__: package,
		'_debugger_ui_preview_test.modules.ui': ui_package, spec.name: module}):
		spec.loader.exec_module(module)
	return module


class PreviewTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.module = load_preview()

	def setUp(self):
		self.state = self.module.PreviewState()

	def test_transport_is_simulated_and_configuration_local(self):
		self.assertEqual(self.state.session.status, 'Paused')
		self.state.transport('continue')
		self.assertEqual(self.state.session.status, 'Running')
		self.state.select_configuration('worker')
		self.assertEqual(self.state.session.status, 'Running')
		self.state.transport('stop')
		self.state.select_configuration('api')
		self.assertEqual(self.state.session.status, 'Running')
		self.state.transport('pause')
		self.assertEqual(self.state.session.status, 'Paused')

	def test_step_only_advances_paused_session(self):
		self.state.step()
		self.assertEqual(self.state.session.steps, 1)
		self.state.transport('continue')
		self.state.step()
		self.assertEqual(self.state.session.steps, 1)
		self.state.transport('restart')
		self.assertEqual(self.state.session.steps, 0)
		self.assertEqual(self.state.session.status, 'Paused')

	def test_instances_do_not_share_mutable_data(self):
		other = self.module.PreviewState()
		self.state.watches.append('custom')
		self.state.breakpoints[0]['enabled'] = False
		self.state.expanded.add('custom')
		self.assertNotIn('custom', other.watches)
		self.assertTrue(other.breakpoints[0]['enabled'])
		self.assertNotIn('custom', other.expanded)

	def test_unknown_expressions_are_not_evaluated(self):
		self.assertEqual(self.state.evaluate('__import__("os").system("bad")'), ('Not in sample data', 'muted'))
		self.assertEqual(self.state.evaluate('request.method'), ('"GET"', 'string'))
		self.state.transport('stop')
		self.assertEqual(self.state.evaluate('request.method'), ('Unavailable while stopped', 'muted'))

	def test_terminals_can_be_closed_and_reopened(self):
		preview = self.make_preview()
		preview.render()
		preview.close_terminal(0)
		self.assertEqual(self.state.terminals, ['zsh · worker'])
		self.assertEqual(self.state.terminal, 0)
		preview.close_terminal(0)
		self.assertEqual(self.state.terminals, [])
		self.state.tab = 'terminal'
		preview.render()
		html = preview.phantoms.update.call_args[0][0][3][1]
		self.assertIn('No terminals', html)
		preview.add_terminal()
		self.assertEqual(self.state.terminal, 0)

	def test_unknown_configuration_is_ignored(self):
		self.state.select_configuration('missing')
		self.assertEqual(self.state.configuration, 'api')

	def make_preview(self, width=1200, foreground='#d8dee9'):
		preview = self.module.DebuggerUiPreview.__new__(self.module.DebuggerUiPreview)
		preview.state = self.state
		preview.view = Mock()
		preview.view.style.return_value = {'foreground': foreground, 'background': '#20242c', 'bluish': '#343e5e', 'redish': '#9b362b', 'selection': '#3b4252', 'accent': '#88c0d0'}
		preview.view.viewport_extent.return_value = (width, 500)
		preview.view.em_width.return_value = 8
		preview.view.settings.return_value.get.side_effect = lambda key, default=None: default
		preview.view.is_valid.return_value = True
		preview.window = Mock()
		preview.phantoms = Mock()
		preview.menu = None
		preview.closed = False
		preview.generation = 0
		preview.handlers = {}
		preview.signature = None
		preview.message = 'Sample data only'
		return preview

	def test_every_tab_renders_and_links_have_handlers(self):
		preview = self.make_preview()
		for tab, _, _ in self.module.TABS:
			self.state.tab = tab
			preview.render()
			phantoms = preview.phantoms.update.call_args[0][0]
			self.assertEqual(len(phantoms), 7 if tab == 'debugger' else 5)
			self.assertEqual([phantom[0] for phantom in phantoms], [0, 1, 2, 3, 4, 5, 6] if tab == 'debugger' else [0, 1, 2, 3, 6])
			self.assertIn('debugger-ui-preview', phantoms[0][1])
			self.assertNotIn('<script', phantoms[3][1])
			self.assertTrue(preview.handlers)

	def test_icons_are_theme_tinted_images(self):
		preview = self.make_preview()
		preview.render()
		html = ''.join(phantom[1] for phantom in preview.phantoms.update.call_args[0][0])
		self.assertIn('<img class="icon', html)
		self.assertIn('data:image/png;base64,', html)
		# the primary icon is the plain text colour, not the accent; the background marks it
		self.assertEqual(preview.tint('primary'), preview.palette['foreground'])
		self.assertNotEqual(preview.tint('primary'), '#88c0d0')
		self.assertIn('background-color: #3b4252', html)
		self.assertNotIn('$selection', html)
		self.assertEqual(preview.tint('danger'), '#9b362b')
		self.assertNotEqual(preview.icon('play', 'primary'), preview.icon('play', 'danger'))
		other = self.make_preview(foreground='#ffffff')
		other.render()
		self.assertNotEqual(preview.icon('close', 'muted'), other.icon('close', 'muted'))
		png = self.module.icon_data_uri('settings', '#000000', 24)
		self.assertTrue(png.startswith('data:image/png;base64,iVBORw0KGgo'))

	def test_disabled_control_has_no_click_handler(self):
		preview = self.make_preview()
		preview.render()
		count = len(preview.handlers)
		html = preview.button('over', 'Step over', Mock(), enabled=False)
		self.assertNotIn('href=', html)
		self.assertIn('unavailable', html)
		self.assertEqual(len(preview.handlers), count)

	def test_tabs_remain_labeled_in_narrow_panel(self):
		preview = self.make_preview(500)
		preview.render()
		header = preview.phantoms.update.call_args[0][0][2][1]
		for _, label, _ in self.module.TABS:
			self.assertIn('>{}</a>'.format(label), header)
		self.assertIn('class="underline"', header)

	def test_dropdown_only_selects_sample_data(self):
		preview = self.make_preview()
		preview.render()
		preview.dropdown = types.SimpleNamespace(Option=lambda *args: args)
		preview.font = 14
		preview.floating_dropdown = types.SimpleNamespace(show=Mock(return_value=types.SimpleNamespace(closed=False, close=Mock())))
		preview.choose_configuration()
		args, kwargs = preview.floating_dropdown.show.call_args
		self.assertIs(args[0], preview.view)
		self.assertEqual([option[0] for option in args[1]], ['api', 'worker', 'tests'])
		self.assertEqual(kwargs['selected'], 'api')
		self.assertEqual(kwargs['location'], self.module.BRAND_ANCHOR)
		self.assertEqual([option[4] for option in args[1]], ['Paused', 'Running', 'Stopped'])
		self.assertEqual(kwargs['action'][0], 'Edit configurations')
		kwargs['on_select']('worker')
		self.assertEqual(preview.state.configuration, 'worker')
		preview.window.run_command.assert_not_called()
		preview.choose_configuration()
		preview.menu.close.assert_called_once()

	def test_metrics_are_integral_and_all_headings_share_baseline_wrapper(self):
		for font in (12, 18, 24):
			preview = self.make_preview()
			preview.view.settings.return_value.get.side_effect = lambda key, default=None, font=font: font if key == 'font_size' else default
			preview.render()
			self.assertIsInstance(preview.font, int)
			html = ''.join(phantom[1] for phantom in preview.phantoms.update.call_args[0][0])
			self.assertNotIn('$', html.split('</style>')[0])
			self.assertNotIn('width:-', html)
			self.assertNotIn('height:-', html)
			self.assertIn('<div class="section-title"><span>&#8203;</span><span class="slot ', html)

	def test_icon_control_dimensions_match_in_enabled_and_disabled_states(self):
		preview = self.make_preview()
		preview.render()
		enabled = preview.button('over', 'Step over', Mock())
		disabled = preview.button('over', 'Step over', Mock(), enabled=False)
		self.assertIn('class="icon-button ', enabled)
		self.assertIn('class="icon-button disabled ', disabled)
		self.assertEqual(enabled.split('>')[0], disabled.split('>')[0])
		size = 'style="width:{0}px;height:{0}px;"'.format(preview.px(1.2))
		self.assertIn(size, enabled)
		self.assertIn(size, disabled)

	def test_watch_text_and_attributes_are_escaped(self):
		preview = self.make_preview()
		self.state.watches = ['<img src=x>"&']
		preview.render()
		html = ''.join(phantom[1] for phantom in preview.phantoms.update.call_args[0][0])
		self.assertIn('&lt;img src=x&gt;&quot;&amp;', html)
		self.assertNotIn('<img src=x>', html)

	def test_stale_and_disposed_callbacks_are_ignored(self):
		preview = self.make_preview()
		preview.render()
		generation = preview.generation
		callback = Mock()
		preview.handlers['test'] = callback
		preview.navigate(generation - 1, 'test')
		callback.assert_not_called()
		preview.navigate(generation, 'test')
		callback.assert_called_once()
		preview.closed = True
		preview.navigate(generation, 'test')
		callback.assert_called_once()

	def test_narrow_and_wide_layouts(self):
		for width, expected in ((1200, 'columns'), (500, 'stacked')):
			preview = self.make_preview(width)
			preview.render()
			html = preview.phantoms.update.call_args[0][0][3][1]
			self.assertIn('class="pane {}'.format(expected), html)


if __name__ == '__main__':
	unittest.main()
