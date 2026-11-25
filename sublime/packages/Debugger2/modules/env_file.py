'''`envFile` in a configuration: the variables of a dotenv file, laid under its `env`

Only some adapters read an `envFile` themselves (vscode-js-debug does, debugpy and delve leave it
to the editor), so it is read here and handed over as `env`, which every adapter takes. What the
configuration sets in `env` wins over the file, as it does everywhere else an `envFile` is read.

Imports no sublime, so it can be exercised from a terminal (`tests/test_env_file.py`).
'''

from __future__ import annotations

import os
import re
from typing import Any


class EnvFileError(Exception):
	pass


_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(.*)$')
_ESCAPES = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"', "'": "'"}


def parse(text: str) -> dict[str, str]:
	'''The variables a dotenv file sets, in the order it sets them

	`KEY=value`, with or without `export` in front. A value in double quotes has its escapes read and
	may run over several lines, one in single quotes is taken as written, and a bare one ends at a
	` #` comment. Anything that is not an assignment is skipped rather than refused: a file that
	half works is more use than an error about a line nobody meant anything by.
	'''
	values: dict[str, str] = {}
	lines = text.lstrip('﻿').splitlines()
	index = 0

	while index < len(lines):
		line = lines[index]
		index += 1

		match = _LINE.match(line)
		if not match or line.lstrip().startswith('#'):
			continue

		key, rest = match.group(1), match.group(2).strip()

		if rest[:1] in ('"', "'"):
			quote = rest[0]
			body = rest[1:]
			end = _closing_quote(body, quote)

			# a quoted value that is not closed on its line runs on until one that closes it
			while end < 0 and index < len(lines):
				body += '\n' + lines[index]
				index += 1
				end = _closing_quote(body, quote)

			value = body[:end] if end >= 0 else body
			if quote == '"':
				value = re.sub(r'\\(.)', lambda m: _ESCAPES.get(m.group(1), m.group(0)), value)
		else:
			value = re.split(r'\s+#', rest, maxsplit=1)[0].strip()

		values[key] = value

	return values


def _closing_quote(body: str, quote: str) -> int:
	index = 0
	while index < len(body):
		character = body[index]
		if character == '\\' and quote == '"':
			index += 2
			continue
		if character == quote:
			return index
		index += 1
	return -1


def paths(configuration: dict[str, Any]) -> list[str]:
	'''The files a configuration names: `envFile` is one path or a list of them'''
	value = configuration.get('envFile')
	if not value:
		return []
	if isinstance(value, str):
		return [value]
	if isinstance(value, list) and all(isinstance(item, str) for item in value):
		return [item for item in value if item]

	raise EnvFileError('`envFile` has to be a path or a list of paths')


def read(files: list[str], base: str | None) -> dict[str, str]:
	'''The variables of every file, a later file winning over an earlier one

	A path that is not absolute is looked for from `base`, the `cwd` of the configuration or the
	folder of the project.
	'''
	values: dict[str, str] = {}

	for file in files:
		path = os.path.expanduser(file)
		if not os.path.isabs(path) and base:
			path = os.path.join(base, path)

		try:
			with open(path, encoding='utf-8') as f:
				values.update(parse(f.read()))
		except OSError as error:
			raise EnvFileError(f'Unable to read envFile `{path}`: {error.strerror or error}')

	return values


def merged(env: Any, values: dict[str, str]) -> Any:
	'''`env` with the variables of the file under it, in whichever shape the configuration wrote it

	Most adapters take an object. lldb also takes a list of `KEY=value`, and a configuration that
	wrote one gets one back.
	'''
	if isinstance(env, list):
		set_by_configuration = {str(item).split('=', 1)[0] for item in env}
		return [f'{key}={value}' for key, value in values.items() if key not in set_by_configuration] + env

	result = dict(values)
	if isinstance(env, dict):
		result.update(env)
	return result


def apply(configuration: dict[str, Any], base: str | None) -> list[str]:
	'''Moves what `envFile` names into `env`, and returns the names that came from the file

	`envFile` is taken out: an adapter that reads the file itself would read it a second time, and
	relative to wherever it happens to be running.
	'''
	files = paths(configuration)
	if not files:
		return []

	values = read(files, base)
	configuration['env'] = merged(configuration.get('env'), values)
	del configuration['envFile']
	return list(values)
