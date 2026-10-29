"""Real local Git repositories exercise launch updates without network/installer side effects."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from auto_update import LaunchLock, Updater, update_status

OUTPUT = ROOT / 'test-output' / 'updater'
OUTPUT.mkdir(parents=True, exist_ok=True)

def git(path, *args):
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='check-', dir=OUTPUT)
        self.area = Path(self.temp.name).resolve()
        self.upstream = self.area / 'source'; self.upstream.mkdir()
        self.remote = self.area / 'origin.git'
        git(self.upstream, 'init', '-b', 'main')
        git(self.upstream, 'config', 'user.email', 'tests@example.invalid')
        git(self.upstream, 'config', 'user.name', 'Updater tests')
        (self.upstream / '.gitignore').write_text('.updates/\nmodels/\ntranscripts/\nbin/\n.venv/\n')
        (self.upstream / 'app.py').write_text('# v1\n')
        (self.upstream / 'requirements.txt').write_text('example==1\n')
        (self.upstream / 'build-capture.cmd').write_text('@echo test\n')
        (self.upstream / 'native').mkdir()
        (self.upstream / 'native' / 'capture.cpp').write_text('// v1\n')
        git(self.upstream, 'add', '.')
        git(self.upstream, 'commit', '-m', 'initial')
        git(self.area, 'init', '--bare', '-b', 'main', str(self.remote))
        git(self.upstream, 'remote', 'add', 'origin', str(self.remote))
        git(self.upstream, 'push', 'origin', 'main')
        self.root = self.area / 'app'
        git(self.area, 'clone', str(self.remote), str(self.root))
        git(self.root, 'config', 'user.email', 'tests@example.invalid')
        git(self.root, 'config', 'user.name', 'Updater tests')
        self.steps = []
        self.service = self.make_service()
        self.service.prepare()  # A previously installed, working copy.
        self.steps.clear()

    def tearDown(self):
        assert self.area.is_relative_to(OUTPUT.resolve()), self.area
        self.temp.cleanup()

    def make_service(self, **kwargs):
        service = Updater(self.root, expected_remote=str(self.remote), running=kwargs.get('running', lambda: False))
        service.build_supported = True
        service.install_dependencies = lambda: self.steps.append('dependencies')
        def build():
            self.steps.append('capture')
            (self.root / 'bin').mkdir(exist_ok=True)
            (self.root / 'bin' / 'capture.exe').write_bytes(b'compiled helper')
        service.build_capture = build
        return service

    def publish(self, changes):
        for name, value in changes.items():
            target = self.upstream / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)
            git(self.upstream, 'add', '-f', name)
        git(self.upstream, 'commit', '-m', 'merged changes')
        git(self.upstream, 'push', 'origin', 'main')
        return git(self.upstream, 'rev-parse', 'HEAD')

    def test_fast_forward_and_data_preservation(self):
        for folder in ('models', 'transcripts'):
            (self.root / folder).mkdir()
            (self.root / folder / 'protected.txt').write_text('keep exactly')
        target = self.publish({'app.py': '# v2\n'})
        outcome = self.service.run()
        self.assertTrue(outcome.launch)
        self.assertEqual(outcome.status, 'updated')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), target)
        self.assertEqual(self.steps, [])
        for folder in ('models', 'transcripts'):
            self.assertEqual((self.root / folder / 'protected.txt').read_text(), 'keep exactly')

    def test_only_changed_inputs_are_prepared_once(self):
        self.publish({'requirements.txt': 'example==2\n', 'native/capture.cpp': '// v2\n'})
        self.assertTrue(self.service.run().launch)
        self.assertEqual(self.steps, ['dependencies', 'capture'])
        self.steps.clear()
        self.assertEqual(self.service.run().status, 'current')
        self.assertEqual(self.steps, [])

    def test_capture_build_replaces_only_after_success(self):
        def compile_helper(arguments, **kwargs):
            staging = kwargs['cwd']
            self.assertTrue((staging / 'native' / 'capture.cpp').is_file())
            (staging / 'bin').mkdir()
            (staging / 'bin' / 'capture.exe').write_bytes(b'new executable')
        self.service.command = compile_helper
        Updater.build_capture(self.service)
        self.assertEqual((self.root / 'bin' / 'capture.exe').read_bytes(), b'new executable')
        self.assertEqual(list(self.service.folder.glob('capture-*')), [])

    def test_failed_capture_build_preserves_existing_executable(self):
        def broken_build(*args, **kwargs):
            raise RuntimeError('compiler failed')
        self.service.command = broken_build
        with self.assertRaisesRegex(RuntimeError, 'compiler failed'):
            Updater.build_capture(self.service)
        self.assertEqual((self.root / 'bin' / 'capture.exe').read_bytes(), b'compiled helper')
        self.assertEqual(list(self.service.folder.glob('capture-*')), [])

    def test_dirty_checkout_is_not_changed(self):
        self.publish({'app.py': '# remote change\n'})
        (self.root / 'app.py').write_text('# my unfinished changes\n')
        self.assertEqual(self.service.run().status, 'local_changes')
        self.assertEqual((self.root / 'app.py').read_text(), '# my unfinished changes\n')
        self.assertEqual(self.steps, [])

    def test_changed_shared_constraints_trigger_dependency_install(self):
        self.publish({'requirements.txt': '-c requirements/constraints.txt\nexample\n',
                      'requirements/constraints.txt': 'example==1\n'})
        self.assertTrue(self.service.run().launch)
        self.steps.clear()
        self.publish({'requirements/constraints.txt': 'example==2\n'})
        self.assertTrue(self.service.run().launch)
        self.assertEqual(self.steps, ['dependencies'])
        self.steps.clear()
        self.assertEqual(self.service.run().status, 'current')
        self.assertEqual(self.steps, [])

    def test_untracked_files_are_preserved(self):
        self.publish({'new.py': '# upstream\n'})
        (self.root / 'new.py').write_text('# my new file\n')
        self.assertEqual(self.service.run().status, 'local_changes')
        self.assertEqual((self.root / 'new.py').read_text(), '# my new file\n')

    def test_diverged_history_is_not_reset(self):
        (self.root / 'mine.txt').write_text('local commit')
        git(self.root, 'add', 'mine.txt'); git(self.root, 'commit', '-m', 'local work')
        before = git(self.root, 'rev-parse', 'HEAD')
        self.publish({'app.py': '# remote\n'})
        self.assertEqual(self.service.run().status, 'diverged')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), before)

    def test_development_branch_is_skipped(self):
        git(self.root, 'checkout', '-b', 'feature')
        self.assertEqual(self.service.run().status, 'development')
        self.assertEqual(git(self.root, 'branch', '--show-current'), 'feature')

    def test_failed_fetch_opens_installed_copy(self):
        original = self.service.git
        def offline(*args, **kwargs):
            if args[0] == 'fetch':
                raise RuntimeError('offline')
            return original(*args, **kwargs)
        self.service.git = offline
        outcome = self.service.run()
        self.assertTrue(outcome.launch)
        self.assertEqual(outcome.status, 'offline')
        self.assertEqual(self.steps, [])

    def test_failed_preparation_retries_on_next_launch(self):
        target = self.publish({'requirements.txt': 'example==2\n'})
        def fail():
            raise RuntimeError('test installer failed')
        self.service.install_dependencies = fail
        outcome = self.service.run()
        self.assertFalse(outcome.launch)
        self.assertEqual(outcome.status, 'failed')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), target)
        self.assertEqual(self.make_service().run().status, 'current')
        self.assertEqual(self.steps, ['dependencies'])

    def test_running_app_is_never_modified(self):
        self.service.running = lambda: True
        self.service.git = lambda *args, **kwargs: self.fail('Git must not mutate a running copy')
        self.assertEqual(self.service.run().status, 'running')
        self.assertEqual(self.steps, [])

    def test_duplicate_launch_is_serialized(self):
        with LaunchLock(self.root) as acquired:
            self.assertTrue(acquired)
            outcome = self.service.run()
            self.assertEqual(outcome.status, 'busy')
            self.assertFalse(outcome.launch)

    def test_remote_cannot_overwrite_app_data(self):
        (self.root / 'models').mkdir()
        (self.root / 'models' / 'protected.txt').write_text('my model')
        self.publish({'models/protected.txt': 'accidentally tracked upstream'})
        self.assertEqual(self.service.run().status, 'protected_data')
        self.assertEqual((self.root / 'models' / 'protected.txt').read_text(), 'my model')

    def test_app_starting_during_fetch_defers_update(self):
        before = git(self.root, 'rev-parse', 'HEAD')
        self.publish({'app.py': '# remote\n'})
        calls = []
        def running():
            calls.append(True)
            return len(calls) > 1
        self.service.running = running
        self.assertEqual(self.service.run().status, 'deferred')
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), before)

    def test_unexpected_remote_is_not_used(self):
        self.service.expected_remote = 'https://github.com/other/repo'
        self.assertEqual(self.service.run().status, 'development')
        self.assertEqual(self.steps, [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
