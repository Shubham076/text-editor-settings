from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_debugger_test_runner', ROOT / 'modules' / 'test_runner.py')
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

GO = '''package plugin

import "testing"

// Note: disable zscaler while running this test on local
func TestPlugin(t *testing.T) {
	if true {
	}
}

func helper() {}

func Testify() {}

func TestMain(m *testing.M) {}

func Test(t *testing.T) {}

func Test_lower(t *testing.T) {
}

func BenchmarkEncode(b *testing.B) {
}

func FuzzParse(f *testing.F) {
}

func Example() {
}

func ExampleClient_Do() {
}

func (s *Suite) TestMethod() {
}
	func TestIndented(t *testing.T) {}
'''


class GoTests(unittest.TestCase):
	def test_finds_what_go_test_would_run(self):
		names = [test.name for test in runner.go_find(GO)]

		self.assertEqual(names, ['TestPlugin', 'Test_lower', 'BenchmarkEncode', 'FuzzParse', 'Example', 'ExampleClient_Do'])

	def test_offset_is_the_start_of_the_declaration(self):
		test = runner.go_find(GO)[0]

		self.assertTrue(GO[test.offset:].startswith('func TestPlugin('))
		self.assertEqual(GO[test.end - 2:test.end], '\n}')

	def test_the_language_is_picked_by_file_name(self):
		self.assertEqual(runner.language_for('/src/plugin/plugin_test.go').key, 'go')
		self.assertIsNone(runner.language_for('/src/plugin/plugin.go'))
		self.assertIsNone(runner.language_for(None))

	def test_cursor_inside_a_test_is_that_test(self):
		tests = runner.go_find(GO)

		self.assertEqual(runner.test_at(tests, GO.index('if true')).name, 'TestPlugin')
		self.assertEqual(runner.test_at(tests, GO.index('func TestPlugin')).name, 'TestPlugin')
		self.assertIsNone(runner.test_at(tests, GO.index('func helper')))
		self.assertIsNone(runner.test_at(tests, 0))

	def test_a_test_runs_alone_in_its_package(self):
		configuration = runner.go_configuration('/src/plugin/plugin_test.go', 'TestPlugin')

		self.assertEqual(configuration, {
			'name': 'TestPlugin (plugin)',
			'type': 'go',
			'request': 'launch',
			'mode': 'test',
			'program': '/src/plugin',
			'cwd': '/src/plugin',
			'args': ['-test.run', '^TestPlugin$', '-test.v'],
		})

	def test_a_benchmark_runs_without_the_tests(self):
		configuration = runner.go_configuration('/src/plugin/plugin_test.go', 'BenchmarkEncode')

		self.assertEqual(configuration['args'], ['-test.run', '^$', '-test.bench', '^BenchmarkEncode$', '-test.v'])

	def test_overrides_are_laid_over_the_generated_configuration(self):
		language = runner.language_for('/src/plugin/plugin_test.go')
		settings = {'go': {'env': {'A': '1', 'B': '1'}, 'args': ['-test.count=1'], 'buildFlags': '-tags=x', 'name': 'mine'}, 'python': {'cwd': '/nope'}}
		project = {'go': {'env': {'B': '2'}, 'cwd': '/elsewhere'}}

		configuration = runner.configuration_for(language, '/src/plugin/plugin_test.go', 'TestPlugin', settings, None, project)

		self.assertEqual(configuration['env'], {'A': '1', 'B': '2'})
		self.assertEqual(configuration['args'], ['-test.run', '^TestPlugin$', '-test.v', '-test.count=1'])
		self.assertEqual(configuration['buildFlags'], '-tags=x')
		self.assertEqual(configuration['cwd'], '/elsewhere')
		self.assertEqual(configuration['program'], '/src/plugin')
		# the icon finds its running test by this name
		self.assertEqual(configuration['name'], 'TestPlugin (plugin)')



SUBTESTS = '''package x

type tc struct {
	name string
	n    int
}

var shared = []tc{
	{"first shared", 1},
	{name: "second shared"},
}

func TestTable(t *testing.T) {
	tests := []struct {
		name       string
		setupMocks func(t *testing.T)
	}{
		{
			name:       "sunny day cache hit",
			setupMocks: func(t *testing.T) { x := map[string]int{"}": 1}; _ = '{' },
		},
		{
			name: "built " + suffix,
		},
		{
			// name: "commented"
			name: `raw one`,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Run("inside a row", func(t *testing.T) {})
		})
	}
}

func TestMap(t *testing.T) {
	cases := map[string]struct{ in string }{
		"empty input":   {in: ""},
		"dots.and+plus": {in: "x"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) { _ = c })
	}
}

func TestLiteral(t *testing.T) {
	t.Run("outer one", func(t *testing.T) {
		t.Run("leaf", func(t *testing.T) {})
		for _, tt := range shared {
			t.Run(tt.name, func(t *testing.T) {})
		}
	})
	t.Run(fmt.Sprintf("built %d", 1), func(t *testing.T) {})
	for _, tt := range []tc{{"inline first", 1}, {name: "inline keyed"}} {
		t.Run(tt.name, func(t *testing.T) {})
	}
}

func TestElsewhere(t *testing.T) {
	for _, tt := range loadCases() {
		t.Run(tt.name, func(t *testing.T) {})
	}
}
'''


class GoSubtests(unittest.TestCase):
	def setUp(self):
		self.tests = runner.go_find(SUBTESTS)
		self.names = [test.name for test in self.tests]

	def at(self, name):
		test = next(test for test in self.tests if test.name == name)
		return SUBTESTS[test.offset:test.end]

	def test_each_row_of_a_table_is_a_subtest(self):
		self.assertEqual([name for name in self.names if name.startswith('TestTable')],
			['TestTable', 'TestTable/sunny_day_cache_hit', 'TestTable/raw_one'])

	def test_a_row_is_from_its_brace_to_its_brace(self):
		row = self.at('TestTable/sunny_day_cache_hit')

		self.assertTrue(row.startswith('{\n\t\t\tname:'))
		self.assertTrue(row.endswith("_ = '{' },\n\t\t}"))

	def test_a_name_that_is_built_or_commented_out_is_not_one(self):
		self.assertFalse(any('built' in name or 'commented' in name for name in self.names))

	def test_nothing_inside_a_subtest_whose_name_is_not_known(self):
		self.assertFalse(any('inside_a_row' in name for name in self.names))

	def test_the_keys_of_a_map_are_subtests(self):
		self.assertEqual([name for name in self.names if name.startswith('TestMap')],
			['TestMap', 'TestMap/empty_input', 'TestMap/dots.and+plus'])

	def test_literal_names_nest(self):
		self.assertEqual(sorted(name for name in self.names if name.startswith('TestLiteral')), sorted([
			'TestLiteral', 'TestLiteral/outer_one', 'TestLiteral/outer_one/leaf',
			'TestLiteral/outer_one/first_shared', 'TestLiteral/outer_one/second_shared',
			'TestLiteral/inline_first', 'TestLiteral/inline_keyed',
		]))

	def test_a_table_declared_in_the_file_has_its_icons_on_its_rows(self):
		self.assertTrue(self.at('TestLiteral/outer_one/first_shared').startswith('{"first shared"'))
		self.assertEqual([test.offset for test in self.tests], sorted(test.offset for test in self.tests))

	def test_a_table_that_is_made_somewhere_else_has_no_rows(self):
		self.assertEqual([name for name in self.names if name.startswith('TestElsewhere')], ['TestElsewhere'])

	def test_cursor_in_a_row_is_that_row(self):
		self.assertEqual(runner.test_at(self.tests, SUBTESTS.index('setupMocks: func')).name, 'TestTable/sunny_day_cache_hit')
		self.assertEqual(runner.test_at(self.tests, SUBTESTS.index('for _, tt := range tests')).name, 'TestTable')
		self.assertEqual(runner.test_at(self.tests, SUBTESTS.index('t.Run("leaf"') + 3).name, 'TestLiteral/outer_one/leaf')

	def test_a_subtest_runs_by_the_names_on_the_way_to_it(self):
		configuration = runner.go_configuration('/src/x/x_test.go', 'TestMap/dots.and+plus')

		self.assertEqual(configuration['name'], 'TestMap/dots.and+plus (x)')
		self.assertEqual(configuration['args'], ['-test.run', '^TestMap$/^dots\\.and\\+plus$', '-test.v'])


PYTHON = """import pytest


def helper():
    pass


def test_top():
    values = [
        1,
    ]

    def test_inner():
        pass


async def test_async():
    pass


class TestThing:
    def test_a(self):
        pass

    def helper(self):
        pass

    class TestInner:
        def test_b(self):
            pass


class Plain:
    def test_not_collected(self):
        pass


class Legacy(unittest.TestCase):
    def test_c(self):
        pass
"""


class PythonTests(unittest.TestCase):
	def test_finds_what_pytest_collects(self):
		self.assertEqual([test.name for test in runner.python_find(PYTHON)], [
			'test_top', 'test_async', 'TestThing', 'TestThing::test_a', 'TestThing::TestInner',
			'TestThing::TestInner::test_b', 'Legacy', 'Legacy::test_c',
		])

	def test_a_test_runs_to_the_end_of_its_body(self):
		tests = {test.name: test for test in runner.python_find(PYTHON)}
		top = tests['test_top']

		self.assertTrue(PYTHON[top.offset:top.end].startswith('def test_top():'))
		self.assertTrue(PYTHON[top.offset:top.end].endswith('pass'))
		self.assertEqual(runner.test_at(list(tests.values()), PYTHON.index('def test_b') + 5).name, 'TestThing::TestInner::test_b')

	def test_configuration_runs_the_one_test_with_pytest(self):
		configuration = runner.python_configuration('/nowhere/tests/test_thing.py', 'TestThing::test_a')

		self.assertEqual(configuration['name'], 'TestThing::test_a (test_thing.py)')
		self.assertEqual(configuration['module'], 'pytest')
		self.assertEqual(configuration['args'], ['/nowhere/tests/test_thing.py::TestThing::test_a', '-s'])
		self.assertEqual(configuration['cwd'], '/nowhere/tests')
		self.assertEqual(runner.python_command(configuration), [
			'cd /nowhere/tests && python -m pytest /nowhere/tests/test_thing.py::TestThing::test_a -s',
		])

	def test_files(self):
		for file, key in (('/a/test_x.py', 'python'), ('/a/x_test.py', 'python'), ('/a/x.py', None), ('/a/contest.py', None)):
			language = runner.language_for(file)
			self.assertEqual(language.key if language else None, key, file)


JAVA = """package a.b;

import org.junit.jupiter.api.Test;

class FooTest {
    String text = "{ // not a brace";

    @Test
    void adds() { int x = 1; }

    @ParameterizedTest(name = "{0}")
    @ValueSource(ints = {1, 2})
    public void many(int x) throws Exception {
    }

    void helper() {}

    @Nested
    class Inner {
        @org.junit.Test public void deep() {}
    }
}

class Other { void x() {} }
"""


class JavaTests(unittest.TestCase):
	def test_finds_the_methods_junit_runs_and_their_classes(self):
		self.assertEqual([test.name for test in runner.java_find(JAVA)], [
			'FooTest', 'FooTest#adds', 'FooTest#many', 'FooTest$Inner', 'FooTest$Inner#deep',
		])

	def test_a_method_is_from_its_annotation_to_the_end_of_its_body(self):
		many = next(test for test in runner.java_find(JAVA) if test.name == 'FooTest#many')

		self.assertTrue(JAVA[many.offset:many.end].startswith('@ParameterizedTest'))
		self.assertTrue(JAVA[many.offset:many.end].endswith('Exception {\n    }'))

	def test_configuration_attaches_to_what_the_build_runs(self):
		with tempfile.TemporaryDirectory() as root:
			root = os.path.realpath(root)
			maven = os.path.join(root, 'maven', 'src', 'test', 'java')
			gradle = os.path.join(root, 'gradle', 'app', 'src', 'test', 'java')
			os.makedirs(maven)
			os.makedirs(gradle)
			for file in (('maven', 'pom.xml'), ('maven', 'mvnw'), ('gradle', 'gradlew'), ('gradle', 'app', 'build.gradle.kts')):
				open(os.path.join(root, *file), 'w').close()

			configuration = runner.java_configuration(os.path.join(maven, 'FooTest.java'), 'FooTest#adds')
			self.assertEqual(configuration['name'], 'FooTest#adds (FooTest.java)')
			self.assertEqual(configuration['request'], 'attach')
			self.assertEqual(configuration['cwd'], os.path.join(root, 'maven'))
			self.assertEqual(configuration['command'], [
				os.path.join(root, 'maven', 'mvnw'), 'test', '-Dtest=FooTest#adds',
				'-Dsurefire.failIfNoSpecifiedTests=false', '-Dmaven.surefire.debug',
			])

			configuration = runner.java_configuration(os.path.join(gradle, 'FooTest.java'), 'FooTest$Inner#deep')
			self.assertEqual(configuration['cwd'], os.path.join(root, 'gradle', 'app'))
			self.assertEqual(configuration['command'], [
				os.path.join(root, 'gradle', 'gradlew'), 'test', '--tests', 'FooTest$Inner.deep', '--debug-jvm',
			])
			self.assertIn("--tests 'FooTest$Inner.deep' --debug-jvm", runner.java_command(configuration)[0])


JEST = """import x from 'y';

describe('math', () => {
  it('adds', () => { expect(1).toBe(1) });
  test.skip('skipped', () => {});
  it.todo('later');

  describe("deep (x)", function () {
    test.only(`plain`, async () => {});
    test(`built ${a}`, () => {});
  });

  describe.each([1, 2])('each %s', (n) => {
    it('inside each', () => {});
  });

  test.each`a | b
  ${1} | ${2}`('row $a', () => {});
});

test('top', () => {});
foo.it('not a test', () => {});
"""


class JestTests(unittest.TestCase):
	def test_finds_the_tests_whose_names_are_written_down(self):
		self.assertEqual([test.name for test in runner.jest_find(JEST)], [
			'math ›', 'math › adds', 'math › deep (x) ›', 'math › deep (x) › plain', 'top',
		])

	def test_a_pattern_matches_the_one_test_or_everything_in_a_describe(self):
		self.assertEqual(runner.jest_pattern('math › deep (x) › plain'), '^math deep \\(x\\) plain$')
		self.assertEqual(runner.jest_pattern('math › deep (x) ›'), '^math deep \\(x\\) ')
		self.assertEqual(runner.jest_label('/a/x.test.ts', 'math ›'), 'math (x.test.ts)')

	def test_configuration_runs_the_file_in_one_process(self):
		with tempfile.TemporaryDirectory() as root:
			root = os.path.realpath(root)
			package = os.path.join(root, 'packages', 'app')
			os.makedirs(os.path.join(package, 'src'))
			os.makedirs(os.path.join(root, 'node_modules', 'jest', 'bin'))
			open(os.path.join(root, 'node_modules', 'jest', 'bin', 'jest.js'), 'w').close()
			open(os.path.join(package, 'package.json'), 'w').close()
			file = os.path.join(package, 'src', 'x.test.ts')

			configuration = runner.jest_configuration(file, 'math › adds')

			self.assertEqual(configuration['type'], 'node')
			self.assertEqual(configuration['cwd'], package)
			self.assertEqual(configuration['program'], os.path.join(root, 'node_modules', 'jest', 'bin', 'jest.js'))
			self.assertEqual(configuration['args'], [
				'--runInBand', '--colors', '--cacheDirectory', runner.JEST_CACHE, '--runTestsByPath', file, '-t', '^math adds$'])
			# source maps are looked for in the repository, which here is as far up as jest is installed
			self.assertEqual(configuration['resolveSourceMapLocations'], [os.path.join(root, '**'), '!**/node_modules/**', '!**/generated/**'])
			self.assertTrue(runner.language_for(file).stderr_is_output)
			self.assertFalse(runner.language_for('/a/b_test.go').stderr_is_output)
			self.assertTrue(runner.jest_command(configuration)[0].endswith("-t '^math adds$'"))

	def test_a_debugged_test_gets_its_source_maps_in_the_code_and_a_cache_of_its_own(self):
		configuration = runner.jest_configuration('/repo/src/x.test.ts', 'adds')

		# loaded before jest, from this package, and it is a file that is there
		self.assertEqual(configuration['runtimeArgs'], ['--require', runner.JEST_PRELOAD])
		self.assertTrue(os.path.isfile(runner.JEST_PRELOAD), runner.JEST_PRELOAD)
		self.assertTrue(os.path.isabs(runner.JEST_PRELOAD))

		# not jest's own cache: that one has code that was made without the map
		cache = configuration['args'][configuration['args'].index('--cacheDirectory') + 1]
		self.assertEqual(cache, runner.JEST_CACHE)
		self.assertNotIn('jest_dx', cache)

		# and what is said to be run is what is run
		command = runner.jest_command(configuration)[0]
		self.assertIn('--require', command)
		self.assertLess(command.index('--require'), command.index('jest.js'))

	@unittest.skipUnless(shutil.which('node'), 'node is not installed')
	def test_the_preload_has_swc_write_the_map_into_the_code_and_changes_nothing_else(self):
		with tempfile.TemporaryDirectory() as root:
			# what a project has: swc, something that uses it, and something that does not
			swc = os.path.join(root, 'node_modules', '@swc', 'core')
			other = os.path.join(root, 'node_modules', 'other')
			os.makedirs(swc)
			os.makedirs(other)
			with open(os.path.join(swc, 'index.js'), 'w') as f:
				f.write('''
					Object.defineProperty(exports, '__esModule', { value: true });
					exports.version = '1.2.3';
					exports.transformSync = function (source, options) { return { code: source, options: options, self: this === exports }; };
					exports.transform = function (source, options) { return Promise.resolve({ options: options }); };
					exports.parseSync = function (source, options) { return { options: options }; };
				''')
			with open(os.path.join(other, 'index.js'), 'w') as f:
				f.write('module.exports = { transformSync: function (source, options) { return { options: options }; } };')
			script = os.path.join(root, 'run.js')
			with open(script, 'w') as f:
				f.write('''
					const swc = require('@swc/core');
					const asked = { sourceMaps: true, jsc: { target: 'es2017' } };
					const sync = swc.transformSync('code', asked);
					swc.transform('code', asked).then((later) => {
						console.log(JSON.stringify({
							sync: sync.options, self: sync.self, later: later.options, asked: asked,
							parse: swc.parseSync('code', { sourceMaps: true }).options,
							version: swc.version, esModule: swc.__esModule, same: require('@swc/core') === swc,
							other: require('other').transformSync('code', { sourceMaps: true }).options,
						}));
					});
				''')

			def run(*arguments):
				return json.loads(subprocess.run(['node', *arguments, script], cwd=root, capture_output=True, text=True, check=True).stdout)

			plain = run()
			self.assertEqual(plain['sync'], {'sourceMaps': True, 'jsc': {'target': 'es2017'}})

			loaded = run('--require', runner.JEST_PRELOAD)
			# the map goes into the code, for a transform that is waited for and one that is not
			self.assertEqual(loaded['sync'], {'sourceMaps': 'inline', 'jsc': {'target': 'es2017'}})
			self.assertEqual(loaded['later'], {'sourceMaps': 'inline', 'jsc': {'target': 'es2017'}})
			# what the project handed over is not written to, and swc is called as it always was
			self.assertEqual(loaded['asked'], {'sourceMaps': True, 'jsc': {'target': 'es2017'}})
			self.assertTrue(loaded['self'])
			# everything else of swc is as it was, and it is the one module however often it is asked for
			self.assertEqual(loaded['parse'], {'sourceMaps': True})
			self.assertEqual((loaded['version'], loaded['esModule'], loaded['same']), ('1.2.3', True, True))
			# and a module that is not swc is not touched, whatever its functions are called
			self.assertEqual(loaded['other'], {'sourceMaps': True})

	def test_files(self):
		for file, key in (('/a/x.test.tsx', 'jest'), ('/a/x.spec.js', 'jest'), ('/a/__tests__/x.mjs', 'jest'), ('/a/x.ts', None)):
			language = runner.language_for(file)
			self.assertEqual(language.key if language else None, key, file)


class CommandTests(unittest.TestCase):
	def test_go_says_what_delve_runs(self):
		configuration = runner.merged(runner.go_configuration('/src/pkg/a_test.go', 'TestX/a_b'), {'buildFlags': '-tags=integration'})

		self.assertEqual(runner.go_command(configuration), ["cd /src/pkg && ./__debug_bin -test.run '^TestX$/^a_b$' -test.v"])

	def test_the_name_of_a_configuration_is_the_label(self):
		for language in runner.LANGUAGES:
			self.assertEqual(language.configuration('/a/b/c_test.go', 'X')['name'], language.label('/a/b/c_test.go', 'X'), language.key)


if __name__ == '__main__':
	unittest.main()
