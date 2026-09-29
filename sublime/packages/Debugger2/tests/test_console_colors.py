from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class ConsoleColorTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		package = types.ModuleType('_console_color_test')
		package.__path__ = []
		core = types.ModuleType('_console_color_test.core')
		core.debug = Mock()
		cls.modules = patch.dict(sys.modules, {
			'_console_color_test': package,
			'_console_color_test.core': core,
		})
		cls.modules.start()
		spec = importlib.util.spec_from_file_location('_console_color_test.ansi', ROOT / 'modules' / 'ansi.py')
		cls.ansi = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(cls.ansi)

	@classmethod
	def tearDownClass(cls):
		cls.modules.stop()

	def test_region_colors_use_only_their_own_scope(self):
		for color, scope in {
			'red': 'region.redish.debugger',
			'green': 'region.greenish.debugger',
			'yellow': 'region.yellowish.debugger',
			'blue': 'region.bluish.debugger',
			'magenta': 'region.purplish.debugger',
			'cyan': 'region.cyanish.debugger',
		}.items():
			with self.subTest(color=color):
				self.assertEqual(self.ansi.escape_codes_by_color[color]['scope'], scope)

	def test_shipped_syntax_matches_generator(self):
		self.assertEqual(
			(ROOT / 'contributes' / 'Syntax' / 'DebuggerConsole.sublime-syntax').read_text(),
			self.ansi.generate_ansi_syntax(),
		)

	def test_console_does_not_override_scope_backgrounds(self):
		self.assertNotIn('debugger.background', self.ansi.generate_ansi_syntax())

	def test_console_input_and_results_are_plain_text_with_source_scopes_inside(self):
		by_color = self.ansi.escape_codes_by_color
		# neither has an ansi code: only the console writes them, and their markers are the longest
		# so no other marker is read as a prefix of them
		self.assertEqual(by_color['input']['escape'], [])
		self.assertEqual(by_color['result']['escape'], [])
		longest = max(len(item['match']) for item in self.ansi.escape_codes if item['color'] not in ('input', 'result'))
		self.assertGreater(len(by_color['input']['match']), longest)
		self.assertGreater(len(by_color['result']['match']), len(by_color['input']['match']))
		# both take the plain text colour: a meta scope no colour scheme paints
		self.assertTrue(by_color['input']['scope'].startswith('meta.'))
		self.assertTrue(by_color['result']['scope'].startswith('meta.'))
		syntax = self.ansi.generate_ansi_syntax()
		# the prompt is scoped once, by handing over to a context without the prompt rule
		self.assertIn("      scope: meta.input.debugger comment.debugger punctuation.definition.prompt.debugger\n      set: input-body", syntax)
		self.assertIn('  input-body:\n    - meta_scope: meta.input.debugger', syntax)
		# strings, numbers and constants inside a result carry the scopes source code uses
		for scope in ('string.quoted.double.debugger', 'string.quoted.single.debugger', 'constant.numeric.debugger', 'constant.language.debugger'):
			self.assertIn('      scope: ' + scope, syntax)
		self.assertLess(syntax.index('  result:'), syntax.index('string.quoted.double.debugger'))
		self.assertLess(syntax.index('string.quoted.double.debugger'), syntax.index('  input:'))

	def test_explicit_colors_and_ansi_colors_use_the_same_markers(self):
		for item in self.ansi.escape_codes:
			if not item.get('scope', '').startswith('region.'):
				continue
			with self.subTest(color=item['color']):
				self.assertEqual(self.ansi.ansi_colorize('message', item['color']), '\u200c' + item['match'] + 'message')
				for escape in item['escape']:
					self.assertEqual(self.ansi.ansi_colorize(escape + 'message'), item['match'] + 'message')

	def test_default_output_resets_color_without_assigning_a_scope(self):
		self.assertNotIn('scope', self.ansi.escape_codes_by_color['foreground'])
		for color in (None, 'foreground'):
			with self.subTest(color=color):
				self.assertEqual(self.ansi.ansi_colorize('message', color, 'red'), '\u200c\u200bmessage')


if __name__ == '__main__':
	unittest.main()
