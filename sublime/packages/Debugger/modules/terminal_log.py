'''Keeps the log of a configuration up to date with the terminal its program runs in, see `log_file`

A terminal is a view that Terminus redraws, there is no stream of what was printed to listen to.
So the view is read when it has changed, a few times a second at most, and the log is written
from what it shows. The lines a long line was wrapped onto are put back together on the way
(`task_ready.unwrapped`): a log is searched, and a line broken wherever the panel happened to
be wide enough is not found.
'''

from __future__ import annotations
from typing import Callable

import sublime

from . import task_ready
from .log_file import LogFile

INTERVAL = 500


class TerminalLog:
	def __init__(self, log: LogFile, view: Callable[[], 'sublime.View | None'], columns: Callable[[], 'int | None']):
		self.log = log
		self.view = view
		self.columns = columns

		self.changes = -1
		# every width the terminal has had, a row keeps the one it was drawn at
		self.widths: set[int] = set()
		self.closed = False

		log.terminal = True
		self.poll()

	def poll(self) -> None:
		if self.closed:
			return
		self.snapshot()
		sublime.set_timeout(self.poll, INTERVAL)

	def snapshot(self) -> None:
		view = self.view()
		if not view or not view.is_valid():
			return

		changes = view.change_count()
		if changes == self.changes:
			return
		self.changes = changes

		if columns := self.columns():
			self.widths.add(columns)

		rows = view.substr(sublime.Region(0, view.size())).split('\n')
		self.log.replace('\n'.join(task_ready.unwrapped(rows, self.widths)))

	def close(self) -> None:
		'''The last of it, once: whatever was printed since the view was last read'''
		if self.closed:
			return
		self.snapshot()
		self.closed = True
