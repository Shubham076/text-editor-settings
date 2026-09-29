from __future__ import annotations
from typing import TYPE_CHECKING

import sublime

from . import core
from .live_ui import LiveUI

if TYPE_CHECKING:
	from .output_panel import OutputPanel


class OutputPanelTabsPhantom(core.Dispose):
	def __init__(self, panel: OutputPanel, view: sublime.View, body=False, header_view: sublime.View | None = None, layout='debugger'):
		self.live = LiveUI(panel, view, body=body, header_view=header_view, layout=layout)
		self.dispose_add(self.live)

	def invalidated_layout(self):
		self.live.invalidate()
