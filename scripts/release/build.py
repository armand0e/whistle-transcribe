"""Build a Windows x64 bundle and installer without collecting any user data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from version import VERSION

NODE_VERSION = '24.22.2'
NODE_SHA256 = 'ca1bff5d8ead13c9f2ea404a176db46bd430704d5b5113734049fa365e7799e2'

def prepare():
    target = ROOT / 'build' / 'release-assets'
    target.mkdir(parents=True, exist_ok=True)
    capture = ROOT / 'bin' / 'capture.exe'
    if not capture.is_file():
        subprocess.run(['cmd.exe', '/d', '/c', 'build-capture.cmd'], cwd=ROOT, check=True)
    shutil.copy2(capture, target / 'capture.exe')
    archive = target / 'node.zip'
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA256:
        with urllib.request.urlopen(f'https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip', timeout=60) as response:
            with archive.open('wb') as file:
                shutil.copyfileobj(response, file)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA256:
        raise RuntimeError('Node runtime checksum mismatch.')
    with zipfile.ZipFile(archive) as files:
        for member, name in (('node.exe', 'node.exe'), ('LICENSE', 'NODE-LICENSE.txt')):
            (target / name).write_bytes(files.read(f'node-v{NODE_VERSION}-win-x64/{member}'))
    (target / 'version.json').write_text(json.dumps({'version': VERSION}), encoding='utf-8')
    # Native Windows fonts, but no visible test window.
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    from PySide6.QtWidgets import QApplication
    import theme
    app = QApplication([])
    theme.app_icon(256).save(str(target / 'whistle.ico'))
    (target / 'windows-version.txt').write_text(f'''VSVersionInfo(ffi=FixedFileInfo(filevers=({VERSION.replace('.', ', ')}, 0), prodvers=({VERSION.replace('.', ', ')}, 0), mask=0x3f, flags=0, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription', 'Whistle — local audio transcription'), StringStruct('FileVersion', '{VERSION}'), StringStruct('ProductName', 'Whistle'), StringStruct('ProductVersion', '{VERSION}')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])''', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', default=shutil.which('ISCC.exe'))
    parser.add_argument('--bundle-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build the Windows installer on Windows x64.')
    # A developer PATH can contain incompatible Qt/ICU/codec DLLs (for example
    # from PDF tools). Resolve platform libraries from Windows, not that PATH.
    windows = Path(os.environ.get('WINDIR', 'C:/Windows'))
    os.environ['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent,
        Path(sys.base_prefix), windows / 'System32', windows, windows / 'System32/Wbem']))
    prepare()
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build' / 'pyinstaller'),
                    str(ROOT / 'scripts' / 'release' / 'whistle.spec')], cwd=ROOT, check=True)
    bundle = ROOT / 'dist' / 'Whistle'
    shutil.copy2(ROOT / 'build/release-assets/whistle.ico', bundle / '_internal' / 'whistle.ico')
    shutil.copy2(ROOT / 'build/release-assets/version.json', bundle / 'version.json')
    smoke_root = ROOT / 'test-output' / 'release' / 'bundle-smoke'
    smoke_root.mkdir(parents=True, exist_ok=True)
    report = smoke_root / 'report.json'
    env = dict(os.environ, WHISTLE_DATA_DIR=str(smoke_root), QT_QPA_PLATFORM='offscreen')
    subprocess.run([str(bundle / 'Whistle.exe'), '--smoke-test', str(report)], env=env, check=True, timeout=180)
    result = json.loads(report.read_text(encoding='utf-8'))
    if not result.get('ok'):
        raise RuntimeError(result)
    print('PASS: frozen app, worker imports, media decoding, native helper, bundled runtime', flush=True)
    if not args.bundle_only:
        if not args.iscc:
            parser.error('Pass --iscc path/to/ISCC.exe to build the installer.')
        subprocess.run([args.iscc, '/DAppVersion=' + VERSION, '/DBundleDir=' + str(bundle),
                        '/DOutputDir=' + str(ROOT / 'dist'), str(ROOT / 'scripts/release/installer.iss')], check=True)
        installer = ROOT / 'dist' / f'Whistle-Setup-{VERSION}-x64.exe'
        checksum = hashlib.sha256(installer.read_bytes()).hexdigest()
        (ROOT / 'dist/SHA256SUMS.txt').write_text(checksum + '  ' + installer.name + '\n', encoding='ascii')
        print('Installer:', installer, flush=True)

if __name__ == '__main__':
    main()
