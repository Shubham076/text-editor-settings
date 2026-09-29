'''Completions for the debug console from the language server, through the LSP package.

An adapter's `completions` request knows the runtime, but most adapters answer with little more than
names. A language server knows the types, the members and their documentation, and shows them in the
editor already. LSP only attaches servers to file views though, never to a panel, so the console asks
the server itself: it opens a shadow copy of the file the debugger is paused in, with the typed
expression inserted on a new line at the paused frame, requests completion there, and closes the copy
again. Nothing touches the real file or the server's view of it.

Everything here that talks to LSP is imported lazily and guarded, so the console works exactly as before
when LSP is missing, ignored, or has no server for the file.
'''
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Callable

import os
import sublime

from . import core

if TYPE_CHECKING:
	from . import dap
	from .debugger import Debugger

# how long the console waits for the server before showing what it has from the adapter
TIMEOUT_SECONDS = 3.0

# what the shadow copy of a file is called: `main.py` -> `main.debug_console.py`, in the same directory
# so relative imports and the module search path resolve as they do for the real file
SHADOW_SUFFIX = '.debug_console'

# LSP CompletionItemKind -> Sublime kind. The numbers are from the LSP specification.
KINDS: dict[int, tuple[int, str, str]] = {}


def _kinds():
	if KINDS:
		return KINDS
	function, variable, type_, namespace, keyword, snippet, ambiguous = (
		sublime.KIND_FUNCTION, sublime.KIND_VARIABLE, sublime.KIND_TYPE, sublime.KIND_NAMESPACE,
		sublime.KIND_KEYWORD, sublime.KIND_SNIPPET, sublime.KIND_AMBIGUOUS)
	for number, kind in (
		(2, function), (3, function), (4, function),
		(5, variable), (6, variable), (10, variable), (12, variable), (21, variable),
		(7, type_), (8, type_), (13, type_), (20, type_), (22, type_), (25, type_),
		(9, namespace), (14, keyword), (15, snippet),
	):
		KINDS[number] = kind
	KINDS[0] = ambiguous
	return KINDS


def kind_for(lsp_kind: int | None):
	kinds = _kinds()
	return kinds.get(lsp_kind or 0, kinds[0])


def shadow_document(content: str, line: int, expression: str) -> tuple[str, int, int]:
	'''The file with `expression` on a new line after `line` (1-based, the paused frame's line)

	The new line takes the indentation of the frame's line, so it sits inside the same block and the
	server sees the same locals. Returns the text and the 0-based line and character of the caret at
	the end of the expression.
	'''
	lines = content.split('\n')
	index = min(max(line, 1), len(lines)) - 1
	current = lines[index]
	indent = current[:len(current) - len(current.lstrip())]
	lines.insert(index + 1, indent + expression)
	return '\n'.join(lines), index + 1, len(indent) + len(expression)


def shadow_path(path: str) -> str:
	stem, extension = os.path.splitext(path)
	return stem + SHADOW_SUFFIX + extension


def items_of(response: Any) -> list[dict]:
	'''The items of a completion response, which is a list, a CompletionList or null'''
	if isinstance(response, dict):
		response = response.get('items')
	return [item for item in (response or []) if isinstance(item, dict) and item.get('label')]


def insert_text_of(item: dict) -> str:
	'''What choosing an item types: its insertText, else its label. Snippet syntax is not expanded.'''
	text = item.get('insertText') or item.get('label') or ''
	if item.get('insertTextFormat') == 2:
		# a snippet: keep the part before the first placeholder so nothing odd is inserted
		text = text.split('$', 1)[0]
	return text


def request(debugger: Debugger, session: dap.Session, expression: str, on_result: Callable[[list[dict]], None]) -> bool:
	'''Asks the language server of the paused frame's file to complete `expression`

	`on_result` gets the raw LSP completion items on Sublime's main thread, or an empty list when the
	server does not answer in time. Returns False, without calling back, when there is nothing to ask:
	no paused frame with a file, no LSP, or no server for that file. The caller then shows the adapter's
	items on their own.
	'''
	frame = session.selected_frame
	path = frame.source.path if frame and frame.source else None
	if not path or not frame.line:
		return False

	try:
		from .hover import is_lsp_ignored
		if is_lsp_ignored():
			return False
		from LSP.plugin.core.registry import windows  # type: ignore
		from LSP.plugin.core.protocol import Notification, Request  # type: ignore
		from LSP.plugin.core.types import basescope2languageid  # type: ignore
		from LSP.plugin.core.url import filename_to_uri  # type: ignore
	except ImportError:
		return False
	except Exception:
		core.exception()
		return False

	view = debugger.window.find_open_file(path)
	manager = windows.lookup(debugger.window)
	if not view or not manager:
		return False

	syntax = view.syntax()
	language_id = basescope2languageid(syntax.scope) if syntax else None
	if not language_id:
		return False

	text, line, character = shadow_document(view.substr(sublime.Region(0, view.size())), frame.line, expression)
	uri = filename_to_uri(shadow_path(path))
	answered = [False]

	def finish(items: list[dict]):
		if answered[0]:
			return
		answered[0] = True
		sublime.set_timeout(lambda: on_result(items))

	def on_worker_thread():
		try:
			lsp_session = next((s for s in manager.get_sessions() if s.can_handle(view, 'file', 'completionProvider', True)), None)
			if not lsp_session:
				finish([])
				return

			def close():
				try:
					lsp_session.send_notification(Notification.didClose({'textDocument': {'uri': uri}}))
				except Exception:
					core.exception()

			def on_response(response: Any):
				close()
				finish(items_of(response))

			def on_error(error: Any):
				close()
				core.debug('language server completion failed:', error)
				finish([])

			lsp_session.send_notification(Notification.didOpen({'textDocument': {'uri': uri, 'languageId': language_id, 'version': 1, 'text': text}}))
			lsp_session.send_request_async(
				Request('textDocument/completion', {'textDocument': {'uri': uri}, 'position': {'line': line, 'character': character}, 'context': {'triggerKind': 1}}),
				on_response, on_error)
		except Exception:
			core.exception()
			finish([])

	# LSP's session methods run on Sublime's worker thread; the answer is handed back to the main thread
	sublime.set_timeout_async(on_worker_thread)
	sublime.set_timeout(lambda: finish([]), int(TIMEOUT_SECONDS * 1000))
	return True
