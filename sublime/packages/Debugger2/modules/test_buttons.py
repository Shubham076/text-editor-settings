from __future__ import annotations
from typing import Any, ClassVar

import sublime
import sublime_plugin

from . import configurations
from . import core
from . import dap
from . import test_runner
from . import ui

from .project_buttons import ACTION_RUN, ACTION_STOP, Icon, ProjectButtons
from .settings import Settings

# how long typing has to pause before the tests of a file are looked for again
MODIFIED_DELAY = 400

# a declaration inside one of these is text that happens to look like a test
NOT_CODE = 'comment, string'

# the language of each test that was started, by the name of its configuration: what a session of that
# name says it is running is that language's to say
started: dict[str, test_runner.Language] = {}


def overrides(window: sublime.Window | None) -> list[Any]:
	'''What the user laid over the generated configurations: the setting, then the project on top of it'''
	project: Any = (window.project_data() if window else None) or {}

	return [Settings.test_configurations, project.get('debugger_test_configurations')]


def tests_in(view: sublime.View, language: test_runner.Language) -> list[test_runner.Test]:
	text = view.substr(sublime.Region(0, view.size()))

	return [test for test in language.find(text) if not view.match_selector(test.offset, NOT_CODE)]


@core.run
async def start(view: sublime.View, name: str, no_debug: bool = False) -> None:
	'''Debugs one test of the file in a view, by the name its runner knows it by'''
	from .debugger import Debugger

	window = view.window()
	language = test_runner.language_for(view.file_name())
	if not window or not language:
		return

	# a test file is reason enough to have a debugger, a project does not have to be set up for one
	debugger = Debugger.get(window, create=True)
	if not debugger:
		return

	# delve builds what is on disk, an unsaved test would not be the one that runs
	if view.is_dirty():
		view.run_command('save')

	try:
		json = test_runner.configuration_for(language, view.file_name() or '', name, *overrides(window))

		# listed with the configurations of the project and started as one of them: it becomes the
		# selection, so the bar stops and restarts it and the callstack and console are its
		debugger.project.add_transient(dap.Configuration.from_json(json, -1), keep=configurations.running(debugger))
		started[json['name']] = language
		await debugger.start(no_debug=no_debug, args={'configuration': json['name']})

	except Exception as error:
		core.exception()
		debugger.console.error(f'Unable to start {name}: {error}')


def session_started(session: dap.Session) -> None:
	'''Says what a test is run as, at the top of the output of its session

	Asked of the session rather than said when the icon is clicked: the configuration of a session has
	the users values laid over it and its variables filled in, and a restart from the bar comes by here too.
	'''
	language = started.get(session.configuration.name)
	if not language or getattr(session, 'parent', None):
		return

	try:
		for line in language.command(session.configuration):
			session.console.info(line)
	except Exception:
		core.exception()


def stderr_is_output(session: Any) -> bool:
	'''Whether what a session writes to stderr is the report of a test runner, see `Language.stderr_is_output`'''
	# no further up than a session can be nested, whatever it is that was handed in
	for _ in range(16):
		parent = getattr(session, 'parent', None)
		if not parent:
			break
		session = parent

	language = started.get(getattr(getattr(session, 'configuration', None), 'name', None))  # type: ignore[arg-type]
	return bool(language and language.stderr_is_output)


class TestButtons(ProjectButtons):
	'''A play icon at the head of each test in a test file, which runs that one test

	Without the debugger: the test becomes the selection of the bar, and the bug there debugs it.

	The icons of a project file, on something else: the same phantoms, drawn and compared the same
	way and for the same reasons, which is why this is a `ProjectButtons`. What differs is where they
	go and what a click starts, a configuration that is generated for the test rather than one read
	out of the project.

	While its test is running an icon is a stop, found the way a project file finds it: by the name of
	the configuration.
	'''

	views: ClassVar[dict[int, TestButtons]] = {}  # type: ignore[assignment]

	# the edits of each view that are waiting out `MODIFIED_DELAY`, only the last of them redraws
	pending: ClassVar[dict[int, int]] = {}

	@staticmethod
	def refresh(view: sublime.View) -> None:
		if not test_runner.language_for(view.file_name()):
			return

		buttons = TestButtons.views.get(view.id()) or TestButtons(view)
		buttons.render()

	@staticmethod
	def refresh_all() -> None:
		for window in sublime.windows():
			for view in window.views():
				TestButtons.refresh(view)

	@staticmethod
	def refresh_later(view: sublime.View) -> None:
		if view.id() not in TestButtons.views:
			return

		count = TestButtons.pending[view.id()] = TestButtons.pending.get(view.id(), 0) + 1

		def run() -> None:
			if TestButtons.pending.get(view.id()) != count:
				return

			TestButtons.pending.pop(view.id(), None)
			if view.is_valid():
				TestButtons.refresh(view)

		sublime.set_timeout(run, MODIFIED_DELAY)

	@staticmethod
	def dispose_all() -> None:
		for buttons in list(TestButtons.views.values()):
			buttons.dispose()

	def __init__(self, view: sublime.View) -> None:
		# not `ProjectButtons.__init__`: it erases every debugger phantom of the view, and a source file
		# has others, the inline markers of column breakpoints for one
		core.Dispose.__init__(self)
		self.view = view
		self.phantoms = []
		self.targets = []

		TestButtons.views[view.id()] = self

	def dispose(self) -> None:
		core.Dispose.dispose(self)
		self.clear()
		TestButtons.views.pop(self.view.id(), None)
		TestButtons.pending.pop(self.view.id(), None)

	def icons(self, is_running: bool, index: int) -> tuple[Icon, ...]:
		# one icon, not the run and debug pair of a project file: a file of tests has one on nearly
		# every other line. Debugging a test is the bug on the bar once it has been run, or the menu
		if is_running:
			return ((self.file(ui.Images.shared.stop), f'{ACTION_STOP}:{index}'),)

		return ((self.file(ui.Images.shared.play), f'{ACTION_RUN}:{index}'),)

	def render(self) -> None:
		from .debugger import Debugger

		file = self.view.file_name()
		language = test_runner.language_for(file)

		if not file or not language or not Settings.test_buttons:
			self.clear()
			return

		# the icons do not wait for a debugger, the first click is what makes one
		window = self.view.window()
		debugger = Debugger.get(window) if window else None
		running = configurations.running(debugger) if debugger else set()

		wanted: list[tuple[int, tuple[Icon, ...]]] = []
		targets: list[str] = []

		for test in tests_in(self.view, language):
			wanted.append((self.view.line(test.offset).begin(), self.icons(language.label(file, test.name) in running, len(targets))))
			targets.append(test.name)

		if wanted == self.current() and targets == self.targets:
			return

		self.clear()
		self.targets = targets

		for at, icons in wanted:
			self.add(at, icons)

	@core.run
	async def navigate(self, href: str) -> None:
		from .debugger import Debugger

		action, _, index = href.partition(':')
		if not index.isdigit() or int(index) >= len(self.targets):
			return

		name = self.targets[int(index)]

		if action == ACTION_RUN:
			await start(self.view, name, no_debug=True)
			return

		window = self.view.window()
		debugger = Debugger.get(window) if window else None
		language = test_runner.language_for(self.view.file_name())

		if action == ACTION_STOP and debugger and language:
			running_as = language.label(self.view.file_name() or '', name)
			if session := configurations.session_for(debugger, running_as):
				await debugger.stop(session)


def refresh_all() -> None:
	TestButtons.refresh_all()


class DebuggerTestFileListener(sublime_plugin.EventListener):
	def on_load(self, view: sublime.View) -> None:
		TestButtons.refresh(view)

	def on_activated(self, view: sublime.View) -> None:
		# as in a project file: a click activates the view before it navigates, and render() leaves
		# unchanged icons alone so the clicked one is still there
		TestButtons.refresh(view)

	def on_post_save(self, view: sublime.View) -> None:
		TestButtons.refresh(view)

	def on_modified(self, view: sublime.View) -> None:
		# a test that was just typed gets its icon, and one that was renamed runs under its new name
		TestButtons.refresh_later(view)

	def on_close(self, view: sublime.View) -> None:
		if buttons := TestButtons.views.get(view.id()):
			buttons.dispose()
