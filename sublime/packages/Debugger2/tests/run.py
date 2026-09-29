#!/usr/bin/env python3
'''Run the variable formatting tests, or regenerate their expected labels.

	python3 tests/run.py             # run them
	python3 tests/run.py --update    # rewrite fixtures/expected.json, then run them

`--update` is for when a change is deliberate: regenerate, read the diff to see exactly
which adapter values moved and how, and commit it with the change.
'''

from __future__ import annotations

import json
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent


def update_expected() -> None:
	sys.path.insert(0, str(TESTS))
	import test_variable_format as t

	path = t.FIXTURES / 'expected.json'
	before = json.loads(path.read_text()) if path.exists() else {}
	after = t.expected_labels()
	path.write_text(json.dumps(after, indent=1, sort_keys=True, ensure_ascii=False) + '\n')

	changed = 0
	for fixture in sorted(set(before) | set(after)):
		old, new = before.get(fixture, {}), after.get(fixture, {})
		for value in sorted(set(old) | set(new)):
			if old.get(value) != new.get(value):
				changed += 1
				print(f'  {fixture}\n    value {value[:88]!r}\n      was {old.get(value)!r}\n      now {new.get(value)!r}')

	total = sum(len(v) for v in after.values())
	print(f'\nwrote {path.relative_to(TESTS.parent)}: {total} labels, {changed} changed')


def main() -> int:
	if '--update' in sys.argv:
		update_expected()
		sys.argv.remove('--update')

	sys.path.insert(0, str(TESTS))
	suite = unittest.defaultTestLoader.discover(str(TESTS), pattern='test_*.py')
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
	raise SystemExit(main())
