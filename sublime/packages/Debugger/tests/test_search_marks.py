from __future__ import annotations

import unittest
from unittest.mock import Mock

from test_live_ui import ROOT, load_module, sublime_stubs


class SearchMarksTests(unittest.TestCase):
	"""The marks of a search in a panel go when something is typed, not when the program prints"""

	def setUp(self):
		stubs = sublime_stubs()
		stubs.sublime_plugin.TextInputHandler = type('TextInputHandler', (), {})
		self.search = load_module('_search_test', ROOT / 'modules/search.py', {'sublime': stubs.sublime, 'sublime_plugin': stubs.sublime_plugin})
		self.view = Mock()
		self.view.id.return_value = 7
		self.search._searches[7] = {'query': 'error', 'index': 3, 'shown': True}
		self.addCleanup(self.search._searches.clear)
		self.listener = self.search.DebuggerSearchListener()

	def modified_by(self, command):
		self.view.command_history.return_value = (command, {}, 1)
		self.listener.on_modified(self.view)

	def test_what_the_program_prints_leaves_the_marks_and_the_place(self):
		self.modified_by('debugger_edit')
		self.view.erase_regions.assert_not_called()
		self.assertEqual(self.search._searches[7], {'query': 'error', 'index': 3, 'shown': True})

	def test_typing_takes_the_marks_and_keeps_the_search(self):
		self.modified_by('insert')
		self.assertEqual(self.view.erase_regions.call_count, 2)
		self.assertEqual(self.search._searches[7], {'query': 'error', 'index': 3, 'shown': False})


if __name__ == '__main__':
	unittest.main()
