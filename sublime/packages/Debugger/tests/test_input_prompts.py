from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_input_prompts_test', ROOT / 'modules' / 'input_prompts.py')
input_prompts = importlib.util.module_from_spec(spec)
# a dataclass looks its module up by name while it is being defined
sys.modules[spec.name] = input_prompts
spec.loader.exec_module(input_prompts)


class DefinitionTests(unittest.TestCase):
	def test_a_prompt_and_how_it_is_written_in_a_configuration(self):
		input = input_prompts.definition({'id': 'testName', 'type': 'promptString', 'description': 'Test to run', 'default': 'test_login'})
		self.assertEqual((input.id, input.type, input.description, input.default), ('testName', 'promptString', 'Test to run', 'test_login'))
		self.assertEqual(input.variable, 'input:testName')

	def test_a_prompt_is_what_an_input_is_when_it_does_not_say(self):
		self.assertEqual(input_prompts.definition({'id': 'port'}).type, 'promptString')

	def test_a_default_that_is_a_number_or_a_boolean_is_its_text(self):
		self.assertEqual(input_prompts.definition({'id': 'port', 'default': 8080}).default, '8080')
		self.assertEqual(input_prompts.definition({'id': 'verbose', 'default': True}).default, 'true')

	def test_the_options_of_a_list_are_text_or_a_label_and_a_value(self):
		input = input_prompts.definition({'id': 'env', 'type': 'pickString', 'options': ['local', {'label': 'Staging (eu)', 'value': 'staging-eu'}, 3]})
		self.assertEqual([(option.label, option.value) for option in input.options], [('local', 'local'), ('Staging (eu)', 'staging-eu'), ('3', '3')])

	def test_what_is_wrong_with_an_input_is_said(self):
		for json, said in (
			('testName', 'has to be an object'),
			({}, 'needs an `id`'),
			({'id': 'a:b'}, 'cannot have'),
			({'id': 'x', 'type': 'command', 'command': 'pick'}, 'is not supported'),
			({'id': 'x', 'type': 'dropdown'}, '`type` is'),
			({'id': 'x', 'type': 'pickString'}, 'needs `options`'),
			({'id': 'x', 'type': 'pickString', 'options': [{}]}, 'an option is text'),
		):
			with self.assertRaises(input_prompts.InputError) as raised:
				input_prompts.definition(json)
			self.assertIn(said, str(raised.exception))

	def test_the_good_ones_are_kept_and_the_bad_ones_reported(self):
		inputs, problems = input_prompts.definitions([{'id': 'a'}, {'type': 'promptString'}, {'id': 'b'}, {'id': 'a', 'default': 'second'}])
		self.assertEqual([input.id for input in inputs], ['a', 'b'])
		# defined twice, the first one is the one: the project is listed before the settings
		self.assertEqual(inputs[0].default, '')
		self.assertEqual(len(problems), 1)
		self.assertEqual(input_prompts.definitions(None), ([], []))


class InitialTests(unittest.TestCase):
	def test_a_prompt_starts_on_the_last_answer_and_the_default_before_there_is_one(self):
		input = input_prompts.definition({'id': 'name', 'default': 'test_login'})
		self.assertEqual(input.initial(None), 'test_login')
		self.assertEqual(input.initial('test_logout'), 'test_logout')
		self.assertEqual(input_prompts.definition({'id': 'name'}).initial(None), '')

	def test_a_list_starts_on_the_last_answer_while_it_is_still_a_choice(self):
		input = input_prompts.definition({'id': 'env', 'type': 'pickString', 'options': ['local', 'staging', 'production'], 'default': 'staging'})
		self.assertEqual(input.initial(None), 'staging')
		self.assertEqual(input.initial('production'), 'production')
		self.assertEqual(input.initial('retired'), 'staging')
		self.assertEqual(input_prompts.definition({'id': 'env', 'type': 'pickString', 'options': ['a', 'b']}).initial(None), 'a')


class AskTests(unittest.TestCase):
	def test_an_input_is_asked_on_every_start_unless_it_or_the_setting_says_once(self):
		plain = input_prompts.definition({'id': 'name'})
		self.assertTrue(plain.asked(None))
		self.assertTrue(plain.asked('answered'))
		self.assertTrue(plain.asked('answered', 'always'))
		self.assertFalse(plain.asked('answered', 'once'))
		# a setting that is neither is the same as not having set it
		self.assertTrue(plain.asked('answered', 'sometimes'))

	def test_what_an_input_says_wins_over_the_setting(self):
		once = input_prompts.definition({'id': 'name', 'ask': 'once'})
		always = input_prompts.definition({'id': 'name', 'ask': 'always'})
		self.assertFalse(once.asked('answered', 'always'))
		self.assertTrue(always.asked('answered', 'once'))

	def test_once_still_asks_until_there_is_an_answer(self):
		once = input_prompts.definition({'id': 'name', 'ask': 'once'})
		self.assertTrue(once.asked(None))
		# an empty answer is an answer
		self.assertFalse(once.asked(''))

	def test_a_choice_that_is_no_longer_offered_is_asked_for_again(self):
		once = input_prompts.definition({'id': 'env', 'type': 'pickString', 'options': ['local', 'staging'], 'ask': 'once'})
		self.assertFalse(once.asked('staging'))
		self.assertTrue(once.asked('retired'))

	def test_ask_is_always_or_once(self):
		with self.assertRaises(input_prompts.InputError) as raised:
			input_prompts.definition({'id': 'name', 'ask': 'never'})
		self.assertIn('`ask` is', str(raised.exception))


class PromptInputTests(unittest.TestCase):
	'''`inputs.PromptInput` with a command palette that answers what the test says'''

	def setUp(self):
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		self.addCleanup(loop.close)
		self.loop = loop
		self.asked = []
		# what the next question is answered with, `None` for escape
		self.replies = []
		test = self

		class InputText:
			def __init__(self, run, placeholder=None, initial=None):
				self.run, self.placeholder, self.initial = run, placeholder, initial

			def __await__(self):
				return self.answer().__await__()

			async def answer(self):
				test.asked.append(('text', self.placeholder, self.initial))
				await asyncio.sleep(0)
				reply = test.replies.pop(0)
				if reply is not None:
					self.run(reply)

		class InputListItem:
			def __init__(self, run, text):
				self.run, self.text = run, text

		class InputList:
			def __init__(self, placeholder='', index=0):
				self.placeholder, self.index, self.values = placeholder, index, []

			def __getitem__(self, values):
				self.values = values
				return self

			def __await__(self):
				return self.answer().__await__()

			async def answer(self):
				test.asked.append(('list', self.placeholder, [item.text for item in self.values], self.index))
				await asyncio.sleep(0)
				reply = test.replies.pop(0)
				if reply is not None:
					self.values[reply].run()

		class Input:
			pass

		core = types.ModuleType('_pi.core')
		core.Future = lambda: loop.create_future()
		core.CancelledError = asyncio.CancelledError
		core.run = lambda coroutine: loop.create_task(coroutine)
		ui = types.ModuleType('_pi.ui')
		ui.InputText, ui.InputList, ui.InputListItem = InputText, InputList, InputListItem
		dap = types.ModuleType('_pi.dap')
		dap.Error = RuntimeError
		package = types.ModuleType('_pi')
		package.__path__ = []
		dap_package = types.ModuleType('_pi.dap')
		modules = {
			'_pi': package, '_pi.core': core, '_pi.ui': ui, '_pi.dap': dap,
			'_pi.dap.configuration': types.SimpleNamespace(Input=Input), '_pi.input_prompts': input_prompts,
		}
		dap.__path__ = []
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)

		spec = importlib.util.spec_from_file_location('_pi.inputs', ROOT / 'modules' / 'inputs.py')
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		self.PromptInput = module.PromptInput
		self.answers = {}

	def input(self, setting='always', **json):
		'''An input as a start makes one: `setting` is `inputs_ask`, `ask` in `json` is the inputs own'''
		return self.PromptInput(input_prompts.definition(json), self.answers, setting)

	def run_all(self, *coroutines):
		async def gather():
			return await asyncio.gather(*coroutines, return_exceptions=True)
		return self.loop.run_until_complete(gather())

	def test_text_is_asked_for_and_is_the_value(self):
		self.replies = ['test_checkout']
		value, = self.run_all(self.input(id='name', description='Test to run', default='test_login').resolve())
		self.assertEqual(value, 'test_checkout')
		self.assertEqual(self.asked, [('text', 'Test to run', 'test_login')])

	def test_the_next_start_is_offered_the_last_answer(self):
		self.replies = ['test_checkout', 'test_checkout']
		self.run_all(self.input(id='name', default='test_login').resolve())
		self.run_all(self.input(id='name', default='test_login').resolve())
		self.assertEqual([asked[2] for asked in self.asked], ['test_login', 'test_checkout'])

	def test_a_choice_is_its_value_and_the_list_starts_on_the_last_one(self):
		options = ['local', {'label': 'Staging (eu)', 'value': 'staging-eu'}]
		self.replies = [1, 1]
		value, = self.run_all(self.input(id='env', type='pickString', options=options).resolve())
		self.assertEqual(value, 'staging-eu')
		self.run_all(self.input(id='env', type='pickString', options=options).resolve())
		self.assertEqual(self.asked[0], ('list', 'env', ['local', 'Staging (eu)'], 0))
		self.assertEqual(self.asked[1][3], 1)

	def test_used_twice_it_is_asked_once(self):
		self.replies = ['8080']
		input = self.input(id='port')
		self.assertEqual(self.run_all(input.resolve(), input.resolve(), input.resolve()), ['8080', '8080', '8080'])
		self.assertEqual(len(self.asked), 1)

	def test_two_questions_at_once_are_asked_one_after_the_other(self):
		self.replies = ['first', 'second']
		values = self.run_all(self.input(id='a').resolve(), self.input(id='b').resolve())
		self.assertEqual(values, ['first', 'second'])
		self.assertEqual([asked[1] for asked in self.asked], ['a', 'b'])

	def test_escape_is_not_an_answer_and_the_next_question_is_still_asked(self):
		self.replies = [None, 'second']
		first, second = self.run_all(self.input(id='a', default='kept').resolve(), self.input(id='b').resolve())
		self.assertIsInstance(first, asyncio.CancelledError)
		self.assertEqual(second, 'second')
		# what was not answered is not remembered as an answer
		self.assertEqual(self.answers, {'b': 'second'})

	def test_asked_once_it_is_not_asked_on_the_next_start(self):
		self.replies = ['test_checkout']
		first, = self.run_all(self.input(id='name', ask='once').resolve())
		second, = self.run_all(self.input(id='name', ask='once').resolve())
		self.assertEqual((first, second), ('test_checkout', 'test_checkout'))
		self.assertEqual(len(self.asked), 1)

	def test_the_setting_decides_for_an_input_that_does_not_say(self):
		self.replies = ['one', 'two', 'three']
		self.run_all(self.input('once', id='a').resolve())
		self.run_all(self.input('once', id='a').resolve())
		self.assertEqual(len(self.asked), 1)
		# and one that says always is asked whatever the setting is
		self.run_all(self.input('once', id='b', ask='always').resolve())
		self.run_all(self.input('once', id='b', ask='always').resolve())
		self.assertEqual(len(self.asked), 3)

	def test_forgetting_the_answers_is_how_once_is_asked_again(self):
		self.replies = ['first', 'second']
		self.run_all(self.input(id='name', ask='once', default='start').resolve())
		# what `Debugger: Ask Inputs Again` does
		self.answers.clear()
		value, = self.run_all(self.input(id='name', ask='once', default='start').resolve())
		self.assertEqual(value, 'second')
		self.assertEqual([asked[2] for asked in self.asked], ['start', 'start'])

	def test_escape_the_first_time_leaves_once_to_be_asked_again(self):
		self.replies = [None, 'answered']
		first, = self.run_all(self.input(id='name', ask='once').resolve())
		self.assertIsInstance(first, asyncio.CancelledError)
		second, = self.run_all(self.input(id='name', ask='once').resolve())
		self.assertEqual(second, 'answered')
