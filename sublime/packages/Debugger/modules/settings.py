from __future__ import annotations
from typing import Callable, ForwardRef, Generic, Any, TypeVar, cast
from . import core

import importlib
import sublime

T = TypeVar('T')


# What a group of settings is for, the comment above its object in the settings file. A setting is
# in a group by its key: `console.font_size` is `font_size` of the `console` object.
GROUPS = {
	'ui': 'The debugger ui: the toolbar, tabs, panes (breakpoints, call stack, variables) and menus.',
	'console': 'The console and terminal panels the debugger creates (the text, not the header above it).',
	'inline_values': 'The values of variables written at the end of the lines that mention them, while stopped.',
	'editor': 'What the debugger draws in your files.',
	'adapters': 'Paths and options of the debug adapters.',
	'global': 'Configurations, tasks, inputs and compounds that every project has, as a project file lists them under `debugger_configurations` and the like.',
}
# the order of the settings file; a key that is not listed comes after these
ORDER = ['open_at_startup', 'always_keep_visible', 'session_panels', 'inputs_ask', 'ui', 'console', 'inline_values', 'editor',
	'test_configurations', 'adapters', 'global', 'integrated_output_panels', 'development']


class Setting(Generic[T], object):
	"""One setting of `Debugger.sublime-settings`

	`key` is its name in the file, `group.name` for one inside an object: `console.font_size` is

		"console": {"font_size": 17}

	Sublime lays the user's file over the package's a top level key at a time, so a user who sets
	one key of a group has replaced the whole object, and the other keys of the group are not in
	it. They are then what `default` says, which is why the defaults are here and the objects in
	the package's file are only what is shown to be copied.
	"""

	# every setting, in the order they were defined; the settings file and its schema are made of these
	all: list[Setting] = []

	def __init__(self, key: str, default: T, description: str = '', visible=True, schema: Any | None = None) -> None:
		self.key = key
		self.group, _, self.name = key.rpartition('.')
		self.default: Any = default
		self.description = description
		self.visible = visible
		self.schema = schema
		Setting.all.append(self)

	def get(self) -> T:
		if not self.group:
			return cast(T, SettingsRegistery.settings.get(self.key, self.default))
		values = SettingsRegistery.settings.get(self.group)
		if isinstance(values, dict) and self.name in values:
			return cast(T, values[self.name])
		return cast(T, self.default)

	def set(self, value: T) -> None:
		if not self.group:
			SettingsRegistery.settings.set(self.key, cast(Any, value))
			return
		# the object is replaced by one with this key changed, the rest of it as it was
		values = SettingsRegistery.settings.get(self.group)
		values = dict(values) if isinstance(values, dict) else {}
		values[self.name] = value
		SettingsRegistery.settings.set(self.group, values)

	@property
	def value(self) -> T:
		return self.get()

	@value.setter
	def value(self, value: T):
		self.set(value)

	def __get__(self, obj, objtype=None) -> T:
		return self.get()

	def update(self, value: T):
		self.set(value)
		SettingsRegistery.save()

	def __set__(self, obj, value: T):
		self.set(value)
		SettingsRegistery.save()

	def json_schema(self) -> dict[str, Any]:
		import textwrap
		import typing

		t = typing.get_args(self.__orig_class__)[0]  # type: ignore
		types: dict[Any, Any] = {
			bool: 'boolean', int: 'number', float: 'number', str: 'string',
			ForwardRef('int|None'): ['number', 'null'], ForwardRef('float|None'): ['number', 'null'], ForwardRef('str|None'): ['string', 'null'],
		}
		schema = dict(self.schema) if self.schema else {'type': types.get(t, ['object', 'array'])}
		schema['description'] = textwrap.dedent(self.description).strip().split('\n')[0]
		return schema


def settings_in_order(visible_only: bool = False) -> list[tuple[str, list[Setting]]]:
	"""(top level key, its settings) in the order of the file: a setting of its own, or the settings of a group"""
	entries: dict[str, list[Setting]] = {}
	for setting in Setting.all:
		if visible_only and not setting.visible:
			continue
		entries.setdefault(setting.group or setting.key, []).append(setting)
	return sorted(entries.items(), key=lambda entry: ORDER.index(entry[0]) if entry[0] in ORDER else len(ORDER))


def settings_file_text() -> str:
	"""The package's `Debugger.sublime-settings`: every visible setting at its default under its description"""
	import json
	import textwrap

	def comment(text: str, indent: str) -> str:
		lines = textwrap.dedent(text).strip().split('\n')
		return ''.join(f'{indent}// {line}\n' if line else f'{indent}//\n' for line in lines) if text.strip() else ''

	output = '{\n' + comment('''
		The settings of a group are the keys of one object. To change one, give its object with
		only that key in your own file; the other keys of the group keep their defaults:

		    "console": {"font_size": 17}
	''', '\t') + '\n'
	for key, settings in settings_in_order(visible_only=True):
		if key not in GROUPS and not settings[0].group:
			setting = settings[0]
			output += comment(setting.description, '\t') + f'\t{json.dumps(key)}: {json.dumps(setting.default)},\n\n'
			continue
		output += comment(GROUPS.get(key, ''), '\t') + f'\t{json.dumps(key)}: {{\n'
		for index, setting in enumerate(settings):
			output += ('\n' if index else '') + comment(setting.description, '\t\t') + f'\t\t{json.dumps(setting.name)}: {json.dumps(setting.default)},\n'
		output += '\t},\n\n'
	return output + '}\n'


def settings_schema() -> dict[str, Any]:
	properties: dict[str, Any] = {}
	for key, settings in settings_in_order():
		if key not in GROUPS and not settings[0].group:
			properties[key] = settings[0].json_schema()
			continue
		properties[key] = {
			'type': 'object',
			'description': GROUPS.get(key, ''),
			'additionalProperties': False,
			'properties': {setting.name: setting.json_schema() for setting in settings},
		}
	return {'additionalProperties': False, 'properties': properties}


class Settings:
	open_at_startup = Setting[bool](
		key='open_at_startup',
		default=False,
		description='Open the debugger automatically when a project that is set up for debugging is opened.',
	)

	always_keep_visible = Setting[bool](
		key='always_keep_visible',
		default=False,
		description='Always keep the debugger panel visible',
	)

	hover_in_lsp_popup = Setting[bool](
		key='editor.hover_in_lsp_popup',
		default=True,
		description='When the LSP package is installed show the value of the hovered expression inside the LSP hover popup instead of in a separate popup. Requires a restart.',
	)

	inline_values = Setting[bool](
		key='inline_values.enabled',
		default=True,
		description='''
		While stopped, writes the values of the variables of the selected frame at the end of the lines
		that mention them, from the top of the function down to the line that is stopped on.
		''',
	)

	inline_values_color = Setting['str|None'](
		key='inline_values.color',
		default=None,
		description='''
		Colour of the inline values, as css: "#8a6d3b", "rgb(120, 90, 200)", "var(--bluish)". Defaults
		to the text colour of the colour scheme.
		''',
	)

	inline_values_opacity = Setting[float](
		key='inline_values.opacity',
		default=0.75,
		description='How strongly the inline values are drawn, from 0.1 (barely there) to 1 (as solid as the code).',
	)

	inline_values_font_style = Setting[str](
		key='inline_values.font_style',
		default='italic',
		description='Style of the inline values: "italic", "normal", "bold" or "bold italic".',
	)

	inline_values_font_face = Setting['str|None'](
		key='inline_values.font_face',
		default=None,
		description='Font family of the inline values. Defaults to the font of the file they are drawn in.',
	)

	inline_values_font_size = Setting['float|None'](
		key='inline_values.font_size',
		default=None,
		description='Font size of the inline values. Defaults to 90% of the font size of the file they are drawn in.',
	)

	inputs_ask = Setting[str](
		key='inputs_ask',
		default='always',
		description='''
		How often a value of `debugger_inputs` (`${input:id}`) is asked for.
		"always": on every start, offering the last answer first.
		"once": the first time, and the answer is used from then on without asking, until
		`Debugger: Ask Inputs Again` is run or Sublime is restarted.
		An input can say for itself with `"ask": "once"` or `"ask": "always"`, which wins over this.
		''',
	)

	font_size = Setting['float|None'](
		key='ui.font_size',
		default=None,
		description='Font size of the debugger ui: toolbar, tabs, panes and menus. Defaults to 87.5% of the font size in your preferences.',
	)

	font_face = Setting['str|None'](
		key='ui.font_face',
		default=None,
		description='Font family of the debugger ui: toolbar, tabs, panes and menus. Defaults to the font_face in your preferences.',
	)

	line_padding = Setting[int](
		key='ui.line_padding',
		default=0,
		description='Extra space in pixels above and below each row of the debugger ui panes (breakpoints, call stack, variables).',
	)

	console_bar_position = Setting[str](
		key='ui.bar_position',
		default='bottom',
		description="""
		Where the console's toolbar and tabs sit. "bottom": a fixed strip below the output that stays
		put while the output scrolls. "top": drawn above the first line, scrolling with the output.
		Applies to consoles created after the change.
		""",
	)

	console_font_size = Setting['float|None'](
		key='console.font_size',
		default=None,
		description='Text size of the console and terminal panels the debugger creates. Defaults to the debugger ui font size.',
	)

	console_font_face = Setting['str|None'](
		key='console.font_face',
		default=None,
		description='Font for the text of the console and terminal panels the debugger creates. Defaults to the font_face in your preferences.',
	)

	console_line_padding = Setting[int](
		key='console.line_padding',
		default=2,
		description='Extra space in pixels above and below each line of text in the console and terminal panels the debugger creates.',
	)



	external_terminal = Setting[str](
		key='console.external_terminal',
		default='terminus',
		description="""
		A configuration says where its output goes with "console": "internal" (the Console tab of the
		debugger, and what it gets when it does not say) or "console": "external" (a terminal, for a
		program that reads what is typed or draws on the screen). This is which terminal that is:
		"terminus" Terminus as a tab of the editor. The Terminus package must be installed https://github.com/randy3k/Terminus
		"terminus_panel" Terminus in the debugger panel, as its Terminal tab
		"platform" Terminal on MacOS, CMD (Not tested) on Windows, (Unimplemented) on Linux
		""",
	)

	icon_foreground_color = Setting[bool](
		key='ui.icons_follow_color_scheme',
		default=True,
		description="""
		Draws the debugger icons in the foreground colour of the colour scheme. The artwork is unchanged,
		only the colour: minihtml cannot tint an image, so the tint is applied to the png before it is
		handed over. Breakpoints keep their own colours.
		""",
	)

	project_file_buttons = Setting[bool](
		key='editor.project_file_buttons',
		default=True,
		description="""
		Draws a play icon at the head of each configuration in the .sublime-project file, and a settings
		icon on debugger_configurations. They are clickable, which is why they sit in the text rather
		than the gutter: Sublime will draw a gutter icon but has no event for a click on one.
		""",
	)

	test_buttons = Setting[bool](
		key='editor.test_buttons',
		default=True,
		description="""
		Draws a play icon at the head of each test in a test file, which debugs that one test.
		Go: the Test, Benchmark, Fuzz and Example functions of a _test.go file, and the subtests whose
		names are written in the file: t.Run("name", ...) and the rows of a table.
		Python: the test functions, test classes and their methods in test_*.py and *_test.py, run by pytest.
		Java: the methods junit runs (@Test and the like) and their classes, run by the maven or gradle build of the project.
		Jest: the describe, it and test calls of *.test.* and *.spec.* files and of files in __tests__.
		""",
	)

	test_configurations = Setting['dict[str, Any]'](
		key='test_configurations',
		default={},
		description="""
		Values laid over the configuration that is generated to debug a test, by language (go, python, java, jest):
		{"go": {"env": {"SKIP_IO_TESTS": "1"}, "buildFlags": "-tags=integration", "args": ["-test.count=1"]}}
		`args` are added after the generated ones, objects such as `env` are merged, anything else
		replaces. A project can set the same under `debugger_test_configurations`, which wins.
		""",
	)

	session_panels = Setting[bool](
		key='session_panels',
		default=True,
		description="""
		Gives each running configuration a callstack and a console of its own instead of sharing one of
		each, so two configurations running at the same time can be told apart.
		""",
	)

	console_minimum_height = Setting[int](
		key='console.minimum_height',
		default=20,
		description="""
		Controls the minimum height of the debugger output panels in lines
		""",
	)
	json_logs = Setting[str](
		key='console.json_logs',
		default='off',
		description="""
		How a line of output that is a json object (a structured log) is shown, in the console and in
		the terminals the debugger opens. "compact": one line, `10:32:01 INFO message key=value`.
		"fields": the message, then a line for each field. "pretty": the json, indented. "off" (the default): as
		it was printed. A configuration or a task can set its own with a `json_logs` key.
		""",
	)
	console_scrollback_limit = Setting[int](
		key='console.scrollback_limit',
		default=2000,
		description="""
		Limits the number of lines allowed in the console before lines are removed
		""",
	)

	bring_window_to_front_on_pause: bool = False

	development = Setting[bool](
		key='development',
		default=False,
		description='Additional console logs and some new features are locked behind this flag',
	)

	node = Setting['str|None'](
		key='adapters.node',
		default=None,
		description='Path of `node`, for the adapters that run on it; without it the one in your path is used.',
	)

	integrated_output_panels = Setting['dict[str, dict[str, str]]'](
		key='integrated_output_panels',
		default={},
		description="""
		Output panels outside of the debugger can be integrated into the tabbed debugger interface (note: In some cases output panels may cause issues and not work correctly depending on who owns them)
		An example for interating the Diagnostics panel of LSP and a Terminus output panel.

		"integrated_output_panels": {
			"diagnostics": {
				"name": "Diagnostics",
			},
			"Terminus": {
				"name": "Terminal",
				"position": "bottom",
			}
		}
		""",
	)

	global_debugger_configurations = Setting['list[Any]'](
		key='global.configurations',
		default=[],
		description='Global debugger configurations that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_configuration'},
		},
	)

	global_debugger_tasks = Setting['list[Any]'](
		key='global.tasks',
		default=[],
		description='Global debugger tasks that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_task'},
		},
	)

	global_debugger_inputs = Setting['list[Any]'](
		key='global.inputs',
		default=[],
		description='Global debugger inputs, the values `${input:id}` asks for, that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_input'},
		},
	)

	global_debugger_compounds = Setting['list[Any]'](
		key='global.compounds',
		default=[],
		description='Global debugger compounds that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_compound'},
		},
	)


# Settings __set__ method will not get called on a class so just override the class with an instance of itself...
Settings = Settings()  # type: ignore


class SettingsRegistery:
	settings: sublime.Settings
	package_control_settings: sublime.Settings

	@staticmethod
	def initialize(on_updated: Callable[[], None]):
		SettingsRegistery.settings = sublime.load_settings('Debugger.sublime-settings')
		SettingsRegistery.settings.add_on_change('debugger_settings', on_updated)

		SettingsRegistery.package_control_settings = sublime.load_settings('Package Control.sublime-settings')
		SettingsRegistery.package_control_settings.add_on_change('debugger_settings', on_updated)

	@staticmethod
	def is_package_installed(package: str) -> bool:
		# ignored packages that are not .sublime-package are still importable so they have to be checked separately
		ignored_packages = cast('list[str]', sublime.load_settings('Preferences.sublime-settings').get('ignored_packages') or [])
		if package in ignored_packages:
			return False

		try:
			importlib.import_module(package)
			return True
		except Exception:
			return False

	@staticmethod
	def save():
		sublime.save_settings('Debugger.sublime-settings')

	@staticmethod
	def schema():
		return settings_schema()

	@staticmethod
	def generate_settings():
		with open(f'{core.package_path()}/Debugger.sublime-settings', 'w') as f:
			f.write(settings_file_text())
