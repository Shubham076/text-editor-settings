from __future__ import annotations
from typing import Any

from . import util
from .. import dap
from .. import core

import ast
import re

import sublime
import shutil
import os
import subprocess
import shlex

from pathlib import Path


class PythonInstaller(util.GitSourceInstaller):
	async def post_install(self, version: str, log: dap.Console):
		path = Path(self.temporary_install_path())
		metadata = path / 'debugpy_info.json'
		if metadata.is_file():
			info = core.json_decode_file(str(metadata))
			entries = info.get('any')
			entry = entries[0] if isinstance(entries, list) and entries else entries
			url = entry.get('url') if isinstance(entry, dict) else None
			if not isinstance(url, str) or not url.startswith('https://'):
				raise dap.Error('Release debugpy_info.json does not contain a valid debugpy download URL')
			await util.request.download_and_extract_zip(url, str(path / 'debugpy'), log=log)
		else:
			debugpy_version = self.pinned_debugpy_version(path / 'noxfile.py')
			release = await util.request.json(f'https://pypi.org/pypi/debugpy/{debugpy_version}/json')
			wheel = next((item for item in release.get('urls', [])
				if item.get('packagetype') == 'bdist_wheel' and not item.get('yanked')
				and item.get('filename', '').startswith(f'debugpy-{debugpy_version}-')
				and item.get('filename', '').endswith('-none-any.whl')), None)
			if not wheel:
				raise dap.Error(f'No supported universal debugpy wheel found for pinned version {debugpy_version}')
			digest = wheel.get('digests', {}).get('sha256', '')
			if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
				raise dap.Error('The debugpy wheel is missing a valid SHA-256 digest')
			url = wheel.get('url', '')
			if not isinstance(url, str) or not url.startswith('https://files.pythonhosted.org/'):
				raise dap.Error('The debugpy wheel has an invalid download URL')
			log.info(f'Using debugpy {debugpy_version} pinned by extension {version}')
			await util.request.download_and_extract_zip(url, str(path / 'debugpy'), log=log, sha256=digest)

		if not (path / 'debugpy/debugpy/adapter/__main__.py').is_file():
			raise dap.Error('The downloaded debugpy package does not contain the adapter entry point')

	@staticmethod
	def pinned_debugpy_version(path: Path) -> str:
		try:
			module = ast.parse(path.read_text(encoding='utf-8'))
		except (OSError, SyntaxError) as error:
			raise dap.Error('Unable to read the pinned debugpy version from noxfile.py') from error
		for node in module.body:
			if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'DEBUGPY_VERSION' for target in node.targets):
				if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
					version = node.value.value
					if re.fullmatch(r'\d+\.\d+\.\d+[A-Za-z0-9.+-]*', version):
						return version
		raise dap.Error('The release does not define a literal pinned DEBUGPY_VERSION version in noxfile.py')


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


class Python(dap.Adapter):
	type = ['debugpy', 'python']
	docs = 'https://github.com/microsoft/vscode-docs/blob/main/docs/python/debugging.md#python-debug-configurations-in-visual-studio-code'

	installer = PythonInstaller(type='debugpy', repo='microsoft/vscode-python-debugger')

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

		install_path = self.installer.install_path()

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
				console.info('Detected virtual environment for `{}`'.format(folder))
			elif shutil.which('python3'):
				python = shutil.which('python3')
			else:
				python = shutil.which('python')

		if not python:
			raise dap.Error('Unable to find `python3` or `python`')

		console.info('Using python `{}`'.format(python))

		return dap.StdioTransport(
			[
				f'{python}',
				f'{install_path}/debugpy/debugpy/adapter',
			]
		)

	async def on_custom_event(self, session: dap.Session, event: str, body: Any):
		if event == 'debugpyAttach':
			configuration = dap.Configuration.from_json(body, -1)
			configuration_expanded = await configuration.Expanded([], session.configuration.variables)
			await session.debugger.launch(self, configuration_expanded, parent=session)
		else:
			core.info(f'event not handled `{event}`')

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
