'''The build of a Go program for the debugger, kept between starts

Delve builds the program itself when a configuration is in `debug` or `test` mode: `go build` with
the optimisations off, into a binary under a name it makes up for the occasion and deletes when
the session ends. Go's build cache keeps the compiled packages, but a binary that is not there
has to be linked again, on every start, whether anything changed or not. For a large program
that is most of the wait.

So the build is done here instead, the way delve does it and with the same flags, into a file
that stays where it is: one for each configuration, in a folder of the package's own. Go then
finds the binary of the last start, sees that nothing it was made of has changed, and does
nothing. Delve is handed the binary to run (`exec` mode) in place of the source to build.

Nothing here knows of Sublime: what is to be run and what the configuration turns into is worked
out as plain values (`plan`), which the Go adapter acts on.
'''

from __future__ import annotations

import hashlib
import os
import re
import shlex
import time
from typing import Any, NamedTuple

# what delve builds with: no optimisation and no inlining, so every line can be stopped on and
# every variable read
DEBUG_FLAGS = ['-gcflags', 'all=-N -l']

# the modes delve builds in; every other one is given a binary or a process and is left alone
BUILT_MODES = ('debug', 'test')

# what the configuration was before it was turned into one that runs a binary, kept on it under
# this key: a configuration that is started again is the same object, and has to be built again
# from what it was, not run again as the binary it became
ORIGINAL = '__go_build'
CHANGED_KEYS = ('mode', 'program', 'cwd', 'buildFlags', 'output')

# the environment that changes what is built, and so which binary it is
BUILD_ENVIRONMENT = ('GOOS', 'GOARCH', 'GOFLAGS', 'CGO_ENABLED', 'GOEXPERIMENT', 'GOTOOLCHAIN', 'CC', 'CXX', 'CGO_CFLAGS', 'CGO_LDFLAGS')


class Plan(NamedTuple):
	command: list[str]
	# where `go` is run, `None` for where the debugger itself runs, as delve would have been
	cwd: 'str | None'
	output: str
	# the keys of the configuration to set, `None` for one to take off
	changes: 'dict[str, Any]'
	# what is being built, as the configuration names it
	label: str


def restore(configuration: 'dict[str, Any]') -> None:
	'''Puts a configuration that was turned into one that runs a binary back as it was written'''
	original = configuration.pop(ORIGINAL, None)
	if not isinstance(original, dict):
		return
	for key in CHANGED_KEYS:
		if key in original:
			configuration[key] = original[key]
		else:
			configuration.pop(key, None)


def apply(configuration: 'dict[str, Any]', plan: Plan) -> None:
	'''Turns the configuration into one that runs the binary of `plan`, remembering what it was'''
	configuration[ORIGINAL] = {key: configuration[key] for key in CHANGED_KEYS if key in configuration}
	for key, value in plan.changes.items():
		if value is None:
			configuration.pop(key, None)
		else:
			configuration[key] = value


def build_flags(value: Any) -> 'list[str]':
	'''`buildFlags` as arguments: delve takes a list, or one string it splits the way a shell would'''
	if isinstance(value, (list, tuple)):
		return [str(item) for item in value]
	if isinstance(value, str) and value.strip():
		return shlex.split(value)
	return []


def plan(configuration: 'dict[str, Any]', cache: str, go: str = 'go', windows: bool = os.name == 'nt') -> 'Plan | None':
	'''What to run to build the program of a configuration, and what the configuration becomes

	`None` for a configuration delve does not build for: one that attaches, runs a binary it was
	given, or reaches a delve that is already running somewhere (`port`), which builds where it is.
	'''
	if configuration.get('request', 'launch') != 'launch' or configuration.get('port'):
		return None
	mode = configuration.get('mode') or 'debug'
	program = configuration.get('program')
	if mode not in BUILT_MODES or not isinstance(program, str) or not program:
		return None

	flags = build_flags(configuration.get('buildFlags'))
	cwd = configuration.get('cwd') or None
	env = configuration.get('env') or {}

	# Delve runs `go` where it was started itself, which is the `cwd` of the configuration. Without
	# one it is wherever Sublime happens to be, which is no module; the folder of the program is,
	# when the program says where that is
	build_cwd = cwd
	if not build_cwd and os.path.isabs(program):
		build_cwd = os.path.dirname(program) if program.endswith('.go') else program

	# One binary for each thing that can be built differently. The name is for whoever looks into
	# the folder, the digest is what tells two of them apart
	identity = [mode, program, build_cwd or '', go, *flags, *(f'{name}={env.get(name)}' for name in BUILD_ENVIRONMENT if env.get(name) is not None)]
	digest = hashlib.sha1('\0'.join(identity).encode()).hexdigest()[:12]
	# The binary of a test is the binary of its package, whichever test of it is run: named after
	# the package, the tests of one share it. Named after the test there was one for each test
	package = os.path.basename((os.path.dirname(program) if program.endswith('.go') else program).rstrip('/\\'))
	label = package if mode == 'test' else configuration.get('name') or package
	name = re.sub(r'[^\w.-]+', '-', str(label or 'program')).strip('-.') or 'program'
	output = os.path.join(cache, f'{name[:40]}-{digest}' + ('.test' if mode == 'test' else '') + ('.exe' if windows else ''))

	# the arguments delve gives `go`, in its order: the debug flags, then the configuration's own
	# (a `-gcflags` among them is the later one, and wins, as it does with delve)
	command = [go, 'test', '-c'] if mode == 'test' else [go, 'build']
	command += ['-o', output, *DEBUG_FLAGS, *flags, program]

	changes: dict[str, Any] = {'mode': 'exec', 'program': output, 'buildFlags': None, 'output': None}
	if mode == 'test' and not cwd:
		# go runs a test in the folder of its package, and so does delve when it is not told where
		directory = os.path.dirname(program) if program.endswith('.go') else program
		changes['cwd'] = directory if os.path.isabs(directory) or not build_cwd else os.path.normpath(os.path.join(build_cwd, directory))
	return Plan(command, build_cwd, output, changes, program)


def clean(cache: str, max_age_hours: float, now: 'float | None' = None) -> 'list[str]':
	'''Removes the binaries that were not built for longer than `max_age_hours`; returns their paths

	`go build` marks a binary it found up to date as built just now, so the age of one is the time
	since its configuration was last started, not since it was first made. One that is removed is
	built again, linked from the packages go still has compiled, the next time it is wanted. A
	program that is running from its binary keeps running: the file is gone from the folder, not
	from under the process.
	'''
	if max_age_hours is None or max_age_hours <= 0:
		return []
	now = time.time() if now is None else now
	removed: list[str] = []
	try:
		names = os.listdir(cache)
	except OSError:
		return removed
	for name in names:
		path = os.path.join(cache, name)
		try:
			if os.path.isfile(path) and now - os.path.getmtime(path) > max_age_hours * 3600:
				os.remove(path)
				removed.append(path)
		except OSError:
			# in use on Windows, or gone already: it is tried again at the next start
			continue
	return removed
