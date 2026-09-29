from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class LspCompletionsTests(unittest.TestCase):
	def setUp(self):
		package = types.ModuleType('_lsp_completions_test')
		package.__path__ = []
		core = types.ModuleType('_lsp_completions_test.core')
		core.exception = Mock()
		core.debug = Mock()
		self.sublime = types.ModuleType('sublime')
		for name in ('KIND_FUNCTION', 'KIND_VARIABLE', 'KIND_TYPE', 'KIND_NAMESPACE', 'KIND_KEYWORD', 'KIND_SNIPPET', 'KIND_AMBIGUOUS'):
			setattr(self.sublime, name, name)
		self.sublime.Region = lambda a, b=None: (a, b)
		self.sublime.set_timeout = lambda callback, delay=0: callback() if not delay else None
		self.sublime.set_timeout_async = lambda callback: callback()
		modules = {'_lsp_completions_test': package, '_lsp_completions_test.core': core, 'sublime': self.sublime}
		self.patch = patch.dict(sys.modules, modules)
		self.patch.start()
		self.addCleanup(self.patch.stop)
		spec = importlib.util.spec_from_file_location('_lsp_completions_test.lsp_completions', ROOT / 'modules' / 'lsp_completions.py')
		self.module = importlib.util.module_from_spec(spec)
		sys.modules[spec.name] = self.module
		self.addCleanup(lambda: sys.modules.pop(spec.name, None))
		spec.loader.exec_module(self.module)
		self.module.KINDS.clear()

	def test_shadow_document_puts_the_expression_in_the_frames_block(self):
		content = 'def run():\n    settings = load()\n    if settings:\n        print(settings)\n    return settings\n'
		text, line, character = self.module.shadow_document(content, 4, 'settings.')
		self.assertEqual(text.split('\n')[4], '        settings.')
		self.assertEqual((line, character), (4, 8 + len('settings.')))
		self.assertEqual(text.split('\n')[3], '        print(settings)')
		self.assertEqual(len(text.split('\n')), len(content.split('\n')) + 1)

	def test_shadow_document_clamps_lines_outside_the_file(self):
		text, line, _ = self.module.shadow_document('a = 1\nb = 2', 99, 'b.')
		self.assertEqual(text, 'a = 1\nb = 2\nb.')
		self.assertEqual(line, 2)
		text, line, _ = self.module.shadow_document('a = 1', 0, 'a.')
		self.assertEqual((text, line), ('a = 1\na.', 1))

	def test_shadow_path_keeps_directory_and_extension(self):
		self.assertEqual(self.module.shadow_path('/src/app/main.py'), '/src/app/main.debug_console.py')
		self.assertEqual(self.module.shadow_path('/src/server.go'), '/src/server.debug_console.go')

	def test_items_accept_list_completion_list_and_null(self):
		items = [{'label': 'timeout', 'kind': 5}, {'label': ''}, 'junk']
		self.assertEqual(self.module.items_of(items), [{'label': 'timeout', 'kind': 5}])
		self.assertEqual(self.module.items_of({'isIncomplete': False, 'items': items}), [{'label': 'timeout', 'kind': 5}])
		self.assertEqual(self.module.items_of(None), [])

	def test_insert_text_prefers_insert_text_and_trims_snippets(self):
		self.assertEqual(self.module.insert_text_of({'label': 'timeout'}), 'timeout')
		self.assertEqual(self.module.insert_text_of({'label': 'get', 'insertText': 'get()'}), 'get()')
		self.assertEqual(self.module.insert_text_of({'label': 'get', 'insertText': 'get(${1:key})', 'insertTextFormat': 2}), 'get(')

	def test_kinds_map_to_sublime_kinds(self):
		kind_for = self.module.kind_for
		self.assertEqual(kind_for(2), 'KIND_FUNCTION')
		self.assertEqual(kind_for(5), 'KIND_VARIABLE')
		self.assertEqual(kind_for(7), 'KIND_TYPE')
		self.assertEqual(kind_for(9), 'KIND_NAMESPACE')
		self.assertEqual(kind_for(14), 'KIND_KEYWORD')
		self.assertEqual(kind_for(15), 'KIND_SNIPPET')
		self.assertEqual(kind_for(None), 'KIND_AMBIGUOUS')
		self.assertEqual(kind_for(99), 'KIND_AMBIGUOUS')

	def test_request_declines_without_a_paused_frame_or_lsp(self):
		debugger = Mock()
		session = types.SimpleNamespace(selected_frame=None)
		self.assertFalse(self.module.request(debugger, session, 'x.', Mock()))
		frame = types.SimpleNamespace(source=types.SimpleNamespace(path='/src/main.py'), line=3)
		session = types.SimpleNamespace(selected_frame=frame)
		hover = types.ModuleType('_lsp_completions_test.hover')
		hover.is_lsp_ignored = lambda: False
		with patch.dict(sys.modules, {'_lsp_completions_test.hover': hover, 'LSP': None}):
			self.assertFalse(self.module.request(debugger, session, 'x.', Mock()))

	def test_request_opens_a_shadow_document_asks_and_closes_it(self):
		frame = types.SimpleNamespace(source=types.SimpleNamespace(path='/src/main.py'), line=2)
		session = types.SimpleNamespace(selected_frame=frame)
		view = Mock()
		view.substr.return_value = 'x = 1\ny = x\n'
		view.size.return_value = 12
		view.syntax.return_value = types.SimpleNamespace(scope='source.python')
		debugger = Mock()
		debugger.window.find_open_file.return_value = view
		lsp_session = Mock()
		lsp_session.can_handle.return_value = True
		def send_request_async(request, on_result, on_error=None):
			self.assertEqual(request.method, 'textDocument/completion')
			self.assertEqual(request.params['position'], {'line': 2, 'character': 2})
			on_result({'items': [{'label': 'real', 'kind': 6, 'detail': 'int'}]})
		lsp_session.send_request_async = send_request_async
		manager = types.SimpleNamespace(get_sessions=lambda: [lsp_session])
		notifications = []
		class Notification:
			def __init__(self, method, params):
				self.method, self.params = method, params
			@classmethod
			def didOpen(cls, params):
				notifications.append(('didOpen', params))
				return cls('textDocument/didOpen', params)
			@classmethod
			def didClose(cls, params):
				notifications.append(('didClose', params))
				return cls('textDocument/didClose', params)
		class Request:
			def __init__(self, method, params, view=None):
				self.method, self.params, self.view = method, params, view
		lsp = types.ModuleType('LSP')
		lsp.__path__ = []
		plugin = types.ModuleType('LSP.plugin')
		plugin.__path__ = []
		core_pkg = types.ModuleType('LSP.plugin.core')
		core_pkg.__path__ = []
		registry = types.ModuleType('LSP.plugin.core.registry')
		registry.windows = types.SimpleNamespace(lookup=lambda window: manager)
		protocol = types.ModuleType('LSP.plugin.core.protocol')
		protocol.Notification, protocol.Request = Notification, Request
		lsp_types = types.ModuleType('LSP.plugin.core.types')
		lsp_types.basescope2languageid = lambda scope: 'python'
		url = types.ModuleType('LSP.plugin.core.url')
		url.filename_to_uri = lambda path: 'file://' + path
		hover = types.ModuleType('_lsp_completions_test.hover')
		hover.is_lsp_ignored = lambda: False
		results = []
		with patch.dict(sys.modules, {'LSP': lsp, 'LSP.plugin': plugin, 'LSP.plugin.core': core_pkg, 'LSP.plugin.core.registry': registry,
			'LSP.plugin.core.protocol': protocol, 'LSP.plugin.core.types': lsp_types, 'LSP.plugin.core.url': url, '_lsp_completions_test.hover': hover}):
			self.assertTrue(self.module.request(debugger, session, 'y.', results.append))
		self.assertEqual(results, [[{'label': 'real', 'kind': 6, 'detail': 'int'}]])
		self.assertEqual([name for name, _ in notifications], ['didOpen', 'didClose'])
		opened = notifications[0][1]['textDocument']
		self.assertEqual(opened['uri'], 'file:///src/main.debug_console.py')
		self.assertEqual(opened['languageId'], 'python')
		self.assertEqual(opened['text'], 'x = 1\ny = x\ny.\n')
		self.assertEqual(notifications[1][1]['textDocument']['uri'], opened['uri'])
		# the real file is never touched
		view.replace.assert_not_called()
		lsp_session.can_handle.assert_called_once_with(view, 'file', 'completionProvider', True)


if __name__ == '__main__':
	unittest.main()
