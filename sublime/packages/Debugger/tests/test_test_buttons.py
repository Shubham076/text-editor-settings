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
sys.path.insert(0, str(ROOT / 'tests'))

from test_project_buttons import FakeView, Region  # noqa: E402

GO = '''package plugin

/*
func TestInAComment(t *testing.T) {}
*/

func TestPlugin(t *testing.T) {
	run()
}

func helper() {}

func TestOther(t *testing.T) {
}
'''


class FakeSourceView(FakeView):
	def __init__(self, text, window, file='/src/plugin/plugin_test.go'):
		super().__init__(text, window)
		self.file = file
		self.dirty = False
		self.commands = []

	def file_name(self):
		return self.file

	def size(self):
		return len(self.text)

	def substr(self, region):
		return self.text[region.a:region.b]

	def line(self, at):
		return super().line(Region(at) if isinstance(at, int) else at)

	def match_selector(self, point, selector):
		return self.text.rfind('/*', 0, point) > self.text.rfind('*/', 0, point)

	def is_dirty(self):
		return self.dirty

	def is_valid(self):
		return True

	def run_command(self, command):
		self.commands.append(command)


def load(name, file):
	spec = importlib.util.spec_from_file_location(name, file)
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


class TestButtonsTests(unittest.TestCase):
	def setUp(self):
		root = types.ModuleType('_tbt')
		root.__path__ = []
		package = types.ModuleType('_tbt.modules')
		package.__path__ = []
		core = types.ModuleType('_tbt.modules.core')
		core.run = lambda function: function
		core.exception = Mock()

		class Dispose:
			def __init__(self):
				pass

			def dispose(self):
				pass

		core.Dispose = Dispose
		ui = types.ModuleType('_tbt.modules.ui')
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
		ui_icons = types.ModuleType('_tbt.modules.ui.icons')
		ui_icons.icon_data_uri = lambda name, colour, size: 'data:drawn-{}-{}'.format(name, colour)
		ui_view = types.ModuleType('_tbt.modules.ui.view')
		ui_view.lightness_from_color = lambda color: 1.0
		self.settings = types.SimpleNamespace(project_file_buttons=True, test_buttons=True, test_configurations={'go': {'env': {'A': '1'}}})
		settings = types.ModuleType('_tbt.modules.settings')
		settings.Settings = self.settings
		self.running = set()
		self.sessions = {}
		self.configurations = types.SimpleNamespace(
			running=lambda debugger: self.running, names=lambda debugger: [],
			start=Mock(), session_for=lambda debugger, name: self.sessions.get(name))
		self.debugger = types.SimpleNamespace(
			stop=AsyncMock(), start=AsyncMock(), console=Mock(), project=types.SimpleNamespace(add_transient=Mock()))
		self.get = Mock(return_value=self.debugger)
		debugger_module = types.ModuleType('_tbt.modules.debugger')
		debugger_module.Debugger = types.SimpleNamespace(get=self.get)
		dap = types.ModuleType('_tbt.modules.dap')
		dap.Configuration = types.SimpleNamespace(from_json=lambda json, index: ('configuration', json, index))
		commands = types.ModuleType('_tbt.modules.commands')
		commands.__path__ = []
		self.timeouts = []
		project = types.ModuleType('_tbt.modules.project')
		project.read_project_data = lambda window: window.project_data()
		sublime = types.ModuleType('sublime')
		sublime.Region = Region
		sublime.LAYOUT_INLINE = 1
		sublime.load_binary_resource = lambda file: b'png'
		sublime.windows = lambda: []
		sublime.set_timeout = lambda function, delay=0: self.timeouts.append(function)
		sublime_plugin = types.ModuleType('sublime_plugin')
		sublime_plugin.EventListener = object
		self.modules = patch.dict(sys.modules, {
			'_tbt': root, '_tbt.modules': package, '_tbt.modules.core': core, '_tbt.modules.ui': ui,
			'_tbt.modules.ui.view': ui_view, '_tbt.modules.ui.icons': ui_icons, '_tbt.modules.settings': settings, '_tbt.modules.dap': dap,
			'_tbt.modules.configurations': self.configurations, '_tbt.modules.debugger': debugger_module,
			'_tbt.modules.commands': commands, '_tbt.modules.project': project, 'sublime': sublime, 'sublime_plugin': sublime_plugin,
		})
		self.modules.start()
		self.addCleanup(self.modules.stop)
		for name in ('test_runner', 'project_buttons', 'test_buttons'):
			module = load('_tbt.modules.' + name, ROOT / 'modules' / (name + '.py'))
			setattr(package, name, module)
		self.module = sys.modules['_tbt.modules.test_buttons']
		self.module.TestButtons.views.clear()
		self.module.TestButtons.pending.clear()
		self.window = Mock()
		self.window.project_data.return_value = {'debugger_test_configurations': {'go': {'env': {'B': '2'}}}}
		self.view = FakeSourceView(GO, self.window)

	def refresh(self):
		self.module.TestButtons.refresh(self.view)
		return self.module.TestButtons.views[self.view.id()]

	def hrefs(self):
		return [re.search(r'href="([^"]*)"', html).group(1) for _, html, _ in self.view.phantoms.values()]

	def click(self, href):
		pid = next(pid for pid, (_, html, _) in self.view.phantoms.items() if f'"{href}"' in html)
		asyncio.run(self.view.click(pid))

	def test_an_icon_at_the_head_of_each_test_and_nowhere_else(self):
		buttons = self.refresh()

		self.assertEqual(buttons.targets, ['TestPlugin', 'TestOther'])
		self.assertEqual(self.hrefs(), ['run:0', 'run:1'])
		at = [region.a for region, _, _ in self.view.phantoms.values()]
		self.assertEqual(at, [GO.index('func TestPlugin'), GO.index('func TestOther')])

	def test_other_files_get_nothing(self):
		self.view.file = '/src/plugin/plugin.go'
		self.module.TestButtons.refresh(self.view)

		self.assertEqual(self.view.phantoms, {})
		self.assertEqual(self.module.TestButtons.views, {})

	def test_icons_do_not_need_a_debugger(self):
		self.get.return_value = None
		self.refresh()

		self.assertEqual(self.hrefs(), ['run:0', 'run:1'])

	def test_other_phantoms_of_the_file_are_left_alone(self):
		other = self.view.add_phantom('debugger', Region(0), '<body>breakpoint</body>', 1, lambda href: None)
		self.refresh()
		self.module.TestButtons.dispose_all()

		self.assertEqual(sorted(self.view.phantoms), [other])
		self.assertEqual(self.module.TestButtons.views, {})

	def test_activation_does_not_recreate_unchanged_icons(self):
		self.refresh()
		first = sorted(self.view.phantoms)
		for _ in range(3):
			self.refresh()

		self.assertEqual(sorted(self.view.phantoms), first)
		self.assertEqual(self.view.erased, [])

	def test_click_starts_the_one_test_with_the_users_overrides(self):
		self.view.dirty = True
		self.refresh()
		self.click('run:0')

		self.get.assert_called_with(self.window, create=True)
		self.assertEqual(self.view.commands, ['save'])
		(configuration,), kwargs = self.debugger.project.add_transient.call_args
		_, json, index = configuration
		self.assertEqual(index, -1)
		self.assertEqual(json['name'], 'TestPlugin (plugin)')
		self.assertEqual(json['args'], ['-test.run', '^TestPlugin$', '-test.v'])
		self.assertEqual(json['env'], {'A': '1', 'B': '2'})
		self.assertEqual(kwargs, {'keep': set()})
		# the one icon of a test runs it without the debugger, debugging it is the bug on the bar
		self.debugger.start.assert_awaited_once_with(no_debug=True, args={'configuration': 'TestPlugin (plugin)'})
		self.assertFalse(any('debug:' in html for _, html, _ in self.view.phantoms.values()))

	def test_a_started_test_says_what_it_runs_in_its_own_console(self):
		self.refresh()
		self.click('run:0')

		class Configuration(dict):
			name = 'TestPlugin (plugin)'

		(configuration,), _ = self.debugger.project.add_transient.call_args
		session = types.SimpleNamespace(configuration=Configuration(configuration[1]), parent=None, console=Mock())
		self.module.session_started(session)

		lines = [call.args[0] for call in session.console.info.call_args_list]
		self.assertEqual(lines, ["cd /src/plugin && ./__debug_bin -test.run '^TestPlugin$' -test.v"])

		# a configuration of the project is not a test, and neither is what an adapter starts under one
		other = types.SimpleNamespace(configuration=types.SimpleNamespace(name='Server'), parent=None, console=Mock())
		child = types.SimpleNamespace(configuration=Configuration(), parent=session, console=Mock())
		self.module.session_started(other)
		self.module.session_started(child)
		other.console.info.assert_not_called()
		child.console.info.assert_not_called()

	def test_the_stderr_of_a_jest_run_is_its_report_and_of_a_go_run_is_not(self):
		runner = sys.modules['_tbt.modules.test_runner']
		languages = {language.key: language for language in runner.LANGUAGES}
		self.module.started.update({'adds (x.test.ts)': languages['jest'], 'TestPlugin (plugin)': languages['go']})
		self.addCleanup(self.module.started.clear)

		def session(name, parent=None):
			return types.SimpleNamespace(configuration=types.SimpleNamespace(name=name), parent=parent)

		jest = session('adds (x.test.ts)')
		self.assertTrue(self.module.stderr_is_output(jest))
		# what js-debug starts under it writes the results, and is the same run
		self.assertTrue(self.module.stderr_is_output(session('child', parent=jest)))
		self.assertFalse(self.module.stderr_is_output(session('TestPlugin (plugin)')))
		self.assertFalse(self.module.stderr_is_output(session('Server')))

	def test_a_running_test_shows_stop_and_a_click_stops_it(self):
		self.running = {'TestOther (plugin)'}
		self.sessions = {'TestOther (plugin)': object()}
		self.refresh()
		self.assertEqual(self.hrefs(), ['run:0', 'stop:1'])

		self.click('stop:1')

		self.debugger.stop.assert_awaited_once_with(self.sessions['TestOther (plugin)'])
		self.debugger.start.assert_not_awaited()

	def test_a_test_typed_in_gets_its_icon_once_typing_pauses(self):
		self.refresh()
		self.view.text += '\nfunc TestNew(t *testing.T) {\n}\n'
		self.module.TestButtons.refresh_later(self.view)
		self.module.TestButtons.refresh_later(self.view)
		first, last = self.timeouts

		first()
		self.assertEqual(self.hrefs(), ['run:0', 'run:1'])
		last()
		self.assertEqual(self.hrefs(), ['run:0', 'run:1', 'run:2'])

	def test_disabled_setting_and_bad_links(self):
		buttons = self.refresh()
		for href in ('run:9', 'run:x', 'stop:', 'other:0'):
			asyncio.run(buttons.navigate(href))
		self.debugger.start.assert_not_awaited()
		self.debugger.stop.assert_not_awaited()

		self.settings.test_buttons = False
		self.refresh()
		self.assertEqual(self.view.phantoms, {})


if __name__ == '__main__':
	unittest.main()
