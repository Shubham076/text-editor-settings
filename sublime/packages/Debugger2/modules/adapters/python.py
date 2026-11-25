from __future__ import annotations
from typing import Any

from . import util
from .. import dap
from .. import core
from ..variable_format import PYTHON_GROUPS

import sublime
import shutil
import os
import subprocess
import shlex

from pathlib import Path


def variable_presentation(configured: Any) -> Any:
	'''The `variablePresentation` a configuration is launched with

	debugpy folds an object's `__dunder__` members, methods and nested classes into collapsed group
	rows, but lists its `_protected` members inline, so a pydantic model shows `_abc_impl` and a
	dozen bound methods next to its fields. Grouped, they are one collapsed row after the fields
	(`VariablesPane`). A configuration that sets `protected` or `all` itself is left as it is.
	'''
	if not isinstance(configured, dict):
		configured = {}
	if 'protected' in configured or 'all' in configured:
		return configured
	return dict(configured, protected='group')


# what debugpy lists under a value that is not part of what the value holds, see `PYTHON_GROUPS`
SYNTHETIC_CHILDREN = {'len()', *PYTHON_GROUPS}

# a mapping debugpy does not know how to open, as the dict it can. Anything else evaluates to None
MAPPING_AS_DICT = "(lambda v: dict(v) if isinstance(v, __import__('collections.abc').abc.Mapping) else None)({})"


class Python(dap.Adapter):
	type = ['debugpy', 'python']
	docs = 'https://github.com/microsoft/vscode-docs/blob/main/docs/python/debugging.md#python-debug-configurations-in-visual-studio-code'

	installer = util.OpenVsxInstaller(type='debugpy', repo='ms-python/debugpy')

	async def start(self, console: dap.Console, configuration: dap.ConfigurationExpanded):
		configuration['variablePresentation'] = variable_presentation(configuration.get('variablePresentation'))

		if configuration.request == 'attach':
			connect = configuration.get('connect')
			if connect:
				host = connect.get('host', 'localhost')
				port = connect.get('port')
				return dap.SocketTransport(host, port)

			port = configuration.get('port')
			if port:
				host = configuration.get('host', 'localhost')
				return dap.SocketTransport(host, port)

			if not configuration.get('listen') and not configuration.get('processId'):
				sublime.error_message('Warning: Check your debugger configuration.\n\n"attach" requires "connect", "listen" or "processId".\n\nIf they contain a $variable that variable may not have existed.')

		python = configuration.get('pythonPath') or configuration.get('python')

		configuration['cwd'] = configuration.get('cwd', await configuration.variables['folder'])
		if not python:
			if 'cwd' in configuration:
				venv = self.get_venv(console, Path(configuration['cwd']))
			elif 'program' in configuration:
				venv = self.get_venv(console, Path(configuration['program']).parent)
			else:
				venv = None

			if venv:
				python, folder = venv
				console.info(f'Detected virtual environment for `{folder}`')
			elif shutil.which('python3'):
				python = shutil.which('python3')
			else:
				python = shutil.which('python')

		if not python:
			raise dap.Error('Unable to find `python3` or `python`')

		console.info(f'Using python `{python}`')

		install_path = self.installer.install_path()
		paths = [
			# the adapter, not the package it is in: run as a script `debugpy` is the command line of
			# the debugger, which prints how it is used and ends
			f'{install_path}/bundled/libs/debugpy/adapter', # new path using openvsx
			f'{install_path}/debugpy/debugpy/adapter'
		]

		for path in paths:
			if not os.path.exists(path):
				continue

			return dap.StdioTransport(
				[
					f'{python}',
					path,
				]
			)

		raise dap.Error(f'Unable to find debugpy searched {paths}')

	async def on_custom_event(self, session: dap.Session, event: str, body: Any):
		if event == 'debugpyAttach':
			configuration = dap.Configuration.from_json(body, -1)
			configuration_expanded = await configuration.Expanded([], session.configuration.variables)
			await session.debugger.launch(self, configuration_expanded, parent=session)
		else:
			core.info(f'event not handled `{event}`')

	async def on_variable_children(self, variable: dap.Variable, children: list[dap.Variable]) -> list[dap.Variable]:
		'''The items of a mapping debugpy opens to nothing but its group rows

		debugpy lists the items of a `dict` and of little else. A `mappingproxy`, which is what a class
		`__dict__` and a frozen settings object are, opens to `special variables` and `function variables`
		and nothing more: its contents exist only in the repr, which the row drops because an open row
		is expected to list them underneath. So a value that came back with no data of its own is asked
		for again as a dict, and the items of that are what it opens to.
		'''
		expression = variable.evaluateName
		if not expression or not variable.value or any(child.name not in SYNTHETIC_CHILDREN for child in children):
			return children

		wrapped = MAPPING_AS_DICT.format(expression)

		try:
			response = await variable.session.evaluate_expression(wrapped, 'watch')
			if not response.variablesReference:
				return children

			items = await variable.session.get_variables(response.variablesReference)
		except dap.Error:
			return children

		items = [item for item in items if item.name not in PYTHON_GROUPS]

		# debugpy names each item by the expression it was reached through, and the mapping itself can be
		# subscripted, so there is no reason for a copied expression to carry the conversion
		for item in items:
			if item.evaluateName:
				item.evaluateName = item.evaluateName.replace(wrapped, expression)

		return items + [child for child in children if child.name in PYTHON_GROUPS]

	# TODO: patch in env since python seems to not inherit it from the adapter process.
	# async def configuration_resolve(self, configuration: dap.ConfigurationExpanded):
	# 	...

	@property
	def configuration_snippets(self) -> list[dict[str, Any]]:
		return [
			{
				'label': 'Python: Current File',
				'body': {
					'name': 'Python: Current File',
					'type': 'python',
					'request': 'launch',
					'program': '\\${file}',
				},
			},
			{
				'label': 'Python: Attach using process id',
				'body': {
					'name': 'Python: Attach using process id',
					'type': 'python',
					'request': 'launch',
					'processId': '${1:process id}',
				},
			},
		]

	def get_venv(self, console: dap.Console, start: Path) -> tuple[Path, Path] | None:
		"""
		Searches a venv in `start` and all its parent directories.
		"""
		resolved = start.resolve()
		for folder in [resolved] + list(resolved.parents):
			python_path = self.resolve_python_path_from_venv_folder(console, folder)
			if python_path:
				return python_path, folder
		return None

	def resolve_python_path_from_venv_folder(self, console: dap.Console, folder: Path) -> Path | None:
		"""
		Resolves the python binary from venv.
		"""

		def binary_from_python_path(path: Path) -> Path | None:
			if sublime.platform() == 'windows':
				binary_path = path / 'Scripts' / 'python.exe'
			else:
				binary_path = path / 'bin' / 'python'

			return binary_path if os.path.isfile(binary_path) else None

		# Config file, venv resolution command, post-processing
		venv_config_files = [
			('Pipfile', ['pipenv', '--py'], None),
			('poetry.lock', ['poetry', 'env', 'info', '-p'], binary_from_python_path),
			('.python-version', ['pyenv', 'which', 'python'], None),
		]

		if sublime.platform() == 'windows':
			# do not create a window for the process
			startupinfo = subprocess.STARTUPINFO()  # type: ignore
			startupinfo.wShowWindow = subprocess.SW_HIDE  # type: ignore
			startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore
		else:
			startupinfo = None  # type: ignore

		for config_file, command, post_processing in venv_config_files:
			full_config_file_path = folder / config_file
			if os.path.isfile(full_config_file_path):
				try:
					python_path = Path(subprocess.check_output(command, cwd=folder, startupinfo=startupinfo, universal_newlines=True).strip())
					return post_processing(python_path) if post_processing else python_path
				except FileNotFoundError:
					console.warn(f'{config_file} detected but {command[0]} not found')
				except subprocess.CalledProcessError:
					console.warn(f'{config_file} detected but {" ".join(map(shlex.quote, command))} exited with non-zero exit status')

		# virtual environment as subfolder in project
		for file in folder.iterdir():
			maybe_venv_path = folder / file
			if os.path.isfile(maybe_venv_path / 'pyvenv.cfg'):
				binary = binary_from_python_path(maybe_venv_path)
				if binary is not None:
					return binary  # found a venv

		return None
