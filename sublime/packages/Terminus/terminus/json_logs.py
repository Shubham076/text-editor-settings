'''Logs a program prints as json, one object a line, made readable

	{"level":"info","ts":"2026-11-26T10:32:01.123Z","msg":"request completed","status":200}

reads, in the `compact` mode, as

	10:32:01.123 INFO  request completed  status=200

This file is the same in the Debugger (`modules/json_logs.py`) and in Terminus
(`terminus/json_logs.py`): neither package needs the other, so each has a copy, and a test of the
Debugger fails when the two differ. It imports nothing of Sublime's.

Only a whole line that parses as a json object is touched, with a real parser: quotes, braces and
escapes inside a value are the parser's business. Everything else is passed on as it came.

What comes out is coloured with the eight plain ansi colours and nothing else, which both a
terminal and the Debugger's console understand. A value is text of the program, not of the
terminal: a control character in it (an escape that would start a colour, or move the cursor) is
written out as its `\\uXXXX`, never sent.
'''

import json
import re
import time

MODES = ('off', 'compact', 'fields', 'pretty')

TIME_KEYS = ('ts', 'time', 'timestamp', '@timestamp', 't', 'asctime')
LEVEL_KEYS = ('level', 'lvl', 'severity', 'levelname', 'loglevel', 'log.level')
MESSAGE_KEYS = ('msg', 'message', 'event')

RESET = '\x1b[0m'
DIM = '\x1b[90m'
RED = '\x1b[31m'
GREEN = '\x1b[32m'
YELLOW = '\x1b[33m'
BLUE = '\x1b[34m'
MAGENTA = '\x1b[35m'
CYAN = '\x1b[36m'

# The name of a field is what the eye looks for in a line of them, so it has a colour of its own
# and is not dimmed: grey on the background of a light colour scheme was hard to read. A number
# or a constant is the colour a colour scheme tends to give one. Only the time is dimmed.
KEY = CYAN
CONSTANT = MAGENTA

# what pino and bunyan write for a level
NUMERIC_LEVELS = {10: 'trace', 20: 'debug', 30: 'info', 40: 'warn', 50: 'error', 60: 'fatal'}
LEVEL_NAMES = {'warning': 'warn', 'err': 'error', 'critical': 'fatal', 'crit': 'fatal', 'information': 'info', 'dbg': 'debug'}
LEVEL_COLORS = {
	'trace': DIM, 'debug': BLUE, 'info': GREEN, 'notice': GREEN, 'warn': YELLOW,
	'error': RED, 'fatal': RED, 'panic': RED, 'dpanic': RED, 'alert': RED, 'emergency': RED,
}

# a line longer than this is not looked at: it is data, not a log
MAX_LINE = 256 * 1024

SGR = r'(?:\x1b\[[0-9;]*m)*'
# a line that may be an object, whatever colour the program wrapped it in
CANDIDATE = re.compile(r'^(\s*)' + SGR + r'(\{.*\})' + SGR + r'\s*$', re.DOTALL)
# a piece of a line that may still become one
OPENING = re.compile(r'^\s*' + SGR + r'\{')
# the full screen of an editor or a pager: lines are placed there, not printed
ALTERNATE_SCREEN = re.compile(r'\x1b\[\?(?:1049|1047|47)([hl])')
ISO_TIME = re.compile(r'^\d{4}-\d\d-\d\d[T ](\d\d:\d\d:\d\d)(?:[.,](\d+))?')
# what must not reach a terminal or a view as itself: the control characters, the invisible
# characters (the console's colour markers are zero-width spaces), and the ones that reorder text
UNSAFE = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]')
UNSAFE_INLINE = re.compile('[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]')
SHORT_ESCAPES = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}


class Number(str):
	'''A number as the program wrote it: `1.50` stays `1.50`, and a long integer keeps its digits'''


def parse(line):
	'''The object a line is, or `None`; the second value is the blank the line started with'''
	if len(line) > MAX_LINE:
		return None, ''
	match = CANDIDATE.match(line)
	if not match:
		return None, ''
	try:
		value = json.loads(match.group(2), parse_float=Number, parse_int=Number, parse_constant=Number)
	except (ValueError, RecursionError):
		return None, ''
	if not isinstance(value, dict) or not value:
		return None, ''
	return value, match.group(1)


def escape(text, inline=True):
	'''`text` with nothing in it that a terminal or a view would act on; a block keeps its newlines and tabs'''
	def replacement(match):
		character = match.group()
		return SHORT_ESCAPES.get(character) or '\\u{:04x}'.format(ord(character))
	return (UNSAFE_INLINE if inline else UNSAFE).sub(replacement, text)


def paint(text, color, colors):
	return color + text + RESET if colors and color and text else text


def take(record, keys):
	'''Takes the first of `keys` the record has a plain value for out of it'''
	for key in keys:
		value = record.get(key)
		if isinstance(value, str) and not isinstance(value, Number) and value.strip() or isinstance(value, Number):
			del record[key]
			return value
	return None


def time_text(value):
	'''The time of day of a timestamp: of an iso date its own, of an epoch the local one'''
	if value is None:
		return ''
	if isinstance(value, Number):
		try:
			seconds = float(value)
		except ValueError:
			return escape(value)
		# seconds, milliseconds, microseconds or nanoseconds since 1970, told apart by their size
		for scale in (1, 1e3, 1e6, 1e9):
			if abs(seconds) / scale < 1e11:
				seconds /= scale
				break
		try:
			local = time.localtime(seconds)
		except (OverflowError, OSError, ValueError):
			return escape(value)
		return '{}.{:03d}'.format(time.strftime('%H:%M:%S', local), int(seconds * 1000) % 1000)
	match = ISO_TIME.match(value)
	if not match:
		return escape(value.strip())
	return match.group(1) + ('.' + (match.group(2) + '00')[:3] if match.group(2) else '')


def level_text(value):
	'''(name, colour) of a level: `INFO` in green; `('', None)` when there is none'''
	if value is None:
		return '', None
	name = str(value).strip().lower()
	if isinstance(value, Number):
		try:
			name = NUMERIC_LEVELS.get(int(float(value)), name)
		except (ValueError, OverflowError):
			pass
	name = LEVEL_NAMES.get(name, name)
	return escape(name.upper()), LEVEL_COLORS.get(name)


def headline(record, colors):
	'''`10:32:01.123 INFO  request completed`, from the fields it takes out of the record'''
	when = time_text(take(record, TIME_KEYS))
	level, color = level_text(take(record, LEVEL_KEYS))
	message = take(record, MESSAGE_KEYS)
	parts = []
	if when:
		parts.append(paint(when, DIM, colors))
	if level:
		parts.append(paint(level.ljust(5), color, colors))
	if message is not None:
		# a message of several lines is one line here, the headline is what a log is found by
		parts.append(escape(str(message)))
	return ' '.join(parts)


def scalar(value, colors):
	'''A value that is not a string, an object or a list: a number, `true`, `false`, `null`'''
	if value is None:
		text = 'null'
	elif value is True:
		text = 'true'
	elif value is False:
		text = 'false'
	else:
		text = escape(str(value))
	return paint(text, CONSTANT, colors)


def quoted(text):
	'''A string in quotes, for where it would not be told from what is around it'''
	return '"' + escape(text.replace('\\', '\\\\').replace('"', '\\"')) + '"'


def inline(value, colors, top=True):
	'''A value on one line: `GET`, `"two words"`, `200`, `[admin, dev]`, `{id: 42}`'''
	if isinstance(value, str) and not isinstance(value, Number):
		bare = value and not re.search(r'\s', value) and (top or not re.search(r'[,:\[\]{}"]', value))
		return escape(value) if bare else quoted(value)
	if isinstance(value, list):
		return '[' + ', '.join(inline(item, colors, False) for item in value) + ']'
	if isinstance(value, dict):
		return '{' + ', '.join('{}: {}'.format(paint(key_text(key), KEY, colors), inline(item, colors, False)) for key, item in value.items()) + '}'
	return scalar(value, colors)


def key_text(key):
	return escape(key) if key and not re.search(r'[\s=:"]', key) else quoted(key)


def is_block(value):
	'''A string of several lines: a stack trace, a query. It is shown as the lines it is'''
	return isinstance(value, str) and not isinstance(value, Number) and '\n' in value.strip('\r\n')


def block(value, indent, newline):
	lines = value.strip('\r\n').replace('\r\n', '\n').split('\n')
	return (newline + indent).join(escape(line.rstrip('\r'), inline=False).expandtabs(4) for line in lines)


def flatten(record, prefix=''):
	'''(key, value) of every field, an object inside as `user.id`, `user.name`'''
	for key, value in record.items():
		name = prefix + key_text(key)
		if isinstance(value, dict) and value:
			for pair in flatten(value, name + '.'):
				yield pair
		else:
			yield name, value


def compact(record, colors, newline):
	'''One line a log: the headline, then `key=value` of the rest; a value of several lines goes below'''
	line = headline(record, colors)
	fields, blocks = [], []
	for key, value in flatten(record):
		if is_block(value):
			blocks.append('    ' + paint(key + ':', KEY, colors) + ' ' + block(value, '      ', newline))
		else:
			fields.append(paint(key, KEY, colors) + paint('=', DIM, colors) + inline(value, colors))
	if fields:
		line += ('  ' if line else '') + ' '.join(fields)
	return newline.join([line] + blocks if line else blocks)


def fields(record, colors, newline):
	'''The headline, and under it a line a field, the values in a column'''
	lines = [headline(record, colors)]
	names = [key_text(key) for key in record]
	width = max([len(name) for name in names] or [0])
	for name, value in zip(names, record.values()):
		text = block(value, ' ' * (width + 6), newline) if is_block(value) else inline(value, colors)
		lines.append('    ' + paint(name.ljust(width), KEY, colors) + '  ' + text)
	return newline.join(line for line in lines if line)


def pretty(value, colors, newline, depth=0, key=None):
	'''The json itself, indented. It stays json: a string keeps its quotes and its escapes'''
	indent = '  ' * (depth + 1)
	if isinstance(value, dict) and value:
		items = ['{}{}: {}'.format(indent, paint(dumps(name), KEY, colors), pretty(item, colors, newline, depth + 1, name)) for name, item in value.items()]
		return '{' + newline + (',' + newline).join(items) + newline + '  ' * depth + '}'
	if isinstance(value, list) and value:
		items = [indent + pretty(item, colors, newline, depth + 1) for item in value]
		return '[' + newline + (',' + newline).join(items) + newline + '  ' * depth + ']'
	if isinstance(value, Number):
		return paint(escape(value), CONSTANT, colors)
	if isinstance(value, str):
		color = level_text(value)[1] if depth == 0 and key in LEVEL_KEYS else None
		return paint(dumps(value), color, colors)
	if isinstance(value, (dict, list)):
		return '{}' if isinstance(value, dict) else '[]'
	return scalar(value, colors)


def dumps(text):
	# json escapes the control characters; the invisible ones it leaves are escaped the same way
	return escape(json.dumps(text, ensure_ascii=False))


def format_line(line, mode='compact', colors=True, newline='\n'):
	'''`line` (without its line ending) formatted, or `None` when it is not a json object or `mode` is off'''
	if mode not in MODES or mode == 'off':
		return None
	record, lead = parse(line)
	if record is None:
		return None
	try:
		if mode == 'pretty':
			text = pretty(record, colors, newline)
		else:
			text = (compact if mode == 'compact' else fields)(record, colors, newline)
	except RecursionError:
		return None
	if not text:
		return None
	return lead + text.replace(newline, newline + lead) if lead else text


def mode_of(*values):
	'''The first of `values` that names a mode, `off` when none does: a task's own, then the setting'''
	for value in values:
		if value is True:
			return 'compact'
		if value is False:
			return 'off'
		if isinstance(value, str) and value in MODES:
			return value
	return 'off'


class Stream:
	'''Formats the json lines of output that arrives in pieces

	`feed` takes a piece and returns what can be shown of it by now, as (text, formatted) pairs.
	A line is only known for json when it has ended, so a piece that opens with `{` and has no
	newline yet is held back; `flush` gives it up as it is, for when the rest does not come (a
	program that prints `{` and waits). Anything that cannot be the start of an object is passed
	on at once, so a prompt, a progress bar or what is typed is never held.

	With `terminal` the lines end in `\\r\\n` as they came, and nothing is touched while a full
	screen program (an editor, a pager) has the alternate screen.
	'''

	def __init__(self, mode='compact', colors=True, terminal=False):
		self.mode = mode if mode in MODES else 'off'
		self.colors = colors
		self.terminal = terminal
		self.held = ''
		self.alternate = False

	@property
	def pending(self):
		return bool(self.held)

	def feed_text(self, text):
		return ''.join(piece for piece, _ in self.feed(text))

	def feed(self, text):
		if self.mode == 'off' or not text:
			return [(text, False)] if text else []
		out = []
		if self.terminal:
			at = 0
			for match in ALTERNATE_SCREEN.finditer(text):
				self.lines(text[at:match.end()], out)
				self.alternate = match.group(1) == 'h'
				at = match.end()
			self.lines(text[at:], out)
		else:
			self.lines(text, out)
		return self.merged(out)

	def flush(self):
		held, self.held = self.held, ''
		return [(held, False)] if held else []

	def lines(self, text, out):
		if self.alternate:
			held, self.held = self.held, ''
			if held + text:
				out.append((held + text, False))
			return
		text = self.held + text
		self.held = ''
		start = 0
		while True:
			end = text.find('\n', start)
			if end < 0:
				break
			line = text[start:end]
			ending = '\n'
			if line.endswith('\r'):
				line, ending = line[:-1], '\r\n'
			formatted = format_line(line, self.mode, self.colors, ending) if '{' in line else None
			out.append((line + ending, False) if formatted is None else (formatted + ending, True))
			start = end + 1
		rest = text[start:]
		if rest and len(rest) <= MAX_LINE and OPENING.match(rest):
			self.held = rest
		elif rest:
			out.append((rest, False))

	@staticmethod
	def merged(pieces):
		out = []
		for text, formatted in pieces:
			if out and out[-1][1] == formatted:
				out[-1] = (out[-1][0] + text, formatted)
			else:
				out.append((text, formatted))
		return out
