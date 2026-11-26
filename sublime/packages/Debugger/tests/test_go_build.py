from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_go_build_test', ROOT / 'modules/go_build.py')
go_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(go_build)

CACHE = '/cache'


def plan(**configuration):
	configuration.setdefault('name', 'server')
	configuration.setdefault('request', 'launch')
	return go_build.plan(configuration, CACHE, go='/bin/go', windows=False)


class PlanTests(unittest.TestCase):
	def test_a_program_is_built_as_delve_builds_it_into_a_file_of_the_cache(self):
		built = plan(program='cmd/release/main.go', cwd='/src/app')
		self.assertTrue(built.output.startswith('/cache/server-'))
		self.assertEqual(built.command, ['/bin/go', 'build', '-o', built.output, '-gcflags', 'all=-N -l', 'cmd/release/main.go'])
		self.assertEqual(built.cwd, '/src/app')

	def test_the_configuration_becomes_one_that_runs_the_binary(self):
		built = plan(program='cmd/release/main.go', cwd='/src/app', buildFlags='-tags=x')
		self.assertEqual(built.changes, {'mode': 'exec', 'program': built.output, 'buildFlags': None, 'output': None})

	def test_build_flags_come_after_the_debug_flags_as_a_string_or_a_list(self):
		for flags in ("-tags='integration e2e' -race", ['-tags=integration e2e', '-race']):
			built = plan(program='.', cwd='/src/app', buildFlags=flags)
			self.assertEqual(built.command[4:], ['-gcflags', 'all=-N -l', "-tags=integration e2e", '-race', '.'])

	def test_a_test_is_built_with_go_test_and_run_in_the_folder_of_its_package(self):
		built = plan(mode='test', program='/src/app/pkg/store')
		self.assertEqual(built.command[:3], ['/bin/go', 'test', '-c'])
		self.assertTrue(built.output.endswith('.test'))
		self.assertEqual(built.cwd, '/src/app/pkg/store')
		self.assertEqual(built.changes['cwd'], '/src/app/pkg/store')
		# a `cwd` the configuration has is the one that counts
		self.assertNotIn('cwd', plan(mode='test', program='./pkg/store', cwd='/src/app/pkg/store').changes)
		self.assertEqual(plan(mode='test', program='pkg/store/store_test.go', cwd=None).changes['cwd'], 'pkg/store')

	def test_without_a_cwd_go_runs_in_the_folder_of_the_program(self):
		self.assertEqual(plan(program='/src/app/cmd/release/main.go').cwd, '/src/app/cmd/release')
		self.assertIsNone(plan(program='cmd/release/main.go').cwd)

	def test_what_delve_does_not_build_is_left_alone(self):
		self.assertIsNone(plan(mode='exec', program='/bin/app'))
		self.assertIsNone(plan(request='attach', mode='local', processId=1))
		self.assertIsNone(plan(mode='debug', program='main.go', port=2345))
		self.assertIsNone(plan(mode='debug'))
		self.assertIsNone(plan(mode='core', program='/bin/app'))

	def test_no_mode_is_debug(self):
		self.assertEqual(plan(program='main.go').command[1], 'build')

	def test_each_thing_that_builds_differently_has_a_binary_of_its_own(self):
		outputs = {
			plan(program='.', cwd='/src/app').output,
			plan(program='.', cwd='/src/other').output,
			plan(program='./cmd', cwd='/src/app').output,
			plan(program='.', cwd='/src/app', buildFlags='-race').output,
			plan(program='.', cwd='/src/app', mode='test').output,
			plan(program='.', cwd='/src/app', env={'GOOS': 'linux'}).output,
			plan(program='.', cwd='/src/app', name='other').output,
		}
		self.assertEqual(len(outputs), 7)
		# what does not change the build does not change the binary
		self.assertEqual(plan(program='.', cwd='/src/app', args=['-v'], env={'PORT': '1'}).output, plan(program='.', cwd='/src/app').output)

	def test_the_tests_of_a_package_share_one_binary(self):
		one = plan(mode='test', program='/src/app/pkg/store', name='TestSave', args=['-test.run', '^TestSave$'])
		other = plan(mode='test', program='/src/app/pkg/store', name='TestLoad', args=['-test.run', '^TestLoad$'])
		self.assertEqual(one.output, other.output)
		self.assertTrue(os.path.basename(one.output).startswith('store-'))

	def test_the_name_of_the_binary_is_safe_as_a_file_name(self):
		built = plan(program='.', cwd='/src', name='ps-global server (launch) / "x"')
		self.assertRegex(os.path.basename(built.output), r'^[\w.-]+$')


class ConfigurationTests(unittest.TestCase):
	def test_started_again_a_configuration_is_built_from_what_it_was_written_as(self):
		configuration = {'name': 'server', 'request': 'launch', 'program': 'main.go', 'cwd': '/src', 'buildFlags': '-race', 'args': ['-v']}
		written = dict(configuration)
		built = go_build.plan(configuration, CACHE, go='/bin/go', windows=False)
		go_build.apply(configuration, built)
		self.assertEqual((configuration['mode'], configuration['program']), ('exec', built.output))
		self.assertNotIn('buildFlags', configuration)
		self.assertEqual(configuration['args'], ['-v'])
		# as it is now it is not something to build
		self.assertIsNone(go_build.plan(configuration, CACHE, go='/bin/go', windows=False))

		go_build.restore(configuration)
		self.assertEqual(configuration, written)
		self.assertEqual(go_build.plan(configuration, CACHE, go='/bin/go', windows=False), built)

	def test_a_cwd_given_to_a_test_is_taken_off_again(self):
		configuration = {'name': 't', 'request': 'launch', 'mode': 'test', 'program': '/src/pkg'}
		go_build.apply(configuration, go_build.plan(configuration, CACHE, go='/bin/go', windows=False))
		self.assertEqual(configuration['cwd'], '/src/pkg')
		go_build.restore(configuration)
		self.assertEqual(configuration, {'name': 't', 'request': 'launch', 'mode': 'test', 'program': '/src/pkg'})

	def test_restoring_what_was_never_changed_changes_nothing(self):
		configuration = {'mode': 'exec', 'program': '/bin/app'}
		go_build.restore(configuration)
		self.assertEqual(configuration, {'mode': 'exec', 'program': '/bin/app'})


class CleanTests(unittest.TestCase):
	def test_binaries_older_than_the_limit_are_removed_and_the_rest_kept(self):
		with tempfile.TemporaryDirectory() as cache:
			now = 1_000_000_000
			for name, hours in (('old', 25), ('fresh', 23), ('ancient', 500)):
				path = os.path.join(cache, name)
				Path(path).write_text('binary')
				os.utime(path, (now - hours * 3600, now - hours * 3600))
			os.mkdir(os.path.join(cache, 'folder'))
			removed = go_build.clean(cache, 24, now=now)
			self.assertEqual(sorted(os.path.basename(path) for path in removed), ['ancient', 'old'])
			self.assertEqual(sorted(os.listdir(cache)), ['folder', 'fresh'])

	def test_no_limit_and_no_folder_remove_nothing(self):
		with tempfile.TemporaryDirectory() as cache:
			path = os.path.join(cache, 'old')
			Path(path).write_text('binary')
			os.utime(path, (0, 0))
			self.assertEqual(go_build.clean(cache, 0), [])
			self.assertTrue(os.path.exists(path))
		self.assertEqual(go_build.clean('/no/such/folder', 24), [])


if __name__ == '__main__':
	unittest.main()
