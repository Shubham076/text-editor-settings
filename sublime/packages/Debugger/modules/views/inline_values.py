from __future__ import annotations
from typing import TYPE_CHECKING

import sublime

from .. import ui
from .. import dap
from .. import inline_values
from ..variable_format import value_summary
from ..settings import Settings

if TYPE_CHECKING:
	from .selected_line import SelectedLine

# the scopes of a frame that are asked for their variables. Locals and arguments come first with
# every adapter, and what is past the first few is a closure of a closure
MAX_SCOPES = 3

HTML = """
	<body id="debugger-inline-values">
		<style>
			div.values {{
				/* beside the code and not part of it: faded, slanted and a little smaller, unless
				   the `inline_values_*` settings say otherwise */
				{}
				padding-left: 2rem;
			}}
		</style>
		<div class="values">{}</div>
	</body>
"""


def style() -> str:
	'''The css of an inline value, as the settings have it now'''
	return inline_values.style_css(
		Settings.inline_values_color,
		Settings.inline_values_opacity,
		Settings.inline_values_font_style,
		Settings.inline_values_font_face,
		Settings.inline_values_font_size,
	)


async def frame_values(scopes: list[dap.Variable]) -> tuple[dict[str, str], list[tuple[str, str]]]:
	'''The variables of a frame by name, as they are written beside a line, and what was just returned to it

	`scopes` are the scopes of the frame, innermost first. A name an inner scope has hides the same
	name further out, which is what the program sees as well. What a call returned is listed by
	the adapter among the locals, under a name no line of source has (`inline_values.returned_by`).
	'''
	values: dict[str, str] = {}
	returned: list[tuple[str, str]] = []
	asked = 0

	for scope in scopes:
		if not inline_values.is_frame_scope(scope.name, scope.expensive, scope.presentationHint):
			continue

		if asked == MAX_SCOPES:
			break
		asked += 1

		for variable in await scope.children():
			if variable.name in values or variable.value is None:
				continue

			# something with children is its type or its length, the contents are a hover away
			text = value_summary(variable) if variable.has_children else variable.value
			if not text:
				continue

			function = inline_values.returned_by(variable.name)
			if function is None:
				values[variable.name] = text
			else:
				returned.append((function, text))

	return values, returned


class InlineValues:
	'''The values of the variables of a frame, at the end of the lines of its function that mention them

	From the first line of the function to the line that is stopped on. The stopped line already
	has a phantom at its end, so its values are handed to that one (`SelectedLine.set_values`).
	'''

	def __init__(self, selected: SelectedLine, values: dict[str, str], returned: list[tuple[str, str]] = []):
		self.selected = selected
		self.phantoms: list[ui.RawPhantom] = []

		view = selected.view
		stopped = selected.line - 1

		symbol_lines = [view.rowcol(region.begin())[0] for region, _ in view.symbols()]
		first = inline_values.first_line(stopped, symbol_lines)

		def line_region(line: int) -> sublime.Region:
			return view.line(view.text_point(line, 0))

		def is_code(line: int, column: int) -> bool:
			return not view.match_selector(view.text_point(line, column), 'comment, string')

		lines = ((line, view.substr(line_region(line))) for line in range(first, stopped + 1))

		css = style()

		# a font size set larger than the text of the file takes more of the stopped line than the
		# width of its characters says
		size = Settings.inline_values_font_size
		view_size = view.settings().get('font_size')
		scale = size / view_size if isinstance(size, (int, float)) and isinstance(view_size, (int, float)) and view_size > 0 else 1.0

		by_line = inline_values.values_by_line(lines, values, is_code)

		# what the call that was just stepped out of, or over, came back with: first on the line
		# that is stopped on, which is the line it came back to
		if returned:
			text = inline_values.returned_text(returned)
			by_line[stopped] = f'{text}, {by_line[stopped]}' if stopped in by_line else text

		for line, text in by_line.items():
			if line == stopped:
				selected.set_values(text, css, scale)
				continue

			end = line_region(line).b
			self.phantoms.append(ui.RawPhantom(view, sublime.Region(end, end), HTML.format(css, ui.html_escape(text)), layout=sublime.LAYOUT_INLINE))

	def dispose(self):
		for phantom in self.phantoms:
			phantom.dispose()
		self.phantoms.clear()
		self.selected.set_values('')
