from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent


class InputListTests(unittest.TestCase):
	'''The lists of the debugger (the configurations, the settings): a row is chosen by a click or by enter'''

	def setUp(self):
		package = types.ModuleType('_ilt')
		package.__path__ = []
		modules = types.ModuleType('_ilt.modules')
		modules.__path__ = []
		ui = types.ModuleType('_ilt.modules.ui')
		ui.__path__ = []
		core = types.SimpleNamespace(run=lambda function: function, Future=Mock, CancelledError=Exception,
			platform=types.SimpleNamespace(unicode_checked_sigil='x', unicode_unchecked_sigil='o'))
		modules.core = core
		sublime = types.ModuleType('sublime')
		sublime.KIND_AMBIGUOUS = (0, '', '')
		sublime.KIND_ID_AMBIGUOUS = 0
		sublime_plugin = types.ModuleType('sublime_plugin')
		sublime_plugin.ListInputHandler = object
		sublime_plugin.TextInputHandler = object
		patcher = patch.dict(sys.modules, {
			'_ilt': package, '_ilt.modules': modules, '_ilt.modules.ui': ui, '_ilt.modules.core': core,
			'sublime': sublime, 'sublime_plugin': sublime_plugin,
		})
		patcher.start()
		self.addCleanup(patcher.stop)
		spec = importlib.util.spec_from_file_location('_ilt.modules.ui.input', ROOT / 'modules/ui/input.py')
		self.module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = self.module
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		spec.loader.exec_module(self.module)

		self.run, self.run_alt = Mock(), Mock()
		self.list = self.module.InputList('Run configuration')[[self.module.InputListItem(self.run, 'api', run_alt=self.run_alt)]]

	def test_enter_chooses_the_row_and_it_comes_with_no_event(self):
		self.list.confirm(0, None)
		self.run.assert_called_once()
		self.run_alt.assert_not_called()

	def test_a_click_chooses_the_row(self):
		self.list.confirm(0, {'modifier_keys': {}})
		self.run.assert_called_once()

	def test_a_click_with_alt_or_super_is_the_other_action_of_the_row(self):
		self.list.confirm(0, {'modifier_keys': {'alt': True}})
		self.run_alt.assert_called_once()
		self.run.assert_not_called()


if __name__ == '__main__':
	unittest.main()
