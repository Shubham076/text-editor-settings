from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock
import zipfile

from test_live_ui import ROOT, load_module


class InstallerBase:
	def __init__(self, type, repo):
		self.type, self.repo = type, repo

	def install_path(self):
		return str(self.path)


def package(name):
	module = types.ModuleType(name)
	module.__path__ = []
	return module


class Configuration(dict):
	"""`dap.ConfigurationExpanded` without sublime: a dict with `request` and awaitable variables"""
	request = 'launch'

	async def folder(self):
		return '/project'

	@property
	def variables(self):
		return {'folder': self.folder()}


class PythonAdapterTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.path = Path(self.temporary.name)
		self.transport = Mock(side_effect=lambda command: command)
		self.modules = {
			'_python_installer_test': package('_python_installer_test'),
			'_python_installer_test.modules': package('_python_installer_test.modules'),
			'_python_installer_test.modules.adapters': package('_python_installer_test.modules.adapters'),
			'_python_installer_test.modules.adapters.util': types.SimpleNamespace(OpenVsxInstaller=InstallerBase),
			'_python_installer_test.modules.dap': types.SimpleNamespace(Adapter=type('Adapter', (), {}), Error=RuntimeError, StdioTransport=self.transport),
			'_python_installer_test.modules.core': types.SimpleNamespace(),
			'sublime': types.SimpleNamespace(),
		}
		self.module = load_module('_python_installer_test.modules.adapters.python', ROOT / 'modules/adapters/python.py', self.modules)
		self.adapter = self.module.Python()
		self.adapter.installer.path = self.path
		self.console = Mock()

	def start(self):
		return asyncio.run(self.adapter.start(self.console, Configuration(python='/usr/bin/python3')))

	def test_protected_members_are_grouped_unless_the_configuration_says_otherwise(self):
		presentation = self.module.variable_presentation
		self.assertEqual(presentation(None), {'protected': 'group'})
		self.assertEqual(presentation({'special': 'hide'}), {'special': 'hide', 'protected': 'group'})
		self.assertEqual(presentation({'protected': 'inline'}), {'protected': 'inline'})
		self.assertEqual(presentation({'all': 'inline'}), {'all': 'inline'})

	def test_debugpy_comes_from_the_ms_python_extension_on_openvsx(self):
		self.assertIsInstance(self.adapter.installer, InstallerBase)
		self.assertEqual((self.adapter.installer.type, self.adapter.installer.repo), ('debugpy', 'ms-python/debugpy'))

	def test_openvsx_install_layout_is_used_when_present(self):
		(self.path / 'bundled/libs/debugpy').mkdir(parents=True)
		self.assertEqual(self.start(), ['/usr/bin/python3', str(self.path / 'bundled/libs/debugpy')])

	def test_legacy_install_layout_still_starts(self):
		(self.path / 'debugpy/debugpy/adapter').mkdir(parents=True)
		self.assertEqual(self.start(), ['/usr/bin/python3', str(self.path / 'debugpy/debugpy/adapter')])

	def test_openvsx_layout_wins_over_legacy_layout(self):
		(self.path / 'bundled/libs/debugpy').mkdir(parents=True)
		(self.path / 'debugpy/debugpy/adapter').mkdir(parents=True)
		self.assertEqual(self.start()[1], str(self.path / 'bundled/libs/debugpy'))

	def test_missing_adapter_names_the_paths_searched(self):
		with self.assertRaisesRegex(RuntimeError, 'bundled/libs/debugpy'):
			self.start()
		self.transport.assert_not_called()


class DownloadIntegrityTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.path = Path(self.temporary.name) / 'wheel'
		data = io.BytesIO()
		with zipfile.ZipFile(data, 'w') as archive:
			archive.writestr('debugpy/adapter/__main__.py', '')
			archive.writestr('debugpy-1.8.20.dist-info/METADATA', 'Name: debugpy')
		self.archive = data.getvalue()
		def executor(fn):
			async def call(*args, **kwargs):
				return fn(*args, **kwargs)
			return call
		dependencies = {
			'_download_test': package('_download_test'), '_download_test.modules': package('_download_test.modules'),
			'_download_test.modules.adapters': package('_download_test.modules.adapters'),
			'_download_test.modules.adapters.util': package('_download_test.modules.adapters.util'),
			'_download_test.modules.core': types.SimpleNamespace(run_in_executor=executor, ZipFile=zipfile.ZipFile,
				remove_file_or_dir=lambda path: Path(path).unlink()),
			'_download_test.modules.dap': types.SimpleNamespace(Error=RuntimeError, stdio=Mock()),
			'sublime': types.SimpleNamespace(status_message=Mock()),
		}
		self.module = load_module('_download_test.modules.adapters.util.request', ROOT / 'modules/adapters/util/request.py', dependencies)
		self.module.request = AsyncMock(return_value=types.SimpleNamespace(data=io.BytesIO(self.archive), headers={}))

	def test_valid_digest_allows_extraction(self):
		asyncio.run(self.module.download_and_extract_zip('https://example.invalid/wheel', str(self.path), sha256=hashlib.sha256(self.archive).hexdigest()))
		self.assertTrue((self.path / 'debugpy/adapter/__main__.py').is_file())

	def test_digest_mismatch_prevents_extraction(self):
		with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
			asyncio.run(self.module.download_and_extract_zip('https://example.invalid/wheel', str(self.path), sha256='0' * 64))
		self.assertFalse(self.path.exists())


if __name__ == '__main__':
	unittest.main()
