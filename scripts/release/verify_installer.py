"""Install/upgrade/uninstall in an isolated location; never touch real shortcuts/data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def run(arguments, env, timeout=300):
    result = subprocess.run(list(map(str, arguments)), env=env, capture_output=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=timeout)
    if result.returncode not in (0, 3010):
        detail = ''
        if '--smoke-test' in arguments:
            report = Path(arguments[arguments.index('--smoke-test') + 1])
            if report.exists():
                detail = report.read_text(encoding='utf-8')
        raise RuntimeError(f'Command failed ({result.returncode}): {arguments[0]}\n' +
                           result.stderr.decode('utf-8', 'replace') + detail)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run installer verification on Windows.')
    installer = args.installer.resolve()
    area = ROOT / 'test-output' / 'release'
    area.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix='installer-', dir=area)).resolve()
    assert sandbox.is_relative_to(area.resolve())
    program = sandbox / 'program files'
    data = sandbox / 'library'
    (data / 'transcripts').mkdir(parents=True)
    marker = data / 'transcripts' / 'keep.txt'
    marker.write_text('Preserve this library across upgrade and uninstall.', encoding='utf-8')
    before = hashlib.sha256(marker.read_bytes()).hexdigest()
    settings = data / 'settings.json'
    settings.write_text(json.dumps({'welcomed': True, 'appearance': 'dark'}), encoding='utf-8')
    settings_hash = hashlib.sha256(settings.read_bytes()).hexdigest()
    (data / 'app.py').write_text('# fixture for detecting a pre-src source installation\n')
    windows = Path(os.environ.get('WINDIR', 'C:/Windows'))
    env = dict(os.environ, WHISTLE_DATA_DIR=str(data), WHISTLE_CONFIG_DIR=str(sandbox / 'config'),
               WHISTLE_INSTALL_DIR=str(program), QT_QPA_PLATFORM='offscreen',
               PATH=os.pathsep.join(map(str, [windows / 'System32', windows])))
    shortcut = sandbox / 'old-source.lnk'
    create_shortcut = sandbox / 'create-shortcut.ps1'
    create_shortcut.write_text('''param([string]$LinkPath, [string]$SourceRoot)
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($LinkPath)
$link.TargetPath = Join-Path $env:WINDIR 'System32\\wscript.exe'
$link.Arguments = '"' + (Join-Path $SourceRoot 'Launch Whistle.vbs') + '"'
$link.WorkingDirectory = $SourceRoot
$link.Save()
''', encoding='utf-8')
    run([windows / 'System32/WindowsPowerShell/v1.0/powershell.exe', '-NoProfile', '-File',
         create_shortcut, shortcut, data], env)
    command = [installer, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
               '/NOCLOSEAPPLICATIONS', '/ISOLATEDTEST=1', '/NOSHORTCUTS=1', '/DIR=' + str(program),
               '/LEGACYSHORTCUTTEST=' + str(shortcut), '/CONFIGTESTDIR=' + str(sandbox / 'config')]
    for attempt in (1, 2):
        run([*command, '/LOG=' + str(sandbox / f'install-{attempt}.log')], env)
        bootstrap = sandbox / 'config' / 'bootstrap.json'
        assert json.loads(bootstrap.read_text(encoding='utf-8-sig'))['data_dir'] == str(data)
        env.pop('WHISTLE_DATA_DIR', None)  # Prove the installed app discovers the migrated data by itself.
        report = sandbox / f'smoke-{attempt}.json'
        run([program / 'Whistle.exe', '--smoke-test', report], env, timeout=180)
        result = json.loads(report.read_text(encoding='utf-8'))
        assert result.get('ok'), result
        assert result['data_dir'] == str(data.resolve()), result
        assert hashlib.sha256(marker.read_bytes()).hexdigest() == before
        assert hashlib.sha256(settings.read_bytes()).hexdigest() == settings_hash
        print(f'PASS: isolated installer run {attempt}, frozen startup/worker/decode, settings/library preserved', flush=True)
    # Windows PowerShell's native argument path can best-fit some Unicode
    # characters while constructing a legacy .lnk fixture. Test Unicode data
    # independently through the actual UTF-8/BOM bootstrap format instead.
    unicode_data = sandbox / 'library-β'
    (unicode_data / 'transcripts').mkdir(parents=True)
    unicode_marker = unicode_data / 'transcripts' / 'keep.txt'
    unicode_marker.write_bytes(marker.read_bytes())
    (unicode_data / 'settings.json').write_bytes(settings.read_bytes())
    bootstrap.write_text(json.dumps({'data_dir': str(unicode_data)}, ensure_ascii=False), encoding='utf-8-sig')
    report = sandbox / 'smoke-unicode.json'
    run([program / 'Whistle.exe', '--smoke-test', report], env, timeout=180)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result.get('ok') and result['data_dir'] == str(unicode_data.resolve()), result
    print('PASS: UTF-8/BOM bootstrap and Unicode data path work in the installed app/worker', flush=True)
    run([program / 'unins000.exe', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/ISOLATEDTEST=1'], env)
    assert hashlib.sha256(marker.read_bytes()).hexdigest() == before
    assert hashlib.sha256(settings.read_bytes()).hexdigest() == settings_hash
    assert unicode_marker.read_bytes() == marker.read_bytes()
    assert not (program / 'Whistle.exe').exists()
    print('PASS: uninstall removes program files and retains all user data', flush=True)
    (sandbox / 'verified.json').write_text(json.dumps({'ok': True, 'installer': installer.name,
        'sha256': hashlib.sha256(installer.read_bytes()).hexdigest()}), encoding='utf-8')

if __name__ == '__main__':
    main()
