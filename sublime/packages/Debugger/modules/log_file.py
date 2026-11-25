'''`log` in a configuration: what the program prints, kept in a file as well as shown

	"log": {"file": "${project_path}/logs/api.log", "append": false}

One file for everything the program writes, as it is read in the console or the terminal: what
was written to stdout and what was written to stderr in the order they came. A terminal has
already put the two together by the time anything can read it, so one file is also the only
thing that is the same for a program started in the console and one started in a terminal.

Imports no sublime, so it can be exercised from a terminal (`tests/test_log_file.py`).
'''

from __future__ import annotations

import os
import re
from typing import Any

# colours and cursor movement mean something to a terminal and nothing in a file
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]')


class LogError(Exception):
	pass


def options(value: Any, base: str | None) -> tuple[str, bool] | None:
	'''The file a configuration logs to and whether it is added to, `None` when it does not log

	A path that is not absolute is looked for from `base`, the `cwd` of the configuration or the
	folder of the project.
	'''
	if value is None or value is False:
		return None

	if not isinstance(value, dict):
		raise LogError('`log` has to be an object: {"file": "path", "append": false}')

	unknown = sorted(set(value) - {'file', 'append'})
	if unknown:
		raise LogError('`log` has no `{}`, it takes `file` and `append`'.format('`, `'.join(unknown)))

	file = value.get('file')
	if not isinstance(file, str) or not file.strip():
		raise LogError('`log` needs a `file`, the path the output is written to')

	append = value.get('append', False)
	if not isinstance(append, bool):
		raise LogError('`append` of `log` is true or false')

	path = os.path.expanduser(file.strip())
	if not os.path.isabs(path) and base:
		path = os.path.join(base, path)

	return os.path.normpath(path), append


def clean(text: str) -> str:
	return _ANSI.sub('', text).replace('\r\n', '\n').replace('\r', '\n')


class LogFile:
	'''The file of one run of a configuration

	Written to in one of two ways. Output that arrives in pieces, from the adapter, is added as it
	comes (`write`). The text of a terminal is not pieces, it is a screen that is redrawn, so it is
	written whole each time it is read (`replace`), over what this run wrote before and after
	whatever was already in the file when `append` kept it.
	'''

	def __init__(self, path: str, append: bool = False):
		self.path = path
		self.append = append
		# whether the program runs in a terminal, which says which of the two ways is the one used
		self.terminal = False

		try:
			folder = os.path.dirname(path)
			if folder:
				os.makedirs(folder, exist_ok=True)

			self.file: Any = open(path, 'a' if append else 'w', encoding='utf-8', newline='\n')
			# a run added to one that did not end its last line starts on a line of its own
			if append and self.file.tell() and not _ends_with_newline(path):
				self.file.write('\n')
				self.file.flush()

			# where this run starts, which is where the text of a terminal is rewritten from
			self.start = self.file.tell()

		except OSError as error:
			raise LogError(f'Unable to write the log `{path}`: {error.strerror or error}')

	def write(self, text: str) -> None:
		if not self.file or not text:
			return
		try:
			self.file.write(clean(text))
			# a log is read while the program runs, and after it was killed
			self.file.flush()
		except (OSError, ValueError):
			self.close()

	def replace(self, text: str) -> None:
		if not self.file:
			return
		try:
			text = clean(text)
			if text and not text.endswith('\n'):
				text += '\n'
			self.file.seek(self.start)
			self.file.truncate()
			self.file.write(text)
			self.file.flush()
		except (OSError, ValueError):
			self.close()

	def close(self) -> None:
		file, self.file = self.file, None
		if file:
			try:
				file.close()
			except OSError:
				...


def _ends_with_newline(path: str) -> bool:
	try:
		with open(path, 'rb') as file:
			file.seek(-1, os.SEEK_END)
			return file.read(1) == b'\n'
	except OSError:
		return True
