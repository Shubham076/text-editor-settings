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

	def temporary_install_path(self):
		return str(self.path)


def package(name):
	module = types.ModuleType(name)
	module.__path__ = []
	return module


class PythonInstallerTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.path = Path(self.temporary.name)
		self.request = types.SimpleNamespace(json=AsyncMock(), download_and_extract_zip=AsyncMock(side_effect=self.extract))
		self.modules = {
			'_python_installer_test': package('_python_installer_test'),
			'_python_installer_test.modules': package('_python_installer_test.modules'),
			'_python_installer_test.modules.adapters': package('_python_installer_test.modules.adapters'),
			'_python_installer_test.modules.adapters.util': types.SimpleNamespace(GitSourceInstaller=InstallerBase, request=self.request),
			'_python_installer_test.modules.dap': types.SimpleNamespace(Adapter=type('Adapter', (), {}), Error=RuntimeError),
			'_python_installer_test.modules.core': types.SimpleNamespace(json_decode_file=lambda path: json.loads(Path(path).read_text())),
			'sublime': types.SimpleNamespace(),
		}
		self.module = load_module('_python_installer_test.modules.adapters.python', ROOT / 'modules/adapters/python.py', self.modules)
		self.installer = self.module.PythonInstaller(type='debugpy', repo='microsoft/vscode-python-debugger')
		self.installer.path = self.path
		self.log = Mock()

	async def extract(self, url, path, **kwargs):
		entry = Path(path) / 'debugpy/adapter/__main__.py'
		entry.parent.mkdir(parents=True)
		entry.write_text('')

	def metadata(self, **overrides):
		wheel = {'filename': 'debugpy-1.8.20-py2.py3-none-any.whl', 'packagetype': 'bdist_wheel',
			'url': 'https://files.pythonhosted.org/debugpy.whl', 'digests': {'sha256': 'a' * 64}, 'yanked': False}
		wheel.update(overrides)
		return {'info': {'version': '1.8.20'}, 'urls': [wheel]}

	def modern_release(self):
		(self.path / 'noxfile.py').write_text('import nox\nDEBUGPY_VERSION = "1.8.20"\nraise AssertionError("must not execute")\n')
		self.request.json.return_value = self.metadata()

	def test_protected_members_are_grouped_unless_the_configuration_says_otherwise(self):
		presentation = self.module.variable_presentation
		self.assertEqual(presentation(None), {'protected': 'group'})
		self.assertEqual(presentation({'special': 'hide'}), {'special': 'hide', 'protected': 'group'})
		self.assertEqual(presentation({'protected': 'inline'}), {'protected': 'inline'})
		self.assertEqual(presentation({'all': 'inline'}), {'all': 'inline'})

	def test_modern_release_uses_pinned_universal_wheel_without_executing_nox(self):
		self.modern_release()
		asyncio.run(self.installer.post_install('2026.6.0', self.log))
		self.request.json.assert_awaited_once_with('https://pypi.org/pypi/debugpy/1.8.20/json')
		self.request.download_and_extract_zip.assert_awaited_once_with(
			'https://files.pythonhosted.org/debugpy.whl', str(self.path / 'debugpy'), log=self.log, sha256='a' * 64)
		self.assertTrue((self.path / 'debugpy/debugpy/adapter/__main__.py').is_file())

	def test_legacy_metadata_accepts_list_and_object_formats(self):
		for entries in ([{'url': 'https://example.invalid/debugpy.zip'}], {'url': 'https://example.invalid/debugpy.zip'}):
			with self.subTest(entries=entries):
				(self.path / 'debugpy_info.json').write_text(json.dumps({'any': entries}))
				self.request.download_and_extract_zip.reset_mock()
				self.request.download_and_extract_zip.side_effect = None
				entry = self.path / 'debugpy/debugpy/adapter/__main__.py'
				entry.parent.mkdir(parents=True, exist_ok=True)
				entry.write_text('')
				asyncio.run(self.installer.post_install('2025.0.0', self.log))
				self.request.download_and_extract_zip.assert_awaited_once_with(
					'https://example.invalid/debugpy.zip', str(self.path / 'debugpy'), log=self.log)
		self.request.json.assert_not_awaited()

	def test_nonliteral_version_pin_is_rejected(self):
		(self.path / 'noxfile.py').write_text('DEBUGPY_VERSION = get_latest_version()')
		with self.assertRaisesRegex(RuntimeError, 'version'):
			asyncio.run(self.installer.post_install('2026.6.0', self.log))
		self.request.json.assert_not_awaited()

	def test_native_or_yanked_wheels_are_not_selected(self):
		self.modern_release()
		for overrides in ({'filename': 'debugpy-1.8.20-cp312-cp312-win_amd64.whl'}, {'yanked': True}):
			self.request.json.return_value = self.metadata(**overrides)
			with self.assertRaisesRegex(RuntimeError, 'wheel'):
				asyncio.run(self.installer.post_install('2026.6.0', self.log))
		self.request.download_and_extract_zip.assert_not_awaited()

	def test_missing_digest_is_rejected(self):
		self.modern_release()
		self.request.json.return_value = self.metadata(digests={})
		with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
			asyncio.run(self.installer.post_install('2026.6.0', self.log))
		self.request.download_and_extract_zip.assert_not_awaited()

	def test_install_requires_adapter_entrypoint(self):
		self.modern_release()
		self.request.download_and_extract_zip.side_effect = None
		with self.assertRaisesRegex(RuntimeError, 'adapter'):
			asyncio.run(self.installer.post_install('2026.6.0', self.log))


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
