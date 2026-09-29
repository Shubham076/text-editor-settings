from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable


if TYPE_CHECKING:
	from .debugger import Debugger

import sublime

from . import core
from . import ui
from . import dap

from .settings import Settings
from .variable_format import value_summary
from .views.variable import VariableView

from .ansi import ansi_colorize

from .output_window_protocol import ProtocolConsoleWindow
from .output_panel import OutputPanel


PROGRAM_OUTPUT_BATCH_DELAY_MS = 16


class ConsoleOutputPanel(OutputPanel, dap.Console):
	def __init__(self, debugger: Debugger, session: dap.Session | None = None, protocol: ProtocolConsoleWindow | None = None, show_panel=False) -> None:
		# a session console is named after its configuration, `Test 1` rather than `Console: Test 1`, the
		# console is the only per session panel so there is nothing to tell it apart from
		# Every console, a configuration's output as much as the debugger's own debug console, keeps
		# its toolbar in the fixed strip below the output, so the controls sit in the same place
		# whichever console is open and stay put however long the output gets. The tab row sits above
		# the output, where every panel has it; the strip's back arrow returns to the call stack.
		super().__init__(debugger, 'Debugger', name=session.name if session else 'Console', show_panel=show_panel, show_tabs=True, remove_last_newline=True,
			bottom_bar=Settings.console_bar_position == 'bottom')

		self.on_input = core.Event[str]()
		self.on_navigate = core.Event[dap.SourceLocation]()
		self.debugger = debugger

		# set when this panel is one configurations console rather than the debuggers own
		self.session = session

		# a session console borrows the debuggers protocol window: there is only ever one of those and it
		# already keeps a view per session, so a second one would be a second window
		self.owns_protocol = protocol is None
		self.protocol = protocol or ProtocolConsoleWindow()

		if self.owns_protocol:
			self.dispose_add(self.protocol)

		self.view.assign_syntax(core.package_path_relative('contributes/Syntax/DebuggerConsole.sublime-syntax'))
		self.color: str | None = None
		self.phantoms: list[ui.Phantom | ui.RawPhantom | RegionAnnotation] = []
		self.input_size = 0

		self.indent = ''
		self.forced_indent = ''

		self._history_offset = 0
		self._history = []

		self._last_output_event: dap.OutputEvent | None = None
		self._program_output_batch: list[str] = []
		self._program_output_batch_color: str | None = None
		self._program_output_batch_revision = 0
		self._program_output_batch_scheduled = False

		settings = self.view.settings()
		settings.set('auto_complete_selector', 'debugger.console')
		# the completion popup opens on its own after a member access, as it does in the editor with
		# LSP; adapters that name their own trigger characters replace these once a session is up
		settings.set('auto_complete', True)
		# only what the language server offers: no editor snippets, no completions remembered from
		# other buffers (`on_query_completions` inhibits the buffer words)
		settings.set('auto_complete_include_snippets', False)
		settings.set('auto_complete_include_snippets_when_typing', False)
		settings.set('auto_complete_use_history', False)
		self.update_completion_triggers(None)

		self.clear()

	def edit(self, fn: Callable[[sublime.Edit], Any]):
		h = self.view.viewport_extent()[1]
		extend_y = self.view.layout_extent()[1]
		position_y = self.view.viewport_position()[1]

		at_bottom_ish = ((position_y + h) - extend_y) >= 0

		is_read_only = self.view.is_read_only()
		if is_read_only:
			self.view.set_read_only(False)
			core.edit(self.view, fn)
			self.view.set_read_only(True)
		else:
			core.edit(self.view, fn)

		if at_bottom_ish:
			self.scroll_to_end()

	def ensure_scrollback_size(self):
		while len(self.phantoms) > Settings.console_scrollback_annotation_limit:
			self.phantoms.pop(0).dispose()

		line_count = self.view.rowcol(self.view.size())[0]

		if line_count > Settings.console_scrollback_limit:
			remove = line_count - Settings.console_scrollback_limit
			region = sublime.Region(0, self.view.text_point(remove, 0))
			self.edit(lambda e: self.view.replace(e, region, ''))

	def program_output(self, session: dap.Session, event: dap.OutputEvent):
		type = event.category or 'console'
		if type == 'telemetry':
			return

		source = None
		if event.source:
			source = dap.SourceLocation(event.source, event.line)

		# ignore if the group has the same header
		# this is mostly a workaround for this bug in node... https://github.com/nodejs/node/issues/31973
		if self._last_output_event and self._last_output_event.group == 'start' and self._last_output_event.output == event.output:
			self._last_output_event = event
			return

		self._last_output_event = event

		# a program's output reads as plain text, like the editor's own; only what the adapter
		# flags stands out: errors in red, `important` in magenta
		color_for_type: dict[str | None, str | None] = {
			'stderr': 'red',
			'stdout': 'foreground',
			'important': 'magenta',
		}

		color = color_for_type.get(type) or 'foreground'

		# Startup output commonly arrives as one DAP event per line. Rendering every one immediately
		# makes Sublime perform a buffer edit, viewport check, scrollback check and possible scroll for
		# each line. Collect only plain stream output for one UI frame; structured output keeps the
		# existing immediate path below.
		if event.output and type in ('stdout', 'stderr') and not event.group and not event.variablesReference and not event.source:
			self.queue_program_output(event.output, color)
			return

		# A structured event must remain after all stream output that preceded it.
		self.flush_program_output()

		if event.group == 'end':
			self.end_indent()

		if event.variablesReference:
			output = event.output
			region = self.write(output, color, ensure_new_line=False, ignore_indent=False, annotation_region=True)

			async def appendVariabble(variablesReference: int) -> None:
				try:
					variables = await session.get_variables(variablesReference, without_names=True)
					at = region.location().a

					for variable in variables:
						self.write_variable(variable, at)

				# if a request is cancelled it is because the debugger session ended
				except core.CancelledError:
					...
				# In some cases the variable cannot be fetched since the debugger session was terminated because of the exception
				# However the exception message is actually important and needs to be shown to the user...
				except Exception:
					core.exception('Unable to fetch variables')
					# todo: this should be inserted into the place the phantom was going to be?
					# self.append_text(event.category or 'console', self.indent + event.output, event.source, event.line)

			core.run(appendVariabble(event.variablesReference))

		elif event.output:
			self.write(event.output, color, ignore_indent=False)
			if event.source:
				region = RegionAnnotation(self.view, sublime.Region(self.at() - 1), self.on_navigate, source=source)
				self.phantoms.append(region)

		if event.group == 'start' or event.group == 'startCollapsed':
			self.start_indent()

	def is_output_identical(self, last_event: dap.OutputEvent, event: dap.OutputEvent):
		if not event.output:
			return False
		return last_event.category == event.category and last_event.output == event.output

	def queue_program_output(self, text: str, color: str) -> None:
		# A color transition needs the same newline and ANSI handling as an ordinary write, so finish
		# the current color before starting the next batch.
		if self._program_output_batch and self._program_output_batch_color != color:
			self.flush_program_output()

		self._program_output_batch.append(text)
		self._program_output_batch_color = color
		if self._program_output_batch_scheduled:
			return

		self._program_output_batch_scheduled = True
		revision = self._program_output_batch_revision
		sublime.set_timeout(lambda: self.flush_scheduled_program_output(revision), PROGRAM_OUTPUT_BATCH_DELAY_MS)

	def flush_scheduled_program_output(self, revision: int) -> None:
		# A clear, disposal or synchronous flush invalidates the callback that was already scheduled.
		if revision == self._program_output_batch_revision:
			self.flush_program_output()

	def flush_program_output(self) -> None:
		if not self._program_output_batch:
			return

		text = ''.join(self._program_output_batch)
		color = self._program_output_batch_color
		self.discard_program_output()
		assert color is not None
		self._write(text, color, ignore_indent=False)

	def discard_program_output(self) -> None:
		self._program_output_batch_revision += 1
		self._program_output_batch_scheduled = False
		self._program_output_batch.clear()
		self._program_output_batch_color = None

	def start_indent(self, forced: bool = False):
		self.flush_program_output()
		if forced:
			self.forced_indent += '\t'
		else:
			self.indent += '\t'

	def end_indent(self, forced: bool = False):
		self.flush_program_output()
		if forced:
			self.forced_indent = self.forced_indent[:-1]
		else:
			self.indent = self.indent[:-1]

	def at(self):
		# there is always a single invisible character at the end of the content otherwise every single write causes the phantom to be out of position and require re-rendering
		if input := self.input_region():
			return max(input.a - 1, 0)
		return max(self.view.size() - 1, 0)

	def is_newline_required(self, at: int | None = None):
		if at is None:
			at = self.at()

		if self.removed_newline == at:
			return False

		if at != 0 and self.view.substr(at - 1) != '\n':
			return True

		return False

	def write(self, text: str, color: str | None, ensure_new_line=False, ignore_indent: bool = True, annotation_region: bool = False) -> RegionAnnotation:
		# Console messages, expression results and user interaction must stay after any program output
		# already received, even if its scheduled batch has not rendered yet.
		self.flush_program_output()
		return self._write(text, color, ensure_new_line, ignore_indent, annotation_region)

	def _write(self, text: str, color: str | None, ensure_new_line=False, ignore_indent: bool = True, annotation_region: bool = False) -> RegionAnnotation:
		indent = ''

		if not ignore_indent and self.indent:
			indent += self.indent
		if self.forced_indent:
			indent += self.forced_indent

		if indent:
			text = indent + text
			text = text.replace('\n', '\n' + indent, text.count('\n') - 1)

		# if we are changing color we want it on its own line
		if (ensure_new_line or self.color != color) and self.is_newline_required():
			self.edit(lambda edit: self.view.insert(edit, self.at(), '\n'))

		colored = ansi_colorize(text, color, self.color)
		region: Any = None

		def edit(edit: sublime.Edit):
			nonlocal region
			at = self.at()
			self.view.insert(edit, at, colored)
			if annotation_region:
				region = RegionAnnotation(self.view, sublime.Region(at), self.on_navigate)
				self.phantoms.append(region)

		self.edit(edit)
		self.color = color

		self.ensure_scrollback_size()
		return region

	def marker_html(self, marker: str):
		# the view's own background, not `var(--background)`: a scheme's popup css may redefine that
		# variable (everforest points it at its cream popup colour) and Sublime applies it here too
		background = self.view.style().get('background', 'transparent')
		return f"""
			<style>
			html {{
				background-color: {background};
			}}
			a {{
				color: color(var(--foreground) alpha(0.25));
				text-decoration: none;
				padding-left: 0.0rem;
				padding-right: 0.5rem;
			}}
			</style>
			<body id="debugger">
				<a href="">{marker}</a>
			</body>
		"""

	def write_evaluated(self, session: dap.Session, result: dap.EvaluateResponse):
		'''The result of an expression typed into the console

		A plain value is its text. A value with children is its text as well, the whole value the
		adapter rendered (`AgenticPluginConfig(api_key='set', timeout=30, ...)`), with the expander in
		front of it to read the children one per line underneath. The console has the room for it; the
		Variables pane's short label (`value_summary`) is only the fallback when the adapter sent no
		text. Writing an empty string there, as this used to, left a row with nothing but the expander.
		'''
		if result.variablesReference:
			variable = dap.Variable.from_evaluate(session, '', result)
			label = result.result or value_summary(variable) or result.type or ''
			region = self.write(label, 'result', ensure_new_line=True, annotation_region=True)
			self.write_variable(variable, region.location().a)
		elif result.result:
			self.write(result.result, 'result', ensure_new_line=True)

	def write_variable(self, variable: dap.Variable, at: int):
		expanded_phantom: ui.Phantom|None = None
		phantom = ui.RawPhantom(self.view, sublime.Region(at, at), self.marker_html(core.platform.unicode_unchecked_sigil))
		self.phantoms.append(phantom)


		def on_navigate(_: str):
			nonlocal expanded_phantom

			sigil = core.platform.unicode_unchecked_sigil if expanded_phantom else core.platform.unicode_checked_sigil
			phantom.update(self.marker_html(sigil))

			if expanded_phantom:
				expanded_phantom.dispose()
				expanded_phantom = None
				return

			with ui.Phantom(self.view, phantom.position(), sublime.LAYOUT_BELOW) as p:
				expanded_phantom = p
				self.phantoms.append(p)
				with ui.div(width=10000):
					view = VariableView(self.debugger, variable, children_only=True)
					view.set_expanded()

		phantom.on_navigate = on_navigate

	def clear(self):
		self.discard_program_output()
		self.indent = ''
		self.forced_indent = ''

		# clearing a borrowed protocol window would clear it for every other session too
		if self.owns_protocol:
			self.protocol.clear()
		self.dispose_phantoms()
		self._last_output_event = None
		self.color = None
		self.edit(lambda edit: self.view.replace(edit, sublime.Region(0, self.view.size()), '\u200b'))
		self.view.set_read_only(True)

	def on_selection_modified(self):
		input = self.input_region()
		if not input:
			self.view.set_read_only(True)
			return

		sel = self.view.sel()
		end_of_input = input.b

		for region in sel:
			if region.a < end_of_input:
				self.view.set_read_only(True)
				return

			self.view.set_read_only(False)

	# if you type outside of the input region we want it to scroll_to_end so you are tying into the input region
	def on_query_context(self, key: str, operator: int, operand: Any, match_all: bool) -> bool | None:
		if input := self.input_region():
			sel = self.view.sel()
			end_of_input = input.b

			for region in sel:
				if region.a < end_of_input:
					self.scroll_to_end()
					return

			return
		return None

	def on_post_text_command(self, command_name: str, args: Any):
		if command_name == 'copy':
			sublime.set_clipboard(sublime.get_clipboard().replace('\u200c', '').replace('\u200b', ''))

		# left_delete seems to cause issues with the layout not being updated so manually call on_text_changed
		if command_name == 'left_delete':
			self.force_invalidate_layout()

	def on_text_command(self, command_name: str, args: Any):  # type: ignore
		if not self.view.is_auto_complete_visible() and command_name == 'move' and args['by'] == 'lines':
			self.enable_input_mode()
			if args['forward']:
				self.autofill(-1)
			else:
				self.autofill(1)
			return 'noop'

	def update_completion_triggers(self, session: dap.Session | None):
		'''Characters that open the completion popup in the input line: the adapter's, else `.` and `[`'''
		self.view.settings().set('auto_complete_triggers', self.completion_triggers(session, 'debugger.console'))

	def on_query_completions(self, prefix: str, locations: list[int]) -> Any:
		'''The completion popup of the input line: the language server's items, or no popup at all

		Only the server knows the types and members of what is typed, the way the editor's popup does.
		Sublime's own buffer words and snippets are inhibited, and the adapter's bare names and the input
		history stay out of the popup (the history is still on the up and down arrows). Without LSP, a
		frame or a server for its file there is nothing worth showing: the list stays empty and no
		popup opens. Which frame is asked about is `completion_session`.
		'''
		input = self.input_region()
		if not input:
			return

		self.update_completion_triggers(self.completion_session())
		text = self.view.substr(sublime.Region(input.b, self.view.size()))
		return self.language_server_completion_list(self.view, text)

	def on_deactivated(self):
		if input := self.input_region():
			text_region = sublime.Region(input.b, self.view.size())
			if text_region.size() == 0:
				self.disable_input_mode()

	def input_region(self):
		regions = self.view.get_regions('input')
		if not regions:
			return None
		region = regions[0]

		if region.size() != self.input_size:
			self.view.erase_regions('input')
			self.edit(lambda edit: self.view.erase(edit, region))
			return None

		return region

	def disable_input_mode(self):
		if input := self.input_region():
			self.view.erase_regions('input')
			self.edit(lambda edit: self.view.erase(edit, sublime.Region(input.a, self.view.size())))

	def enable_input_mode(self):
		self.flush_program_output()
		if self.input_region():
			return

		size = self.view.size()

		def edit(edit):
			# the prompt sits after a blank line, like the expression echoed in its place on enter
			# (`ensure_blank_line`); the text before the trailing zero-width character is the output
			marker = '\n' * self.newlines_to_blank_line(size - 1) + '\u200c:'
			input_size = self.view.insert(edit, size, marker)
			self.input_size = input_size
			self.view.add_regions('input', [sublime.Region(size, size + input_size)])

		self.edit(edit)
		self.view.set_read_only(False)
		self.scroll_to_end()

	def enter(self):
		self.flush_program_output()
		input = self.input_region()
		if not input:
			self.enable_input_mode()
			return False

		text_region = sublime.Region(input.b, self.view.size())
		text = self.view.substr(text_region)
		if not text:
			self.disable_input_mode()
			return True

		self.edit(
			lambda edit: (
				self.view.erase(edit, text_region),
				self.view.sel().clear(),
				self.view.sel().add(self.view.size()),
			)
		)

		self.on_input(text)
		# echoed as typed, in plain text with the prompt dimmed (`input` in ansi.py), so the
		# expression and what it evaluated to (`result`) read like a transcript of the editor; a
		# blank line in front keeps one evaluation apart from the last
		self.ensure_blank_line()
		self.write(':' + text, 'input', True)
		self._history_offset = 0
		self._history.append(text)

		# reset the input mode since line 0 is handled differntly in enable_input_mode and we just added a newline
		self.disable_input_mode()
		self.enable_input_mode()
		return True

	def newlines_to_blank_line(self, at: int) -> int:
		'''How many newlines at `at` leave exactly one empty line between the text before it and the next line

		None when there is no text before it, so the first line of an empty console is used.
		'''
		if at <= 0:
			return 0
		before = self.view.substr(sublime.Region(max(0, at - 2), at))
		return max(0, 2 - (len(before) - len(before.rstrip('\n'))))

	def ensure_blank_line(self):
		'''An empty line before whatever is written next, unless the console is empty or one is there

		Air between one evaluation and the next, so an expression and its result read as one entry.
		'''
		missing = self.newlines_to_blank_line(self.at())
		if missing:
			self.edit(lambda edit: self.view.insert(edit, self.at(), '\n' * missing))

	def autofill(self, offset: int):
		self._history_offset += offset
		self._history_offset = min(max(0, self._history_offset), len(self._history))
		self.enable_input_mode()
		input = self.input_region()
		if not input:
			return False

		text_region = sublime.Region(input.b, self.view.size())
		if self._history_offset:
			self.edit(
				lambda edit: (
					self.view.replace(edit, text_region, self._history[-self._history_offset]),
					self.view.sel().clear(),
					self.view.sel().add(self.view.size()),
				)
			)
		else:
			self.edit(
				lambda edit: (
					self.view.erase(edit, text_region),
					self.view.sel().clear(),
					self.view.sel().add(self.view.size()),
				)
			)

	def log(self, type: str, value: Any, source: dap.SourceLocation | None = None, session: dap.Session | None = None, html: ui.Html | None = None):
		if type in ('error', 'error-no-open', 'stderr') and (session or self.session) and self.debugger.session_panels:
			self.debugger.session_panels.reveal_console(session or self.session)
		if type == 'transport':
			self.protocol.log('transport', value, source, session)
		elif type == 'error-no-open':
			self.write(str(value).rstrip('\n'), 'red', ensure_new_line=True)
		elif type == 'error':
			self.write(str(value).rstrip('\n'), 'red', ensure_new_line=True)
			self.open()
		elif type == 'group-start':
			if value is not None:
				self.write(str(value), None, ensure_new_line=True)
			self.start_indent(forced=True)
		elif type == 'group-end':
			self.end_indent(forced=True)
			if value is not None:
				self.write(str(value), None, ensure_new_line=True)
		elif type == 'stdout':
			self.protocol.log('stdout', value, source, session)
			self.write(str(value), None)
		elif type == 'stderr':
			self.protocol.log('stderr', value, source, session)
			self.write(str(value), 'red')
		elif type == 'stdout':
			self.write(str(value), None)
		elif type == 'warn':
			self.write(str(value).rstrip('\n'), 'yellow', ensure_new_line=True)
		elif type == 'success':
			self.write(str(value).rstrip('\n'), 'green', ensure_new_line=True)
		else:
			self.write(str(value).rstrip('\n'), 'comment', ensure_new_line=True)

		if source:
			self.phantoms.append(RegionAnnotation(self.view, sublime.Region(self.at() - 1), self.on_navigate, source=source))

		if html:
			self.phantoms.append(ui.RawPhantom(self.view, self.at() - 1, html=html.html, on_navigate=html.on_navigate))

	def dispose_phantoms(self):
		for phantom in self.phantoms:
			phantom.dispose()
		self.phantoms.clear()

	def dispose(self):
		self.discard_program_output()
		super().dispose()
		self.dispose_phantoms()
		self.protocol.dispose()


class RegionAnnotation(core.Dispose):
	next_annotation_id = 0

	def __init__(self, view: sublime.View, region: sublime.Region, on_navigate: Callable[[dap.SourceLocation], Any], count: int | None = None, source: dap.SourceLocation | None = None) -> None:
		self.view = view

		RegionAnnotation.next_annotation_id += 1
		self.id = f'debugger.{RegionAnnotation.next_annotation_id}'

		self.on_navigate = on_navigate
		self._update(region, count, source)

		self.dispose_add(lambda: self.view.erase_regions(self.id))

	def update(self, count: int | None, source: dap.SourceLocation | None):
		self._update(self.location(), count, source)

	def _update(self, region: sublime.Region, count: int | None, source: dap.SourceLocation | None):
		if source or count and count > 1:
			if source:
				on_navigate = lambda _: self.on_navigate(source)
				source_html = f'<a href="">{source.name}</a>'
			else:
				on_navigate = None
				source_html = ''

			count_html = f'<span>{count}</span>' if count else ''

			# the view's own background, not `var(--background)`: a scheme's popup css may redefine that
			# variable (everforest points it at its cream popup colour) and Sublime applies it to annotations
			background = self.view.style().get('background', 'transparent')

			html = f"""
			<style>
				html {{
					background-color: {background};
				}}
				a {{
					color: color(var(--foreground) alpha(0.33));
					text-decoration: none;
				}}
				span {{
					color: color(var(--foreground) alpha(0.66));
					background-color: color(var(--accent) alpha(0.5));
					padding-right: 1.1rem;
					padding-left: -0.1rem;
					border-radius: 0.5rem;
				}}
			</style>
			<body id="debugger">
				<div>
					{count_html}
					{source_html}
				</div>
			</body>
			"""

			self.view.add_regions(self.id, [region], annotation_color='#fff0', annotations=[html], on_navigate=on_navigate)
		else:
			self.view.add_regions(self.id, [region])

	def location(self):
		return self.view.get_regions(self.id)[0]
