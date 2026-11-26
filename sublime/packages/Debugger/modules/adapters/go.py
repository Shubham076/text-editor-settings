from __future__ import annotations
from . import util
from .. import dap
from .. import core
from ..settings import Setting
from ..core.util import package_storage_path
from .. import go_build

import shutil
import subprocess
import time
import os


@core.run_in_executor
def run_build(command: list[str], cwd: str | None, env: dict[str, str]) -> tuple[int, str]:
	'''Runs the build off the main thread; (exit status, everything it printed)'''
	startupinfo = None
	if os.name == 'nt':
		startupinfo = subprocess.STARTUPINFO()  # type: ignore
		startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore
	process = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, startupinfo=startupinfo)
	return process.returncode, process.stdout.decode('utf-8', 'replace')


class Go(dap.Adapter):
	type = 'go'
	docs = 'https://github.com/golang/vscode-go/blob/master/docs/debugging.md#launch-configurations'

	installer = util.GitInstaller(type='go', repo='golang/vscode-go')

	go_dlv = Setting['str|None'](key='adapters.go_dlv', default=None, description='Path of `dlv`; without it the one in your path is used.')
	go_build_cache = Setting[bool](
		key='adapters.go_build_cache',
		default=True,
		description='''
		Go: the debugger builds the program itself and keeps the binary between starts, so a start
		with nothing changed builds nothing and one after a change builds only what changed. Off,
		delve builds it, into a binary it deletes afterwards, and links it again on every start.
		A configuration can say for itself with `"go_build_cache": false`.
		''',
	)
	go_build_cache_hours = Setting[float](
		key='adapters.go_build_cache_hours',
		default=24,
		description='''
		Go: a kept binary that was not started for this many hours is removed, as a configuration
		is started. It is built again the next time it is wanted. 0 keeps them all.
		''',
	)

	async def start(self, console: dap.Console, configuration: dap.ConfigurationExpanded):
		if configuration.get('port'):
			host = configuration.get('host', 'localhost')
			port = configuration['port']
			command = None
			console.info(f'Start remote debugging, connecting {host}:{port}')
		else:
			host = 'localhost'
			port = util.get_open_port()
			dlv = self.go_dlv or shutil.which('dlv')
			if not dlv:
				raise dap.Error('`dlv` not found see https://github.com/go-delve/delve for setting up delve')

			command = [dlv, 'dap', '--listen', f'{host}:{port}']

		cwd = configuration.get('cwd')

		env = {}
		env.update(os.environ)
		env.update(configuration.get('env') or {})

		if command:
			await self.build(console, configuration, env)

		def stdout(data: str):
			# ignore this none program output line
			if data.startswith('DAP server listening at:'):
				return

			console.log('stdout', data)

		def stderr(data: str):
			console.log('stderr', data)

		return dap.SocketTransport(
			host=host,
			port=port,
			command=command,
			cwd=cwd,
			env=env,
			stderr=stderr,
			stdout=stdout,
		)

	async def build(self, console: dap.Console, configuration: dap.ConfigurationExpanded, env: dict[str, str]):
		'''Builds the program into a binary that is kept, and has delve run that (see `go_build`)

		With the flags delve builds with, so what is debugged is what delve would have built. The
		configuration is changed to one that runs the binary; started again it is first put back
		as it was written, and built from that.
		'''
		go_build.restore(configuration)
		enabled = configuration.get('go_build_cache')
		if not (self.go_build_cache if enabled is None else enabled):
			return

		go = shutil.which('go', path=env.get('PATH'))
		if not go:
			# delve says so better than a guess here would
			return

		cache = os.path.join(package_storage_path(ensure_exists=True), 'go-build')
		os.makedirs(cache, exist_ok=True)
		plan = go_build.plan(configuration, cache, go)
		if not plan:
			return

		# before the build, so that a binary that is too old is the one built again now
		removed = go_build.clean(cache, self.go_build_cache_hours)
		if removed:
			core.info('go build cache: removed {} old binaries'.format(len(removed)))

		existed = os.path.exists(plan.output)
		# a mark in front of the line spins while go is at it, and says how it ended
		done = console.progress('Building {}'.format(plan.label))
		started = time.time()
		try:
			status, output = await run_build(plan.command, plan.cwd, env)
		except BaseException as error:
			done(False)
			if isinstance(error, OSError):
				raise dap.Error('Unable to run `{}`: {}'.format(go, error))
			raise
		done(status == 0 and os.path.exists(plan.output))
		if status != 0 or not os.path.exists(plan.output):
			# what the compiler said is the error, the line after it only says that it stopped here
			console.error(output.strip() or '`{}` exited with status {}'.format(' '.join(plan.command), status))
			raise dap.Error('the build failed')

		if output.strip():
			console.info(output.strip())
		core.info('go build: {:.2f}s, {}: {}'.format(time.time() - started, 'binary was there' if existed else 'new binary', ' '.join(plan.command)))
		go_build.apply(configuration, plan)
