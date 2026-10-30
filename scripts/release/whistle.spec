# Build one shared runtime with a windowed app and a cancellable console worker.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
staging = root / 'build' / 'release-assets'
datas = [(str(root / 'LICENSE'), '.'), (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
         (str(staging / 'capture.exe'), 'bin'), (str(staging / 'node.exe'), 'bin'),
         (str(staging / 'NODE-LICENSE.txt'), 'licenses'), (str(staging / 'version.json'), '.')]
binaries = []
hidden = ['fermion.transcribe', 'fermion._speech', 'needle.agent.whistle', 'needle.agent.fetch']
for package in ('faster_whisper', 'needle', 'fermion', 'yt_dlp', 'yt_dlp_ejs'):
    datas += collect_data_files(package, include_py_files=(package == 'fermion'))
    binaries += collect_dynamic_libs(package)
hidden += collect_submodules('fermion._speech')
hidden += collect_submodules('yt_dlp.extractor')
hidden += ['torch', 'transformers', 'transformers.models.parakeet.configuration_parakeet',
           'transformers.models.parakeet.modeling_parakeet']
for distribution in ('cactus-needle', 'fermion-research', 'faster-whisper', 'ctranslate2',
                     'huggingface-hub', 'tokenizers', 'yt-dlp', 'yt-dlp-ejs', 'soxr', 'numpy',
                     'PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'pyinstaller'):
    datas += copy_metadata(distribution)

a = Analysis([str(root / 'scripts' / 'release' / 'entry.py')], pathex=[str(root / 'src')],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['torchaudio', 'torchvision', 'tensorflow',
                       'jax', 'matplotlib', 'IPython', 'pytest', 'pip', 'setuptools'], noarchive=False)
# Preserve distribution license/metadata files for the modules actually bundled.
from importlib.metadata import packages_distributions
from PyInstaller.building.utils import format_binaries_and_datas
mapping = packages_distributions()
for distribution in sorted({d for module, _, _ in a.pure for d in mapping.get(module.split('.')[0], [])}):
    a.datas += [(dest, source, 'DATA') for dest, source in format_binaries_and_datas(copy_metadata(distribution))]
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Whistle',
          console=False, icon=str(staging / 'whistle.ico'), version=str(staging / 'windows-version.txt'),
          upx=False)
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='WhistleWorker',
             console=True, icon=str(staging / 'whistle.ico'), version=str(staging / 'windows-version.txt'),
             upx=False)
bundle = COLLECT(gui, worker, a.binaries, a.datas, name='Whistle', upx=False)
