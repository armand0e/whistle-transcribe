"""Stable-version checks, checksum verification, caching and installer handoff without network."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from auto_update import LaunchLock, atomic_json
from release_update import API_URL, REPOSITORY, ReleaseUpdater, current_version, select_release, start_install, version_tuple

class Response(io.BytesIO):
    def __init__(self, value, etag=None):
        super().__init__(value)
        self.headers = {'ETag': etag}

class Releases(unittest.TestCase):
    def setUp(self):
        output = ROOT / 'test-output' / 'release-updates'
        output.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=output)
        self.root = Path(self.temp.name)
        self.binary = b'fixture installer, never executed'
        self.name = 'Whistle-Setup-0.2.0-x64.exe'
        self.checksum = hashlib.sha256(self.binary).hexdigest()
        self.info = {'tag_name': 'v0.2.0', 'draft': False, 'prerelease': False, 'assets': [
            {'name': self.name, 'size': len(self.binary), 'digest': 'sha256:' + self.checksum,
             'browser_download_url': self.url(self.name)},
            {'name': 'SHA256SUMS.txt', 'browser_download_url': self.url('SHA256SUMS.txt')}]}
        self.calls = []
        self.service = ReleaseUpdater(self.root, running=lambda: False, installed='0.1.0', opener=self.open)
        self.service.command = lambda *a, **k: self.fail('Release updates must never run Git, pip, or a compiler')

    def tearDown(self):
        self.temp.cleanup()

    def url(self, name):
        return f'https://github.com/{REPOSITORY}/releases/download/v0.2.0/{name}'

    def open(self, url, etag=None):
        self.calls.append((url, etag))
        if url == API_URL:
            return Response(json.dumps(self.info).encode(), 'release-etag')
        if url.endswith('SHA256SUMS.txt'):
            return Response((self.checksum + '  ' + self.name + '\n').encode())
        self.assertEqual(url, self.url(self.name))
        return Response(self.binary)

    def test_newer_stable_release_downloads_verified_installer(self):
        result = self.service.run()
        self.assertEqual(result.status, 'ready')
        self.assertFalse(result.launch)
        self.assertEqual(Path(result.installer).read_bytes(), self.binary)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_same_version_skips_download(self):
        self.service.installed = '0.2.0'
        self.assertEqual(self.service.run().status, 'current')
        self.assertEqual([c[0] for c in self.calls], [API_URL])

    def test_newer_installed_version_is_not_downgraded(self):
        self.service.installed = '0.10.0'
        self.assertEqual(self.service.run().status, 'current')
        self.assertEqual(len(self.calls), 1)

    def test_numeric_versions_and_invalid_tags(self):
        self.assertGreater(version_tuple('v0.10.0'), version_tuple('v0.2.0'))
        for value in ('v0.2.0-beta', '../../bad', 'latest', 'v01.2.0', ''):
            with self.assertRaises(ValueError): version_tuple(value)

    def test_drafts_and_prereleases_are_not_installed(self):
        for flag in ('draft', 'prerelease'):
            self.info[flag] = True
            self.assertIsNone(select_release(self.info, '0.1.0'))
            self.info[flag] = False

    def test_checksum_failure_keeps_installed_app(self):
        self.binary = b'x' * len(self.binary)
        result = self.service.run()
        self.assertEqual(result.status, 'offline')
        self.assertTrue(result.launch)
        self.assertIsNone(result.installer)
        self.assertFalse(list(self.root.rglob('*.exe')))
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_manifest_must_match_github_asset_digest(self):
        self.info['assets'][0]['digest'] = 'sha256:' + '0' * 64
        self.assertEqual(self.service.run().status, 'offline')
        self.assertEqual(len(self.calls), 2)

    def test_foreign_asset_and_missing_manifest_are_rejected(self):
        self.info['assets'][0]['browser_download_url'] = 'https://example.org/payload.exe'
        self.assertEqual(self.service.run().status, 'offline')
        self.assertEqual(len(self.calls), 1)
        self.info['assets'].pop()
        self.assertEqual(self.service.run().status, 'offline')

    def test_verified_download_is_reused(self):
        first = self.service.run()
        self.calls.clear()
        second = self.service.run()
        self.assertEqual(first.installer, second.installer)
        self.assertEqual(len(self.calls), 2)  # API + checksum, no second installer download.

    def test_conditional_request_can_use_304_cache(self):
        self.service.run()
        original = self.open
        def cached(url, etag=None):
            if url == API_URL:
                self.assertEqual(etag, 'release-etag')
                raise urllib.error.HTTPError(url, 304, 'Not modified', {}, None)
            return original(url, etag)
        self.service.opener = cached
        self.service.installed = '0.2.0'
        self.assertEqual(self.service.run().status, 'current')

    def test_offline_and_no_releases_launch_existing_copy(self):
        for code in (404, 403, 500):
            def unavailable(*args, **kwargs):
                raise urllib.error.HTTPError(API_URL, code, 'Unavailable', {}, None)
            self.service.opener = unavailable
            result = self.service.run()
            self.assertTrue(result.launch)
            self.assertEqual(result.status, 'no_release' if code == 404 else 'offline')

    def test_legacy_source_launcher_migrates_but_installed_versions_are_respected(self):
        with patch('release_update.FROZEN', False), patch('release_update.installed_executable', return_value=None):
            self.assertEqual(current_version(), '0.0.0')
        program = self.root / 'installed'
        program.mkdir()
        (program / 'version.json').write_text('{"version":"1.2.3"}')
        with patch('release_update.FROZEN', False), patch('release_update.installed_executable', return_value=program / 'Whistle.exe'), \
             patch('release_update.installed_directory', return_value=program):
            self.assertEqual(current_version(), '1.2.3')

    def test_running_app_skips_network_and_install(self):
        self.service.running = lambda: True
        self.assertEqual(self.service.run().status, 'running')
        self.assertFalse(self.calls)

    def test_app_started_during_download_defers_install(self):
        checks = []
        def running():
            checks.append(True)
            return len(checks) > 1
        self.service.running = running
        self.assertEqual(self.service.run().status, 'deferred')

    def test_simultaneous_launcher_and_active_setup_are_serialized(self):
        with LaunchLock(self.root):
            self.assertEqual(self.service.run().status, 'busy')
        atomic_json(self.root / '.updates/installing.json', {'pid': os.getpid()})
        self.assertEqual(self.service.run().status, 'busy')
        self.assertFalse(self.calls)

    def test_installer_handoff_waits_for_launcher_and_preserves_source_data(self):
        result = self.service.run()
        config = self.root / 'user-config'
        with patch('release_update.CONFIG_DIR', config), patch('release_update.FROZEN', False), \
             patch('release_update.app_running', return_value=False), \
             patch('subprocess.Popen') as spawn:
            # Patch the stdlib call only while handing off; no fixture installer runs.
            spawn.return_value.pid = 12345
            self.assertTrue(start_install(result.installer, self.root))
            arguments = spawn.call_args.args[0]
            self.assertIn('/WHISTLEPID=' + str(os.getpid()), arguments)
            self.assertIn('/NOCLOSEAPPLICATIONS', arguments)
            self.assertEqual(json.loads((config / 'bootstrap.json').read_text())['data_dir'], str(self.root.resolve()))
        with self.assertRaises(ValueError): start_install(self.root / 'outside.exe', self.root)

if __name__ == '__main__':
    unittest.main(verbosity=2)
