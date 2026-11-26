from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'modules/json_logs.py'
# the copy Terminus has, when the two packages sit side by side as they do in the repository
TERMINUS_COPY = ROOT.parent / 'Terminus/terminus/json_logs.py'

spec = importlib.util.spec_from_file_location('_json_logs_test', SOURCE)
json_logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(json_logs)

INFO = '{"level":"info","ts":"2026-11-26T10:32:01.123Z","msg":"request completed","method":"GET","status":200,"user":{"id":42,"roles":["admin","dev"]}}'


def plain(line, mode='compact'):
	return json_logs.format_line(line, mode, colors=False)


class FormatTests(unittest.TestCase):
	def test_compact_is_one_line_with_the_time_level_and_message_first(self):
		self.assertEqual(plain(INFO), '10:32:01.123 INFO  request completed  method=GET status=200 user.id=42 user.roles=[admin, dev]')

	def test_fields_puts_each_field_on_a_line_of_its_own(self):
		self.assertEqual(plain(INFO, 'fields').split('\n'), [
			'10:32:01.123 INFO  request completed',
			'    method  GET',
			'    status  200',
			'    user    {id: 42, roles: [admin, dev]}',
		])

	def test_pretty_is_still_the_same_json(self):
		tricky = json.dumps({'level': 'warn', 'msg': 'a "quoted" \\ value\n\twith lines', 'n': [1, {'k': None}], 'empty': {}, 'unicode': 'héllo ✓'})
		self.assertEqual(json.loads(plain(tricky, 'pretty')), json.loads(tricky))

	def test_what_is_not_a_json_object_is_left_alone(self):
		for line in ('plain text', '{"a":1', '[1,2]', '{}', '"text"', '42', 'prefix {"a":1}', '{"a":1} suffix', '{a:1}', "{'a':1}", ''):
			self.assertIsNone(plain(line), line)

	def test_off_and_unknown_modes_format_nothing(self):
		self.assertIsNone(plain(INFO, 'off'))
		self.assertIsNone(plain(INFO, 'fancy'))

	def test_quotes_braces_and_separators_inside_a_value_are_part_of_the_value(self):
		line = json.dumps({'msg': 'done', 'path': '/users?q="bob"&x={1}', 'note': 'two words', 'eq': 'a=b', 'empty': ''})
		self.assertEqual(plain(line), 'done  path=/users?q="bob"&x={1} note="two words" eq=a=b empty=""')

	def test_a_value_of_several_lines_goes_below_as_the_lines_it_is(self):
		line = json.dumps({'level': 'error', 'msg': 'query failed', 'err': 'syntax error at "}"\n  at db.query (db.js:12)\n\tat handler', 'retry': False})
		self.assertEqual(plain(line).split('\n'), [
			'ERROR query failed  retry=false',
			'    err: syntax error at "}"',
			'        at db.query (db.js:12)',
			'          at handler',
		])

	def test_control_and_invisible_characters_in_a_value_are_written_out_not_sent(self):
		# an escape would start a colour or move the cursor of a terminal; a zero-width space is a
		# colour marker of the console
		line = json.dumps({'msg': 'a\x1b[31mred\x07', 'k': 'x\u200by\u202ez\r', 'block': 'one\n\x1b[2Jtwo'})
		for mode in ('compact', 'fields', 'pretty'):
			text = plain(line, mode)
			for character in '\x1b\x07\u200b\u202e\r':
				self.assertNotIn(character, text, mode)
		self.assertIn('a\\u001b[31mred\\u0007', plain(line))
		# the carriage return is blank, so the value is in quotes
		self.assertIn('k="x\\u200by\\u202ez\\r"', plain(line))

	def test_the_only_escapes_in_the_output_are_the_colours(self):
		line = json.dumps({'level': 'info', 'ts': 1, 'msg': 'm', 'k': '\x1b[2J', 'n': 1})
		for mode in ('compact', 'fields', 'pretty'):
			text = json_logs.format_line(line, mode)
			known = (json_logs.RESET, json_logs.DIM, json_logs.RED, json_logs.GREEN, json_logs.YELLOW, json_logs.BLUE, json_logs.MAGENTA, json_logs.CYAN)
			for piece in text.split('\x1b')[1:]:
				self.assertTrue(any(('\x1b' + piece).startswith(code) for code in known), repr(piece))

	def test_numbers_are_shown_as_they_were_written(self):
		self.assertEqual(plain('{"a":1.50,"b":12345678901234567890,"c":1e3,"d":-0.0}'), 'a=1.50 b=12345678901234567890 c=1e3 d=-0.0')

	def test_levels_by_name_and_by_number(self):
		for value, name, color in (('"warning"', 'WARN', json_logs.YELLOW), ('50', 'ERROR', json_logs.RED), ('"DEBUG"', 'DEBUG', json_logs.BLUE), ('30', 'INFO', json_logs.GREEN), ('"custom"', 'CUSTOM', None)):
			self.assertEqual(json_logs.level_text(json.loads(value, parse_int=json_logs.Number)), (name, color))
		self.assertEqual(plain('{"severity":"warning","message":"slow"}'), 'WARN  slow')

	def test_time_from_a_date_with_or_without_fraction_and_from_an_epoch(self):
		self.assertEqual(json_logs.time_text('2026-11-26T10:32:01Z'), '10:32:01')
		self.assertEqual(json_logs.time_text('2026-11-26 10:32:01,5'), '10:32:01.500')
		self.assertEqual(json_logs.time_text('2026-11-26T10:32:01.123456789+05:30'), '10:32:01.123')
		self.assertEqual(json_logs.time_text('yesterday'), 'yesterday')
		# the same instant in seconds, milliseconds and nanoseconds reads the same
		seconds = json_logs.time_text(json_logs.Number('1795689122'))
		self.assertRegex(seconds, r'^\d\d:\d\d:02\.000$')
		self.assertEqual(json_logs.time_text(json_logs.Number('1795689122000')), seconds)
		self.assertEqual(json_logs.time_text(json_logs.Number('1795689122000000000')), seconds)

	def test_a_log_with_none_of_the_known_fields_is_its_fields(self):
		self.assertEqual(plain('{"a":1,"b":"x"}'), 'a=1 b=x')
		self.assertEqual(plain('{"msg":""}'), 'msg=""')

	def test_the_blank_a_line_starts_with_is_kept_on_every_line_of_it(self):
		self.assertEqual(plain('  {"msg":"m","e":"a\\nb"}'), '  m\n      e: a\n        b')

	def test_a_line_the_program_coloured_is_still_found(self):
		self.assertEqual(plain('\x1b[32m{"msg":"m"}\x1b[0m'), 'm')

	def test_a_very_long_line_and_a_very_deep_one_are_left_alone(self):
		self.assertIsNone(plain('{"a":"' + 'x' * json_logs.MAX_LINE + '"}'))
		self.assertIsNone(plain('{"a":' * 100000 + '1' + '}' * 100000))

	def test_mode_of_takes_the_first_that_names_a_mode(self):
		self.assertEqual(json_logs.mode_of(None, 'pretty', 'compact'), 'pretty')
		self.assertEqual(json_logs.mode_of('nonsense', None), 'off')
		self.assertEqual(json_logs.mode_of(True), 'compact')
		self.assertEqual(json_logs.mode_of(False, 'compact'), 'off')
		self.assertEqual(json_logs.mode_of('off', 'compact'), 'off')


class StreamTests(unittest.TestCase):
	def test_a_line_that_arrives_in_pieces_is_formatted_once_it_has_ended(self):
		stream = json_logs.Stream('compact', colors=False)
		self.assertEqual(stream.feed('before\n{"msg":"he'), [('before\n', False)])
		self.assertTrue(stream.pending)
		self.assertEqual(stream.feed('llo","k":1}\nafter'), [('hello  k=1\n', True), ('after', False)])
		self.assertFalse(stream.pending)

	def test_what_cannot_start_an_object_is_never_held(self):
		stream = json_logs.Stream('compact', colors=False)
		self.assertEqual(stream.feed('$ '), [('$ ', False)])
		self.assertEqual(stream.feed('Password: '), [('Password: ', False)])
		self.assertFalse(stream.pending)

	def test_a_held_start_is_given_up_as_it_is(self):
		stream = json_logs.Stream('compact', colors=False)
		self.assertEqual(stream.feed('{ waiting'), [])
		self.assertEqual(stream.flush(), [('{ waiting', False)])
		self.assertEqual(stream.flush(), [])

	def test_terminal_lines_keep_their_line_endings(self):
		stream = json_logs.Stream('compact', colors=False, terminal=True)
		self.assertEqual(stream.feed_text('{"msg":"m","e":"a\\nb"}\r\nplain\r\n'), 'm\r\n    e: a\r\n      b\r\nplain\r\n')

	def test_nothing_is_touched_on_the_alternate_screen(self):
		stream = json_logs.Stream('compact', colors=False, terminal=True)
		inside = '\x1b[?1049h{"msg":"in an editor"}\r\n'
		self.assertEqual(stream.feed_text(inside), inside)
		self.assertEqual(stream.feed_text('{"msg":"still"}\r\n'), '{"msg":"still"}\r\n')
		self.assertEqual(stream.feed_text('\x1b[?1049l{"msg":"out"}\r\n'), '\x1b[?1049lout\r\n')

	def test_off_passes_everything_through(self):
		stream = json_logs.Stream('off')
		self.assertEqual(stream.feed('{"msg":"m"}\n{'), [('{"msg":"m"}\n{', False)])
		self.assertFalse(stream.pending)

	def test_no_output_is_lost_or_reordered_whatever_the_pieces(self):
		text = 'a\n{"msg":"m"}\r\n{not json}\n  {"k":[1,2]}\nlast {'
		whole = json_logs.Stream('compact', colors=False)
		expected = whole.feed_text(text) + ''.join(piece for piece, _ in whole.flush())
		for size in (1, 2, 3, 7):
			stream = json_logs.Stream('compact', colors=False)
			out = ''.join(stream.feed_text(text[at:at + size]) for at in range(0, len(text), size))
			out += ''.join(piece for piece, _ in stream.flush())
			self.assertEqual(out, expected, size)


class CopyTests(unittest.TestCase):
	@unittest.skipUnless(TERMINUS_COPY.exists(), 'Terminus is not beside the Debugger here')
	def test_terminus_has_the_same_file(self):
		self.assertEqual(TERMINUS_COPY.read_bytes(), SOURCE.read_bytes(),
			'modules/json_logs.py and Terminus/terminus/json_logs.py differ: copy the one that was changed over the other')


if __name__ == '__main__':
	unittest.main()
