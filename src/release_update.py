"""Versioned GitHub Release updates. No Git, pip, or build tools on the user's PC."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from auto_update import LaunchLock, Outcome, Updater as UpdateLog, app_running, pid_alive, read_json
from paths import APP_DIR, CONFIG_DIR, FROZEN, ROOT, installed_directory, installed_executable
from version import VERSION

REPOSITORY = 'armand0e/whistle-transcribe'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_INSTALLER = 1_500_000_000

def version_tuple(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value or '')
    if not match:
        raise ValueError('The release must have a stable vMAJOR.MINOR.PATCH version.')
    return tuple(map(int, match.groups()))

def current_version():
    if not FROZEN and not installed_executable():
        return '0.0.0'  # A legacy source checkout has no installed executable release yet.
    if not FROZEN and installed_executable():
        value = read_json(installed_directory() / 'version.json').get('version')
        try:
            version_tuple(value)
            return value
        except (ValueError, TypeError):
            pass
    return VERSION

def asset_url(asset, tag):
    name = asset.get('name', '')
    expected = f'https://github.com/{REPOSITORY}/releases/download/{quote(tag, safe="")}/{quote(name, safe="")}'
    if asset.get('browser_download_url') != expected:
        raise ValueError('The release asset does not belong to the expected GitHub repository.')
    return expected

def select_release(info, installed):
    if info.get('draft') or info.get('prerelease'):
        return None
    tag = info.get('tag_name')
    if version_tuple(tag) <= version_tuple(installed):
        return None
    name = f'Whistle-Setup-{tag.removeprefix("v")}-x64.exe'
    assets = info.get('assets', [])
    setup = next((a for a in assets if a.get('name') == name), None)
    checksums = next((a for a in assets if a.get('name') == 'SHA256SUMS.txt'), None)
    if not setup or not checksums:
        raise ValueError('The release is missing its Windows installer or checksums.')
    if type(setup.get('size')) is not int or not 0 < setup['size'] <= MAX_INSTALLER:
        raise ValueError('The release installer size is invalid.')
    asset_url(setup, tag); asset_url(checksums, tag)
    return tag, setup, checksums

def request(url, etag=None):
    headers = {'User-Agent': 'Whistle/' + VERSION, 'Accept': 'application/vnd.github+json'}
    if etag:
        headers['If-None-Match'] = etag
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=12)

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

class ReleaseUpdater(UpdateLog):
    def __init__(self, root=ROOT, progress=None, running=None, opener=None, installed=None):
        super().__init__(root, progress=progress, running=running)
        self.opener = opener or request
        self.installed = installed or current_version()

    def latest(self):
        cache = read_json(self.folder / 'release-cache.json')
        try:
            with self.opener(API_URL, cache.get('etag')) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('The release response is too large.')
                info = json.loads(raw)
                if not isinstance(info, dict):
                    raise ValueError('Invalid release metadata.')
                from auto_update import atomic_json
                atomic_json(self.folder / 'release-cache.json', {'etag': response.headers.get('ETag'), 'release': info})
                return info
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and isinstance(cache.get('release'), dict):
                return cache['release']
            if exc.code == 404:
                return None  # No published release yet; the installed copy remains usable.
            raise

    def download(self, tag, setup, checksums):
        with self.opener(asset_url(checksums, tag)) as response:
            manifest = response.read(65537)
        if len(manifest) > 65536:
            raise ValueError('The release checksum manifest is too large.')
        matches = re.findall(r'^([0-9a-fA-F]{64})\s+\*?' + re.escape(setup['name']) + r'\s*$',
                             manifest.decode('utf-8'), re.MULTILINE)
        if len(matches) != 1:
            raise ValueError('No unique checksum was found for the installer.')
        expected = matches[0].lower()
        digest = setup.get('digest')
        if digest and digest != 'sha256:' + expected:
            raise ValueError('GitHub and the release manifest disagree about the installer checksum.')
        directory = self.folder / 'releases' / tag
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / setup['name']
        if target.is_file() and target.stat().st_size == setup['size'] and sha256(target) == expected:
            return target
        temporary = target.with_suffix('.part')
        try:
            with self.opener(asset_url(setup, tag)) as response, temporary.open('wb') as file:
                received = 0
                digest = hashlib.sha256()
                percent = -1
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > setup['size']:
                        raise ValueError('The installer exceeded its declared size.')
                    file.write(block); digest.update(block)
                    value = int(received * 100 / setup['size'])
                    if value != percent:
                        percent = value; self.progress(f'Downloading Whistle {tag}: {value}%')
            if received != setup['size'] or digest.hexdigest() != expected:
                raise ValueError('Installer checksum/size verification failed. The installed app was not changed.')
            os.replace(temporary, target)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def run(self):
        with LaunchLock(self.root) as acquired:
            if not acquired:
                return Outcome('busy', 'Whistle is already checking for updates.', False)
            installing = read_json(self.folder / 'installing.json').get('pid', 0)
            if type(installing) is int and pid_alive(installing):
                return Outcome('busy', 'A Whistle update is being installed.', False)
            if self.running():
                return self.finish('running', 'Whistle is already open. Release updates wait for the next full start.')
            try:
                self.progress('Checking GitHub Releases…')
                info = self.latest()
                if info is None:
                    return self.finish('no_release', 'No stable release is published yet. Opening the existing copy.')
                release = select_release(info, self.installed) if info else None
                if not release:
                    return self.finish('current', f'Whistle {self.installed} is current. Opening the app…', version=self.installed)
                tag, setup, checksums = release
                installer = self.download(tag, setup, checksums)
                if self.running():
                    return self.finish('deferred', 'The update is downloaded. It will install after Whistle is fully closed.')
                self.finish('ready', f'Installing Whistle {tag}…', release=tag, version=self.installed)
                return Outcome('ready', f'Installing Whistle {tag}…', False, str(installer))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.note(str(exc))
                return self.finish('offline', 'Could not finish the release check. Opening the installed copy.')

def start_install(installer, root=ROOT):
    """Spawn Setup, which waits for this launcher's PID before replacing files."""
    import subprocess
    from auto_update import atomic_json, NO_WINDOW
    root = Path(root).resolve()
    path = Path(installer).resolve()
    if not path.is_relative_to(root / '.updates' / 'releases') or path.suffix.lower() != '.exe':
        raise ValueError('Invalid staged installer path.')
    if app_running(root):
        return False
    # A source installation keeps its existing data instead of copying gigabytes
    # or giving the user an apparently empty library after the first installer.
    if not FROZEN and not (CONFIG_DIR / 'bootstrap.json').exists() and root != CONFIG_DIR:
        atomic_json(CONFIG_DIR / 'bootstrap.json', {'data_dir': str(root)})
    process = subprocess.Popen([str(path), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                                '/NOCLOSEAPPLICATIONS', '/RUNAPP=1', f'/WHISTLEPID={os.getpid()}',
                                '/DIR=' + str(APP_DIR if FROZEN else installed_directory())],
                               cwd=path.parent, creationflags=NO_WINDOW)
    atomic_json(root / '.updates' / 'installing.json', {'pid': process.pid, 'installer': str(path)})
    return True
