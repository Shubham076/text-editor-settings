from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_env_file_test', ROOT / 'modules' / 'env_file.py')
env_file = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env_file)


class ParseTests(unittest.TestCase):
	def test_assignments_comments_and_export(self):
		text = '# a comment\n\nA=1\nexport B = two\n  C=three # trailing\nnot an assignment\nD=\n'
		self.assertEqual(env_file.parse(text), {'A': '1', 'B': 'two', 'C': 'three', 'D': ''})

	def test_quotes(self):
		text = 'A="one # not a comment"\nB=\'two\\n\'\nC="three\\nlines"\nD="has \\"quotes\\"" # after\n'
		self.assertEqual(env_file.parse(text), {'A': 'one # not a comment', 'B': 'two\\n', 'C': 'three\nlines', 'D': 'has "quotes"'})

	def test_a_double_quoted_value_runs_over_lines(self):
		self.assertEqual(env_file.parse('KEY="-----BEGIN\nabc\n-----END"\nNEXT=1\n'), {'KEY': '-----BEGIN\nabc\n-----END', 'NEXT': '1'})

	def test_a_hash_without_a_space_is_part_of_the_value(self):
		self.assertEqual(env_file.parse('URL=http://host/#anchor\n'), {'URL': 'http://host/#anchor'})

	def test_a_later_assignment_wins(self):
		self.assertEqual(env_file.parse('A=1\nA=2\n'), {'A': '2'})


class ApplyTests(unittest.TestCase):
	def setUp(self):
		self.directory = tempfile.TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.base = Path(self.directory.name)
		(self.base / '.env').write_text('A=file\nB=file\n')
		(self.base / 'second.env').write_text('B=second\nC=second\n')

	def test_the_configuration_wins_over_the_file_and_envFile_is_taken_out(self):
		configuration = {'envFile': '.env', 'env': {'A': 'configuration'}}
		names = env_file.apply(configuration, str(self.base))

		self.assertEqual(configuration, {'env': {'A': 'configuration', 'B': 'file'}})
		self.assertEqual(names, ['A', 'B'])

	def test_a_list_of_files_and_an_absolute_path(self):
		configuration = {'envFile': ['.env', str(self.base / 'second.env')]}
		env_file.apply(configuration, str(self.base))
		self.assertEqual(configuration['env'], {'A': 'file', 'B': 'second', 'C': 'second'})

	def test_an_env_written_as_a_list_stays_a_list(self):
		configuration = {'envFile': '.env', 'env': ['A=configuration', 'Z=1']}
		env_file.apply(configuration, str(self.base))
		self.assertEqual(configuration['env'], ['B=file', 'A=configuration', 'Z=1'])

	def test_nothing_named_changes_nothing(self):
		configuration = {'env': {'A': '1'}}
		self.assertEqual(env_file.apply(configuration, None), [])
		self.assertEqual(configuration, {'env': {'A': '1'}})

	def test_a_missing_file_is_an_error_that_names_it(self):
		with self.assertRaises(env_file.EnvFileError) as raised:
			env_file.apply({'envFile': 'missing.env'}, str(self.base))
		self.assertIn('missing.env', str(raised.exception))

	def test_something_that_is_not_a_path_is_refused(self):
		with self.assertRaises(env_file.EnvFileError):
			env_file.apply({'envFile': {'a': 1}}, str(self.base))
