'''A DAP client just large enough to record what an adapter reports for a variable.

The fixtures under `tests/fixtures/` were recorded with this. It speaks the protocol over
stdio or a socket, launches a program, stops on a line, and walks `variables` from the
top frame.

`supportsVariableType` has to be set in `initialize` or an adapter is entitled to leave
`type` out of its response, and the label falls back to the whole value.
'''

from __future__ import annotations

import json
import socket
import subprocess
import time


class DapClient:
	def __init__(self, command: list[str], port: int | None = None, env: dict | None = None):
		self._seq = 0
		self._buffer = b''
		self._socket = None
		self._process = subprocess.Popen(
			command,
			stdin=None if port else subprocess.PIPE,
			stdout=None if port else subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			env=env,
		)

		if port:
			time.sleep(1.5)
			self._socket = socket.create_connection(('127.0.0.1', port), timeout=20)

	def send(self, command: str, **arguments):
		self._seq += 1
		body = json.dumps({'seq': self._seq, 'type': 'request', 'command': command, 'arguments': arguments}).encode()
		message = b'Content-Length: %d\r\n\r\n' % len(body) + body

		if self._socket:
			self._socket.sendall(message)
		else:
			assert self._process.stdin
			self._process.stdin.write(message)
			self._process.stdin.flush()

	def _read(self, count: int) -> bytes:
		if self._socket:
			while len(self._buffer) < count:
				chunk = self._socket.recv(65536)
				if not chunk:
					raise EOFError
				self._buffer += chunk
			out, self._buffer = self._buffer[:count], self._buffer[count:]
			return out

		assert self._process.stdout
		return self._process.stdout.read(count)

	def receive(self) -> dict:
		header = b''
		while b'\r\n\r\n' not in header:
			byte = self._read(1)
			if not byte:
				raise EOFError
			header += byte

		length = int([line.split(b':')[1] for line in header.split(b'\r\n') if line.lower().startswith(b'content-length')][0])
		return json.loads(self._read(length))

	def wait_for(self, predicate, limit: int = 600) -> dict:
		for _ in range(limit):
			message = self.receive()
			if predicate(message):
				return message
		raise TimeoutError('no matching message')

	def response(self, command: str) -> dict:
		return self.wait_for(lambda m: m.get('command') == command and m.get('type') == 'response')

	def stop_at(self, adapter_id: str, source: str, line: int, **launch):
		self.send('initialize', adapterID=adapter_id, supportsVariableType=True, supportsMemoryReferences=True)
		self.response('initialize')
		self.send('launch', request='launch', **launch)
		self.send('setBreakpoints', source={'path': source}, breakpoints=[{'line': line}])
		self.response('setBreakpoints')
		self.send('configurationDone')

		stopped = self.wait_for(lambda m: m.get('event') == 'stopped')
		self.send('stackTrace', threadId=stopped['body']['threadId'])
		frames = self.response('stackTrace')
		self.send('scopes', frameId=frames['body']['stackFrames'][0]['id'])
		scopes = self.response('scopes')
		return [s for s in scopes['body']['scopes'] if 'ocal' in s['name']][0]['variablesReference']

	def walk(self, reference: int, depth: int = 0, path: str = '', max_depth: int = 3) -> list[dict]:
		'''Every variable under `reference`, as the fixtures store them'''
		if depth > max_depth:
			return []

		self.send('variables', variablesReference=reference)
		out = []

		for variable in self.response('variables')['body']['variables']:
			child = variable.get('variablesReference', 0)
			name = f'{path}.{variable["name"]}' if path else variable['name']
			out.append({
				'name': name,
				'value': variable['value'],
				'type': variable.get('type'),
				'hasChildren': child > 0,
			})
			if child:
				out += self.walk(child, depth + 1, name, max_depth)

		return out

	def close(self):
		if self._socket:
			self._socket.close()
		self._process.kill()
