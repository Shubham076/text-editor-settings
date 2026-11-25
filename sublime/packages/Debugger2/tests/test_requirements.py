from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_requirements_test', ROOT / 'modules' / 'requirements.py')
requirements = importlib.util.module_from_spec(spec)
spec.loader.exec_module(requirements)


class TerminusRequirementTests(unittest.TestCase):
	def test_there_to_be_used(self):
		self.assertIsNone(requirements.state(['Debugger2', 'Terminus'], ['Vintage']))

	def test_not_installed(self):
		self.assertEqual(requirements.state(['Debugger2'], []), requirements.MISSING)
		self.assertIn('not installed', requirements.message(requirements.MISSING))

	def test_installed_and_disabled_is_said_differently(self):
		self.assertEqual(requirements.state(['Terminus'], ['Terminus']), requirements.IGNORED)
		self.assertIn('disabled', requirements.message(requirements.IGNORED))
		self.assertNotIn('Install it now', requirements.message(requirements.IGNORED))
