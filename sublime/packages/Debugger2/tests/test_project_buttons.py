from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class Region:
	def __init__(self, a, b=None):
		self.a = a
		self.b = a if b is None else b

	def begin(self):
		return min(self.a, self.b)


class FakeView:
	'''Just enough of `sublime.View`: a text buffer plus phantoms that keep their id until erased'''

	def __init__(self, text, window):
		self.text = text
		self._window = window
		self.phantoms = {}
		self.next_id = 100
		self.erased = []

	def id(self):
		return 7

	def file_name(self):
		return '/project/demo.sublime-project'

	def window(self):
		return self._window

	def style(self):
		return {'background': '#ffffff'}

	def find(self, pattern, start):
		match = re.compile(pattern).search(self.text, start)
		return Region(match.start(), match.end()) if match else None

	def line(self, region):
		start = self.text.rfind('\n', 0, region.begin()) + 1
		end = self.text.find('\n', region.begin())
		return Region(start, len(self.text) if end < 0 else end)

	def add_phantom(self, key, region, html, layout, on_navigate):
		self.next_id += 1
		self.phantoms[self.next_id] = (region, html, on_navigate)
		return self.next_id

	def erase_phantom_by_id(self, pid):
		self.erased.append(pid)
		self.phantoms.pop(pid, None)

	def query_phantom(self, pid):
		return [Region(self.phantoms[pid][0].a)] if pid in self.phantoms else []

	def erase_phantoms(self, key):
		self.erased.extend(sorted(self.phantoms))
		self.phantoms.clear()

	def click(self, pid):
		region, html, on_navigate = self.phantoms[pid]
		href = re.search(r'href="([^"]*)"', html).group(1)
		return on_navigate(href)


class ProjectButtonsTests(unittest.TestCase):
	def setUp(self):
		root = types.ModuleType('_pbt')
		root.__path__ = []
		self.menus = types.SimpleNamespace(show=Mock(), settings_options=lambda: ['options'], SETTINGS_CAPTION='Debugger settings')
		package = types.ModuleType('_pbt.modules')
		package.__path__ = []
		commands = types.ModuleType('_pbt.modules.commands')
		commands.__path__ = []
		commands_commands = types.ModuleType('_pbt.modules.commands.commands')
		commands_commands.ChangeConfiguration = object()
		core = types.ModuleType('_pbt.modules.core')
		core.run = lambda function: function
		core.Dispose = type('Dispose', (), {'dispose': lambda self: None})
		ui = types.ModuleType('_pbt.modules.ui')
		ui.__path__ = []

		class RawPhantom:
			def __init__(self, view, region, html, layout=1, on_navigate=None):
				self.view = view
				self.pid = view.add_phantom('debugger', region, html, layout, on_navigate)

			def dispose(self):
				self.view.erase_phantom_by_id(self.pid)

		ui.RawPhantom = RawPhantom
		ui.Image = object
		ui.Images = types.SimpleNamespace(shared=types.SimpleNamespace(**{
			name: types.SimpleNamespace(file_light=name + '-light.png', file_dark=name + '-dark.png')
			for name in ('settings', 'play', 'stop')
		}))
		ui_view = types.ModuleType('_pbt.modules.ui.view')
		ui_view.lightness_from_color = lambda color: 1.0
		self.settings = types.SimpleNamespace(project_file_buttons=True)
		settings = types.ModuleType('_pbt.modules.settings')
		settings.Settings = self.settings
		self.configurations = types.SimpleNamespace(
			running=lambda debugger: self.running, names=lambda debugger: list(self.names),
			start=Mock(), session_for=lambda debugger, name: self.sessions.get(name))
		self.debugger = types.SimpleNamespace(stop=AsyncMock(), run_action=Mock())
		debugger_module = types.ModuleType('_pbt.modules.debugger')
		debugger_module.Debugger = types.SimpleNamespace(get=lambda window: self.debugger)
		sublime = types.ModuleType('sublime')
		sublime.Region = Region
		sublime.LAYOUT_INLINE = 1
		sublime.load_binary_resource = lambda file: b'png'
		sublime.windows = lambda: []
		sublime_plugin = types.ModuleType('sublime_plugin')
		sublime_plugin.EventListener = object
		self.modules = patch.dict(sys.modules, {
			'_pbt': root, '_pbt.debugger_ui_menu': self.menus, '_pbt.modules': package, '_pbt.modules.commands': commands,
			'_pbt.modules.commands.commands': commands_commands, '_pbt.modules.core': core,
			'_pbt.modules.ui': ui, '_pbt.modules.ui.view': ui_view,
			'_pbt.modules.settings': settings, '_pbt.modules.configurations': self.configurations,
			'_pbt.modules.debugger': debugger_module, 'sublime': sublime, 'sublime_plugin': sublime_plugin,
		})
		self.modules.start()
		self.addCleanup(self.modules.stop)
		spec = importlib.util.spec_from_file_location('_pbt.modules.project_buttons', ROOT / 'modules' / 'project_buttons.py')
		self.module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = module = self.module
		spec.loader.exec_module(module)
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		self.module.ProjectButtons.views.clear()
		self.names = ['Agent Mac', 'Say "hi"']
		self.running = set()
		self.sessions = {}
		self.view = FakeView('{\n\t"debugger_configurations": [\n\t\t{\n\t\t\t"name": "Agent Mac",\n\t\t\t"type": "debugpy"\n\t\t},\n'
			'\t\t{\n\t\t\t"name": "Say \\"hi\\"",\n\t\t\t"type": "debugpy"\n\t\t}\n\t]\n}\n', window=Mock())

	def refresh(self):
		self.module.ProjectButtons.refresh(self.view)
		return self.module.ProjectButtons.views[self.view.id()]

	def hrefs(self):
		return [re.search(r'href="([^"]*)"', html).group(1) for _, html, _ in self.view.phantoms.values()]

	def test_activation_does_not_recreate_unchanged_icons(self):
		self.refresh()
		first = sorted(self.view.phantoms)
		self.assertEqual(len(first), 2)
		for _ in range(3):
			self.refresh()
		self.assertEqual(sorted(self.view.phantoms), first)
		self.assertEqual(self.view.erased, [])

	def test_icons_left_by_a_previous_plugin_instance_are_cleared_first(self):
		stale = self.view.add_phantom('debugger', Region(0), '<body>old</body>', 1, lambda href: None)
		self.refresh()
		self.assertNotIn(stale, self.view.phantoms)
		self.assertEqual(len(self.view.phantoms), 2)
		self.assertIn(stale, self.view.erased)

	def test_dispose_all_takes_every_icon_off_every_file(self):
		self.refresh()
		self.module.ProjectButtons.dispose_all()
		self.assertEqual(self.view.phantoms, {})
		self.assertEqual(self.module.ProjectButtons.views, {})

	def test_icons_are_redrawn_when_a_configuration_starts_or_stops(self):
		self.refresh()
		self.assertEqual(self.hrefs(), ['settings', 'run:0'])
		self.running = {'Agent Mac'}
		self.refresh()
		self.assertEqual(self.hrefs(), ['settings', 'stop:0'])
		self.assertEqual(len(self.view.erased), 2)
		self.running = set()
		self.refresh()
		self.assertEqual(self.hrefs(), ['settings', 'run:0'])

	def test_names_with_spaces_and_quotes_stay_out_of_the_link_and_still_start(self):
		self.names = ['Agent Mac', 'Say "hi"']
		self.view.text = self.view.text.replace('"Say \\"hi\\""', '"Say "hi""')
		buttons = self.refresh()
		html = ''.join(html for _, html, _ in self.view.phantoms.values())
		self.assertNotIn('Agent Mac', html)
		self.assertNotIn('Say', html)
		self.assertEqual(buttons.targets, ['Agent Mac', 'Say "hi"'])
		run_ids = [pid for pid, (_, html, _) in self.view.phantoms.items() if 'run:' in html]
		for pid, name in zip(run_ids, buttons.targets):
			asyncio.run(self.view.click(pid))
			self.configurations.start.assert_called_with(self.debugger, name)

	def test_click_on_a_running_configuration_stops_its_session(self):
		self.running = {'Agent Mac'}
		self.sessions = {'Agent Mac': object()}
		self.refresh()
		pid = next(pid for pid, (_, html, _) in self.view.phantoms.items() if 'stop:0' in html)
		asyncio.run(self.view.click(pid))
		self.debugger.stop.assert_awaited_once_with(self.sessions['Agent Mac'])

	def test_settings_icon_and_bad_links_do_not_start_anything(self):
		buttons = self.refresh()
		pid = next(pid for pid, (_, html, _) in self.view.phantoms.items() if 'settings' in html)
		asyncio.run(self.view.click(pid))
		# the settings icon opens the configuration quick panel, as the toolbar gear does
		self.debugger.run_action.assert_called_once()
		for href in ('run:9', 'run:x', 'stop:', 'other:0'):
			asyncio.run(buttons.navigate(href))
		self.configurations.start.assert_not_called()
		self.debugger.stop.assert_not_awaited()

	def test_disabled_setting_clears_icons_and_dispose_forgets_the_view(self):
		buttons = self.refresh()
		self.settings.project_file_buttons = False
		self.refresh()
		self.assertEqual(self.view.phantoms, {})
		self.settings.project_file_buttons = True
		self.refresh()
		self.assertEqual(len(self.view.phantoms), 2)
		buttons.dispose()
		self.assertEqual(self.view.phantoms, {})
		self.assertNotIn(self.view.id(), self.module.ProjectButtons.views)


if __name__ == '__main__':
	unittest.main()
