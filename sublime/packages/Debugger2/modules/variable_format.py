from __future__ import annotations

from typing import Protocol


'''How the value of a variable is turned into what a row shows.

An adapter puts the whole recursive serialization of a value in the DAP `value` field, and
each one formats it its own way: delve writes `main.Config {Name: "x"}`, debugpy writes
`Name(a=1)` for an object and only the contents for a dict, lldb writes `Item @ 0x16fdfe260`.
Nothing here talks to sublime or to a session, so it can be exercised on its own — see
`tests/`.
'''


# The rows debugpy folds an object's members into when they are not its data: `__dunder__`
# members, methods, nested classes and, with `variablePresentation.protected` at `group` (the
# python adapter's default), its `_protected` members. Each is a collapsed row that opens to the
# members; it belongs after the object's own fields, and a hover leaves it out altogether
PYTHON_GROUPS = ('special variables', 'function variables', 'class variables', 'protected variables')


class SummarizableVariable(Protocol):
	'''What summarizing a value needs of it, so this module does not depend on `dap`'''

	value: str | None
	type: str | None
	memoryReference: str | None

	@property
	def has_children(self) -> bool: ...


# how many characters of a row the popup shows before it wraps, and how a continuation and a
# child of a row are indented under it
WRAP_WIDTH = 100
CONTINUATION_INDENT = '    '
CHILD_INDENT = '  '

# delve writes the length, the capacity and the contents of a slice as top level commas of the field
# it belongs to, so `Tags: []string len: 2, cap: 2, ["x","y"]` is one field and not four
_CONTINUATION_KEYS = ('len', 'cap')


# contents this wide leave no room for the name in front of them once the row is indented, and the
# popup wraps at a hundred characters
MAX_INLINE_CONTENTS = 80


def _is_flat_contents(value: str) -> bool:
	'''Whether `value` holds only scalars, nothing that is listed as a row of its own underneath

	How long a value is says nothing about how much it holds. An adapter renders only so many levels
	and elides the rest, debugpy writing `{...}`, so `{'a': {'x': 1, 'y': {...}}}` is short and stands
	for an arbitrary amount. Previewing contents inline is only worth it when they are all there.
	'''
	depth = 0
	quote = ''
	escaped = False

	for character in value:
		if quote:
			if escaped:
				escaped = False
			elif character == '\\':
				escaped = True
			elif character == quote:
				quote = ''
			continue

		if character in '\'"':
			quote = character
			continue

		if character in '{[(':
			depth += 1
			# past the container itself, so this item has contents of its own
			if depth > 1:
				return False
		elif character in '}])':
			depth -= 1

	# an adapter that elided the contents left nothing to preview
	return '...' not in value


def value_summary(variable: SummarizableVariable) -> str:
	'''A short type level label for a value that has children

	The DAP `value` of an expandable variable is often the entire recursive serialization of its contents,
	delve for instance renders a slice as `[]main.item len: 5, cap: 8, [{Name: "item-1", ...}, ...]`.
	Using that as the label of the row repeats every child that is listed below it and pushes the rest of
	the row off the end, so only the part in front of the contents is kept, plus the address of the value
	when the adapter reports one.
	'''
	value = (variable.value or '').strip()

	if not variable.has_children:
		return value

	index = _contents_index(value)
	if index < 0:
		return value

	summary = value[:index].strip().rstrip(',').strip()

	# adapters that render a container as nothing but its contents, like `[1, 2, 3]`, leave no type or
	# length in front of it. Contents that are all there and fit on the row preview inline; otherwise
	# the reported type stands in for them and the items are read one per line underneath
	if not summary:
		if variable.type and (len(value) > MAX_INLINE_CONTENTS or not _is_flat_contents(value)):
			return variable.type
		return value

	if variable.memoryReference:
		summary += f' {variable.memoryReference}'

	return summary


def _closes_at_end(value: str, start: int) -> bool:
	'''Whether the `(` at `start` opens a group that runs to the end of the value

	A python repr renders the contents of an object as `Name(a=1, b=2)`, so the group reaches the end.
	Delve reports the dynamic type of an interface in front of its contents, as in
	`error(*errors.errorString) *{s: "boom"}`, where it does not — that group is part of the type and
	belongs in the summary rather than being mistaken for the start of the contents.

	An unterminated group counts, since an adapter that capped the value cut it off inside the contents.
	'''
	depth = 0
	quote = ''
	escaped = False

	for index in range(start, len(value)):
		character = value[index]

		if quote:
			if escaped:
				escaped = False
			elif character == '\\':
				escaped = True
			elif character == quote:
				quote = ''
			continue

		if character in '\'"':
			quote = character
			continue

		if character == '(':
			depth += 1
			continue

		if character == ')':
			depth -= 1
			if depth == 0:
				return not value[index + 1 :].strip()

	return True


def _contents_index(value: str) -> int:
	'''The index at which the adapter started rendering the contents of a container, or -1

	The contents are the first `{`, the first `(` that opens a group reaching the end of the value, or
	the first `[` that is not part of a type. A `[` belongs to a type when an identifier runs into it, as
	in `map[string]int`, or when it holds nothing or a number, as in the go types `[]main.item` and
	`[5]int`. Looking forwards rather than stripping the group the value ends with matters because
	adapters cap the length of a value, delve for one, so the contents are often left unterminated.

	A `{`, `(` or `[` inside a string literal is part of a value the adapter already rendered, not the
	start of the contents, so literals are stepped over.
	'''
	quote = ''
	escaped = False

	for index, character in enumerate(value):
		if quote:
			if escaped:
				escaped = False
			elif character == '\\':
				escaped = True
			elif character == quote:
				quote = ''
			continue

		if character in '\'"':
			quote = character
			continue

		if character == '{':
			return index

		# a python object renders as `Name(...)`, which is contents, while delve writes the type of an
		# interface as `Iface(Concrete) {...}`, which is not
		if character == '(' and _closes_at_end(value, index):
			return index

		if character != '[':
			continue

		# `previous` is empty at the start of the value, where there is no identifier for the `[` to be
		# part of, and an empty string is a substring of anything
		previous = value[index - 1] if index else ''
		if previous and (previous.isalnum() or previous in '_.'):
			continue

		end = value.find(']', index)
		inner = value[index + 1 : end] if end >= 0 else value[index + 1 :]
		if not inner or inner.isdigit():
			continue

		return index

	return -1

def _field_key(field: str) -> str:
	'''What `field` names, up to the separator that follows it, or empty when it names nothing

	A struct separates a field from its value with `:`, a python object with `=`, and either can appear
	inside a string that is part of the value, so only the first one outside a literal counts.
	'''
	quote = ''

	for index, character in enumerate(field):
		if quote:
			if character == quote:
				quote = ''
			continue

		if character in '"\'':
			quote = character
		elif character in ':=':
			return field[:index].strip()

	return ''

def _is_field_key(key: str) -> bool:
	'''Whether `key` reads as the name of a field rather than part of the value in front of it'''
	if key.isidentifier():
		return True

	# a dict writes its keys as literals where a struct writes identifiers
	return len(key) > 1 and key[0] == key[-1] and key[0] in '"\''

def _fields_of(value: str) -> tuple[str, list[str]] | None:
	"""`types.T {A: 1, B: "x, y"}` as its header and one entry per field, or None if it is not one

	The last level the popup goes to prints a value the way the adapter wrote it, on one line, and a
	struct written that way is unreadable long before it is finished. Laying it out down the page rather
	than across it costs nothing, no request and no depth, and reads like the rest of the popup.

	Only top level commas are separators, so a comma inside a string or inside a nested value stays where
	it is. A value that is not this shape does not match and is left alone.
	"""
	# a python object writes its fields inside `(...)` rather than `{...}`, and only where something
	# names it: a bare `(...)` is a tuple, or the address delve writes for a value it stopped short of
	if '{' in value and value.endswith('}'):
		opening = value.find('{')
	elif '(' in value and value.endswith(')') and value[: value.find('(')].strip():
		opening = value.find('(')
	else:
		return None

	header = value[:opening].strip()
	body = value[opening + 1 : -1]

	fields: list[str] = []
	start = 0
	depth = 0
	quote = ''

	for index, character in enumerate(body):
		if quote:
			if character == quote:
				quote = ''
			continue

		if character in '"\'':
			quote = character
		elif character in '{[(':
			depth += 1
		elif character in '}])':
			depth -= 1
		elif character == ',' and depth == 0:
			fields.append(body[start:index].strip())
			start = index + 1

	fields.append(body[start:].strip())

	folded: list[str] = []
	named = False

	for field in fields:
		if not field:
			continue

		key = _field_key(field)
		named = named or (_is_field_key(key) and key not in _CONTINUATION_KEYS)

		# a piece that does not start a field of its own belongs to the one before it
		if folded and (not _is_field_key(key) or key in _CONTINUATION_KEYS):
			folded[-1] += f', {field}'
		else:
			folded.append(field)

	# nothing in it named a field, so the group holds positional values rather than a struct:
	# rust writes `Some(5)`, a js function its parameters, a c++ vector its length
	return (header, folded) if folded and named else None

def _line_for_variable(name: str, value: str | None, indent: str = '') -> str:
	# the popup is a single line per value, embedded newlines would break the alignment of the rows
	text = ' '.join((value or '').split())

	if name:
		text = f'{name}: {text}'

	return indent + text

def _leaf_lines(name: str, value: str | None, indent: str) -> list[str]:
	'''The last level the popup goes to, laid out down the page when it is a struct'''
	line = _line_for_variable(name, value, indent)

	if len(line) > WRAP_WIDTH and (fields := _fields_of(' '.join((value or '').split()))):
		header, entries = fields
		lines = [_line_for_variable(name, header, indent)]

		for entry in entries:
			lines += _wrapped(indent + CHILD_INDENT + entry, indent + CHILD_INDENT + CONTINUATION_INDENT)

		return lines

	return _wrapped(line, indent + CONTINUATION_INDENT)

def _wrapped(text: str, indent: str) -> list[str]:
	'''`text` broken across as many lines as it needs, continuations indented under it

	The popup is a fixed number of characters across and nothing in it wraps, so a value longer than that
	was cut off at the edge with nothing to say it had been: a struct with a few fields in it, or a slice
	of anything with an address in it, is unreadable past the first line. Breaking it here rather than
	leaving it to minihtml also puts the break where a reader would, after a separator.
	'''
	if len(text) <= WRAP_WIDTH:
		return [text]

	lines: list[str] = []
	remaining = text

	while len(remaining) > WRAP_WIDTH:
		# break after the last separator that fits, or mid token when a single one fills the line. A comma
		# on its own counts: delve writes the elements of a slice with no space after them
		window = remaining[:WRAP_WIDTH]
		cut = max(window.rfind(','), window.rfind(' '))
		cut = cut + 1 if cut > len(indent) else WRAP_WIDTH

		lines.append(remaining[:cut].rstrip())
		remaining = indent + remaining[cut:].lstrip()

	lines.append(remaining)
	return lines
