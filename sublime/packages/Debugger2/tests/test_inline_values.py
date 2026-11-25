from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_inline_values_test', ROOT / 'modules' / 'inline_values.py')
inline_values = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inline_values)


class NamesOnLineTests(unittest.TestCase):
	def test_in_the_order_written_and_each_once(self):
		self.assertEqual(inline_values.names_on_line('total = count + total * rate', ['rate', 'total', 'count']), ['total', 'count', 'rate'])

	def test_a_member_of_something_else_is_not_the_variable(self):
		names = ['name', 'user', 'size']
		self.assertEqual(inline_values.names_on_line('print(user.name, other->size, std::size, name)', names), ['user', 'name'])

	def test_part_of_a_longer_name_is_not_the_variable(self):
		self.assertEqual(inline_values.names_on_line('counter = recount + count_', ['count']), [])

	def test_a_spread_is_not_a_member_access(self):
		self.assertEqual(inline_values.names_on_line('call(...args)', ['args']), ['args'])

	def test_php_names(self):
		self.assertEqual(inline_values.names_on_line('$total = $count + 1;', ['$total', '$count']), ['$total', '$count'])

	def test_strings_and_comments_are_left_out_when_asked(self):
		text = 'x = 1  # x is one'
		self.assertEqual(inline_values.names_on_line(text, ['x', 'one'], lambda column: column < text.index('#')), ['x'])


class TextTests(unittest.TestCase):
	def test_a_value_is_one_line_and_cut(self):
		self.assertEqual(inline_values.short_value('a\n   b'), 'a b')
		self.assertEqual(len(inline_values.short_value('x' * 500)), inline_values.MAX_VALUE)
		self.assertTrue(inline_values.short_value('x' * 500).endswith('…'))

	def test_a_line_is_cut_to_whole_variables(self):
		self.assertEqual(inline_values.line_text([('a', '1'), ('b', '"x"')]), 'a = 1, b = "x"')
		self.assertEqual(inline_values.line_text([('a', '1'), ('b', '2'), ('c', '3')], limit=12), 'a = 1, b = 2, …')
		self.assertEqual(inline_values.line_text([('long', 'x' * 50)], limit=12), 'long = xxxx…')


class LinesTests(unittest.TestCase):
	def test_the_function_starts_at_the_last_symbol_above(self):
		self.assertEqual(inline_values.first_line(50, [3, 20, 44, 70]), 44)
		self.assertEqual(inline_values.first_line(44, [44]), 44)

	def test_without_a_symbol_a_few_lines_above_and_never_below_zero(self):
		self.assertEqual(inline_values.first_line(100, []), 100 - inline_values.LINES_WITHOUT_SYMBOL)
		self.assertEqual(inline_values.first_line(5, []), 0)

	def test_a_function_is_only_read_so_far_back(self):
		self.assertEqual(inline_values.first_line(1000, [10]), 1000 - inline_values.MAX_LINES)

	def test_values_by_line(self):
		source = [(10, 'def f(a, b):'), (11, '    # a comment about b'), (12, '    c = a + b'), (13, '    return None')]
		is_code = lambda line, column: line != 11
		self.assertEqual(
			inline_values.values_by_line(source, {'a': '1', 'b': '2', 'c': '3'}, is_code),
			{10: 'a = 1, b = 2', 12: 'c = 3, a = 1, b = 2'},
		)


class ScopeTests(unittest.TestCase):
	def test_the_scopes_of_a_frame(self):
		self.assertTrue(inline_values.is_frame_scope('Locals'))
		self.assertTrue(inline_values.is_frame_scope('Arguments'))
		self.assertTrue(inline_values.is_frame_scope('Closure (outer)'))
		self.assertFalse(inline_values.is_frame_scope('Globals'))
		self.assertFalse(inline_values.is_frame_scope('Global', expensive=True))
		self.assertFalse(inline_values.is_frame_scope('Anything', expensive=True))
		self.assertFalse(inline_values.is_frame_scope('CPU', presentation_hint='registers'))


class StyleTests(unittest.TestCase):
	def test_what_it_is_without_any_setting(self):
		self.assertEqual(
			inline_values.style_css(),
			'color: color(var(--foreground) alpha(0.75)); font-style: italic; font-weight: normal; font-size: 0.9em;',
		)

	def test_every_setting(self):
		self.assertEqual(
			inline_values.style_css('#8a6d3b', 1, 'Bold Italic', 'JetBrains Mono', 12.5),
			'color: color(#8a6d3b alpha(1)); font-style: italic; font-weight: bold; font-size: 12.5px; font-family: "JetBrains Mono";',
		)
		self.assertIn('font-style: normal; font-weight: normal;', inline_values.style_css(font_style='normal'))
		self.assertIn('color(var(--bluish) alpha(0.5))', inline_values.style_css('var(--bluish)', 0.5))

	def test_a_value_that_makes_no_sense_is_passed_over(self):
		default = inline_values.style_css()
		self.assertEqual(inline_values.style_css('red; } body { display: none', 'dark', 7, 'Mono"; color: red', -3), default)
		self.assertEqual(inline_values.style_css(opacity=True, font_size=False), default)

	def test_opacity_stays_readable_and_no_more_than_solid(self):
		self.assertIn('alpha(0.1)', inline_values.style_css(opacity=0))
		self.assertIn('alpha(1)', inline_values.style_css(opacity=9))
