from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_live_ui as fixtures
from test_live_ui import ROOT, load_module


class Region:
	def __init__(self, a, b=None):
		self.a = a
		self.b = a if b is None else b

	def begin(self):
		return min(self.a, self.b)

	def end(self):
		return max(self.a, self.b)

	def empty(self):
		return self.a == self.b

	def size(self):
		return abs(self.b - self.a)

	def __eq__(self, other):
		return (self.a, self.b) == (other.a, other.b)

	def __repr__(self):
		return 'Region({}, {})'.format(self.a, self.b)


class Selection(list):
	def clear(self):
		del self[:]

	def add(self, region):
		self.append(region if isinstance(region, Region) else Region(region))

	def add_all(self, regions):
		self.extend(regions)


class BufferView:
	'''A view with a real buffer and selection; everything else is a mock'''

	def __init__(self, text):
		self.text = text
		self.selection = Selection()
		self.read_only = True
		settings = Mock()
		settings.get.side_effect = lambda key, default=None: 14 if key == 'font_size' else default
		self.settings = Mock(return_value=settings)
		for name in ('assign_syntax', 'show', 'run_command', 'set_viewport_position', 'window'):
			setattr(self, name, Mock())
		self.style = Mock(return_value={'background': '#fafafa', 'foreground': '#606060'})
		self.viewport_extent = Mock(return_value=(1200, 400))
		self.layout_extent = Mock(return_value=(1200, 400))
		self.viewport_position = Mock(return_value=(0, 0))
		self.em_width = Mock(return_value=1)
		self.lines = Mock(return_value=[])
		self.is_auto_complete_visible = Mock(return_value=False)
		self.regions = {}

	def add_regions(self, key, regions, scope='', icon='', flags=0):
		self.regions[key] = list(regions)

	def get_regions(self, key):
		return list(self.regions.get(key, []))

	def erase_regions(self, key):
		self.regions.pop(key, None)

	def type(self, text):
		'''Typing at the caret: the text goes in and the tracked regions after it move along, as in Sublime'''
		at = self.selection[0].b
		self.text = self.text[:at] + text + self.text[at:]
		for key, regions in self.regions.items():
			self.regions[key] = [Region(region.a + len(text), region.b + len(text)) if region.begin() >= at else region for region in regions]
		self.selection.clear()
		self.selection.add(at + len(text))

	def size(self):
		return len(self.text)

	def substr(self, region):
		return self.text[region.begin():region.end()]

	def replace(self, edit, region, text):
		self.text = self.text[:region.begin()] + text + self.text[region.end():]

	def insert(self, edit, point, text):
		self.text = self.text[:point] + text + self.text[point:]
		return len(text)

	def erase(self, edit, region):
		self.replace(edit, region, '')

	def sel(self):
		return self.selection

	def set_read_only(self, value):
		self.read_only = value

	def is_read_only(self):
		return self.read_only

	def is_valid(self):
		return True


class OutputHeaderTests(unittest.TestCase):
	setUp = fixtures.LiveTests.setUp
	make_ui = fixtures.LiveTests.make_ui
	make_strip = fixtures.LiveTests.make_strip

	def test_bottom_bar_header_is_drawn_inline_into_the_strip_and_tabs_above_the_output(self):
		strip = self.make_strip()
		strip_set, tabs_set = Mock(), Mock()
		self.sublime.PhantomSet = Mock(side_effect=[strip_set, tabs_set])
		ui = self.make_ui(header_view=strip)
		self.sublime.PhantomSet.assert_any_call(strip, 'debugger.live_ui')
		self.sublime.PhantomSet.assert_any_call(self.view, 'debugger.live_ui.view')
		ui.render()
		phantoms = strip_set.update.call_args.args[0]
		self.assertEqual(len(phantoms), 1)
		point, html, _, layout = phantoms[0]
		self.assertEqual((point, layout), (0, self.sublime.LAYOUT_INLINE))
		self.assertIn('toolbar joined strip', html)
		# the strip is one row: no brand label, no tabs block; a back arrow leads the row, ahead of the picker
		self.assertNotIn('class="brand"', html)
		self.assertNotIn('class="tabs"', html)
		self.assertNotIn('strip continued', html)
		self.assertNotIn('>Call Stack / Variables</a>', html)
		self.assertIn('Back to call stack', html)
		self.assertIn('class="breakpoints-control" title="Show breakpoints">Breakpoints</a>', html)
		self.assertLess(html.index('Back to call stack'), html.index('Select run configuration'))
		self.assertLess(html.index('Select run configuration'), html.index('Breakpoints'))
		self.assertLess(html.index('Breakpoints'), html.index('Debugger settings'))
		# the tab row is its own phantom above the output's first line, as on the other panels
		tabs = tabs_set.update.call_args.args[0]
		self.assertEqual(len(tabs), 1)
		point, html, _, layout = tabs[0]
		self.assertEqual((point, layout), (0, 3))
		self.assertIn('class="tabs"', html)
		self.assertIn('>Call Stack / Variables</a>', html)
		self.assertNotIn('Breakpoints', html)
		self.assertNotIn('class="toolbar', html)
		self.assertEqual(ui.width, 960)
		ui.keep_header_visible()
		self.view.set_viewport_position.assert_not_called()
		self.core.edit.assert_not_called()
		# closing clears both
		ui.dispose()
		strip_set.update.assert_called_with([])
		tabs_set.update.assert_called_with([])

	def test_bottom_bar_strip_font_is_scaled_until_the_strip_fits_the_header(self):
		strip = self.make_strip(height=22, font=12)
		ui = self.make_ui(header_view=strip)
		ui.render()
		wanted = ui.header_height
		self.assertAlmostEqual(wanted, 14 * 3.8 + 2)
		ui.fit_header()
		strip.settings().set.assert_called_with('font_size', round(12 * wanted / 22, 1))
		strip.settings().set.reset_mock()
		strip.viewport_extent.return_value = (1000, wanted + 1)
		ui.fit_header()
		strip.settings().set.assert_not_called()

	def test_prompt_strip_keeps_the_dashboard_on_screen_while_asking_for_text(self):
		tabs = Mock()
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=tabs)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		self.settings.console_minimum_height = 20
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.backend.watch = Mock()
		self.core.package_path_relative = lambda path: path
		self.window.find_output_panel.return_value = None
		self.window.active_panel.return_value = None
		strip = self.make_strip()
		strip.size.return_value = 0
		self.window.create_io_panel.return_value = (self.view, strip)
		self.view.settings().get.side_effect = lambda key, default=None: 14 if key == 'font_size' else default
		panel = module.OutputPanel.__new__(module.OutputPanel)
		panel.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			module.OutputPanel.__init__(panel, self.backend, 'Dashboard', dashboard=True, prompt_strip=True)
		self.assertIs(panel.prompt_view, strip)
		self.assertIs(module.OutputPanel.from_input_view[strip], panel)
		tabs.assert_called_once_with(panel, self.view, body=True, header_view=None, layout='debugger')
		strip.settings().set.assert_any_call('debugger.prompt', True)
		# the strip completes like the console's input line: a scope of its own for the trigger
		# characters, no buffer words or snippets, and the language server's items through the
		# listener; with no session to ask the empty list goes back at once
		strip.assign_syntax.assert_called_once_with('contributes/Syntax/DebuggerPrompt.sublime-syntax')
		strip.settings().set.assert_any_call('auto_complete', True)
		strip.settings().set.assert_any_call('auto_complete_selector', 'debugger.prompt')
		strip.settings().set.assert_any_call('auto_complete_include_snippets', False)
		strip.settings().set.assert_any_call('auto_complete_triggers', [{'selector': 'debugger.prompt', 'characters': '.['}])
		self.sublime.CompletionList = lambda completions=None, flags=0: ('completions', completions, flags)
		self.sublime.INHIBIT_EXPLICIT_COMPLETIONS = self.sublime.INHIBIT_REORDER = self.sublime.INHIBIT_WORD_COMPLETIONS = 8
		self.backend.session = None
		self.backend.session_panels = None
		strip.substr.return_value = 'settings.'
		sys.modules['_live_test.modules.lsp_completions'] = types.SimpleNamespace(request=Mock(side_effect=AssertionError('nothing to ask')))
		listener = module.OutputPanelEventListener()
		self.assertEqual(listener.on_query_completions(strip, '', [9]), ('completions', [], 8))
		self.assertIsNone(listener.on_query_completions(Mock(), '', [0]))
		# the empty strip carries the default caption as placeholder text
		hint = self.loaded['_live_test.modules.ui'].RawPhantom
		self.assertIn('Expression to watch', hint.call_args.args[2])
		# a prompt focuses the strip and routes enter to its callback, stripped
		received = []
		panel.prompt('Edit expression', 'old', received.append)
		self.window.focus_view.assert_called_with(strip)
		self.assertIn('Edit expression', hint.call_args.args[2])
		panel._on_prompt_input('  new value ')
		self.assertEqual(received, ['new value'])
		self.window.focus_view.assert_called_with(self.view)
		# with no prompt pending, enter adds a watch expression; a blank enter goes to the debug
		# console with its prompt ready, the way enter on the call stack does
		console = self.backend.console
		console.open, console.enable_input_mode, console.scroll_to_end = Mock(), Mock(), Mock()
		panel._on_prompt_input('  ')
		self.backend.watch.add.assert_not_called()
		console.open.assert_called_once()
		console.enable_input_mode.assert_called_once()
		panel._on_prompt_input('config.timeout')
		self.backend.watch.add.assert_called_once_with('config.timeout')
		# escape drops a pending prompt without calling back
		panel.prompt('Expression to watch', '', received.append)
		panel.cancel_prompt()
		panel._on_prompt_input('x')
		self.assertEqual(received, ['new value'])
		self.window.show_input_panel.assert_not_called()

	def test_watch_panel_takes_its_expression_on_a_line_under_the_rows(self):
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		live = types.SimpleNamespace(anchor_text=' \n \n', invalidate=Mock(), toolbar=Mock())
		tabs = Mock(return_value=types.SimpleNamespace(live=live, dispose=Mock()))
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=tabs)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		dependencies['_live_test.modules.output_panel'] = module
		self.dap.SourceLocation = object
		panels = load_module('_live_test.modules.output_panel_callstack', ROOT / 'modules/output_panel_callstack.py', dependencies)
		self.sublime.Region = Region
		self.sublime.HIDDEN = 128
		self.settings.console_minimum_height = 20
		self.settings.console_bar_position = 'bottom'
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.backend.watch = Mock()
		self.backend.session = None
		self.backend.session_panels = None
		self.core.package_path_relative = lambda path: path
		self.core.edit = lambda view, fn: fn(None)
		self.window.find_output_panel.return_value = None
		self.window.active_panel.return_value = None
		strip = self.make_strip()
		view = BufferView(' \n \n')
		self.window.create_io_panel.return_value = (view, strip)
		panel = panels.WatchOutputPanel.__new__(panels.WatchOutputPanel)
		panel.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			panels.WatchOutputPanel.__init__(panel, self.backend)
		# an io panel whose strip holds the toolbar, like the other dashboards; the prompt is the
		# last line of the view, after the phantom anchors, with a marker in front of it
		self.window.create_io_panel.assert_called_once()
		tabs.assert_called_once_with(panel, view, body=True, header_view=strip, layout='watch')
		self.assertIsNone(panel.prompt_view)
		self.assertTrue(panel.input_line)
		self.assertTrue(panel.has_prompt)
		self.assertFalse(panel.lock_selection)
		prefix = ' \n \n  › '
		caption = '\u200bExpression to watch'
		self.assertEqual(panel.input_start, len(prefix))
		# it completes like the prompt strip, on the prompt syntax's scope
		view.assign_syntax.assert_called_once_with('contributes/Syntax/DebuggerPrompt.sublime-syntax')
		applied = [call.args for call in view.settings().set.call_args_list]
		for setting in (('debugger.prompt', True), ('auto_complete', True), ('auto_complete_selector', 'debugger.prompt'),
			('auto_complete_include_snippets', False), ('auto_complete_triggers', [{'selector': 'debugger.prompt', 'characters': '.['}])):
			self.assertIn(setting, applied)
		# the caption stands on the empty line as dimmed text in a tracked region, the caret in front of it
		self.assertEqual(view.text, prefix + caption)
		self.assertEqual(view.get_regions('debugger.placeholder'), [Region(len(prefix), len(prefix) + len(caption))])
		self.assertEqual(list(view.sel()), [Region(len(prefix))])
		self.assertFalse(view.read_only)
		self.assertEqual(panel.input_text(), '')
		# the first keystroke takes the caption away; enter adds the expression and puts it back
		view.type('c')
		panel.on_modified()
		self.assertEqual(view.text, prefix + 'c')
		self.assertEqual(view.get_regions('debugger.placeholder'), [])
		self.assertEqual(list(view.sel()), [Region(len(prefix) + 1)])
		view.type('onfig.timeout')
		panel.on_modified()
		self.assertEqual(view.text, prefix + 'config.timeout')
		panel.enter()
		self.backend.watch.add.assert_called_once_with('config.timeout')
		self.assertEqual(view.text, prefix + caption)
		self.window.focus_view.assert_called_with(view)
		self.assertEqual(list(view.sel()), [Region(len(prefix))])
		# the edit button of a watch puts its expression on the line; enter answers the prompt
		received = []
		panel.prompt('Edit expression', 'old', received.append)
		self.assertEqual(view.text, prefix + 'old')
		self.assertEqual(list(view.sel()), [Region(len(prefix) + 3)])
		view.text = prefix + 'new'
		panel.on_modified()
		panel.enter()
		self.assertEqual(received, ['new'])
		self.backend.watch.add.assert_called_once()
		# a prompt with nothing to edit shows its own caption; escape drops it and the default comes back
		panel.prompt('Edit expression', '', received.append)
		self.assertEqual(view.text, prefix + '\u200bEdit expression')
		panel.cancel_prompt()
		self.assertEqual(view.text, prefix + caption)
		view.type('x')
		panel.on_modified()
		panel.enter()
		self.assertEqual(received, ['new'])
		self.backend.watch.add.assert_called_with('x')
		# a blank enter goes to the debug console with its prompt ready, as on the other tabs
		console = self.backend.console
		console.open, console.enable_input_mode, console.scroll_to_end = Mock(), Mock(), Mock()
		panel.enter()
		console.open.assert_called_once()
		console.enable_input_mode.assert_called_once()
		# an edit that reaches into the marker, or pastes a line break, is put right; deleting
		# everything brings the caption back
		for damaged, typed in ((prefix[:-1] + 'abc', 'abc'), (' \n \nabc', 'abc'), (prefix + 'a\nb', 'a b'), ('', '')):
			with self.subTest(damaged=damaged):
				view.text = damaged
				view.regions.clear()
				panel.on_modified()
				self.assertEqual(view.text, prefix + (typed or caption))
				self.assertEqual(list(view.sel()), [Region(len(prefix) + len(typed))])
		# a caption with its zero-width space deleted is a caption again, not an expression
		view.text = prefix + caption[1:]
		view.regions['debugger.placeholder'] = [Region(len(prefix), len(view.text))]
		panel.on_modified()
		self.assertEqual(view.text, prefix + caption)
		self.assertEqual(panel.input_text(), '')
		# the caret stays where typing goes: in front of the caption, at the end of typed text; a
		# click anywhere else lands there, and a selection stops at the text
		view.selection.clear()
		view.selection.add(Region(len(view.text)))
		panel.on_selection_modified()
		self.assertEqual(list(view.sel()), [Region(len(prefix))])
		view.text = prefix + 'abc'
		view.regions.clear()
		view.selection.clear()
		view.selection.add(Region(1))
		panel.on_selection_modified()
		self.assertEqual(list(view.sel()), [Region(len(view.text))])
		view.selection.clear()
		view.selection.add(Region(2, len(view.text)))
		panel.on_selection_modified()
		self.assertEqual(list(view.sel()), [Region(len(prefix), len(view.text))])
		self.assertFalse(view.read_only)
		# completion asks about what is typed on the line; with no session there is nothing to ask
		self.sublime.CompletionList = lambda completions=None, flags=0: ('completions', completions, flags)
		self.sublime.INHIBIT_EXPLICIT_COMPLETIONS = self.sublime.INHIBIT_REORDER = self.sublime.INHIBIT_WORD_COMPLETIONS = 8
		sys.modules['_live_test.modules.lsp_completions'] = types.SimpleNamespace(request=Mock(side_effect=AssertionError('nothing to ask')))
		view.text = prefix + 'settings.'
		self.assertEqual(panel.on_query_completions('', [len(view.text)]), ('completions', [], 8))
		self.window.show_input_panel.assert_not_called()
		# the view keeps a legible font, padded so the typed text lines up with the placeholder
		with patch.object(module.OutputPanel, 'update_settings'):
			panels.DashboardOutputPanel.update_settings(panel)
		applied = [call.args for call in view.settings().set.call_args_list]
		self.assertNotIn(('font_size', 2), applied)
		self.assertIn(('line_padding_top', 2), applied)
		self.assertIn(('line_padding_bottom', 2), applied)
		# with the toolbar above the tabs the strip is the prompt as before, and enter on the view moves to it
		self.settings.console_bar_position = 'top'
		other_strip = self.make_strip()
		other_strip.size.return_value = 0
		other_view = BufferView(' \n\n  \n')
		self.window.create_io_panel.return_value = (other_view, other_strip)
		other = panels.WatchOutputPanel.__new__(panels.WatchOutputPanel)
		other.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			panels.WatchOutputPanel.__init__(other, self.backend)
		self.assertIs(other.prompt_view, other_strip)
		self.assertFalse(other.input_line)
		self.assertTrue(other.has_prompt)
		self.assertTrue(other.lock_selection)
		self.assertEqual(other_view.text, ' \n\n  \n')
		with patch.object(module.OutputPanel, 'update_settings'):
			panels.DashboardOutputPanel.update_settings(other)
		applied = [call.args for call in other_view.settings().set.call_args_list]
		self.assertIn(('font_size', 2), applied)
		self.assertIn(('line_padding_top', 0), applied)
		other.enter()
		self.window.focus_view.assert_called_with(other_strip)

	def test_bottom_bar_console_uses_an_io_panel_with_a_read_only_strip(self):
		tabs = Mock()
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=tabs)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		self.settings.console_minimum_height = 20
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.window.find_output_panel.return_value = None
		self.window.active_panel.return_value = None
		strip = self.make_strip()
		self.window.create_io_panel.return_value = (self.view, strip)
		self.view.settings().get.side_effect = lambda key, default=None: 14 if key == 'font_size' else default
		panel = module.OutputPanel.__new__(module.OutputPanel)
		panel.update_settings = Mock()
		with patch.dict(sys.modules, dependencies):
			module.OutputPanel.__init__(panel, self.backend, 'Console', bottom_bar=True)
		self.window.create_io_panel.assert_called_once()
		self.assertEqual(self.window.create_io_panel.call_args.args[0], 'Console')
		self.window.create_output_panel.assert_not_called()
		self.assertIs(panel.input_view, strip)
		self.assertIs(module.OutputPanel.from_input_view[strip], panel)
		strip.set_read_only.assert_called_with(True)
		strip.settings().set.assert_any_call('gutter', False)
		tabs.assert_called_once_with(panel, self.view, body=False, header_view=strip, layout='debugger')

	def console_panel(self, session, bar_position):
		'''A `ConsoleOutputPanel` built over a stand-in base that records what it was asked for'''
		from unittest.mock import MagicMock

		class FakeOutputPanel:
			def __init__(self, debugger, panel_name, **kwargs):
				self.debugger, self.panel_name, self.kwargs = debugger, panel_name, kwargs
				self.view = MagicMock()

			def dispose_add(self, *args): ...

		self.settings.console_bar_position = bar_position
		self.core.package_path_relative = lambda path: path
		self.dap.Console = type('Console', (), {})
		self.dap.SourceLocation = type('SourceLocation', (), {})
		# the completion lookup is the base panel's; borrow it for the stand-in base
		real = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dict(self.loaded,
			sublime_plugin=self.preview.sublime_plugin, **{'_live_test.modules.output_panel_tabs': types.SimpleNamespace(OutputPanelTabsPhantom=Mock())}))
		for name in ('completion_session', 'completion_triggers', 'COMPLETION_TRIGGERS', 'language_server_completion_list'):
			setattr(FakeOutputPanel, name, getattr(real.OutputPanel, name))
		dependencies = dict(self.loaded)
		dependencies.update({
			'_live_test.modules.ansi': types.SimpleNamespace(ansi_colorize=lambda *args: ''),
			'_live_test.modules.output_window_protocol': types.SimpleNamespace(ProtocolConsoleWindow=Mock),
			'_live_test.modules.output_panel': types.SimpleNamespace(OutputPanel=FakeOutputPanel),
			'_live_test.modules.lsp_completions': types.SimpleNamespace(),
		})
		module = load_module('_live_test.modules.output_panel_console', ROOT / 'modules/output_panel_console.py', dependencies)
		with patch.object(module.ConsoleOutputPanel, 'clear'):
			return module.ConsoleOutputPanel(self.backend, session=session)

	def test_debug_console_keeps_its_toolbar_in_the_fixed_strip_like_a_configurations_console(self):
		self.settings.session_panels = True
		session = types.SimpleNamespace(name='Real service')
		# the debugger's own console (no session, with per configuration consoles on) and a
		# configuration's console both put the toolbar in the strip below the output
		self.assertTrue(self.console_panel(None, 'bottom').kwargs['bottom_bar'])
		self.assertTrue(self.console_panel(session, 'bottom').kwargs['bottom_bar'])
		# `top` keeps the header above the output for both
		self.assertFalse(self.console_panel(None, 'top').kwargs['bottom_bar'])
		self.assertFalse(self.console_panel(session, 'top').kwargs['bottom_bar'])

	def test_debug_console_completes_in_the_last_runs_frame_when_nothing_is_running(self):
		self.settings.session_panels = True
		self.settings.console_bar_position = 'bottom'
		self.backend.session = None
		frame = types.SimpleNamespace(line=128)
		ended = types.SimpleNamespace(name='ended', selected_frame=frame)
		run_console = types.SimpleNamespace(session=ended)
		record = types.SimpleNamespace(configuration_name='Real service', console_visible=True, console=run_console)
		self.backend.session_panels = types.SimpleNamespace(panels=[record])
		self.backend.output_panels = [run_console]
		debug_console = self.console_panel(None, 'bottom')
		# the debug console: no session of its own, none running, so the last run's frame
		self.assertIs(debug_console.completion_session(), ended)
		# a running session takes precedence
		live = types.SimpleNamespace(name='live', selected_frame=frame)
		self.backend.session = live
		self.assertIs(debug_console.completion_session(), live)
		# a configuration's console always asks in its own session
		own = types.SimpleNamespace(name='own', selected_frame=None)
		self.assertIs(self.console_panel(own, 'bottom').completion_session(), own)
		# a run that never paused has no frame to ask about
		self.backend.session = None
		run_console.session = types.SimpleNamespace(name='ended', selected_frame=None)
		self.assertIsNone(debug_console.completion_session())

	def test_a_blank_line_separates_one_evaluation_from_the_next(self):
		class FakeView:
			'''Just the buffer: the console always keeps one zero-width space at the very end'''
			def __init__(self, text):
				self.text = text
			def size(self):
				return len(self.text)
			def substr(self, region):
				return self.text[region[0]:region[1]]
			def insert(self, edit, at, text):
				self.text = self.text[:at] + text + self.text[at:]
				return len(text)
			def get_regions(self, key):
				return []
			def add_regions(self, key, regions):
				self.regions = regions
			def set_read_only(self, value):
				pass

		console = self.console_panel(None, 'bottom')
		console.edit = lambda fn: fn(None)
		console.scroll_to_end = lambda: None
		for before, after in (
			('​', '​'),                       # an empty console: nothing to separate from
			("'darwin'​", "'darwin'\n\n​"),   # a result with no newline yet: a break and a blank line
			('x\n​', 'x\n\n​'),               # output that ended its line: the blank line only
			('x\n\n​', 'x\n\n​'),             # already there: nothing more
		):
			with self.subTest(before=before):
				console.view = FakeView(before)
				console.ensure_blank_line()
				self.assertEqual(console.view.text, after)
		# the live prompt after the trailing zero-width character follows the same rule, so the
		# cursor waits on a line of its own below a blank one, where the echo will then be written
		for before, marker in (
			('​', '‌:'),                      # first line of an empty console
			("'darwin'​", '\n\n‌:'),
			('x\n​', '\n‌:'),
			('x\n\n​', '‌:'),
		):
			with self.subTest(prompt_after=before):
				console.view = FakeView(before)
				console.enable_input_mode()
				self.assertEqual(console.view.text, before + marker)
				self.assertEqual(console.input_size, len(marker))

	def test_header_does_not_change_native_buffer_font_selection_or_read_only_state(self):
		ui = self.make_ui()
		ui.render()
		self.core.edit.assert_not_called()
		self.view.replace.assert_not_called()
		self.view.set_read_only.assert_not_called()
		self.view.sel.assert_not_called()
		self.view.settings().set.assert_not_called()

	def test_native_header_is_one_above_line_phantom_at_buffer_start(self):
		ui = self.make_ui()
		ui.render()
		phantoms = ui.phantoms.update.call_args.args[0]
		self.assertEqual(len(phantoms), 1)
		point, html, _, layout = phantoms[0]
		self.assertEqual(point, 0)
		self.assertEqual(layout, 3)
		self.assertIn('toolbar joined', html)
		self.assertLess(html.index('toolbar joined'), html.index('class="tabs"'))

	def test_redraw_after_buffer_changes_keeps_anchor_zero_without_writing_text(self):
		ui = self.make_ui()
		ui.render()
		ui.invalidate()
		ui.render()
		self.assertEqual(ui.phantoms.update.call_args.args[0][0][0], 0)
		self.core.edit.assert_not_called()

	def test_short_terminal_output_keeps_header_visible_and_autoscroll_enabled(self):
		ui = self.make_ui()
		self.view.layout_extent.return_value = (1000, 150)
		self.view.viewport_extent.return_value = (1200, 400)
		self.view.viewport_position.return_value = (0, 100)
		self.view.settings().get.side_effect = lambda key, default=None: True if key == 'terminus_view' else default
		ui.keep_header_visible()
		self.view.set_viewport_position.assert_called_once_with((0, 0), False)
		self.view.settings().set.assert_called_once_with('terminus_view.viewport_y', 0)

	def test_long_output_keeps_its_scroll_position(self):
		ui = self.make_ui()
		self.view.layout_extent.return_value = (1000, 1000)
		self.view.viewport_extent.return_value = (1200, 400)
		self.view.viewport_position.return_value = (0, 600)
		ui.keep_header_visible()
		self.view.set_viewport_position.assert_not_called()

	def test_output_edits_refresh_header_and_terminal_cursor_restores_short_viewport(self):
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		ui = self.make_ui()
		panel = types.SimpleNamespace(tabs_phantom=types.SimpleNamespace(live=ui, invalidated_layout=Mock()),
			on_modified=Mock(), on_post_text_command=Mock())
		module.OutputPanel.from_view[self.view] = panel
		listener = module.OutputPanelEventListener()
		listener.on_modified(self.view)
		panel.tabs_phantom.invalidated_layout.assert_called_once()
		panel.on_modified.assert_called_once()
		listener.on_post_text_command(self.view, 'terminus_show_cursor', {})
		self.sublime.set_timeout.assert_any_call(ui.keep_header_visible)
		panel.tabs_phantom.invalidated_layout.reset_mock()
		ui.body = True
		listener.on_modified(self.view)
		panel.tabs_phantom.invalidated_layout.assert_not_called()

	def test_console_and_terminal_hosts_do_not_create_io_panels(self):
		tabs = Mock()
		dependencies = dict(self.loaded, sublime_plugin=self.preview.sublime_plugin)
		dependencies['_live_test.modules.output_panel_tabs'] = types.SimpleNamespace(OutputPanelTabsPhantom=tabs)
		module = load_module('_live_test.modules.output_panel', ROOT / 'modules/output_panel.py', dependencies)
		self.settings.console_minimum_height = 20
		self.backend.window = self.window
		self.backend.add_output_panel = Mock()
		self.window.find_output_panel.return_value = None
		self.window.active_panel.return_value = None
		self.window.create_output_panel.return_value = self.view
		self.view.settings().get.side_effect = lambda key, default=None: 14 if key == 'font_size' else default
		for name in ('Console', 'Terminal'):
			panel = module.OutputPanel.__new__(module.OutputPanel)
			panel.update_settings = Mock()
			with patch.dict(sys.modules, dependencies):
				module.OutputPanel.__init__(panel, self.backend, name)
			self.assertIsNone(panel.input_view)
			self.window.create_output_panel.assert_called_with(name, unlisted=False)
		self.window.create_io_panel.assert_not_called()


if __name__ == '__main__':
	unittest.main()
