"""Entry points, worker paths, and data paths survive the src layout migration."""
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import auto_update
import capture_jobs
import launch
import model_catalog
import paths
import preferences
import transcriber

assert paths.SRC == ROOT / 'src'
assert paths.ROOT == ROOT == model_catalog.ROOT == auto_update.ROOT == transcriber.ROOT
assert preferences.PATH == ROOT / 'settings.json'
command = capture_jobs.helper_command(['convert'])
assert Path(command[2]) == ROOT / 'src' / 'asr_worker.py'
with patch('launch.subprocess.Popen') as spawn, patch('launch.installed_executable', return_value=None):
    launch.open_app()
    assert Path(spawn.call_args.args[0][1]) == ROOT / 'src' / 'app.py'
    assert spawn.call_args.kwargs['cwd'] == ROOT
with patch('capture_jobs.FROZEN', True), patch('capture_jobs.APP_DIR', ROOT / 'fixture-bundle'):
    assert capture_jobs.helper_command(['probe']) == [str(ROOT / 'fixture-bundle' / 'WhistleWorker.exe'), 'probe']

# The pre-migration launcher opens ROOT/app.py after pulling new code, while
# preexisting shortcuts can still point at ROOT/launch.py. Both must route to src.
for name in ('app', 'launch'):
    with patch('runpy.run_path') as execute:
        exec(compile((ROOT / f'{name}.py').read_text(), f'{name}.py', 'exec'),
             {'__name__': '__main__', '__file__': str(ROOT / f'{name}.py')})
        execute.assert_called_once_with(str(ROOT / 'src' / f'{name}.py'), run_name='__main__')

# Setup/help commands are safe and usable from a different working directory.
for script in ('src/asr_worker.py', 'scripts/setup_models.py',
               'scripts/evaluation/evaluate_lecture.py', 'scripts/evaluation/crosscheck_lecture.py',
               'scripts/evaluation/build_lecture_report.py'):
    result = subprocess.run([sys.executable, str(ROOT / script), '--help'], cwd=ROOT / 'tests',
                            capture_output=True, timeout=30)
    assert result.returncode == 0, (script, result.stderr.decode('utf-8', 'replace'))
print('PASS: source/worker/data paths, old launcher compatibility, and setup/evaluation entry points', flush=True)
