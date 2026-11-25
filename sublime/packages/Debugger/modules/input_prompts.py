'''`debugger_inputs`: values a configuration asks for when it is started

	"debugger_inputs": [
		{"id": "testName", "type": "promptString", "description": "Test to run", "default": "test_login"},
		{"id": "environment", "type": "pickString", "options": ["local", "staging"]},
	]

and anywhere in a configuration or a task, `${input:testName}`. The same names and shapes as the
`inputs` of a launch.json, so one copied from there works as it is.

What is defined is read here; asking is the editors (`inputs.PromptInput`). Imports no sublime,
so it can be exercised from a terminal (`tests/test_input_prompts.py`).
'''

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT = 'promptString'
PICK = 'pickString'

# how often an input is asked for: on every start, or the first time and not again until it is
# asked to (`Debugger: Ask Inputs Again`)
ALWAYS = 'always'
ONCE = 'once'

# the prefix of the variable an input is written as: `${input:id}`
PREFIX = 'input:'


class InputError(Exception):
	pass


@dataclass
class Option:
	'''One choice of a `pickString`: what is shown and what it stands for'''

	label: str
	value: str


@dataclass
class InputDefinition:
	id: str
	type: str
	description: str = ''
	default: str = ''
	options: list[Option] = field(default_factory=list)
	# `ALWAYS` or `ONCE`, `None` for whatever the `inputs_ask` setting says
	ask: str | None = None

	@property
	def variable(self) -> str:
		return PREFIX + self.id

	def initial(self, last: str | None) -> str:
		'''What a prompt starts on: the answer of the last time, or else the default

		For a list that is the choice the cursor starts on, and an answer that is no longer one
		of the choices is not offered.
		'''
		candidates = [last, self.default]
		if self.type == PICK:
			values = [option.value for option in self.options]
			return next((value for value in candidates if value in values), values[0] if values else '')

		return next((value for value in candidates if value), '')

	def asked(self, last: str | None, default: Any = ALWAYS) -> bool:
		'''Whether it is asked for now, given what it was last answered with

		`default` is the `inputs_ask` setting, for an input that does not say. One that is asked
		once is asked until it has an answer, and one of a list is asked again when the answer it
		has is no longer one of the choices.
		'''
		ask = self.ask or (default if default in (ALWAYS, ONCE) else ALWAYS)
		if ask == ALWAYS or last is None:
			return True
		if self.type == PICK:
			return last not in [option.value for option in self.options]
		return False


def _text(value: Any) -> str:
	# a default of 8080 or true is what was meant, and what is put into a configuration is text
	if isinstance(value, bool):
		return 'true' if value else 'false'
	if isinstance(value, (int, float)):
		return f'{value:g}'
	return value if isinstance(value, str) else ''


def definition(json: Any) -> InputDefinition:
	'''One entry of `debugger_inputs`, or an `InputError` that says what is wrong with it'''
	if not isinstance(json, dict):
		raise InputError('an input has to be an object: {"id": "name", "type": "promptString"}')

	id = json.get('id')
	if not isinstance(id, str) or not id.strip():
		raise InputError('an input needs an `id`, the name it is used by: `${input:id}`')
	id = id.strip()
	if '}' in id or ':' in id:
		raise InputError(f'the `id` of an input cannot have `}}` or `:` in it: {id!r}')

	type = json.get('type', PROMPT)
	if type == 'command':
		raise InputError(f'input `{id}`: `"type": "command"` is not supported, a command of the editor has no value to give back')
	if type not in (PROMPT, PICK):
		raise InputError(f'input `{id}`: `type` is "{PROMPT}" or "{PICK}"')

	options: list[Option] = []
	if type == PICK:
		listed = json.get('options')
		if not isinstance(listed, list) or not listed:
			raise InputError(f'input `{id}`: a "{PICK}" needs `options`, the list to choose from')

		for item in listed:
			if isinstance(item, dict):
				value = _text(item.get('value'))
				label = _text(item.get('label')) or value
			else:
				value = label = _text(item)
			if not label:
				raise InputError(f'input `{id}`: an option is text, or {{"label": "shown", "value": "used"}}')
			options.append(Option(label, value))

	ask = json.get('ask')
	if ask is not None and ask not in (ALWAYS, ONCE):
		raise InputError(f'input `{id}`: `ask` is "{ALWAYS}" or "{ONCE}"')

	return InputDefinition(
		id=id,
		type=type,
		description=_text(json.get('description')),
		default=_text(json.get('default')),
		options=options,
		ask=ask,
	)


def definitions(entries: Any) -> tuple[list[InputDefinition], list[str]]:
	'''Every input that is defined, and what is wrong with the ones that are not

	One that is defined twice is the first of the two: the project comes before the settings,
	which is the order they are listed in.
	'''
	found: dict[str, InputDefinition] = {}
	problems: list[str] = []

	for entry in entries or []:
		try:
			input = definition(entry)
		except InputError as error:
			problems.append(str(error))
			continue

		found.setdefault(input.id, input)

	return list(found.values()), problems
