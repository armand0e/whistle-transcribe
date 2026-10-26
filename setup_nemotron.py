"""Pinned official NVIDIA Windows binaries, verified against release checksums."""
import hashlib
import json
from pathlib import Path
import zipfile
import requests
from model_catalog import ROOT

VERSION = '0.2.0'

def install():
    for backend in ('cpu', 'cuda'):
        target = ROOT / 'bin' / f'nemo-{backend}'
        if next(target.glob('**/nemo-speech.exe'), None):
            continue
        name = f'nemo-speech-{VERSION}-windows-x86_64-{backend}.zip'
        url = f'https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v{VERSION}/{name}'
        checksum = requests.get(url + '.sha256', timeout=30)
        checksum.raise_for_status()
        expected = checksum.text.split()[0].lower()
        archive = ROOT / 'models' / name
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with archive.open('wb') as output:
                    for block in response.iter_content(1024 * 1024):
                        output.write(block)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'NVIDIA runtime checksum did not match: {name}')
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as files:
            for item in files.infolist():
                resolved = (target / item.filename).resolve()
                if not resolved.is_relative_to(target.resolve()):
                    raise RuntimeError('Runtime archive contains an invalid path.')
            files.extractall(target)
        (target / 'runtime-manifest.json').write_text(json.dumps({'version': VERSION, 'source': url, 'sha256': expected}, indent=2))
        print(f'Installed {backend}: {target}', flush=True)

if __name__ == '__main__':
    install()
