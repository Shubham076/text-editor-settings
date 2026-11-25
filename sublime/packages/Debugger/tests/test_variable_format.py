'''Tests for `modules/variable_format.py`, the label a variable row shows.

Run them with `python3 tests/run.py` from the package directory. Nothing here imports
sublime, so they run in a terminal in well under a second.

Three kinds of test:

- `TestRecordedFixtures` replays values captured over DAP from real adapters and checks the
  label against `fixtures/expected.json`. A change in behaviour shows up as a diff naming
  the adapter and the value. Regenerate with `python3 tests/run.py --update` and read the
  diff before committing it.
- `TestBehaviour` pins the specific defects that were fixed, one test each, so a regression
  names itself rather than showing up as an anonymous fixture diff.
- `TestInvariants` asserts properties that must hold for every adapter, including ones with
  no fixture here: a label is never an unbalanced fragment, and it never ends on a dangling
  separator.
'''

from __future__ import annotations

import json
import importlib.util
import pathlib
import unittest

TESTS = pathlib.Path(__file__).parent
FIXTURES = TESTS / 'fixtures'

# imported by path: the package is not importable as a module outside sublime
_spec = importlib.util.spec_from_file_location('variable_format', TESTS.parent / 'modules' / 'variable_format.py')
assert _spec and _spec.loader
vf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vf)

RECORDED = ('delve.json', 'debugpy.json', 'lldb_c.json', 'lldb_rust.json')


class Variable:
	'''Enough of `dap.Variable` to summarize one'''

	def __init__(self, value, type=None, has_children=True, memoryReference=None):
		self.value = value
		self.type = type
		self._has_children = has_children
		self.memoryReference = memoryReference

	@property
	def has_children(self):
		return self._has_children


def load(name: str) -> dict:
	return json.loads((FIXTURES / name).read_text())


def every_variable():
	'''Every fixture variable as `(source, name, Variable)`'''
	for file in RECORDED:
		doc = load(file)
		for row in doc['variables']:
			yield file, row['name'], Variable(row['value'], row['type'], row['hasChildren'])

	for row in load('synthesized.json')['variables']:
		yield 'synthesized.json', row['name'], Variable(row['value'], row['type'], row['hasChildren'])


def expected_labels() -> dict:
	'''`{fixture: {value: label}}` for everything the fixtures hold'''
	out: dict[str, dict[str, str]] = {}
	for source, _, variable in every_variable():
		out.setdefault(source, {})[variable.value] = vf.value_summary(variable)
	return out


class TestRecordedFixtures(unittest.TestCase):
	def test_labels_match_expected(self):
		expected = load('expected.json')
		actual = expected_labels()

		for source in sorted(set(expected) | set(actual)):
			with self.subTest(fixture=source):
				want, got = expected.get(source, {}), actual.get(source, {})
				self.assertEqual(sorted(want), sorted(got), 'the set of fixture values changed')

				for value in sorted(want):
					self.assertEqual(
						want[value], got[value],
						f'\n  fixture {source}\n  value   {value!r}\n  was     {want[value]!r}\n  now     {got[value]!r}',
					)

	def test_every_recording_has_variables(self):
		for file in RECORDED:
			with self.subTest(fixture=file):
				doc = load(file)
				self.assertTrue(doc['variables'], 'recording is empty')
				self.assertIn('adapter', doc)


class TestBehaviour(unittest.TestCase):
	'''One test per defect that was fixed, so a regression says which'''

	def summary(self, value, type=None, has_children=True, memoryReference=None):
		return vf.value_summary(Variable(value, type, has_children, memoryReference))

	# --- an object summarizes to its type, rather than being cut at a nested brace ---

	def test_python_object_summarizes_to_its_class(self):
		value = "AgenticPluginInstallerSettings(policy=AgenticPluginInstallerPolicy(auto_install='disabled', overrides={}), enabled=True)"
		self.assertEqual(self.summary(value, 'AgenticPluginInstallerSettings'), 'AgenticPluginInstallerSettings')

	def test_python_object_with_no_dict_inside_is_summarized(self):
		value = "PluginOverride(plugin_id='claude-code', auto_install='disabled', release=None)"
		self.assertEqual(self.summary(value, 'PluginOverride'), 'PluginOverride')

	def test_brace_inside_a_string_is_not_the_start_of_contents(self):
		self.assertEqual(self.summary("MyThing(path='/a/{b}/c', n=1)", 'MyThing'), 'MyThing')

	def test_bracket_inside_a_string_is_not_the_start_of_contents(self):
		# lldb writes a char pointer as its address and then the string, and a bracket in that string
		# used to be read as the start of the contents, cutting the label off inside the quotes
		self.assertEqual(self.summary('0x0001 "[a]"', 'const char *'), '0x0001 "[a]"')
		# everything in front of the contents stays in the label, the string included
		self.assertEqual(self.summary('Item "[a]" {Name: 1}', 'Item'), 'Item "[a]"')

	def test_delve_keeps_the_dynamic_type_of_an_interface(self):
		# the `(...)` group does not reach the end of the value, so it is part of the type
		self.assertEqual(self.summary('error(*errors.errorString) *{s: "boom"}', 'error'), 'error(*errors.errorString) *')
		self.assertEqual(self.summary('main.Shape(main.Circle) {R: 2}', 'main.Shape'), 'main.Shape(main.Circle)')

	# --- a container is labelled with its type and read one item per line ---

	def test_a_list_is_recognised_as_a_container(self):
		# regression: `previous` is empty before a leading `[` and '' is a substring of '_.',
		# so every list used to fall through to returning its whole value
		value = "[PluginOverride(plugin_id='a'), PluginOverride(plugin_id='b'), PluginOverride(plugin_id='c')]"
		self.assertEqual(self.summary(value, 'list'), 'list')

	def test_a_dict_holding_an_object_takes_its_type(self):
		value = "{'claude-code': PluginOverride(plugin_id='claude-code', auto_install='disabled')}"
		self.assertEqual(self.summary(value, 'dict'), 'dict')

	def test_a_container_with_no_reported_type_falls_back_to_its_value(self):
		value = '{' + ', '.join(f'{i!r}: {i}' for i in range(40)) + '}'
		self.assertEqual(self.summary(value, None), value)

	# --- flat contents that fit still preview inline ---

	def test_short_flat_contents_preview_inline(self):
		for value in ("{'a': 1, 'b': 2}", '[1, 2, 3]', "['ok', 'yes']", '{}', '[]', "('x', 'y')"):
			with self.subTest(value=value):
				self.assertEqual(self.summary(value, 'dict'), value)

	def test_nesting_is_what_disqualifies_a_preview_not_width(self):
		# the same length, and only one of them is worth previewing
		nested, flat = '[[1, 2], [3, 4]]', "{'a': 1, 'b': 2}"
		self.assertEqual(len(nested), len(flat))
		self.assertEqual(self.summary(nested, 'list'), 'list')
		self.assertEqual(self.summary(flat, 'dict'), flat)

	def test_elided_contents_are_not_previewed(self):
		# 54 characters standing for an unbounded amount: the adapter already gave up
		value = "{'a': {'x': 1, 'y': {...}}, 'b': {'p': 2, 'q': {...}}}"
		self.assertLess(len(value), vf.MAX_INLINE_CONTENTS)
		self.assertEqual(self.summary(value, 'dict'), 'dict')

	def test_flat_but_too_wide_contents_are_not_previewed(self):
		value = "{'url': '" + 'x' * 120 + "'}"
		self.assertTrue(vf._is_flat_contents(value))
		self.assertEqual(self.summary(value, 'dict'), 'dict')

	# --- the memoryReference an adapter reports is kept ---

	def test_memory_reference_is_appended_to_the_summary(self):
		value = '[]types.PluginSelection len: 7, cap: 7, [(*types.PluginSelection)(0x1400013c160)]'
		self.assertEqual(
			self.summary(value, '[]types.PluginSelection', memoryReference='0x1400013c160'),
			'[]types.PluginSelection len: 7, cap: 7 0x1400013c160',
		)

	# --- a value with no children is its own label ---

	def test_a_leaf_is_left_alone(self):
		self.assertEqual(self.summary('"item-1"', 'char[16]', has_children=False), '"item-1"')


class TestFieldLayout(unittest.TestCase):
	'''`_fields_of`: laying a value out down the page instead of across it'''

	def test_a_go_struct_is_one_field_per_line(self):
		self.assertEqual(
			vf._fields_of('main.Config {Name: "x", Port: 8080}'),
			('main.Config', ['Name: "x"', 'Port: 8080']),
		)

	def test_a_python_object_is_one_field_per_line(self):
		self.assertEqual(
			vf._fields_of("PluginOverride(plugin_id='x', auto_install='y')"),
			('PluginOverride', ["plugin_id='x'", "auto_install='y'"]),
		)

	def test_a_dict_is_one_entry_per_line(self):
		self.assertEqual(vf._fields_of("{'a': 1, 'b': 2}"), ('', ["'a': 1", "'b': 2"]))

	def test_a_separator_inside_a_literal_is_part_of_the_value(self):
		self.assertEqual(vf._fields_of('main.Config {Name: "a=b", Port: 1}'), ('main.Config', ['Name: "a=b"', 'Port: 1']))
		self.assertEqual(vf._fields_of("T(path='/a:b/c', n=1)"), ('T', ["path='/a:b/c'", 'n=1']))
		self.assertEqual(vf._fields_of('main.T {A: "x, y", B: 2}'), ('main.T', ['A: "x, y"', 'B: 2']))

	def test_delve_slice_metadata_stays_with_its_field(self):
		header, fields = vf._fields_of('main.Config {Name: "x", Tags: []string len: 2, cap: 2, ["x","y"]}')
		self.assertEqual(header, 'main.Config')
		self.assertEqual(fields, ['Name: "x"', 'Tags: []string len: 2, cap: 2, ["x","y"]'])

	def test_a_positional_group_is_not_a_field_list(self):
		# rust options and tuple variants, js function parameters, a c++ vector length
		for value in ('Some(5)', 'Tagged("t")', 'Point(1, 2)', 'function foo(a, b)', 'ƒ (a, b)',
		              'std::vector<int>(3)', 'Some(Item { name: "x" })'):
			with self.subTest(value=value):
				self.assertIsNone(vf._fields_of(value))

	def test_a_bare_group_is_not_a_field_list(self):
		# a tuple, and the address delve writes for a value it stopped short of
		for value in ("('x', 'y')", '(*main.L4)(0x14000104d98)', '[1, 2, 3]'):
			with self.subTest(value=value):
				self.assertIsNone(vf._fields_of(value))

	def test_a_long_object_is_laid_out_at_the_leaf(self):
		value = "AgenticPluginConfig(api_key='secret-key-value', timeout=5000, max_retries=2, retry_delay_ms=100, fail_open=True)"
		lines = vf._leaf_lines('plugin_config', value, '    ')
		self.assertEqual(lines[0], '    plugin_config: AgenticPluginConfig')
		self.assertIn("      api_key='secret-key-value'", lines)
		self.assertIn('      fail_open=True', lines)

	def test_a_value_that_fits_is_left_on_one_line(self):
		lines = vf._leaf_lines('n', "PluginOverride(plugin_id='x')", '  ')
		self.assertEqual(lines, ["  n: PluginOverride(plugin_id='x')"])


class TestInvariants(unittest.TestCase):
	'''Properties that hold for every adapter, including ones with no fixture here'''

	def test_a_label_is_never_an_unbalanced_fragment(self):
		for source, name, variable in every_variable():
			label = vf.value_summary(variable)
			with self.subTest(fixture=source, name=name):
				self.assertEqual(label.count("'") % 2, 0, f'unbalanced quote in {label!r}')
				self.assertEqual(label.count('"') % 2, 0, f'unbalanced quote in {label!r}')

	def test_a_label_never_ends_on_a_dangling_separator(self):
		for source, name, variable in every_variable():
			label = vf.value_summary(variable).rstrip()
			with self.subTest(fixture=source, name=name):
				if label:
					self.assertNotIn(label[-1], '=(,{[:', f'{label!r} ends mid value')

	def test_a_label_is_the_value_the_type_or_a_prefix_of_the_value(self):
		for source, name, variable in every_variable():
			label = vf.value_summary(variable)
			value = (variable.value or '').strip()
			with self.subTest(fixture=source, name=name):
				prefix = value.startswith(label.rstrip())
				appended = variable.memoryReference and label.endswith(variable.memoryReference)
				self.assertTrue(
					label == value or label == variable.type or prefix or appended,
					f'{label!r} is neither the value, its type, nor a prefix of it',
				)

	def test_a_label_is_never_longer_than_the_value(self):
		for source, name, variable in every_variable():
			variable.memoryReference = None
			label = vf.value_summary(variable)
			with self.subTest(fixture=source, name=name):
				self.assertLessEqual(len(label), len((variable.value or '').strip()))

	def test_a_leaf_is_always_its_own_value(self):
		for source, name, variable in every_variable():
			variable._has_children = False
			with self.subTest(fixture=source, name=name):
				self.assertEqual(vf.value_summary(variable), (variable.value or '').strip())

	def test_flatness_ignores_delimiters_inside_literals(self):
		self.assertTrue(vf._is_flat_contents("{'a': 'x{y}z', 'b': 'p[q]'}"))
		self.assertTrue(vf._is_flat_contents("{'a': 'it\\'s {here}'}"))
		self.assertFalse(vf._is_flat_contents("{'a': {'x': 1}}"))
		self.assertFalse(vf._is_flat_contents("{'a': [1]}"))

	def test_wrapping_never_loses_characters(self):
		for source, name, variable in every_variable():
			value = ' '.join((variable.value or '').split())
			with self.subTest(fixture=source, name=name):
				joined = ''.join(line.strip() for line in vf._wrapped(value, '    '))
				self.assertEqual(joined.replace(' ', ''), value.replace(' ', ''))


if __name__ == '__main__':
	unittest.main(verbosity=2)
