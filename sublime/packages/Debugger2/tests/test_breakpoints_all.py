from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Breakpoint:
	def __init__(self, enabled=True):
		self.enabled = enabled


class Collection:
	def __init__(self, *breakpoints):
		self.breakpoints = list(breakpoints)
		self.updates = 0

	def __iter__(self):
		return iter(self.breakpoints)

	def updated(self):
		self.updates += 1

	def toggle_enabled(self, breakpoint):
		breakpoint.enabled = not breakpoint.enabled
		self.updates += 1


class SetAllEnabledTests(unittest.TestCase):
	def setUp(self):
		names = {
			'_bpa': [], '_bpa.modules': [], '_bpa.modules.ui': None, '_bpa.modules.core': None, '_bpa.modules.dap': [],
			'_bpa.modules.dap.error': ['Error'], '_bpa.modules.dap.session': ['Session'], '_bpa.modules.dap.api': None,
			'_bpa.modules.dap.breakpoint': ['Breakpoint'],
			'_bpa.modules.dap.breakpoint_data': ['DataBreakpoints', 'DataBreakpoint'],
			'_bpa.modules.dap.breakpoint_function': ['FunctionBreakpoints', 'FunctionBreakpoint'],
			'_bpa.modules.dap.breakpoint_source': ['SourceBreakpoints', 'SourceBreakpoint'],
			'_bpa.modules.dap.breakpoint_exception_filters': ['ExceptionBreakpointsFilters', 'ExceptionBreakpointsFilter'],
		}
		modules = {}
		for name, exports in names.items():
			module = modules[name] = types.ModuleType(name)
			if exports == []:
				module.__path__ = []
			for export in exports or ():
				setattr(module, export, type(export, (), {}))
		patcher = patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)

		spec = importlib.util.spec_from_file_location('_bpa.modules.dap.breakpoints', ROOT / 'modules' / 'dap' / 'breakpoints.py')
		module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = module
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		spec.loader.exec_module(module)

		self.breakpoints = object.__new__(module.Breakpoints)
		self.breakpoints.source = Collection(Breakpoint(True), Breakpoint(False), Breakpoint(True))
		self.breakpoints.function = Collection(Breakpoint(True))
		self.breakpoints.data = Collection(Breakpoint(False))
		self.breakpoints.filters = Collection(Breakpoint(True))

	def every(self):
		return [item.enabled for name in ('source', 'function', 'data') for item in getattr(self.breakpoints, name)]

	def test_all_off_and_back_on_and_none_is_lost(self):
		self.breakpoints.set_all_enabled(False)
		self.assertEqual(self.every(), [False] * 5)
		# only the ones that changed are sent again
		self.assertEqual((self.breakpoints.source.updates, self.breakpoints.function.updates, self.breakpoints.data.updates), (2, 1, 0))

		self.breakpoints.set_all_enabled(True)
		self.assertEqual(self.every(), [True] * 5)

	def test_exception_filters_are_left_as_they_are(self):
		self.breakpoints.set_all_enabled(False)
		self.assertEqual([item.enabled for item in self.breakpoints.filters], [True])


if __name__ == '__main__':
	unittest.main()
