from __future__ import annotations
import re
from typing import Any

from . import core


def ansi_colorize(text: str, color: str | None = None, previous_color: str | None = None):
	text = text.replace('\r\n', '\n')

	def replacement(x: Any):
		try:
			return escape_codes_by_code[x.group()]['match']
		except KeyError as e:
			core.debug('Unhandled ansi escape', e)
			return ''

	text = ansi_escape.sub(replacement, text)

	if color != previous_color:
		return escape_code(color) + text
	else:
		return text


def escape_code(color: str | None):
	match = escape_codes_by_color.get(color)
	if not match:
		return '\u200c\u200b'

	return f'\u200c{match["match"]}'


# from https://stackoverflow.com/questions/14693701/how-can-i-remove-the-ansi-escape-sequences-from-a-string-in-python
ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')

escape_codes: list[dict[str, Any]] = [
	{
		'color': 'foreground',
		'escape': ['\u001b[30m', '\u001b[37m', '\u001b[39m', '\u001b[0m', '\u001b[90m'],
		'match': '\u200b',
	},
	{
		'color': 'comment',
		'escape': ['\u001b[90m'],
		'scope': 'comment.debugger',
		'match': '\u200b\u200b',
	},
	{
		'color': 'red',
		'escape': ['\u001b[31m', '\u001b[91m'],
		'scope': 'region.redish.debugger',
		'match': '\u200b\u200b\u200b',
	},
	{
		'color': 'green',
		'escape': ['\u001b[32m', '\u001b[92m'],
		'scope': 'region.greenish.debugger',
		'match': '\u200b\u200b\u200b\u200b',
	},
	{
		'color': 'yellow',
		'escape': ['\u001b[33m', '\u001b[93m'],
		'scope': 'region.yellowish.debugger',
		'match': '\u200b\u200b\u200b\u200b\u200b',
	},
	{
		'color': 'blue',
		'escape': ['\u001b[34m', '\u001b[94m'],
		'scope': 'region.bluish.debugger',
		'match': '\u200b\u200b\u200b\u200b\u200b\u200b',
	},
	{
		'color': 'magenta',
		'escape': ['\u001b[35m', '\u001b[95m'],
		'scope': 'region.purplish.debugger',
		'match': '\u200b\u200b\u200b\u200b\u200b\u200b\u200b',
	},
	{
		'color': 'cyan',
		'escape': ['\u001b[36m', '\u001b[96m'],
		'scope': 'region.cyanish.debugger',
		'match': '\u200b\u200b\u200b\u200b\u200b\u200b\u200b\u200b',
	},
	# The two the console writes itself, with no ansi code of their own. Both take the scheme's
	# plain text colour; what stands out inside them is scoped the way source code is, so the
	# colour scheme decides how a prompt, a string or a number looks.
	{
		# an expression echoed after enter: `:settings.os`, the prompt dimmed like a comment
		'color': 'input',
		'escape': [],
		'scope': 'meta.input.debugger',
		'match': '​' * 9,
		'prompt': ':',
	},
	{
		# what an expression evaluated to: strings, numbers and the language's constants are
		# picked out of the value the adapter rendered, whichever language it is
		'color': 'result',
		'escape': [],
		'scope': 'meta.result.debugger',
		'match': '​' * 10,
		'inner': [
			(r'"(?:[^"\\]|\\.)*"', 'string.quoted.double.debugger'),
			(r"'(?:[^'\\]|\\.)*'", 'string.quoted.single.debugger'),
			(r'\b(?:True|False|None|true|false|null|nil|undefined|NaN|Infinity)\b', 'constant.language.debugger'),
			(r'(?<![\w.])-?(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b', 'constant.numeric.debugger'),
		],
	},
]

escape_codes_by_code: dict[str | None, Any] = {}
escape_codes_by_color: dict[str | None, Any] = {}

for item in escape_codes:
	escape_codes_by_color[item['color']] = item

	for escape in item['escape']:
		escape_codes_by_code[escape] = item


def _yaml_string(value: str) -> str:
	return "'" + value.replace("'", "''") + "'"


def generate_ansi_syntax():
	'''The console syntax: a marker of N zero-width spaces opens a colour's context, `\u200c` closes it

	Longest markers first, since a shorter one is a prefix of every longer one. Each colour has a
	named context; `inner` rules highlight inside it and a `prompt` is scoped once, right after the
	marker, by handing over to a second context that no longer looks for it.
	'''
	yaml = '''%YAML 1.2
---
hidden: true
scope: debugger.console
name: Debugger Console

contexts:
	main:
'''
	items = [item for item in reversed(escape_codes) if item.get('scope')]
	for item in items:
		yaml += f'''		- match: {_yaml_string(item['match'])}
			scope: {item['scope']}
			push: {item['color']}
'''
	for item in items:
		scope, color = item['scope'], item['color']
		body = f'''		- meta_scope: {scope}
		- match: '\u200c'
			scope: {scope}
			pop: true
'''
		if prompt := item.get('prompt'):
			yaml += f'''	{color}:
{body}		- match: {_yaml_string(prompt)}
			scope: {scope} comment.debugger punctuation.definition.prompt.debugger
			set: {color}-body
	{color}-body:
{body}'''
			continue
		yaml += f'	{color}:\n{body}'
		for match, inner_scope in item.get('inner', ()):
			yaml += f'''		- match: {_yaml_string(match)}
			scope: {inner_scope}
'''
	return yaml.replace('\t', '  ')
