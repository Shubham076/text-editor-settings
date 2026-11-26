from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


def bindings():
	text = (ROOT / 'contributes/Commands/Default.sublime-keymap').read_text()
	text = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
	text = re.sub(r',(\s*[\]}])', r'\1', text)
	return json.loads(text)


class KeymapTests(unittest.TestCase):
	def test_enter_in_a_panel_is_not_taken_from_a_list_that_is_open_over_it(self):
		'''The configurations and the settings are lists over the panel, and enter chooses their row'''
		enters = [binding for binding in bindings() if binding['keys'] == ['enter']]
		self.assertEqual(len(enters), 4)
		for binding in enters:
			self.assertIn({'key': 'overlay_visible', 'operator': 'equal', 'operand': False}, binding['context'])


if __name__ == '__main__':
	unittest.main()
