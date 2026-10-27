"""Run every test that needs no audio hardware, models, or Windows: python tests/offline.py"""
from pathlib import Path
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
environment = {**os.environ, 'QT_QPA_PLATFORM': os.environ.get('QT_QPA_PLATFORM', 'offscreen')}
failed = []
for name in ('sessions_offline.py', 'recorder_offline.py', 'ui_offline.py', 'layout_offline.py', 'url_offline.py', 'update_offline.py'):
    print(f'== {name}', flush=True)
    if subprocess.run([sys.executable, str(HERE / name)], cwd=HERE, env=environment, timeout=600).returncode:
        failed.append(name)
print('FAILED: ' + ', '.join(failed) if failed else 'All offline tests passed.')
sys.exit(1 if failed else 0)
