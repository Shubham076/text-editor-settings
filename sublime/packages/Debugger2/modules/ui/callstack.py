from __future__ import annotations

from functools import partial
import os
from typing import TYPE_CHECKING

from .state import session_status
from .style import CH, ZW

if TYPE_CHECKING:
	from .panel import PanelUI


class CallstackPane:
	def __init__(self, ui: PanelUI):
		self.ui = ui
		self.collapsed_threads = set()

	def select_frame(self, session, thread, frame):
		if session not in self.ui.backend.sessions or not thread.stopped:
			return
		self.ui.backend.current_session = session
		session.set_selected(thread, frame)

	def toggle_thread(self, thread):
		key = id(thread)
		if key in self.collapsed_threads:
			self.collapsed_threads.remove(key)
		else:
			self.collapsed_threads.add(key)
		self.ui.invalidate()

	def select_session(self, session):
		if session in self.ui.backend.sessions:
			self.ui.backend.current_session = session
			self.ui.invalidate()

	def session_rows(self, session, width, depth=0):
		ui = self.ui
		rows = []
		if len(ui.scope.sessions) > 1 or depth or session.children:
			rows.append(ui.row(ui.link(ui.text(session.name, width, 'muted'), partial(self.select_session, session), session.name)))
		for thread in session.threads:
			label = ui.text(thread.name, width - 1.8)
			rows.append('<div class="thread">{}</div>'.format(ui.link(label, partial(self.toggle_thread, thread), 'Expand / collapse thread')))
			if not thread.stopped or id(thread) in self.collapsed_threads:
				continue
			frames = ui.tree.get(thread)
			if frames is None or isinstance(frames, str):
				rows.append(ui.row(ui.text(frames or 'Loading…', width, 'muted')))
				continue
			for frame in frames:
				location = '{}:{}'.format(os.path.basename(frame.source.name or frame.source.path or ''), frame.line) if frame.source else ''
				location_width = min((width - 1.8) * 0.45, (len(location) + 1) * CH * 0.9)
				content = ui.text(frame.name, width - 1.8 - location_width) + ui.text(location, location_width, 'right small muted', 0.9)
				selected = session is ui.active_session and frame == session.selected_frame
				rows.append('<div class="frame{}">{}{}</div>'.format(' selected' if selected else '', ZW,
					ui.link(content, partial(self.select_frame, session, thread, frame), frame.name + ' · ' + location)))
				if selected and frame.instructionPointerReference:
					rows.append(ui.row(ui.link('Disassembly', ui.backend.show_disassembly, 'Open disassembly', 'muted')))
		for child in session.children:
			rows.extend(self.session_rows(child, width, depth + 1))
		return rows

	def render(self, width, height=0):
		ui = self.ui
		rows = [ui.heading('Call stack', 'thread', width)]
		if 'thread' in ui.state.expanded:
			for session in ui.scope.sessions:
				rows.extend(self.session_rows(session, width))
			if not ui.scope.sessions:
				rows.append(ui.row('<span class="muted">No active debug session</span>'))
		session = ui.active_session
		message = session_status(session)
		if session and session.selected_thread and session.selected_thread.stopped_reason:
			message = session.selected_thread.stopped_reason
		used = ui.rows_height(rows) + ui.row_height() + 1.3
		rows.append('<div style="height:{}px;"></div>'.format(ui.px(max(0, height - used))))
		rows.append('<div class="pane-status">{}</div>'.format(ui.row(ui.text(message, width, 'muted'))))
		return rows, used
