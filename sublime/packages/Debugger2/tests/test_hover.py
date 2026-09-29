from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path, modules):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	with patch.dict(sys.modules, dict(modules, **{name: module})):
		spec.loader.exec_module(module)
	return module


class Variable:
	def __init__(self, name, value, children=(), type=None):
		self.name = name
		self.value = value
		self.type = type if type is not None else (value if children else None)
		self.memoryReference = None
		self.variablesReference = 1 if children else 0
		self._children = list(children)

	@property
	def has_children(self):
		return bool(self.variablesReference)

	async def fetch(self):
		return self._children


class HoverTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		package = types.ModuleType('_hover_test')
		package.__path__ = []
		modules = types.ModuleType('_hover_test.modules')
		modules.__path__ = []
		views = types.ModuleType('_hover_test.modules.views')
		views.__path__ = []
		sublime = types.ModuleType('sublime')
		sublime_plugin = types.ModuleType('sublime_plugin')
		sublime_plugin.TextCommand = type('TextCommand', (), {})
		dependencies = {
			'_hover_test': package,
			'_hover_test.modules': modules,
			'_hover_test.modules.views': views,
			'_hover_test.modules.core': types.SimpleNamespace(run=lambda fn: fn),
			'_hover_test.modules.dap': types.SimpleNamespace(Error=Exception, Variable=object),
			'_hover_test.modules.ui': types.SimpleNamespace(),
			'_hover_test.modules.debugger': types.SimpleNamespace(Debugger=object),
			'_hover_test.modules.settings': types.SimpleNamespace(Settings=object),
			'_hover_test.modules.views.variable': types.SimpleNamespace(VariableView=object),
			'sublime': sublime,
			'sublime_plugin': sublime_plugin,
		}
		variable_format = load_module('_hover_test.modules.variable_format', ROOT / 'modules/variable_format.py', dependencies)
		dependencies['_hover_test.modules.variable_format'] = variable_format
		cls.hover = load_module('_hover_test.modules.hover', ROOT / 'modules/hover.py', dependencies)

	def test_javascript_prototype_is_shown_but_not_recursively_expanded(self):
		prototype = Variable('[[Prototype]]', 'Object', [Variable('toString', 'ƒ toString()')])
		value = Variable('', 'Object', [Variable('enabled', 'true'), prototype])
		lines = asyncio.run(self.hover._lines_for(value, 0, '', self.hover.MAX_LINES))
		text = '\n'.join(lines)
		self.assertIn('enabled', text)
		self.assertIn('[[Prototype]]', text)
		self.assertNotIn('toString', text)

	def test_javascript_inline_object_preview_is_not_repeated_above_its_children(self):
		prototype = Variable('[[Prototype]]', 'Object', [Variable('toString', 'ƒ toString()')])
		value = Variable(
			'plugin',
			'{timeout: 8000, protectionEnabled: true}',
			[Variable('timeout', '8000'), Variable('protectionEnabled', 'true'), prototype],
			type='Object',
		)
		lines = asyncio.run(self.hover._lines_for(value, 0, '', self.hover.MAX_LINES))
		text = '\n'.join(lines)
		self.assertIn('plugin: Object', text)
		self.assertEqual(text.count('timeout'), 1)
		self.assertEqual(text.count('protectionEnabled'), 1)

	def test_python_object_field_is_laid_out_from_its_repr_not_fetched(self):
		# debugpy: the repr names every field, `dir()` finds the pydantic class attributes as well
		config = Variable(
			'plugin_config',
			"AgenticPluginConfig(api_domain='staging-eu.prompt.security', api_key='5f30a9ee-3277-460c-98b1-fc0908f58373', fail_open=True, max_retries=2)",
			[
				Variable('api_domain', "'staging-eu.prompt.security'"),
				Variable('api_key', "'5f30a9ee-3277-460c-98b1-fc0908f58373'"),
				Variable('fail_open', 'True'),
				Variable('max_retries', '2'),
				Variable('model_computed_fields', '{}', [Variable('len()', '0')]),
				Variable('model_config', "{'strict': True, 'frozen': True}", [Variable("'strict'", 'True'), Variable("'frozen'", 'True'), Variable('len()', '2')]),
				Variable('model_fields', "{'api_domain': FieldInfo(annotation=str, required=True)}", [Variable("'api_domain'", 'FieldInfo(annotation=str, required=True)')]),
			],
		)
		settings = Variable(
			'settings',
			"AgenticPluginInstallerSettings(arch='arm64', plugin_config=AgenticPluginConfig(...), timeout=600)",
			[Variable('arch', "'arm64'"), config, Variable('timeout', '600')],
		)
		lines = asyncio.run(self.hover._lines_for(settings, 0, '', self.hover.MAX_LINES))
		text = '\n'.join(lines)
		# the hovered value is opened: its own fields, one per line
		self.assertIn("  arch: 'arm64'", text)
		self.assertIn('  timeout: 600', text)
		# the object inside it is read off its repr, laid out down the page, and not asked for
		self.assertIn('  plugin_config: AgenticPluginConfig', text)
		self.assertIn("    api_domain='staging-eu.prompt.security'", text)
		self.assertEqual(text.count('api_key'), 1)
		for noise in ('model_fields', 'model_config', 'model_computed_fields', 'FieldInfo', 'len()', 'strict'):
			self.assertNotIn(noise, text)

	def test_debugpy_synthetic_rows_are_left_out_of_the_hovered_value(self):
		value = Variable(
			'',
			"{'a': 1, 'b': 2}",
			[
				Variable("'a'", '1'),
				Variable("'b'", '2'),
				Variable('len()', '2'),
				Variable('special variables', '', [Variable('__class__', "<class 'dict'>")]),
				Variable('function variables', '', [Variable('keys', '<built-in method keys>')]),
			],
		)
		lines = asyncio.run(self.hover._lines_for(value, 0, '', self.hover.MAX_LINES))
		text = '\n'.join(lines)
		self.assertIn("'a': 1", text)
		self.assertIn("'b': 2", text)
		for noise in ('len()', 'special variables', '__class__', 'function variables', 'keys'):
			self.assertNotIn(noise, text)

	def test_opaque_values_below_the_hovered_one_are_still_fetched(self):
		# delve writes an address for what it stopped short of, js-debug a type, debugpy `{...}` for
		# elided contents: each has to be asked for, a repr that names its fields does not
		address = Variable('selection', '(*"types.PluginSelection")(0x1400009e160)', [Variable('Name', '"x"'), Variable('Count', '2')])
		object = Variable('options', 'Object', [Variable('enabled', 'true')])
		elided = Variable('deep', "{'sub': {...}}", [Variable("'sub'", "{'x': 1}", [Variable("'x'", '1')])])
		ellipsis = Variable('nested', '{sub: {…}}', [Variable('sub', '{x: 1}', [Variable('x', '1')])])
		repr = Variable('config', "Config(a=1, sub=Sub(x=2))", [Variable('a', '1'), Variable('sub', 'Sub(x=2)', [Variable('x', '2')])])
		self.assertTrue(self.hover._is_opaque(address))
		self.assertTrue(self.hover._is_opaque(object))
		self.assertTrue(self.hover._is_opaque(elided))
		self.assertTrue(self.hover._is_opaque(ellipsis))
		self.assertFalse(self.hover._is_opaque(repr))
		self.assertFalse(self.hover._is_opaque(Variable('flat', '[1, 2, 3]', [Variable('0', '1')])))

		root = Variable('', 'main.Config', [address, object, elided, repr])
		lines = asyncio.run(self.hover._lines_for(root, 0, '', self.hover.MAX_LINES))
		text = '\n'.join(lines)
		# opened, so the summary drops the address and the fields follow
		self.assertIn('  selection: (*"types.PluginSelection")\n    Name: "x"', text)
		self.assertIn('  options: Object\n    enabled: true', text)
		# the elided dict is asked for, the flat one inside it is complete as written
		self.assertIn("  deep: {'sub': {...}}\n    'sub': {'x': 1}", text)
		self.assertNotIn("'x': 1\n", text)
		# the repr is enough on its own
		self.assertIn('  config: Config(a=1, sub=Sub(x=2))', text)
		self.assertEqual(text.count('x=2'), 1)


if __name__ == '__main__':
	unittest.main()
