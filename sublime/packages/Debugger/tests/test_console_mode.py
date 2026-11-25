from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

from test_open_ui import debugger_method

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_console_mode_test', ROOT / 'modules' / 'console_mode.py')
console_mode = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console_mode)


class ConsoleModeTests(unittest.TestCase):
	def test_a_configuration_says_internal_or_external_and_internal_when_it_says_nothing(self):
		self.assertEqual(console_mode.mode('internal'), 'internal')
		self.assertEqual(console_mode.mode('external'), 'external')
		self.assertEqual(console_mode.mode(None), 'internal')
		self.assertEqual(console_mode.mode('something else'), 'internal')
		self.assertTrue(console_mode.is_internal_by_choice('internal'))
		self.assertFalse(console_mode.is_internal_by_choice(None))
		self.assertFalse(console_mode.is_internal_by_choice('external'))

	def test_an_adapter_is_told_in_its_own_words_and_they_read_back_the_same(self):
		for place in console_mode.PLACES:
			self.assertEqual(console_mode.for_adapter('internal', place), 'internalConsole')
			self.assertEqual(console_mode.for_adapter(None, place), 'internalConsole')
			# what a session keeps is what its adapter was told
			self.assertEqual(console_mode.mode(console_mode.for_adapter('external', place)), 'external')
			self.assertEqual(console_mode.mode(console_mode.for_adapter('internal', place)), 'internal')

		self.assertEqual(console_mode.for_adapter('external', 'terminus_panel'), 'integratedTerminal')
		self.assertEqual(console_mode.for_adapter('external', 'terminus'), 'externalTerminal')
		self.assertEqual(console_mode.for_adapter('external', 'platform'), 'externalTerminal')

	def test_a_configuration_may_only_say_one_of_the_two(self):
		self.assertEqual(console_mode.refused('externalTerminal'), '"console": "externalTerminal" is no longer used, write "console": "external"')
		self.assertEqual(console_mode.refused('integratedTerminal'), '"console": "integratedTerminal" is no longer used, write "console": "external"')
		self.assertEqual(console_mode.refused('internalConsole'), '"console": "internalConsole" is no longer used, write "console": "internal"')
		self.assertEqual(console_mode.refused('terminal'), '"console": "terminal" is not a console, write "console": "internal" or "console": "external"')
		self.assertIsNone(console_mode.refused('internal'))
		self.assertIsNone(console_mode.refused('external'))
		self.assertIsNone(console_mode.refused(None))

	def test_completions_offer_the_two_values_whatever_the_adapter_lists(self):
		listed = {'enum': ['internalConsole', 'integratedTerminal', 'externalTerminal'], 'default': 'integratedTerminal'}
		schema = {'launch': {'properties': {'console': listed, 'nested': {'properties': {'console': dict(listed)}}, 'program': {'type': 'string'}}}}

		result = console_mode.in_schema(schema)

		self.assertEqual(result['launch']['properties']['console']['enum'], ['internal', 'external'])
		self.assertEqual(result['launch']['properties']['nested']['properties']['console']['default'], 'internal')
		self.assertEqual(result['launch']['properties']['program'], {'type': 'string'})

		snippets = [{'label': 'nodemon', 'body': {'console': 'integratedTerminal', 'internalConsoleOptions': 'neverOpen'}}]
		self.assertEqual(console_mode.in_snippet(snippets), [{'label': 'nodemon', 'body': {'console': 'external', 'internalConsoleOptions': 'neverOpen'}}])


class Configuration(dict):
	name = 'App'
	id_ish = 'configuration_App'


class LaunchTests(unittest.TestCase):
	def launch(self, configuration, place='terminus'):
		class Session:
			def __init__(self, configuration=None, parent=None, **kwargs):
				self.configuration, self.parent, self.is_paused = configuration, parent, False

			async def launch(self):
				pass

		debugger = types.SimpleNamespace(sessions=[], console=Mock(), open_session_output=Mock(), open_log=Mock(return_value=None), logs={})
		for event in ('on_session_modules_updated', 'on_session_sources_updated', 'on_session_threads_updated',
			'on_session_variables_updated', 'on_session_updated', 'on_session_output', 'on_session_thread_or_frame_updated',
			'on_session_added', 'on_session_active', 'session_terminal_request', 'session_task_request'):
			setattr(debugger, event, Mock())

		method = debugger_method('launch', {'dap': types.SimpleNamespace(Session=Session, Error=RuntimeError), 'test_buttons': Mock(),
			'Settings': types.SimpleNamespace(external_terminal=place)})
		asyncio.run(method(debugger, Mock(), configuration))
		return debugger

	def test_every_configuration_is_launched_with_one_of_the_two(self):
		for written, place, told in (
			(None, 'terminus', 'internalConsole'),
			('internal', 'terminus', 'internalConsole'),
			('external', 'terminus', 'externalTerminal'),
			('external', 'platform', 'externalTerminal'),
			('external', 'terminus_panel', 'integratedTerminal'),
		):
			configuration = Configuration({'console': written} if written else {})
			debugger = self.launch(configuration, place)
			self.assertEqual(configuration['console'], told, (written, place))

	def test_a_configuration_written_in_the_words_of_the_protocol_is_not_started_and_says_what_to_write(self):
		configuration = Configuration(console='integratedTerminal')

		with self.assertRaises(RuntimeError) as raised:
			self.launch(configuration, 'terminus')

		self.assertEqual(str(raised.exception), 'App: "console": "integratedTerminal" is no longer used, write "console": "external"')
		# nothing was started, and the configuration is as it was written
		self.assertEqual(configuration['console'], 'integratedTerminal')


if __name__ == '__main__':
	unittest.main()
