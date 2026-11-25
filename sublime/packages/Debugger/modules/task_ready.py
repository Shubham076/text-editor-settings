'''The ready signal of a background task: the line of its output that says it can be worked with

A `pre_debug_task` that never ends, a server or a watcher or a tunnel, cannot be waited for and
cannot be not waited for: the first never starts the debugger and the second starts it before
there is anything to connect to. So such a task says what it prints once it is up, `ready_regex`,
and the debugger starts on the first line that matches.

Imports no sublime, so it can be exercised from a terminal (`tests/test_task_ready.py`).
'''

from __future__ import annotations

import re
from typing import Any, Iterable, Pattern

# how long a task is given to say it is ready when it does not say how long that takes
DEFAULT_TIMEOUT = 30.0

# colours and cursor movement, which a line is matched without: a pattern is written from what
# the line reads as, and `Listening` in green is still `Listening`
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]')


class ReadyError(Exception):
	pass


def compile_pattern(pattern: Any) -> Pattern[str]:
	if not isinstance(pattern, str) or not pattern:
		raise ReadyError('`ready_regex` has to be a regular expression')
	try:
		return re.compile(pattern)
	except re.error as error:
		raise ReadyError(f'`ready_regex` is not a regular expression: {error}')


def timeout_of(value: Any) -> float | None:
	'''How many seconds to wait for the signal, `None` for as long as it takes

	`"ready_timeout": 0` is how a task says there is no telling how long it needs.
	'''
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		return DEFAULT_TIMEOUT
	if value <= 0:
		return None
	return float(value)


def clean(text: str) -> str:
	return _ANSI.sub('', text).replace('\r\n', '\n').replace('\r', '\n')


def unwrapped(rows: list[str], widths: Iterable[int]) -> list[str]:
	'''The lines a program printed, from the rows a terminal drew them as

	A terminal has no long lines, it has rows: a line longer than it is wide goes on in the next
	row. A row that is exactly as wide as the terminal is therefore one that went on, and is put
	back together with the row after it. `widths` are the widths the terminal has had, since a
	row keeps the width it was drawn at when the panel is resized.

	A line that happens to be exactly that long is joined to the one after it as well. There is
	no telling the two apart from the rows alone, and it only ever makes a line longer.
	'''
	full = {width for width in widths if width and width > 0}
	lines: list[str] = []
	continued = False

	for row in rows:
		if continued:
			lines[-1] += row
		else:
			lines.append(row)
		continued = len(row) in full

	return lines


def ready_line(pattern: Pattern[str], text: str, widths: Iterable[int] = ()) -> str | None:
	'''The first line of `text` the pattern is found in, anywhere in the line

	`text` is what a terminal shows and `widths` how wide it has been, see `unwrapped`. The rows
	are looked at as they are first: a pattern that fits in a row does not need them rejoined.
	'''
	rows = clean(text).split('\n')

	for line in rows:
		if pattern.search(line):
			return line

	for line in unwrapped(rows, widths):
		if pattern.search(line):
			return line

	return None


def not_ready(name: str, pattern: Pattern[str], reason: str) -> str:
	return f'{name} {reason}: nothing it printed matched `ready_regex` {pattern.pattern!r}. Its output is in its tab'
