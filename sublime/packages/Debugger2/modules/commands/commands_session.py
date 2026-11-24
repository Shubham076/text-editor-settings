from __future__ import annotations
from .. import core
from .. import dap
from ..command import Action, Section


class Start(Action):
	name = 'Start'
	key = 'start'

	# This command has a few modes
	# If a `configuration` argument is passed
	# Open or create the debugger
	# Start the debugger with the provided configuration

	# Otherwise
	# If there is no debugger create the debugger
	# If the debugger is not visible open the debugger
	# If the debugger is visibile start the debugger

	def action_raw(self, view, kwargs):
		from ..debugger import Debugger

		window = core.window_from_view_or_widow(view)
		if not window:
			return

		debugger = Debugger.get(window)

		should_start_debugging = True

		if not debugger:
			debugger = Debugger.create(view)
			should_start_debugging = False

		if not debugger.is_open():
			debugger.open()
			should_start_debugging = False

		if should_start_debugging or len(kwargs):
			debugger.start(args=kwargs)


class StartNoDebug(Action):
	name = 'Start (No Debug)'
	key = 'start_no_debug'

	def action(self, debugger):
		debugger.start(no_debug=True)


class DebugTest(Action):
	name = 'Debug Test Under Cursor'
	key = 'debug_test'
	is_menu_context = True

	no_debug = False

	# the test the cursor is in or on, in a file whose tests are recognised. `action_raw` only: the
	# debugger is made when the test starts, not for a command that had no test to start

	def action_raw(self, view, kwargs):
		from .. import test_buttons
		from .. import test_runner

		window = core.window_from_view_or_widow(view)
		view = window.active_view() if window else None
		language = test_runner.language_for(view.file_name()) if view else None

		if not view or not language:
			core.display('Not a test file the debugger knows how to run')
			return

		test = test_runner.test_at(test_buttons.tests_in(view, language), view.sel()[0].begin())
		if not test:
			core.display('No test under the cursor')
			return

		test_buttons.start(view, test.name, no_debug=self.no_debug)

	def _run(self, view, **kwargs):
		self.action_raw(view, kwargs)

	def _is_visible(self, view, **kwargs):
		from .. import test_runner

		window = core.window_from_view_or_widow(view)
		view = window.active_view() if window else None

		return bool(view and test_runner.language_for(view.file_name()))

	def _is_enabled(self, view, **kwargs):
		return self._is_visible(view, **kwargs)


class RunTest(DebugTest):
	name = 'Run Test Under Cursor (No Debug)'
	key = 'run_test'

	no_debug = True


class Stop(Action):
	name = 'Stop'
	key = 'stop'

	def action(self, debugger):
		debugger.stop()

	def is_enabled(self, debugger):
		return debugger.is_stoppable()


class Continue(Action):
	name = 'Continue'
	key = 'continue'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.resume()
		except dap.Error as e:
			debugger.console.error(f'Unable to continue: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused()


class Pause(Action):
	name = 'Pause'
	key = 'pause'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.pause()
		except dap.Error as e:
			debugger.console.error(f'Unable to pause: {e}')

	def is_enabled(self, debugger):
		return debugger.is_running()


class StepOver(Action):
	name = 'Step Over'
	key = 'step_over'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.step_over(granularity=debugger.stepping_granularity())
		except dap.Error as e:
			debugger.console.error(f'Unable to step over: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused()


class StepIn(Action):
	name = 'Step In'
	key = 'step_in'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.step_in(granularity=debugger.stepping_granularity())
		except dap.Error as e:
			debugger.console.error(f'Unable to step in: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused()


class StepOut(Action):
	name = 'Step Out'
	key = 'step_out'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.step_out(granularity=debugger.stepping_granularity())
		except dap.Error as e:
			debugger.console.error(f'Unable to step out: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused()


Section()


class ReverseContinue(Action):
	name = 'Reverse Continue'
	key = 'reverse_continue'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.reverse_continue()
		except dap.Error as e:
			debugger.console.error(f'Unable to reverse continue: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused_and_reversable()


class StepBack(Action):
	name = 'Step Back'
	key = 'step_back'

	@core.run
	async def action(self, debugger):
		try:
			await debugger.current_session.step_back(granularity=debugger.stepping_granularity())
		except dap.Error as e:
			debugger.console.error(f'Unable to step backwards: {e}')

	def is_enabled(self, debugger):
		return debugger.is_paused_and_reversable()
