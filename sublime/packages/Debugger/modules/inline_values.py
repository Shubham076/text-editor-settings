'''Which values are written at the end of which lines while stopped in a frame

The variables of the frame are matched against the names written in the function, from its first
line down to the line that is stopped on: what is below has not run, and a value beside it would
be one it does not have yet.

Imports no sublime, so it can be exercised from a terminal (`tests/test_inline_values.py`).
'''

from __future__ import annotations

import re
from typing import Callable, Iterable

# `$` for php and javascript, where it is part of a name
IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')

MAX_VALUE = 60
MAX_LINE = 150

# how far above the stopped line is read when nothing says where the function starts, and the most
# that is read when something does
LINES_WITHOUT_SYMBOL = 40
MAX_LINES = 300

# scopes that are not about the frame. An adapter is meant to mark these `expensive`, not all do
SKIPPED_SCOPES = ('global', 'globals', 'register', 'registers', 'static', 'statics', 'module', 'script', 'builtins')

DEFAULT_OPACITY = 0.75
DEFAULT_FONT_STYLE = 'italic'

# what a colour or a font name is made of. Anything else in a setting would end the declaration
# it is written into and start another
_COLOR = re.compile(r'^[A-Za-z0-9#(),.%\s-]+$')
_FONT_FACE = re.compile(r'^[A-Za-z0-9 _.-]+$')


def style_css(
	color: object = None,
	opacity: object = None,
	font_style: object = None,
	font_face: object = None,
	font_size: object = None,
) -> str:
	'''The declarations inline values are drawn with, from the `inline_values_*` settings

	Every one of them is optional and a value that makes no sense is passed over for what it would
	have been without it: a typo in a setting should not take the values off the screen.
	'''
	if not isinstance(opacity, (int, float)) or isinstance(opacity, bool):
		opacity = DEFAULT_OPACITY
	opacity = min(1.0, max(0.1, float(opacity)))

	if isinstance(color, str) and _COLOR.match(color.strip()):
		base = color.strip()
	else:
		base = 'var(--foreground)'

	words = str(font_style if isinstance(font_style, str) else DEFAULT_FONT_STYLE).lower().split()
	declarations = [
		f'color: color({base} alpha({opacity:g}))',
		f'font-style: {"italic" if "italic" in words else "normal"}',
		f'font-weight: {"bold" if "bold" in words else "normal"}',
	]

	if isinstance(font_size, (int, float)) and not isinstance(font_size, bool) and font_size > 0:
		declarations.append(f'font-size: {font_size:g}px')
	else:
		declarations.append('font-size: 0.9em')

	if isinstance(font_face, str) and _FONT_FACE.match(font_face.strip()):
		declarations.append(f'font-family: "{font_face.strip()}"')

	return '; '.join(declarations) + ';'


def is_frame_scope(name: str, expensive: bool = False, presentation_hint: str | None = None) -> bool:
	if expensive or presentation_hint == 'registers':
		return False
	return name.strip().lower() not in SKIPPED_SCOPES


def short_value(value: str, limit: int = MAX_VALUE) -> str:
	'''A value on one line and no longer than `limit`'''
	value = ' '.join(value.split())
	if len(value) > limit:
		value = value[: limit - 1].rstrip() + '…'
	return value


def first_line(stopped_line: int, symbol_lines: Iterable[int]) -> int:
	'''The line to read from, given the lines the symbols of the file are on (all 0 based)

	The last symbol at or above the stopped line is the function it is in, or something inside
	that function, and either way nothing above it belongs to the frame.
	'''
	above = [line for line in symbol_lines if line <= stopped_line]
	start = max(above) if above else stopped_line - LINES_WITHOUT_SYMBOL
	return max(0, start, stopped_line - MAX_LINES)


def returned_by(name: str) -> str | None:
	"""What a variable is the return value of, `None` when it is not one

	After stepping out of a function, or over a call, an adapter lists what came back among the
	locals of the frame, under a name that is not a name of the language: debugpy `(return) parse`,
	vscode-js-debug `Return value`, delve `~r0` for a result that has no name. `''` is a return
	value that does not say of what.
	"""
	name = name.strip()
	lowered = name.lower()

	if lowered.startswith('(return)'):
		function = name[len('(return)'):].strip()
		return f'{function}()' if function else ''
	if lowered in ('return value', 'return', '(return value)'):
		return ''
	if re.match(r'^~r\d+$', name):
		return ''
	return None


def returned_text(returned: list[tuple[str, str]], limit: int = MAX_LINE) -> str:
	"""`parse() returned 8080`, for what was just returned to the line that is stopped on"""
	parts = []
	for function, value in returned:
		value = short_value(value)
		parts.append(f'{function} returned {value}' if function else f'returned {value}')
	return short_value(', '.join(parts), limit)


def names_on_line(text: str, names: Iterable[str], is_code: Callable[[int], bool] | None = None) -> list[str]:
	'''The variables a line of source mentions, in the order it mentions them, each once

	A name after a `.`, `->` or `::` is a member of something else that happens to be called the
	same. `is_code` is asked about the column a name starts at, so one in a string or a comment
	can be left out.
	'''
	known = set(names)
	found: list[str] = []

	for match in IDENTIFIER.finditer(text):
		name = match.group(0)
		if name not in known or name in found:
			continue

		before = text[: match.start()].rstrip()
		if before.endswith('.') and not before.endswith('..'):
			continue
		if before.endswith('->') or before.endswith('::'):
			continue

		if is_code and not is_code(match.start()):
			continue

		found.append(name)

	return found


def line_text(pairs: list[tuple[str, str]], limit: int = MAX_LINE) -> str:
	'''`a = 1, b = "x"`, cut to whole variables that fit in `limit`'''
	text = ''
	for name, value in pairs:
		part = f'{name} = {short_value(value)}'
		candidate = f'{text}, {part}' if text else part
		if len(candidate) > limit:
			if not text:
				return short_value(part, limit)
			return text + ', …'
		text = candidate
	return text


def values_by_line(
	lines: Iterable[tuple[int, str]],
	values: dict[str, str],
	is_code: Callable[[int, int], bool] | None = None,
) -> dict[int, str]:
	'''What is written at the end of each line, for the lines that mention a variable

	`lines` are `(line, text)` and `is_code` is asked about `(line, column)`.
	'''
	result: dict[int, str] = {}

	for line, text in lines:
		check = (lambda column, line=line: is_code(line, column)) if is_code else None
		found = names_on_line(text, values, check)
		if found:
			result[line] = line_text([(name, values[name]) for name in found])

	return result
