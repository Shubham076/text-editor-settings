'''What is written under the line an exception stopped on

An adapter answers `exceptionInfo` with as much or as little as it likes: debugpy gives an id, a
description and a python traceback, delve an id and a description that are often the same text,
vscode-js-debug a stack in `details` and nothing else. The lines here are what is left once the
repeats are taken out and the trace is cut to something that fits beside code.

Imports no sublime, so it can be exercised from a terminal (`tests/test_exception_format.py`).
'''

from __future__ import annotations

from typing import Any

# a trace is read from the top, and the phantom pushes the code under it down by its height
MAX_TRACE_LINES = 12
MAX_INNER = 3


def _field(value: Any, name: str) -> Any:
	if value is None:
		return None
	if isinstance(value, dict):
		return value.get(name)
	return getattr(value, name, None)


def _text(value: Any) -> str:
	return value.strip() if isinstance(value, str) else ''


def exception_lines(info: Any, already_shown: str = '') -> tuple[list[str], list[str]]:
	'''The heading lines and the trace lines of an `exceptionInfo` response

	`already_shown` is the text beside the stopped line (`Stopped: ...`): a heading that only says
	that again is left out.
	'''
	heading: list[str] = []

	def add(line: str):
		line = line.strip()
		if not line or line in heading:
			return
		if already_shown and line in already_shown:
			return
		# a line that holds another says both: `ValueError: boom` after `ValueError` and `boom`
		if any(line in other for other in heading):
			return
		heading[:] = [other for other in heading if other not in line]
		heading.append(line)

	details = _field(info, 'details')

	add(_text(_field(info, 'exceptionId')))
	add(_text(_field(info, 'description')))

	type_name = _text(_field(details, 'typeName')) or _text(_field(details, 'fullTypeName'))
	message = _text(_field(details, 'message'))
	if type_name and message:
		add(f'{type_name}: {message}')
	else:
		add(message or type_name)

	# what it was raised from, as far as the adapter says
	inner = _field(details, 'innerException') or []
	for cause in list(inner)[:MAX_INNER]:
		cause_type = _text(_field(cause, 'typeName')) or _text(_field(cause, 'fullTypeName'))
		cause_message = _text(_field(cause, 'message'))
		if cause_type or cause_message:
			add('Caused by: ' + ': '.join(part for part in (cause_type, cause_message) if part))

	# not stripped as a whole: the indent of the first line is part of how a trace reads
	stack_trace = _field(details, 'stackTrace')
	trace = [line.rstrip() for line in (stack_trace if isinstance(stack_trace, str) else '').splitlines() if line.strip()]
	if len(trace) > MAX_TRACE_LINES:
		hidden = len(trace) - MAX_TRACE_LINES
		trace = trace[:MAX_TRACE_LINES] + [f'… {hidden} more line{"s" if hidden != 1 else ""}, see the call stack']

	# a trace that is one line and already the heading is not a trace
	if len(trace) == 1 and trace[0].strip() in heading:
		trace = []

	return heading, trace
