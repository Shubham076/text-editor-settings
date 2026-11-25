from __future__ import annotations
from typing import Any

'''Where the output of a configuration goes: `"console": "internal"` or `"console": "external"`

internal    the Console tab of the debugger. Output only: nothing can be typed at the program and it
            is not a terminal, which is all a service or a test needs. What a configuration gets
            when it does not say.

external    a terminal, for a program that reads what is typed or draws on the screen. Which
            terminal is the `external_terminal` setting, one of `PLACES`.

Those two are the only names the debugger and its configurations use. Adapters have names of their
own for the same things, and this is the one place that knows them.
'''

INTERNAL = 'internal'
EXTERNAL = 'external'

# `external_terminal`: Terminus as a tab of the editor, Terminus in the debugger panel, the terminal of the system
TAB = 'terminus'
PANEL = 'terminus_panel'
PLATFORM = 'platform'
PLACES = (TAB, PANEL, PLATFORM)

# What the protocol calls them. An adapter is told one of these, and a session keeps what its
# adapter was told, so they are also read back
ADAPTER_INTERNAL = 'internalConsole'
ADAPTER_PANEL = 'integratedTerminal'
ADAPTER_OUTSIDE = 'externalTerminal'


# what the completions of a project file offer for `console`, whatever the adapter: an adapter lists
# the names of the protocol, or does not list the key at all
SCHEMA = {
	'type': 'string',
	'default': INTERNAL,
	'description': 'Where the output of the program goes.',
	'enum': [INTERNAL, EXTERNAL],
	'enumDescriptions': [
		'The Console tab of the debugger. Nothing can be typed at the program',
		'A terminal, for a program that reads what is typed or draws on the screen. Which terminal is the `external_terminal` setting',
	],
}


def in_schema(value: Any) -> Any:
	'''The schema an adapter has for its configurations, with every `console` in it being `SCHEMA`

	Every one: an adapter such as js-debug nests the configurations of what it starts in its own.
	'''
	if isinstance(value, list):
		return [in_schema(item) for item in value]

	if isinstance(value, dict):
		return {key: SCHEMA if key == 'console' and isinstance(item, dict) and 'enum' in item else in_schema(item) for key, item in value.items()}

	return value


def in_snippet(value: Any) -> Any:
	'''A configuration an adapter offers as a starting point, with its `console` in the debuggers words'''
	if isinstance(value, list):
		return [in_snippet(item) for item in value]

	if isinstance(value, dict):
		return {key: mode(item) if key == 'console' and isinstance(item, str) else in_snippet(item) for key, item in value.items()}

	return value


def mode(value: Any) -> str:
	'''`INTERNAL` or `EXTERNAL`, from the `console` of a configuration or of a session

	A session keeps what its adapter was told, so this reads the names of the protocol too. What a
	configuration may say is `refused()`'s to judge, before anything is started.
	'''
	return EXTERNAL if value in (EXTERNAL, ADAPTER_PANEL, ADAPTER_OUTSIDE) else INTERNAL


def is_internal_by_choice(value: Any) -> bool:
	'''Whether a `console` says internal, rather than saying nothing'''
	return bool(value) and mode(value) == INTERNAL


def refused(value: Any) -> str | None:
	'''Why a configuration with this `console` is not started, None when it is one of the two or not there

	The names of the protocol are refused with what to write instead. Running them anyway would keep
	a third and a fourth name for two things alive in every project file.
	'''
	if value is None or value in (INTERNAL, EXTERNAL):
		return None

	if value in (ADAPTER_INTERNAL, 'integratedConsole', ADAPTER_PANEL, ADAPTER_OUTSIDE):
		return f'"console": "{value}" is no longer used, write "console": "{mode(value)}"'

	return f'"console": "{value}" is not a console, write "console": "{INTERNAL}" or "console": "{EXTERNAL}"'


def for_adapter(value: Any, place: str) -> str:
	'''What an adapter is told for a `console`, with `external_terminal` being `place`'''
	if mode(value) == INTERNAL:
		return ADAPTER_INTERNAL

	# an adapter asks for a terminal either way, this only keeps what it asks for true to where it opens
	return ADAPTER_PANEL if place == PANEL else ADAPTER_OUTSIDE
