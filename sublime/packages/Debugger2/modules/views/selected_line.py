from __future__ import annotations

from .. import ui
from .. import dap
from .. import core
from ..exception_format import exception_lines

import sublime


class SelectedLine:
	def __init__(self, view: sublime.View, line: int, column: int | None, thread: dap.Thread):
		# note sublime lines are 0 based not 1 based
		pt_current_line = view.text_point(line - 1, 0)

		end_of_selected_line = view.line(pt_current_line).b
		start_of_selected_line = view.line(pt_current_line).a

		view.add_regions('debugger.selection', [sublime.Region(start_of_selected_line, end_of_selected_line + 1)], scope='region.bluish debugger.selection', flags=sublime.DRAW_NO_OUTLINE)

		if column and column > 1:
			at = view.text_point(line - 1, column - 1)
			view.add_regions('debugger.selection.column', [sublime.Region(at)], scope='region.bluish debugger.selection', flags=sublime.DRAW_EMPTY_AS_OVERWRITE)

		self.stopped_reason = thread.stopped_reason or 'Stopped'

		# what is left of the line between the end of its text and the edge of the view
		self.space_after_line = view.viewport_extent()[0] - view.text_to_layout(end_of_selected_line)[0]

		self.line = line
		self.end_of_selected_line = end_of_selected_line
		self.view = view
		self.values = ''
		self.values_css = ''
		# how much wider than the text of the file a character of the values is, 1 or more
		self.values_scale = 1.0

		self.text = ui.RawPhantom(view, sublime.Region(end_of_selected_line, end_of_selected_line), self.html(), layout=sublime.LAYOUT_INLINE)

		self.more = None
		self.fetch = None

		if thread.stopped_event and thread.stopped_event.reason == 'exception':
			self.fetch = core.run(self.fetch_exception_info(thread))

	def html(self) -> str:
		'''The note at the end of the stopped line: why it stopped, at the right edge of the view

		With inline values on, the values of the variables the line mentions come first, where they
		are on every other line. They share the one phantom because the reason is given a width to
		push it to the edge, and a second phantom beside it would be wrapped onto a line of its own.
		'''
		name = ui.html_escape(self.stopped_reason)
		width = self.space_after_line - 20

		values = self.values
		if values:
			# over rather than under: the note is drawn smaller than the text this is the width of,
			# and coming up short of the edge is better than wrapping
			em = self.view.em_width() * self.values_scale
			room = int(width / em) - len(self.stopped_reason) - 6
			if room < 12:
				values = ''
			elif len(values) > room:
				values = values[: room - 1].rstrip() + '…'

		values_html = ''
		if values:
			width -= (len(values) + 4) * self.view.em_width() * self.values_scale
			values_html = f'<div class="values">{ui.html_escape(values)}</div>'

		return f"""
			<body id="debugger">
				<style>
					html {{
						/* a note beside the code rather than more code: smaller, slanted and bold, so it
						   cannot be read as part of the line it sits on. The colour is the schemes own
						   text colour, barely faded: it sits on the highlight of the stopped line, and
						   the text colour is the one that reads on it in a light scheme and a dark one */
						color: color(var(--foreground) alpha(0.85));
						font-size: 0.85em;
						font-style: italic;
						font-weight: bold;
					}}
					div.content {{
						display: {'inline-block' if values else 'block'};
						text-align: right;
						width: {width}px;
					}}
					div.values {{
						display: inline-block;
						padding-left: 2rem;
						{self.values_css}
					}}
				</style>
				{values_html}<div class="content">
					{name}
				</div>
			</body>
		"""

	def set_values(self, values: str, css: str = '', scale: float = 1.0):
		'''The inline values of the stopped line and the css they are drawn with, `''` for none, see `InlineValues`'''
		if values == self.values and css == self.values_css and scale == self.values_scale:
			return
		self.values_scale = max(1.0, scale)
		self.values = values
		self.values_css = css
		self.text.update(self.html())

	async def fetch_exception_info(self, thread: dap.Thread):
		if not thread.session.capabilities.supportsExceptionInfoRequest:
			return

		try:
			info = await thread.session.exception_info(thread.id)
		except dap.Error as error:
			# the line still says it stopped on an exception, there is just nothing more to say
			core.info(f'exceptionInfo failed: {error}')
			return

		heading, trace = exception_lines(info, self.stopped_reason)
		if not heading and not trace:
			return

		heading_html = ''.join(f'<div class="heading">{ui.html_escape(line)}</div>' for line in heading)
		trace_html = ''.join(f'<div class="trace">{ui.html_escape_multi_line(line)}</div>' for line in trace)

		html_more = f"""
			<body id="debugger">
				<style>
					div.content {{
						color: var(--accent);
						padding: 5px;
						border-radius: 3px;
						background-color: color(var(--accent) alpha(0.1));
					}}
					div.heading {{
						font-weight: bold;
					}}
					div.trace {{
						font-size: 0.9em;
						color: color(var(--foreground) alpha(0.75));
					}}
				</style>
				<div class="content">
					{heading_html}{trace_html}
				</div>
			</body>
		"""
		self.more = ui.RawPhantom(self.view, sublime.Region(self.end_of_selected_line, self.end_of_selected_line), html_more, layout=sublime.LAYOUT_BLOCK)

	def dispose(self):
		self.view.erase_regions('debugger.selection.column')
		self.view.erase_regions('debugger.selection')
		self.text.dispose()
		if self.fetch:
			self.fetch.cancel()
		if self.more:
			self.more.dispose()
