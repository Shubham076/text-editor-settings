from __future__ import annotations
from typing import Any

from .. import core
from .. import dap
from . import util

import sublime
import json
import os
import re
import socket

# what a JVM that was started to wait for a debugger says once it is waiting, and the port it is on
LISTENING = re.compile(r'Listening for transport dt_socket at address: (\d+)')


class Java(dap.Adapter):
	type = 'java'
	docs = 'https://github.com/redhat-developer/vscode-java/blob/master/README.md'

	installer = util.GitInstaller(type='java', repo='microsoft/vscode-java-debug')

	# the command each configuration that has one was started with, by the name of the configuration
	commands: dict[str, Any] = {}

	async def start(self, console: dap.Console, configuration: dap.ConfigurationExpanded):
		# Make sure LSP and LSP-JDTLS are installed
		util.require_package('LSP-jdtls')
		util.require_package('LSP')

		# Configure debugger
		def _is_undefined(key):
			return key not in configuration or isinstance(configuration[key], str) and not configuration[key]

		if _is_undefined('cwd'):
			configuration['cwd'] = await configuration.variables['folder']
		# an attach to a JVM that a command starts, which is how a test is debugged: the build of the
		# project runs it and has its JVM wait. There is no main class to look for, the command has it
		if configuration.request == 'attach' and configuration.get('command'):
			configuration['port'] = await self.run_command(console, configuration)

			try:
				port = await self.lsp_execute_command('vscode.java.startDebugSession')
			except BaseException:
				self.end_command(configuration.name)
				raise

			return dap.SocketTransport('localhost', port)

		if _is_undefined('mainClass') or _is_undefined('projectName'):
			configuration['mainClass'], configuration['projectName'] = await self._get_mainclass_project_name(None if _is_undefined('mainClass') else configuration['mainClass'])
		if _is_undefined('classPaths') and _is_undefined('modulePaths'):
			configuration['modulePaths'], configuration['classPaths'] = await self._resolve_modulepath_classpath(configuration['mainClass'], configuration['projectName'])

		if await self._is_preview_enabled(configuration['mainClass'], configuration['projectName']):
			if 'vmArgs' in configuration:
				configuration['vmArgs'] += ' --enable-preview'
			else:
				configuration['vmArgs'] = '--enable-preview'

		# Start debugging session on the LSP side
		port = await self.lsp_execute_command('vscode.java.startDebugSession')

		return dap.SocketTransport('localhost', port)

	async def run_command(self, console: dap.Console, configuration: dap.ConfigurationExpanded) -> int:
		'''Starts the command of a configuration and waits for the JVM it starts to wait for a debugger

		What comes back is the port that JVM is listening on. What the command prints is the output of
		the session, a build that fails says why there.
		'''
		from ..dap.transports import Process

		command = configuration['command']
		env = {**os.environ, **(configuration.get('env') or {})}

		# Two ways to know the JVM is waiting. It says so, with the port, when the build passes on what
		# it prints. Maven with a current surefire keeps that line to itself, so the port the configuration
		# names is also tried: a JVM that waits for a debugger goes on waiting after a connection that
		# says nothing
		port = int(configuration.get('port') or 5005)
		host = configuration.get('hostName') or 'localhost'
		said: list[int] = []
		ended: list[bool] = []
		# the line can arrive in two pieces, so it is looked for in the end of everything so far
		tail = ''

		def output(kind: str):
			def on_output(data: str):
				nonlocal tail
				console.log(kind, data)

				tail = (tail + data)[-400:]
				if found := LISTENING.search(tail):
					said.append(int(found.group(1)))

			return on_output

		try:
			# something that is already there is not the test, attaching to it would debug the wrong program
			if await self.is_listening(host, port):
				raise dap.Error(f'Port {port} is already in use, a JVM started for this test would not be the one that is attached to')

			process = Process(command, cwd=configuration.get('cwd'), env=env)
		except OSError as error:
			raise dap.Error(f'Unable to run `{command[0]}`: {error}')

		self.end_command(configuration.name)
		self.commands[configuration.name] = process

		process.on_stdout(output('stdout'), lambda: core.call_soon(ended.append, True))
		process.on_stderr(output('stderr'))

		try:
			while True:
				if said:
					return said[0]
				if await self.is_listening(host, port):
					return port
				if ended:
					raise dap.Error(f'`{command[0]}` ended before a test waited for the debugger')

				await core.delay(0.5)

		except BaseException:
			# stopped while the build was still on its way to the test, or the build failed
			self.end_command(configuration.name)
			raise

	@core.run_in_executor
	def is_listening(self, host: str, port: int) -> bool:
		try:
			socket.create_connection((host, port), timeout=1).close()
			return True
		except OSError:
			return False

	def end_command(self, name: str) -> None:
		if process := self.commands.pop(name, None):
			process.dispose()

	def did_stop_debugging(self, session: dap.Session):
		# the build is still running when the test is stopped in the middle, and it goes with it
		if not getattr(session, 'parent', None):
			self.end_command(session.configuration.name)

	async def on_navigate_to_source(self, source: dap.SourceLocation) -> tuple[str, str, list[tuple[str, Any]]] | None:
		if not source.source.path or not source.source.path.startswith('jdt:'):
			return None
		content = await self.get_class_content_for_uri(source.source.path)
		return content, 'text/java', [('lsp_uri', source.source.path)]

	async def get_class_content_for_uri(self, uri):
		return await self.lsp_request('java/classFileContents', {'uri': uri})

	async def _get_mainclass_project_name(self, preferred_mainclass=None):
		mainclasses = await self.lsp_execute_command('vscode.java.resolveMainClass')
		if not mainclasses:
			raise dap.Error('Failed to resolve main class')

		if preferred_mainclass:
			matches = [x for x in mainclasses if x['mainClass'] == preferred_mainclass]
			if matches:
				return matches[0]['mainClass'], matches[0]['projectName']
			else:
				raise dap.Error('Mainclass {} not found. Check your debugger configuration or leave "mainClass" empty to detect the mainclass automatically'.format(preferred_mainclass))

		if len(mainclasses) == 1:
			return mainclasses[0]['mainClass'], mainclasses[0]['projectName']

		# Show panel
		future_index = core.Future()
		items = [sublime.QuickPanelItem(x['mainClass'], x['filePath'], '', (3, '', '')) for x in mainclasses]
		# Preselect mainclass associated with active view
		selected_index = -1
		view = sublime.active_window().active_view()
		if view:
			for i, mainclass in enumerate(mainclasses):
				if mainclass['filePath'] == view.file_name():
					selected_index = i
					break
		if sublime.version() < '4081':
			sublime.active_window().show_quick_panel(items, lambda idx: future_index.set_result(idx), sublime.MONOSPACE_FONT | sublime.KEEP_OPEN_ON_FOCUS_LOST, selected_index)
		else:
			sublime.active_window().show_quick_panel(items, lambda idx: future_index.set_result(idx), sublime.MONOSPACE_FONT | sublime.KEEP_OPEN_ON_FOCUS_LOST, selected_index, placeholder='Select Mainclass')
		index = await future_index

		if index == -1:
			raise dap.Error('Please specify a main class')

		return mainclasses[index]['mainClass'], mainclasses[index]['projectName']

	async def _resolve_modulepath_classpath(self, main_class, project_name):
		classpath_response = await self.lsp_execute_command('vscode.java.resolveClasspath', [main_class, project_name])
		if not classpath_response[0] and not classpath_response[1]:
			raise dap.Error('Failed to resolve classpaths/modulepaths automatically, please specify the value in the debugger configuration')

		module_paths = classpath_response[0]
		class_paths = classpath_response[1]
		return module_paths, class_paths

	async def _is_preview_enabled(self, main_class, project_name):
		# See https://github.com/microsoft/vscode-java-debug/blob/b2a48319952b1af8a4a328fc95d2891de947df94/src/configurationProvider.ts#L297
		return await self.lsp_execute_command(
			'vscode.java.checkProjectSettings',
			[
				json.dumps(
					{
						'className': main_class,
						'projectName': project_name,
						'inheritedOptions': True,
						'expectedOptions': {'org.eclipse.jdt.core.compiler.problem.enablePreviewFeatures': 'enabled'},
					}
				)
			],
		)

	async def lsp_execute_command(self, command, arguments=None):
		return await self.lsp_request('workspace/executeCommand', {'command': command, 'arguments': arguments})

	async def lsp_request(self, method, params) -> Any:
		# LSP-jdtls >= 3.0.0 uses `LSP-jdtls` as the session name, older versions use `jdtls`
		return await util.lsp.request(('LSP-jdtls', 'jdtls'), method, params)
