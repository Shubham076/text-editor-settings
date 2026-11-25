'''What the package cannot do without: Terminus

Every terminal of the debugger is one of its: the tab of a task, of a task that says when it is
ready (`task_runtime_ready`), and of a program started with `"console": "external"`. Package
Control has no way for one package to ask for another, so it is looked for when the package is
loaded and asked for there, once, rather than failing on the first task that is run.
'''

from __future__ import annotations

from typing import Any

TERMINUS = 'Terminus'

MISSING = 'missing'
IGNORED = 'ignored'


def state(packages: list[str], ignored: list[str]) -> str | None:
	'''`None` when Terminus is there to be used, otherwise what is in the way of it

	`packages` are the packages that are installed, by name, and `ignored` the `ignored_packages`
	of the preferences: one that is installed and ignored is as good as not there, and is fixed
	differently.
	'''
	if TERMINUS not in packages:
		return MISSING
	if TERMINUS in ignored:
		return IGNORED
	return None


def message(found: str) -> str:
	if found == IGNORED:
		return (
			'Debugger needs the Terminus package, which is installed but disabled.\n\n'
			'Its tasks and terminals run in it. Enable it with "Package Control: Enable Package", '
			'or take "Terminus" out of "ignored_packages" in your preferences.'
		)
	return (
		'Debugger needs the Terminus package, which is not installed.\n\n'
		'Its tasks and terminals run in it. Install it now with Package Control?'
	)


def installed_packages() -> list[str]:
	import os
	import sublime

	names = set()

	# unpacked in Packages (a symlink to a checkout included), or as a .sublime-package
	try:
		names.update(name for name in os.listdir(sublime.packages_path()) if os.path.isdir(os.path.join(sublime.packages_path(), name)))
	except OSError:
		...
	try:
		names.update(name[: -len('.sublime-package')] for name in os.listdir(sublime.installed_packages_path()) if name.endswith('.sublime-package'))
	except OSError:
		...

	return sorted(names)


def check(log: Any = None) -> str | None:
	'''Looks for Terminus and asks for it when it is not there, returns what was found (`state`)'''
	import sublime

	ignored = sublime.load_settings('Preferences.sublime-settings').get('ignored_packages') or []
	found = state(installed_packages(), list(ignored))
	if not found:
		return None

	if log:
		log(f'Terminus is {found}: tasks and terminals of the debugger will not run without it')

	if found == IGNORED:
		sublime.message_dialog(message(found))
	elif sublime.ok_cancel_dialog(message(found), 'Install Terminus'):
		sublime.active_window().run_command('advanced_install_package', {'packages': TERMINUS})

	return found
