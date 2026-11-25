from __future__ import annotations
from typing import Any, Callable

from .. import ui
from .. import dap
from .. import core

from . import css


class BreakpointsView(ui.div, core.Dispose):
	def __init__(self, breakpoints: dap.Breakpoints, on_navigate: Callable[[dap.SourceLocation], None]) -> None:
		super().__init__()
		self.breakpoints = breakpoints
		self.on_navigate = on_navigate

	def added(self) -> None:
		self.dispose_add(
			self.breakpoints.source.on_updated.add(self._updated),
			self.breakpoints.filters.on_updated.add(self._updated),
			self.breakpoints.data.on_updated.add(self._updated),
			self.breakpoints.function.on_updated.add(self._updated),
		)

	def removed(self) -> None:
		self.dispose()

	def _updated(self, data: Any) -> None:
		self.dirty()

	def render(self):
		for breakpoints in (self.breakpoints.filters, self.breakpoints.function, self.breakpoints.data, self.breakpoints.source):
			for breakpoint in breakpoints:
				BreakpointView(self.breakpoints, breakpoint, self.on_navigate)


class BreakpointGlyph(ui.span):
	def __init__(self, breakpoint, on_click: Callable[[], None]):
		super().__init__(on_click=on_click)
		self.breakpoint = breakpoint
		self.width = 3

	def html(self, available_width: float, available_height: float):
		image = self.breakpoint.image
		if image is ui.Images.shared.dot_emtpy:
			glyph = '&#9675;'
		elif image is ui.Images.shared.dot_log:
			glyph = '&#9670;'
		elif image is ui.Images.shared.dot_expr:
			glyph = '&#9673;'
		else:
			glyph = '&#9679;'
		tag, attributes = self.html_tag_and_attrbutes()
		return (f'<{tag} {attributes} style="display:inline-block;width:2.5rem;height:2.5rem;'
		        f'line-height:2.5rem;font-size:2rem;padding-right:0.5rem;text-align:center;'
		        f'color:var(--redish);">{glyph}</{tag}>')


class BreakpointView(ui.div):
	def __init__(self, breakpoints: dap.Breakpoints, breakpoint: dap.DataBreakpoint | dap.ExceptionBreakpointsFilter | dap.FunctionBreakpoint | dap.SourceBreakpoint, on_navigate: Callable[[dap.SourceLocation], None]) -> None:
		super().__init__()
		self.breakpoints = breakpoints
		self.breakpoint = breakpoint
		self.on_navigate = on_navigate

	def render(self):
		if self.breakpoint.enabled:
			BreakpointGlyph(self.breakpoint, self._on_toggle)
		else:
			ui.icon(self.breakpoint.image, on_click=self._on_toggle)
		ui.text(self.breakpoint.name, css=css.secondary, on_click=self._on_navigate)

		if self.breakpoint.tag:
			ui.spacer()
			ui.text(self.breakpoint.tag, css=css.button, on_click=self._on_navigate)

	def _on_navigate(self) -> None:
		if isinstance(self.breakpoint, dap.SourceBreakpoint):
			self.on_navigate(dap.SourceLocation.from_path(self.breakpoint.file, self.breakpoint.line, self.breakpoint.column))

	def _on_toggle(self) -> None:
		if isinstance(self.breakpoint, dap.DataBreakpoint):
			self.breakpoints.data.toggle_enabled(self.breakpoint)
		elif isinstance(self.breakpoint, dap.FunctionBreakpoint):
			self.breakpoints.function.toggle_enabled(self.breakpoint)
		elif isinstance(self.breakpoint, dap.ExceptionBreakpointsFilter):
			self.breakpoints.filters.toggle_enabled(self.breakpoint)
		elif isinstance(self.breakpoint, dap.SourceBreakpoint):
			self.breakpoints.source.toggle_enabled(self.breakpoint)
		else:
			assert False, 'unreachable'

	def is_removeable(self):
		return not isinstance(self.breakpoint, dap.ExceptionBreakpointsFilter)

	def remove(self) -> None:
		if isinstance(self.breakpoint, dap.ExceptionBreakpointsFilter):
			...
		elif isinstance(self.breakpoint, dap.DataBreakpoint):
			self.breakpoints.data.remove(self.breakpoint)
		elif isinstance(self.breakpoint, dap.FunctionBreakpoint):
			self.breakpoints.function.remove(self.breakpoint)
		elif isinstance(self.breakpoint, dap.SourceBreakpoint):
			self.breakpoints.source.remove(self.breakpoint)
		else:
			assert False, 'unreachable'

	@core.run
	async def edit(self) -> None:
		if isinstance(self.breakpoint, dap.DataBreakpoint):
			await self.breakpoints.data.edit(self.breakpoint)
		elif isinstance(self.breakpoint, dap.FunctionBreakpoint):
			await self.breakpoints.function.edit(self.breakpoint)
		elif isinstance(self.breakpoint, dap.ExceptionBreakpointsFilter):
			await self.breakpoints.filters.edit(self.breakpoint)
		elif isinstance(self.breakpoint, dap.SourceBreakpoint):
			await self.breakpoints.source.edit(self.breakpoint)
		else:
			assert False, 'unreachable'
