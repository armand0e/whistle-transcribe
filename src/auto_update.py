"""Conservative launch-time Git updater. Standard library only: never load Qt here."""
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

from paths import ROOT
EXPECTED_REMOTE = 'https://github.com/armand0e/whistle-transcribe.git'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def read_json(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def update_status(root=ROOT):
    return read_json(Path(root) / '.updates' / 'status.json')

def normalized_remote(value):
    value = value.strip().rstrip('/').removesuffix('.git')
    if value.startswith('git@github.com:'):
        value = 'https://github.com/' + value[len('git@github.com:'):]
    if value.startswith('ssh://git@github.com/'):
        value = 'https://github.com/' + value[len('ssh://git@github.com/'):]
    return value.casefold()

def pid_alive(pid):
    if pid < 1:
        return False
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: do not assume it is safe to update.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

def app_running(root):
    try:
        lines = (Path(root) / 'whistle.lock').read_text(encoding='utf-8').splitlines()
        if len(lines) >= 3 and lines[2].casefold() != socket.gethostname().casefold():
            return True  # A lock belonging to another host is not ours to override.
        return pid_alive(int(lines[0]))
    except (OSError, ValueError, IndexError):
        return False

class LaunchLock(AbstractContextManager):
    """OS-backed lock releases automatically if an updater exits/crashes."""
    def __init__(self, root):
        self.path = Path(root) / '.updates' / 'launch.lock'
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if self.file.tell() == 0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            return False
        return True

    def __exit__(self, *args):
        if self.file:
            self.file.seek(0)
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()

@dataclass
class Outcome:
    status: str
    message: str
    launch: bool = True

class Updater:
    def __init__(self, root=ROOT, progress=None, expected_remote=EXPECTED_REMOTE, running=None):
        self.root = Path(root).resolve()
        self.folder = self.root / '.updates'
        self.folder.mkdir(exist_ok=True)
        self.log = self.folder / 'update.log'
        self.progress = progress or (lambda message: None)
        self.expected_remote = expected_remote
        self.running = running or (lambda: app_running(self.root))
        self.build_supported = sys.platform == 'win32'

    def note(self, message):
        with self.log.open('a', encoding='utf-8') as file:
            file.write(f'{datetime.now().astimezone().isoformat()} {message}\n')

    def command(self, arguments, timeout=15, cwd=None, check=True, log=True):
        environment = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never',
                       'PIP_NO_INPUT': '1', 'PYTHONIOENCODING': 'utf-8'}
        process = subprocess.Popen(arguments, cwd=cwd or self.root, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=NO_WINDOW)
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                               timeout=15, creationflags=NO_WINDOW)
            else:
                process.kill()
            process.communicate()
            raise RuntimeError('Command timed out: ' + Path(arguments[0]).name)
        text = output.decode('utf-8', 'replace').strip()
        if log and text:
            self.note(text)
        if check and process.returncode:
            raise RuntimeError(f'{Path(arguments[0]).name} exited with code {process.returncode}. See the update log.')
        return process.returncode, text

    def git(self, *arguments, **kwargs):
        return self.command(['git', *arguments], **kwargs)

    def finish(self, status, message, launch=True, **details):
        self.note(message)
        self.progress(message)
        atomic_json(self.folder / 'status.json', {'status': status, 'message': message,
                    'checked': datetime.now().astimezone().isoformat(), **details})
        return Outcome(status, message, launch)

    def requirements_hash(self):
        return hashlib.sha256((self.root / 'requirements.txt').read_bytes()).hexdigest()

    def capture_hash(self):
        digest = hashlib.sha256((self.root / 'build-capture.cmd').read_bytes())
        for path in sorted((self.root / 'native').rglob('*')):
            if path.is_file():
                digest.update(path.relative_to(self.root).as_posix().encode('utf-8'))
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def protects_local_data(self, before, target):
        _, changed = self.git('diff', '--name-only', '-z', before, target, log=False)
        folders = {'.venv', 'venv', 'env', 'models', 'recordings', 'audio', 'transcripts', 'bin', 'test-output', '.updates'}
        files = {'settings.json', 'settings.tmp', 'ui-state.json', 'whistle.lock', '.env'}
        for path in changed.split('\0'):
            head = path.replace('\\', '/').split('/')[0].casefold()
            if head in folders or head.startswith('.venv') or head in files:
                return True
        return False

    def install_dependencies(self):
        self.progress('Preparing Python dependencies…')
        python = self.root / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        self.command([str(python), '-m', 'pip', 'install', '--require-virtualenv', '--disable-pip-version-check',
                      '-r', str(self.root / 'requirements.txt')], timeout=1200)

    def build_capture(self):
        self.progress('Rebuilding the audio capture helper…')
        staging = Path(tempfile.mkdtemp(prefix='capture-', dir=self.folder)).resolve()
        try:
            shutil.copy2(self.root / 'build-capture.cmd', staging / 'build-capture.cmd')
            shutil.copytree(self.root / 'native', staging / 'native')
            self.command(['cmd.exe', '/d', '/c', 'build-capture.cmd'], timeout=180, cwd=staging)
            built = staging / 'bin' / 'capture.exe'
            if not built.is_file():
                raise RuntimeError('The capture build produced no executable.')
            (self.root / 'bin').mkdir(exist_ok=True)
            os.replace(built, self.root / 'bin' / 'capture.exe')
        finally:
            # Never delete a computed directory outside the updater's own staging area.
            if staging.is_relative_to(self.folder.resolve()) and staging != self.folder.resolve():
                shutil.rmtree(staging)

    def prepare(self):
        receipt_path = self.folder / 'installed.json'
        receipt = read_json(receipt_path)
        requirements = self.requirements_hash()
        if receipt.get('requirements') != requirements or receipt.get('python') != list(sys.version_info[:2]):
            self.install_dependencies()
            receipt.update(requirements=requirements, python=list(sys.version_info[:2]))
            atomic_json(receipt_path, receipt)
        if self.build_supported:
            capture = self.capture_hash()
            if receipt.get('capture') != capture or not (self.root / 'bin' / 'capture.exe').is_file():
                self.build_capture()
                receipt['capture'] = capture
                atomic_json(receipt_path, receipt)

    def run(self):
        with LaunchLock(self.root) as acquired:
            if not acquired:
                return Outcome('busy', 'Whistle is already checking for updates.', False)
            if self.running():
                return self.finish('running', 'Whistle is already open. Updates are checked at the next full start.')
            self.progress('Checking GitHub for updates…')
            updated = False
            checked_clean = False
            try:
                _, branch = self.git('symbolic-ref', '--short', 'HEAD')
                if branch != 'main':
                    return self.finish('development', 'Update skipped: this checkout is not on main.')
                _, remote = self.git('remote', 'get-url', 'origin', log=False)
                if normalized_remote(remote) != normalized_remote(self.expected_remote):
                    return self.finish('development', 'Update skipped: origin is not the expected Whistle GitHub repository.')
                _, dirty = self.git('status', '--porcelain', '--untracked-files=normal')
                if dirty:
                    return self.finish('local_changes', 'Update skipped to preserve local changes. Your current app will open.')
                checked_clean = True
                _, before = self.git('rev-parse', 'HEAD')
                self.git('fetch', '--quiet', '--no-tags', 'origin', 'refs/heads/main:refs/remotes/origin/main', timeout=12)
                _, target = self.git('rev-parse', 'refs/remotes/origin/main')
                if before != target:
                    code, _ = self.git('merge-base', '--is-ancestor', before, target, check=False)
                    if code:
                        return self.finish('diverged', 'Update skipped: local main has commits not in GitHub main.')
                    if self.protects_local_data(before, target):
                        return self.finish('protected_data', 'Update skipped: GitHub changes would replace local app data or environments.')
                    # Recheck immediately before mutation: do not replace work made during the fetch.
                    if self.running() or self.git('status', '--porcelain', '--untracked-files=normal')[1]:
                        return self.finish('deferred', 'Update postponed because Whistle started or local files changed.')
                    self.progress('Installing the latest merged app…')
                    self.git('merge', '--ff-only', target)
                    updated = True
                    self.note(f'Updated {before} -> {target}')
            except (OSError, RuntimeError) as exc:
                self.note(str(exc))
                # A failed/unreachable Git check does not prevent use of the last installed copy.
                try:
                    if self.running():
                        return self.finish('running', 'Whistle is already open. Updates are checked at the next full start.')
                    if checked_clean and self.git('status', '--porcelain', '--untracked-files=normal')[1]:
                        return self.finish('local_changes', 'Update skipped to preserve local changes. Your current app will open.')
                    self.prepare()
                except (OSError, RuntimeError) as setup_error:
                    self.note(str(setup_error))
                    return self.finish('failed', 'Whistle could not finish preparing the app. Open the update log, then launch again to retry.', False)
                return self.finish('offline', 'Could not check GitHub. Opening the installed copy of Whistle.')
            try:
                if self.running() or self.git('status', '--porcelain', '--untracked-files=normal')[1]:
                    return self.finish('deferred', 'Update postponed because Whistle started or local files changed.')
                self.prepare()
            except (OSError, RuntimeError) as exc:
                self.note(str(exc))
                return self.finish('failed', 'Whistle could not finish preparing the update. Open the update log, then launch again to retry.', False)
            return self.finish('updated' if updated else 'current',
                               'Whistle is updated. Opening the app…' if updated else 'Whistle is up to date. Opening the app…',
                               revision=target)
