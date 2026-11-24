from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('_filled_icons_test', ROOT / 'modules' / 'ui' / 'icons.py')
icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icons)


def covered(name, x, y):
	return icons._icon_coverage(icons.ICONS[name], x, y, 0.5)


class FilledIconTests(unittest.TestCase):
	def test_the_icons_of_a_file_are_filled_and_the_ones_of_the_bar_are_outlines(self):
		# the middle of the triangle and of the square
		self.assertEqual(covered('run-filled', 11, 12), 1.0)
		self.assertEqual(covered('stop-filled', 12, 12), 1.0)
		self.assertEqual(covered('run', 11, 12), 0.0)
		self.assertEqual(covered('stop', 12, 12), 0.0)

	def test_a_filled_icon_has_the_outline_of_the_one_it_fills(self):
		for filled, outline in (('run-filled', 'run'), ('stop-filled', 'stop')):
			for x in range(0, 25, 2):
				for y in range(0, 25, 2):
					# wherever the outline draws, so does the filled one, and neither draws outside it
					if covered(outline, x, y) == 1.0:
						self.assertEqual(covered(filled, x, y), 1.0, (filled, x, y))
			for point in ((1, 1), (23, 1), (1, 23), (23, 23), (22, 2)):
				self.assertEqual(covered(filled, *point), 0.0, (filled, point))

	def test_a_filled_icon_is_a_png(self):
		self.assertTrue(icons.icon_data_uri('run-filled', '#5c6a72', 48).startswith('data:image/png;base64,'))


if __name__ == '__main__':
	unittest.main()
