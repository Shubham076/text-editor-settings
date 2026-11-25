from __future__ import annotations
from typing import TYPE_CHECKING, Any, Awaitable, Callable, cast
from enum import IntEnum
from .. import core
from . import api
from .debugger import ConsoleSessionBound, Debugger
from .error import Error
from .variable import Variable
from .thread import Thread
from .adapter import Adapter
from .configuration import ConfigurationExpanded, TaskExpanded
from .transport import Transport, TransportConnectionError, TransportListener

if TYPE_CHECKING:
	from .breakpoints import SourceBreakpoint, Breakpoint


PROGRESS_LENGTH = 44


class Session(TransportListener, core.Dispose):
	class State(IntEnum):
		STARTING = 3
		STOPPED = 0
		STOPPING = 4

		# puased/running is based on selected thread
		PAUSED = 1
		RUNNING = 2

		def __init__(self, value):
			super().__init__()

			self.status = ''
			self.previous: 'Session.State' = 0  # type: ignore

	on_output: core.Event['Session', api.OutputEvent]

	on_updated: core.Event['Session']
	on_updated_modules: core.Event['Session']
	on_updated_sources: core.Event['Session']
	on_updated_variables: core.Event['Session']
	on_updated_threads: core.Event['Session']
	on_updated_thread_or_frame: core.Event['Session']

	on_finished: Callable[['Session'], None]

	on_task_request: Callable[['Session', TaskExpanded], Awaitable[None]]
	on_terminal_request: Callable[['Session', api.RunInTerminalRequestArguments], Awaitable[api.RunInTerminalResponse]]

	def __init__(self, debugger: Debugger, adapter: Adapter, configuration: ConfigurationExpanded, restart: Any | None, no_debug: bool, parent: Session | None = None) -> None:
		self.adapter = adapter
		self.configuration = configuration
		self.restart = restart
		self.no_debug = no_debug

		self.children: list[Session] = []
		self.parent = parent
		self.debugger = debugger

		if parent:
			parent.children.append(self)

		self.console = ConsoleSessionBound(self, debugger)
		self.state_changed = core.Event[int]()

		self.breakpoints = debugger.breakpoints
		self.breakpoints_for_id: dict[int, Breakpoint] = {}

		self.dispose_add(
			self.breakpoints.data.on_send.add(self.on_send_data_breakpoints),
			self.breakpoints.function.on_send.add(self.on_send_function_breakpoints),
			self.breakpoints.filters.on_send.add(self.on_send_filters),
			self.breakpoints.source.on_send.add(self.on_send_source_breakpoint),
		)

		self._transport_started = False
		self._transport: Transport | None = None

		self.launching_async: core.Future | None = None
		self.capabilities = api.Capabilities()
		self.stop_requested = False
		self.launch_request = True
		self.stepping = False
		self.stepping_hit_stopped_event = False
		self.stopped_unexpectedly = False
		self.terminated_event = None

		self._state = Session.State.STARTING

		self.disposeables: list[Any] = []

		self.threads_for_id: dict[int, Thread] = {}
		self.all_threads_stopped = False
		self.selected_explicitly = False
		self.selected_thread = None
		self.selected_frame = None

		self.threads: list[Thread] = []
		self.variables: list[Variable] = []
		# the frame `variables` are the scopes of, which trails `selected_frame` by a request
		self.variables_frame: api.StackFrame | None = None
		self.sources: dict[int | str, api.Source] = {}
		self.modules: dict[int | str, api.Module] = {}

		self.process: api.ProcessEvent | None = None

		# what the adapter says it is busy with, by the id it reports it under: attaching, loading
		# symbols, building. In the order it started on them
		self.progress: dict[str, tuple[str, str, float | None]] = {}

	@property
	def name(self) -> str:
		return self.configuration.name or (self.process and self.process.name) or 'Untitled'

	@property
	def state(self) -> State:
		return self._state

	@property
	def is_paused(self):
		return self.state == Session.State.PAUSED

	@property
	def is_running(self):
		return self.state == Session.State.RUNNING

	@property
	def is_stoppable(self):
		return self.state != Session.State.STOPPED

	def _change_state(self, state: State) -> None:
		if self._state == state:
			return

		state.previous = self.state
		self._state = state
		self.on_updated(self)

	def _change_state_status(self, status: str):
		self._state.status = status
		self._state.previous = self._state
		self.on_updated(self)

	async def launch(self) -> None:
		if self.launching_async:
			raise Error('Sessions can only be launched once')

		try:
			self.launching_async = self._launch()
			await self.launching_async

		except Exception as e:
			core.exception()
			self.console.error(str(e), self.configuration.source)
			await self.stop_session()
			raise e

		except core.CancelledError:
			...

	@core.run
	async def _launch(self) -> None:
		assert self.state == Session.State.STOPPED, 'debugger not in stopped state?'
		self._change_state(Session.State.STARTING)
		self.configuration = await self.adapter.configuration_resolve(self.configuration)

		installed_version = self.adapter.installed_version
		if not installed_version:
			raise Error('Debug adapter with type name "{}" is not installed. You can install it by running Debugger: Install Adapters'.format(self.adapter.type))

		if not await self.run_pre_debug_task():
			await self.stop_session()
			return

		self._change_state_status('Starting')
		try:
			self.console.log('transport', f'-- adapter: type={self.adapter.type} version={installed_version}')
			transport = await self.adapter.start(console=self.console, configuration=self.configuration)
		except TransportConnectionError as e:
			self.stopped_unexpectedly = True
			raise Error(f'Unable to start adapter: {e}')
		except Exception as e:
			raise Error(f'Unable to start adapter: {e}')

		self._transport = transport
		await self._transport.start(self, self.configuration, self.console)
		self._transport_started = True

		capabilities: api.Capabilities = await self.request(
			'initialize',
			{
				'clientID': 'sublime',
				'clientName': 'Sublime Text',
				'adapterID': self.configuration.type,
				'pathFormat': 'path',
				'linesStartAt1': True,
				'columnsStartAt1': True,
				'supportsVariableType': True,
				'supportsVariablePaging': False,
				'supportsRunInTerminalRequest': True,
				'supportsMemoryReferences': True,
				'supportsInvalidatedEvent': True,
				'supportsProgressReporting': True,
				'locale': 'en-us',
				'supportsANSIStyling': True,
			},
		)
		self.capabilities = capabilities

		# remove/add any exception breakpoint filters
		self.breakpoints.filters.update(capabilities.exceptionBreakpointFilters or [])

		if self.restart:
			self.configuration['__restart'] = self.restart
		if self.no_debug:
			self.configuration['noDebug'] = True

		if self.configuration.request == 'launch':
			self.launch_request = True
			await self.request('launch', self.configuration)
		elif self.configuration.request == 'attach':
			self.launch_request = False
			await self.request('attach', self.configuration)
		else:
			raise Error('expected configuration to have request of either "launch" or "attach" found {}'.format(self.configuration.request))

		self.adapter.did_start_debugging(self)

		# get the baseline threads after launch/attach
		# according to https://microsoft.github.io/debug-adapter-protocol/overview
		self.refresh_threads()

		# At this point we are running?
		self._change_state_status('Running')
		self._change_state(Session.State.RUNNING)

	async def request(self, command: str, arguments: Any) -> Any:
		if not self._transport_started:
			raise Error('Debugging not started')

		if not self._transport:
			raise Error('Debugging ended')

		return await self._transport.send_request(command, arguments)

	async def run_pre_debug_task(self) -> bool:
		'''Runs the tasks of `pre_debug_task` in the order they are listed, and says whether to go on

		One after the other: a build is finished before the server that is started from it, and a
		task with a ready signal is ready before the next one starts. The first that fails is the
		last that is run.
		'''
		for task in self.configuration.pre_debug_tasks:
			self._change_state_status('Running pre debug task')
			if not await self.run_task('pre_debug_task', task):
				return False
		return True

	async def run_post_debug_task(self) -> bool:
		'''Runs the tasks of `post_debug_task`, every one of them whether or not the one before failed

		They are what tidies up after a session, and what is left to tidy does not depend on how
		the tidying before it went.
		'''
		succeeded = True
		for task in self.configuration.post_debug_tasks:
			self._change_state_status('Running post debug task')
			if not await self.run_task('post_debug_task', task):
				succeeded = False
		return succeeded

	async def run_task(self, name: str, task: TaskExpanded) -> bool:
		try:
			await self.on_task_request(self, task)
			return True

		except core.CancelledError:
			self.console.log('error-no-open', f'{name}: cancelled')
			return False

		except Error as e:
			self.console.log('error-no-open', f'{name}: {e}')
			return False

	def _refresh_state(self) -> None:
		try:
			thread = self.command_thread
			if thread.stopped:
				self._change_state_status('Paused')
				self._change_state(Session.State.PAUSED)
			else:
				self._change_state_status('Running')
				self._change_state(Session.State.RUNNING)

		except Error as e:
			self._change_state(Session.State.RUNNING)

	async def add_breakpoints(self) -> None:
		if not self._transport:
			return

		requests: list[Awaitable[Any]] = []

		requests.append(self.set_exception_breakpoint_filters())
		requests.append(self.set_function_breakpoints())

		for file, filebreaks in self.breakpoints.source.breakpoints_per_file().items():
			requests.append(self.set_breakpoints_for_file(file, filebreaks))

		if self.capabilities.supportsDataBreakpoints:
			requests.append(self.set_data_breakpoints())

		await core.gather_results(*requests)

	async def set_exception_breakpoint_filters(self) -> None:
		if not self._transport:
			return
		try:
			filters: list[str] = []
			filterOptions: list[api.ExceptionFilterOptions] = []

			for f in self.breakpoints.filters:
				if f.enabled:
					filters.append(f.dap.filter)
					filterOptions.append(
						api.ExceptionFilterOptions(
							f.dap.filter,
							f.condition,
						)
					)

			await self.request('setExceptionBreakpoints', {'filters': filters, 'filterOptions': filterOptions})
		except Error as e:
			self.console.error('Error while exception filters: {}'.format(e))

	async def set_function_breakpoints(self) -> None:
		if not self._transport:
			return
		breakpoints = list(filter(lambda b: b.enabled, self.breakpoints.function))

		if not self.capabilities.supportsFunctionBreakpoints:
			# only show error message if the user tried to set a function breakpoint when they are not supported
			if breakpoints:
				self.console.error('This debugger does not support function breakpoints')
			return

		try:
			dap_breakpoints = list(map(lambda b: b.dap, breakpoints))

			response = await self.request('setFunctionBreakpoints', {'breakpoints': dap_breakpoints})
			results: list[api.Breakpoint] = response['breakpoints']

			for result, b in zip(results, breakpoints):
				self.breakpoints.function.set_breakpoint_result(b, self, result)
				if result.id is not None:
					self.breakpoints_for_id[result.id] = b

		except Error as e:
			self.console.error('Error while adding function breakpoints: {}'.format(e))

	async def set_data_breakpoints(self) -> None:
		if not self._transport:
			return
		breakpoints = list(filter(lambda b: b.enabled, self.breakpoints.data))
		dap_breakpoints = list(map(lambda b: b.dap, breakpoints))

		try:
			response = await self.request('setDataBreakpoints', {'breakpoints': dap_breakpoints})
			results: list[api.Breakpoint] = response['breakpoints']
			for result, b in zip(results, breakpoints):
				self.breakpoints.data.set_breakpoint_result(b, self, result)
				if result.id is not None:
					self.breakpoints_for_id[result.id] = b

		except Error as e:
			self.console.error('Error while adding data breakpoints: {}'.format(e))

	async def set_breakpoints_for_file(self, file: str, breakpoints: list[SourceBreakpoint]) -> None:
		if not self._transport:
			return

		enabled_breakpoints: list[SourceBreakpoint] = []
		dap_breakpoints: list[api.SourceBreakpoint] = []

		lines: list[int] = []

		for breakpoint in breakpoints:
			if breakpoint.dap.hitCondition and not self.capabilities.supportsHitConditionalBreakpoints:
				self.console.error('This debugger does not support hit condition breakpoints')

			if breakpoint.dap.logMessage and not self.capabilities.supportsLogPoints:
				self.console.error('This debugger does not support log points')

			if breakpoint.dap.condition and not self.capabilities.supportsConditionalBreakpoints:
				self.console.error('This debugger does not support conditional breakpoints')

			if breakpoint.enabled:
				enabled_breakpoints.append(breakpoint)
				dap_breakpoints.append(breakpoint.dap)
				lines.append(breakpoint.dap.line)

		try:
			response = await self.request(
				'setBreakpoints',
				{
					'source': {'path': file},
					'breakpoints': dap_breakpoints,
					'lines': lines,  # for backwards compat
				},
			)
			results: list[dap.Breakpoint] = response['breakpoints']

			if len(results) != len(enabled_breakpoints):
				raise Error('expected #breakpoints to match results')

			for result, b in zip(results, enabled_breakpoints):
				self.breakpoints.source.set_breakpoint_result(b, self, result)
				if result.id is not None:
					self.breakpoints_for_id[result.id] = b

		except Error as e:
			self.console.error('Error while adding breakpoints: {}'.format(e))
			for b in enabled_breakpoints:
				self.breakpoints.source.set_breakpoint_result(b, self, api.Breakpoint(verified=False, message=str(e)))

	def on_send_data_breakpoints(self, any: Any):
		core.run(self.set_data_breakpoints())

	def on_send_function_breakpoints(self, any: Any):
		core.run(self.set_function_breakpoints())

	def on_send_filters(self, any: Any):
		core.run(self.set_exception_breakpoint_filters())

	def on_send_source_breakpoint(self, breakpoint: SourceBreakpoint) -> None:
		core.run(self.set_breakpoints_for_file(breakpoint.file, self.breakpoints.source.breakpoints_for_file(breakpoint.file)))

	async def stop(self):
		# this seems to be what the spec says to do in the overview
		# https://microsoft.github.io/debug-adapter-protocol/overview

		# haven't started session yet
		if self._transport is None:
			await self.stop_session()
			return

		# If the stop is called multiple times then we forcefully stop the session
		if self.stop_requested:
			await self.stop_session()
			return

		self._change_state_status('Stop Requested')
		self.stop_requested = True

		# first try to terminate if we can
		if self.launch_request and self.capabilities.supportsTerminateRequest:
			try:
				await self.request('terminate', {'restart': False})
				await self.stop_session()
				return
			except Error as e:
				core.exception()

		# we couldn't terminate either not a launch request or the terminate request failed
		# so we foreceully disconnect
		await self.request(
			'disconnect',
			{
				'restart': False,
				'terminateDebuggee': True,
			},
		)

		await self.stop_session()

	@property
	def can_restart_natively(self) -> bool:
		'''Whether the adapter can start the program again inside this session

		Not while it is starting or stopping, and not with a task before or after it: a
		`pre_debug_task` is usually the build, and a restart that skips it runs the old program.
		'''
		if not self.capabilities.supportsRestartRequest or not self._transport:
			return False
		if self.stop_requested or self.state not in (Session.State.RUNNING, Session.State.PAUSED):
			return False
		return not self.configuration.pre_debug_tasks and not self.configuration.post_debug_tasks

	async def restart_natively(self) -> None:
		'''The `restart` request: the adapter ends the program and starts it again, the session stays

		What the session knew about the program that was running is thrown away: its threads are
		gone and so is the frame that was selected. The breakpoints are the adapters to keep.
		'''
		self._change_state_status('Restarting')
		await self.request('restart', {'arguments': dict(self.configuration)})

		self.stepping = False
		self.stepping_hit_stopped_event = False
		self.all_threads_stopped = False
		self.terminated_event = None

		self.threads.clear()
		self.threads_for_id.clear()
		self.select(None, None, explicitly=False)

		self.on_updated_threads(self)
		self.refresh_threads()
		self._refresh_state()

	async def stop_session(self) -> None:
		if self.state == Session.State.STOPPING or self.state == Session.State.STOPPED:
			return

		if self._transport_started:
			if not self.stop_requested and not self.terminated_event:
				self.stopped_unexpectedly = True

		self._change_state(Session.State.STOPPING)

		self.dispose_adapter_session()

		await self.run_post_debug_task()
		self._change_state_status('Ended')

		self._change_state(Session.State.STOPPED)
		self.on_finished(self)

	def dispose_adapter_session(self):
		if self.launching_async:
			self.launching_async.cancel()

		self.breakpoints.clear_breakpoint_result(self)
		self.stop_requested = False
		# whatever it was in the middle of, it is not any more
		self.progress.clear()

		if self._transport:
			self.adapter.did_stop_debugging(self)
			self._transport.dispose()
			self._transport = None

	def dispose(self) -> None:
		super().dispose()

		self.dispose_adapter_session()

		if self.parent:
			self.parent.children.remove(self)
			self.parent = None

		# clean up hierarchy if needed
		for child in self.children:
			child.parent = None

	async def resume(self):
		body = await self.request('continue', {'threadId': self.command_thread.id})

		# some adapters aren't giving a response here
		if body:
			allThreadsContinued = body.get('allThreadsContinued', True)
		else:
			allThreadsContinued = True

		self.on_continued_event(api.ContinuedEvent(self.command_thread.id, allThreadsContinued))

	async def reverse_continue(self):
		if not self.capabilities.supportsStepBack:
			self.console.error('This debugger does not support stepping backwards')
			return

		body = await self.request('reverseContinue', {'threadId': self.command_thread.id})

		# some adapters aren't giving a response here
		if body:
			allThreadsContinued = body.get('allThreadsContinued', True)
		else:
			allThreadsContinued = True

		self.on_continued_event(api.ContinuedEvent(self.command_thread.id, allThreadsContinued))

	async def pause(self):
		await self.request('pause', {'threadId': self.command_thread.id})

	async def step(self, command: str, granularity: str | None = None):
		# this is used to so the ui can better handle stepping
		# Ideally the ui does not switch panels when stepping
		# If the user selects the console and steps the program it ideally doesn't switch to the callstack panel
		self.stepping = True
		self.stepping_hit_stopped_event = False

		thread = self.command_thread

		await self.request(
			command,
			{
				'threadId': thread.id,
				'granularity': granularity,
			},
		)
		self.on_continued_event(api.ContinuedEvent(thread.id, False))

	async def step_over(self, granularity: str | None = None):
		await self.step('next', granularity)

	async def step_in(self, granularity: str | None = None):
		await self.step('stepIn', granularity)

	async def step_out(self, granularity: str | None = None):
		await self.step('stepOut', granularity)

	async def step_back(self, granularity: str | None = None):
		if not self.capabilities.supportsStepBack:
			self.console.error('This debugger does not support stepping backwards')
			return

		await self.step('stepBack', granularity)

	async def exception_info(self, thread_id: int) -> api.ExceptionInfoResponseBody:
		return await self.request('exceptionInfo', {'threadId': thread_id})

	async def evaluate(self, expression: str, context: str = 'repl'):
		result = await self.evaluate_expression(expression, context)
		if not result:
			raise Error('expression did not return a result')

		# variablesReference doesn't appear to be optional in the spec... but some adapters treat it as such
		event = api.OutputEvent(result.result + '\n', 'console', variablesReference=result.variablesReference)
		self.on_output(self, event)

	async def evaluate_expression(self, expression: str, context: str | None) -> api.EvaluateResponse:
		frame_id: int | None = None
		if self.selected_frame:
			frame_id = self.selected_frame.id

		response = await self.request('evaluate', api.EvaluateArguments(expression, frame_id, context))

		# the spec doesn't say this is optional? But it seems that some implementations throw errors instead of marking things as not verified?
		if response['result'] is None:
			raise Error('expression did not return a result')

		return response

	async def disassemble(self, memory_reference: str, instruction_offset: int, instruction_count: int) -> api.DisassembleResponseBody:
		return await self.request(
			'disassemble',
			{
				'memoryReference': memory_reference,
				'instructionOffset': instruction_offset,
				'instructionCount': instruction_count,
			},
		)

	async def read_memory(self, memory_reference: str, count: int, offset: int) -> api.ReadMemoryResponse:
		return await self.request('readMemory', {'memoryReference': memory_reference, 'count': count, 'offset': offset})

	async def write_memory(self, memory_reference: str, offset: int | None, allowPartial: bool | None, data: str) -> api.WriteMemoryResponse:
		return await self.request(
			'writeMemory',
			{
				'memoryReference': memory_reference,
				'offset': offset,
				'allowPartial': allowPartial,
				'data': data,
			},
		)

	async def stack_trace(self, thread_id: int) -> list[api.StackFrame]:
		body = await self.request(
			'stackTrace',
			{
				'threadId': thread_id,
			},
		)
		return body['stackFrames']

	async def completions(self, text: str, column: int) -> list[api.CompletionItem]:
		frameId = None
		if self.selected_frame:
			frameId = self.selected_frame.id

		response = await self.request(
			'completions',
			{
				'frameId': frameId,
				'text': text,
				'column': column,
			},
		)
		return response['targets']

	async def set_variable(self, variablesReference: int, name: str, value: str) -> api.SetVariableResponse:
		return await self.request(
			'setVariable',
			{
				'variablesReference': variablesReference,
				'name': name,
				'value': value,
			},
		)

	async def data_breakpoint_info(self, variablesReference: int, name: str) -> api.DataBreakpointInfoResponse:
		response = await self.request(
			'dataBreakpointInfo',
			{
				'variablesReference': variablesReference,
				'name': name,
			},
		)
		return response

	async def refresh_scopes(self, frame: api.StackFrame):
		body = await self.request('scopes', {'frameId': frame.id})
		scopes: list[api.Scope] = body['scopes']
		self.variables = [Variable.from_scope(self, scope) for scope in scopes]
		self.variables_frame = frame
		self.on_updated_variables(self)

	async def get_source(self, source: api.Source) -> tuple[str, str | None]:
		body = await self.request('source', {'source': {'path': source.path, 'sourceReference': source.sourceReference}, 'sourceReference': source.sourceReference})
		return body['content'], body.get('mimeType')

	async def get_variables(self, variablesReference: int, without_names: bool = False) -> list[Variable]:
		response = await self.request('variables', {'variablesReference': variablesReference})

		variables: list[api.Variable] = response['variables']

		# vscode seems to remove the names from variables in output events
		if without_names:
			for v in variables:
				v.name = ''
				v.value = v.value.split('\n')[0]

		return [Variable.from_variable(self, variablesReference, v) for v in variables]

	def on_breakpoint_event(self, event: api.BreakpointEvent):
		assert event.breakpoint.id
		if b := self.breakpoints_for_id.get(event.breakpoint.id):
			self.breakpoints.set_breakpoint_result(b, self, event.breakpoint)
		else:
			core.debug(f'Breakpoint for id not found {event.breakpoint.id}')

	def on_module_event(self, event: api.ModuleEvent):
		if event.reason == 'new':
			self.modules[event.module.id] = event.module

		if event.reason == 'removed':
			try:
				del self.modules[event.module.id]
			except KeyError:
				...
		if event.reason == 'changed':
			self.modules[event.module.id] = event.module

		self.on_updated_modules(self)

	def on_process_event(self, event: api.ProcessEvent):
		self.process = event
		self.on_updated(self)

	def on_loaded_source_event(self, event: api.LoadedSourceEvent):
		id = f'{event.source.name}~{event.source.path}~{event.source.sourceReference}'
		if event.reason == 'new':
			self.sources[id] = event.source

		elif event.reason == 'removed':
			try:
				del self.sources[id]
			except KeyError:
				...
		elif event.reason == 'changed':
			self.sources[id] = event.source

		self.on_updated_sources(self)

	# this is a bit of a weird case. Initialized will happen at some point in time
	# it depends on when the debug adapter chooses it is ready for configuration information
	# when it does happen we can then add all the breakpoints and complete the configuration
	# NOTE: some adapters appear to send the initialized event multiple times

	@core.run
	async def on_initialized_event(self):
		await self.add_breakpoints()

		if self.capabilities.supportsConfigurationDoneRequest:
			await self.request('configurationDone', {})

	def on_output_event(self, event: api.OutputEvent):
		self.on_output(self, event)

	@core.run
	async def on_terminated_event(self, event: api.TerminatedEvent):
		self.terminated_event = event
		await self.stop()

		# TODO: This needs to be handled inside debugger_sessions
		# restarting needs to be handled by creating a new session
		# if event.restart:
		# 	await self.launch(self.adapter, self.configuration, event.restart)

	@core.run
	async def on_transport_closed(self):
		await self.stop_session()

	async def on_reverse_request(self, command: str, arguments: core.JSON) -> core.JSON:
		if command == 'runInTerminal':
			response = await self.on_run_in_terminal(cast(api.RunInTerminalRequestArguments, arguments))
			return cast(core.JSON, response)

		assert self.adapter
		response = await self.adapter.on_custom_request(self, command, arguments)

		if response is None:
			raise Error(f'reverse request not implemented {command}')

		return cast(core.JSON, response)

	async def on_run_in_terminal(self, request: api.RunInTerminalRequestArguments) -> api.RunInTerminalResponse:
		try:
			return await self.on_terminal_request(self, request)
		except Error as e:
			self.console.error(str(e))
			raise e

	@property
	def command_thread(self) -> Thread:
		if self.selected_thread:
			return self.selected_thread
		if self.threads:
			return self.threads[0]

		raise Error('No threads to run command')

	def get_thread(self, id: int):
		t = self.threads_for_id.get(id)
		if t:
			return t
		else:
			t = Thread(self, id, '??', self.all_threads_stopped)
			self.threads_for_id[id] = t
			return t

	def set_selected(self, thread: Thread, frame: api.StackFrame | None):
		self.select(thread, frame, explicitly=True)
		self._refresh_state()

	# after a successfull launch/attach, stopped event, thread event we request all threads
	# see https://microsoft.github.io/debug-adapter-protocol/overview
	# updates all the threads from the dap model
	# @NOTE threads_for_id will retain all threads for the entire session even if they are removed
	@core.run
	async def refresh_threads(self):
		# the Java debugger requires an empty object instead of `None`
		# See https://github.com/daveleroy/sublime_debugger/pull/106#issuecomment-793802989
		response = await self.request('threads', {})
		# See https://github.com/daveleroy/sublime_debugger/pull/106#issuecomment-795949070
		threads: list[dap.Thread] = response.get('threads', [])

		self.threads.clear()
		for thread in threads:
			t = self.get_thread(thread.id)
			t.name = thread.name
			self.threads.append(t)

		self.on_updated_threads(self)

	def on_threads_event(self, event: api.ThreadEvent) -> None:
		self.refresh_threads()

	def on_stopped_event(self, stopped: api.StoppedEvent):
		self.stepping_hit_stopped_event = True

		if stopped.allThreadsStopped or False:
			self.all_threads_stopped = True

			for thread in self.threads:
				thread.set_stopped(None)

		if stopped.threadId is not None:
			stopped_thread_id = stopped.threadId
		elif self.threads:
			stopped_thread_id = self.threads[0].id
		else:
			stopped_thread_id = None

		if stopped_thread_id is not None:
			thread = self.get_thread(stopped_thread_id)

			# @NOTE this thread might be new and not in self.threads so we must update its state explicitly
			thread.set_stopped(stopped)

			if not self.selected_explicitly:
				self.select(thread, None, explicitly=False)
				self.expand_thread(thread)

		self.on_updated_threads(self)
		self.refresh_threads()
		self._refresh_state()

	@core.run
	async def expand_thread(self, thread: Thread):
		children = await thread.children()
		if children and not self.selected_frame and not self.selected_explicitly and self.selected_thread is thread:

			def first_non_subtle_frame(frames: list[api.StackFrame]):
				for frame in frames:
					if frame.presentationHint != 'subtle' and frame.source:
						return frame
				return frames[0]

			frame = first_non_subtle_frame(children)
			self.select(thread, frame, explicitly=False)

			self.on_updated_threads(self)
			self._refresh_state()

	def on_continued_event(self, continued: api.ContinuedEvent):
		# if we hit a stopped event while stepping then the next continue event that is not a stepping event sets stepping to false
		if self.stepping_hit_stopped_event:
			self.stepping = False

		if continued.allThreadsContinued:
			self.all_threads_stopped = False
			for thread in self.threads:
				thread.set_continued(None)

		# @NOTE this thread might be new and not in self.threads so we must update its state explicitly
		thread = self.get_thread(continued.threadId)
		thread.set_continued(continued)

		if continued.allThreadsContinued or thread is self.selected_thread:
			self.select(None, None, explicitly=False)

		self.on_updated_threads(self)
		self._refresh_state()

	def select(self, thread: Thread | None, frame: api.StackFrame | None, explicitly: bool):
		if frame and not thread:
			raise Error('Expected thread')

		self.selected_explicitly = explicitly
		self.selected_thread = thread
		self.selected_frame = frame
		self.on_updated_thread_or_frame(self)

		if frame:
			core.run(self.refresh_scopes(frame))
		else:
			self.variables.clear()
			self.variables_frame = None
			self.on_updated_variables(self)

	@property
	def progress_text(self) -> str:
		'''What the adapter is in the middle of, the most recent thing it started on, `''` for nothing'''
		if not self.progress:
			return ''

		title, message, percentage = list(self.progress.values())[-1]
		text = f'{title}: {message}' if title and message and message != title else title or message
		# it is shown in a badge beside the name of the configuration, which has that much room
		if len(text) > PROGRESS_LENGTH:
			text = text[: PROGRESS_LENGTH - 1].rstrip() + '…'
		if percentage is not None:
			text = f'{text} {percentage:.0f}%'.strip()
		return text

	def on_progress_event(self, event: str, body: Any):
		'''`progressStart`, `progressUpdate` and `progressEnd`: something slow the adapter is doing

		Without these a start that takes half a minute to load symbols looks the same as one that
		is stuck.
		'''
		id = body.get('progressId')
		if id is None:
			return

		if event == 'progressEnd':
			self.progress.pop(id, None)
		else:
			title, message, percentage = self.progress.get(id, ('', '', None))
			title = body.get('title') or title
			# an update without a message keeps the one before it
			message = body.get('message') or message
			if 'percentage' in body and isinstance(body.get('percentage'), (int, float)):
				percentage = max(0.0, min(100.0, float(body.get('percentage'))))
			self.progress[id] = (title, message, percentage)

		self.on_updated(self)

	def on_invalidated_event(self, invalidated: api.InvalidatedEvent):
		areas = invalidated.areas or []

		# 'all' | 'stacks' | 'threads' | 'variables'
		invalidate_all = bool(areas)
		invalidate_threads = False
		invalidate_variables = False
		invalidate_stacks = False

		for area in areas:
			if area == 'stacks':
				invalidate_stacks = True
			elif area == 'threads':
				invalidate_threads = True
			elif area == 'variables':
				invalidate_stacks = True
			else:
				# found unhandled area so just invalidate the entire thing
				invalidate_all = True

		if invalidate_all or invalidate_threads:
			self.refresh_threads()

		if invalidate_all or invalidate_variables:
			if self.selected_frame:
				core.run(self.refresh_scopes(self.selected_frame))

		if invalidate_all or invalidate_stacks:
			for thread in self.threads:
				...
				# if thread.children

	def on_event(self, event: str, body: Any):
		if not self._transport:
			core.debug('on_event: discarded transport ended')
			return

		if event == 'initialized':
			self.on_initialized_event()
		elif event == 'output':
			self.on_output_event(body)
		elif event == 'continued':
			self.on_continued_event(body)
		elif event == 'stopped':
			self.on_stopped_event(body)
		elif event == 'terminated':
			self.on_terminated_event(body)
		elif event == 'thread':
			self.on_threads_event(body)
		elif event == 'breakpoint':
			self.on_breakpoint_event(body)
		elif event == 'module':
			self.on_module_event(body)
		elif event == 'loadedSource':
			self.on_loaded_source_event(body)
		elif event == 'process':
			self.on_process_event(body)
		elif event == 'invalidated':
			self.on_invalidated_event(body)
		elif event in ('progressStart', 'progressUpdate', 'progressEnd'):
			self.on_progress_event(event, body)
		else:
			core.run(self.adapter.on_custom_event(self, event, body))
