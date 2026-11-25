from __future__ import annotations

import importlib.util
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_exception_format_test', ROOT / 'modules' / 'exception_format.py')
exception_format = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exception_format)

lines = exception_format.exception_lines


def info(**fields):
	details = fields.pop('details', None)
	return types.SimpleNamespace(details=types.SimpleNamespace(**details) if details else None, **fields)


class ExceptionLinesTests(unittest.TestCase):
	def test_debugpy_gives_an_id_a_description_and_a_trace(self):
		heading, trace = lines(info(exceptionId='ValueError', description='boom', details={'stackTrace': '  File "a.py", line 1\n    f()\n', 'message': 'boom', 'typeName': 'ValueError'}))
		self.assertEqual(heading, ['ValueError: boom'])
		self.assertEqual(trace, ['  File "a.py", line 1', '    f()'])

	def test_what_the_stopped_line_already_says_is_not_said_again(self):
		heading, trace = lines(info(exceptionId='panic', description='runtime error: index out of range'), 'Stopped: panic: runtime error: index out of range')
		self.assertEqual((heading, trace), ([], []))

	def test_an_id_and_a_description_that_are_the_same_are_one_line(self):
		heading, _ = lines(info(exceptionId='boom', description='boom'))
		self.assertEqual(heading, ['boom'])

	def test_a_response_as_a_dict_and_with_nothing_in_it(self):
		self.assertEqual(lines({'exceptionId': 'E', 'details': {'message': 'm'}}), (['E', 'm'], []))
		self.assertEqual(lines({}), ([], []))

	def test_what_it_was_raised_from(self):
		heading, _ = lines({'exceptionId': 'Outer', 'details': {'innerException': [{'typeName': 'Inner', 'message': 'why'}]}})
		self.assertEqual(heading, ['Outer', 'Caused by: Inner: why'])

	def test_a_long_trace_is_cut_and_says_so(self):
		trace = '\n'.join(f'frame {index}' for index in range(40))
		_, shown = lines({'details': {'stackTrace': trace}})
		self.assertEqual(len(shown), exception_format.MAX_TRACE_LINES + 1)
		self.assertEqual(shown[0], 'frame 0')
		self.assertIn('28 more lines', shown[-1])
