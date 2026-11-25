from __future__ import annotations
from typing import Callable, ForwardRef, Generic, Any, TypeVar, cast
from . import core

import importlib
import sublime

T = TypeVar('T')


class Setting(Generic[T], object):
	def __init__(self, key: str, default: T, description: str = '', visible=True, schema: Any | None = None) -> None:
		self.key = key
		self.default: Any = default
		self.description = description
		self.visible = visible
		self.schema = schema

	@property
	def value(self) -> T:
		return cast(T, SettingsRegistery.settings.get(self.key, self.default))

	@value.setter
	def value(self, value: T):
		return SettingsRegistery.settings.set(self.key, cast(Any, value))

	def __get__(self, obj, objtype=None) -> T:
		return cast(T, SettingsRegistery.settings.get(self.key, self.default))

	def update(self, value: T):
		SettingsRegistery.settings.set(self.key, cast(Any, value))
		SettingsRegistery.save()

	def __set__(self, obj, value: T):
		SettingsRegistery.settings.set(self.key, cast(Any, value))
		SettingsRegistery.save()


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
		key='hover_in_lsp_popup',
		default=True,
		description='When the LSP package is installed show the value of the hovered expression inside the LSP hover popup instead of in a separate popup. Requires a restart.',
	)

	inline_values = Setting[bool](
		key='inline_values',
		default=True,
		description='''
		While stopped, writes the values of the variables of the selected frame at the end of the lines
		that mention them, from the top of the function down to the line that is stopped on.
		''',
	)

	inline_values_color = Setting['str|None'](
		key='inline_values_color',
		default=None,
		description='''
		Colour of the inline values, as css: "#8a6d3b", "rgb(120, 90, 200)", "var(--bluish)". Defaults
		to the text colour of the colour scheme.
		''',
	)

	inline_values_opacity = Setting[float](
		key='inline_values_opacity',
		default=0.75,
		description='How strongly the inline values are drawn, from 0.1 (barely there) to 1 (as solid as the code).',
	)

	inline_values_font_style = Setting[str](
		key='inline_values_font_style',
		default='italic',
		description='Style of the inline values: "italic", "normal", "bold" or "bold italic".',
	)

	inline_values_font_face = Setting['str|None'](
		key='inline_values_font_face',
		default=None,
		description='Font family of the inline values. Defaults to the font of the file they are drawn in.',
	)

	inline_values_font_size = Setting['float|None'](
		key='inline_values_font_size',
		default=None,
		description='Font size of the inline values. Defaults to 90% of the font size of the file they are drawn in.',
	)

	font_size = Setting['float|None'](
		key='font_size',
		default=None,
		description='Font size of the debugger ui: toolbar, tabs, panes and menus. Defaults to 87.5% of the font size in your preferences.',
	)

	font_face = Setting['str|None'](
		key='font_face',
		default=None,
		description='Font family of the debugger ui: toolbar, tabs, panes and menus. Defaults to the font_face in your preferences.',
	)

	line_padding = Setting[int](
		key='line_padding',
		default=0,
		description='Extra space in pixels above and below each row of the debugger ui panes (breakpoints, call stack, variables).',
	)

	console_bar_position = Setting[str](
		key='console_bar_position',
		default='bottom',
		description="""
		Where the console's toolbar and tabs sit. "bottom": a fixed strip below the output that stays
		put while the output scrolls. "top": drawn above the first line, scrolling with the output.
		Applies to consoles created after the change.
		""",
	)

	console_font_size = Setting['float|None'](
		key='console_font_size',
		default=None,
		description='Text size of the console and terminal panels the debugger creates. Defaults to the debugger ui font size.',
	)

	console_font_face = Setting['str|None'](
		key='console_font_face',
		default=None,
		description='Font for the text of the console and terminal panels the debugger creates. Defaults to the font_face in your preferences.',
	)

	console_line_padding = Setting[int](
		key='console_line_padding',
		default=2,
		description='Extra space in pixels above and below each line of text in the console and terminal panels the debugger creates.',
	)

	internal_font_scale = Setting[float](
		key='internal_font_scale',
		default=1,
		description='Expected values of around 0.95 to 1.05. Only change this if the text/images/content are not aligning correctly within the panels (could cause the last panel to be clipped).',
	)

	internal_width_modifier = Setting[float](
		key='internal_width_modifier',
		default=0,
		description='Expected values of around 0 to -5. Only change this if the size of the panels is too large and the last panel is cropped off (adjust internal_font_scale first if text/images/content are not aligned correctly). Negative values make the panels smaller. Postive make them bigger.',
	)

	external_terminal = Setting[str](
		key='external_terminal',
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
		key='icon_foreground_color',
		default=True,
		description="""
		Draws the debugger icons in the foreground colour of the colour scheme. The artwork is unchanged,
		only the colour: minihtml cannot tint an image, so the tint is applied to the png before it is
		handed over. Breakpoints keep their own colours.
		""",
	)

	project_file_buttons = Setting[bool](
		key='project_file_buttons',
		default=True,
		description="""
		Draws a play icon at the head of each configuration in the .sublime-project file, and a settings
		icon on debugger_configurations. They are clickable, which is why they sit in the text rather
		than the gutter: Sublime will draw a gutter icon but has no event for a click on one.
		""",
	)

	test_buttons = Setting[bool](
		key='test_buttons',
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
		key='console_minimum_height',
		default=20,
		description="""
		Controls the minimum height of the debugger output panels in lines
		""",
	)
	console_scrollback_limit = Setting[int](
		key='console_scrollback_limit',
		default=2000,
		description="""
		Limits the number of lines allowed in the console before lines are removed
		""",
	)
	console_scrollback_annotation_limit = Setting[int](
		key='console_scrollback_annotation_limit',
		default=100,
		description='Limits the number of annotationed regions/phantoms (source locations, variables, etc) allowed in the console',
	)

	bring_window_to_front_on_pause: bool = False

	development = Setting[bool](
		key='development',
		default=False,
		description='Additional console logs and some new features are locked behind this flag',
	)

	node = Setting['str|None'](
		key='node',
		default=None,
		description='Sets a specific path for node if not set adapters that require node to run will use whatever is in your path',
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
		key='global_debugger_configurations',
		default=[],
		description='Global debugger configurations that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_configuration'},
		},
	)

	global_debugger_tasks = Setting['list[Any]'](
		key='global_debugger_tasks',
		default=[],
		description='Global debugger tasks that are accessible from every project',
		schema={
			'type': 'array',
			'items': {'$ref': 'sublime://settings/debugger#/definitions/debugger_task'},
		},
	)

	global_debugger_compounds = Setting['list[Any]'](
		key='global_debugger_compounds',
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
		import gc
		import typing
		import textwrap

		properties = {}
		for setting in gc.get_objects():
			if not isinstance(setting, Setting):
				continue

			t = typing.get_args(setting.__orig_class__)[0]  # type: ignore

			schema: dict[str, Any] = {}
			if setting.schema:
				schema = setting.schema
			elif t == bool:
				schema = {'type': 'boolean'}
			elif t == int:
				schema = {'type': 'number'}
			elif t == ForwardRef('int|None'):
				schema = {'type': ['number', 'null']}
			elif t == float:
				schema = {'type': 'number'}
			elif t == ForwardRef('float|None'):
				schema = {'type': ['number', 'null']}
			elif t == str:
				schema = {'type': 'string'}
			elif t == ForwardRef('str|None'):
				schema = {'type': ['string', 'null']}
			else:
				schema = {'type': ['object', 'array']}

			schema['description'] = textwrap.dedent(setting.description).strip().split('\n')[0]
			properties[setting.key] = schema

		return {'additionalProperties': False, 'properties': properties}

	@staticmethod
	def generate_settings():
		import gc
		import json
		import textwrap

		output = '{\n'

		for setting in gc.get_objects():
			if not isinstance(setting, Setting):
				continue

			if not setting.visible:
				continue

			lines = textwrap.dedent(setting.description).strip().split('\n')
			comment = ''
			for line in lines:
				# skip leading empty lines
				if not comment and not line:
					continue

				comment += f'\t// {line}\n'

			output += comment
			output += f'\t{json.dumps(setting.key)}: {json.dumps(setting.default)},'
			output += '\n\n'

		output += '}'

		with open(f'{core.package_path()}/Debugger.sublime-settings', 'w') as f:
			f.write(output)
