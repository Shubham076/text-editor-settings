from __future__ import annotations
from typing import Iterable

import os
import signal
import subprocess
import sys
import tempfile
import time

from . import core


'''Ending what the debugger started when Sublime quits

Quitting Sublime does not unload plugins: the plugin host just goes away. An adapter loses its
pipes and exits, and the program it was debugging, a child of the adapter, is handed to init and
runs on with nobody attached and its port still taken. The same goes for a program started in an
integrated terminal, a child of Terminus.

`on_exit` is the one hook Sublime gives for this. It runs after the api has shut down, so nothing
here may touch `sublime`: no stop request can be sent to an adapter and no window asked anything.
What is left is the process table. Every process the debugger started is a root, the adapters and
the terminals, and everything beneath a root is ended with it: asked first (SIGTERM, so a server
can close its sockets), then killed if it has not gone within `GRACE` seconds. Quitting is already
slow enough, so the wait is short.
'''

GRACE = 1.0
POLL = 0.05
# how long after the request the detached backstop kills what is left, in seconds
BACKSTOP = 3
# what was ended and why, kept small: the one place to look when a process outlives Sublime, since
# by then there is no console to have printed to
LOG = os.path.join(tempfile.gettempdir(), 'sublime-debugger-processes.log')
LOG_LIMIT = 64 * 1024


def log(message: str) -> None:
	try:
		if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_LIMIT:
			os.remove(LOG)
		with open(LOG, 'a') as file:
			file.write('{} [{}] {}\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'), os.getpid(), message))
	except OSError:
		pass


def backstop(pids: list[int]) -> None:
	'''Kills `pids` a few seconds from now from a process of its own

	The wait for a program to stop by itself happens inside the plugin host, and a quitting
	Sublime does not wait for the plugin host. Without this, a program that takes its time over
	SIGTERM (a server draining connections) would outlive the host that was about to kill it.
	'''
	if not pids:
		return
	script = 'sleep {}; kill -9 {} 2>/dev/null'.format(BACKSTOP, ' '.join(str(pid) for pid in pids))
	subprocess.Popen(['/bin/sh', '-c', script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
		start_new_session=True, close_fds=True)


def process_children() -> dict[int, list[int]]:
	'''Every running process by its parent, read once before anything is ended

	Read first because ending a parent re-parents its children to init, and from then on nothing
	ties them to the debugger.
	'''
	output = subprocess.check_output(['ps', '-axo', 'pid=,ppid='], timeout=5).decode('utf-8', 'replace')
	children: dict[int, list[int]] = {}
	for line in output.splitlines():
		parts = line.split()
		if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
			children.setdefault(int(parts[1]), []).append(int(parts[0]))
	return children


def process_trees(roots: Iterable[int], children: dict[int, list[int]]) -> list[int]:
	'''The roots and everything beneath them, each once, the deepest first'''
	ordered: list[int] = []
	seen: set[int] = set()

	def visit(pid: int) -> None:
		if pid in seen:
			return
		seen.add(pid)
		for child in children.get(pid, ()):
			visit(child)
		ordered.append(pid)

	for root in roots:
		visit(root)
	return ordered


def is_running(pid: int) -> bool:
	try:
		# a child of ours that has exited stays in the table until it is waited for
		if os.waitpid(pid, os.WNOHANG)[0] == pid:
			return False
	except OSError:
		pass
	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except OSError:
		pass
	return True


def end_process_trees(roots: Iterable[int], grace: float = GRACE, reason: str = '') -> list[int]:
	'''Ends the roots and everything they started; returns the processes it went after'''
	roots = [pid for pid in roots if pid and pid != os.getpid()]
	if not roots:
		log('{}: nothing running'.format(reason or 'end'))
		return []

	if os.name == 'nt':
		for pid in roots:
			subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		return roots

	pids = process_trees(roots, process_children())
	log('{}: roots {} tree {}'.format(reason or 'end', roots, pids))
	backstop(pids)
	for pid in pids:
		try:
			os.kill(pid, signal.SIGTERM)
		except OSError:
			pass

	deadline = time.monotonic() + grace
	remaining = pids
	while remaining and time.monotonic() < deadline:
		time.sleep(POLL)
		remaining = [pid for pid in remaining if is_running(pid)]

	for pid in remaining:
		try:
			os.kill(pid, signal.SIGKILL)
		except OSError:
			pass
	log('{}: killed after {}s {}'.format(reason or 'end', grace, remaining) if remaining else '{}: all stopped when asked'.format(reason or 'end'))
	return pids


def adapter_pids() -> list[int]:
	from .dap.transports import Process

	return [process.pid for process in list(Process.processes) if process.poll() is None]


def terminal_pids() -> list[int]:
	'''The shells of the terminals the debugger opened: tasks and integrated terminals

	Terminus keeps its terminals by view; the ones that are the debugger's are found by the tag
	the debugger gave them, the name of their panel. Terminus is another package and need not be
	there, so anything unexpected about it means no terminals rather than no cleanup.
	'''
	from .debugger import Debugger
	from .output_panel_terminus import TerminusOutputPanel

	pids: list[int] = []
	try:
		tags = {panel.output_panel_name for debugger in Debugger.debuggers() for panel in debugger.output_panels
			if isinstance(panel, TerminusOutputPanel)}
		module = next((module for name, module in list(sys.modules.items()) if name.endswith('terminus.terminal') and hasattr(module, 'Terminal')), None)
		if not module or not tags:
			return pids
		terminals = list(module.Terminal._terminals.values()) + list(module.Terminal._detached_terminals)
		for terminal in terminals:
			pid = getattr(getattr(terminal, 'process', None), 'pid', None)
			if getattr(terminal, 'tag', None) in tags and isinstance(pid, int):
				pids.append(pid)
	except Exception:
		core.exception()
	return pids


def end_everything() -> list[int]:
	'''Sublime is quitting: end every adapter, terminal and program the debugger started'''
	try:
		return end_process_trees([*adapter_pids(), *terminal_pids()], reason='sublime exit')
	except Exception:
		core.exception()
		return []
