"""Failures/cancellation retain audio and never mark partial work complete."""
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QTimer
from capture_jobs import Recorder, HelperJob
from windows_audio import Window
from model_catalog import validate_choice

application = QCoreApplication([])

def native_pids():
    text = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq nemo-speech.exe', '/FO', 'CSV', '/NH'],
                          capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return {int(row[1]) for row in csv.reader(io.StringIO(text)) if len(row) > 1 and row[1].isdigit()}

try:
    validate_choice('phonon2', 'cuda', 'en')
    raise AssertionError('CPU-only model accepted CUDA')
except ValueError:
    pass

bad = ROOT / 'test-output' / 'invalid.wav'
bad.write_bytes(b'not a WAV file')
worker = Recorder(Window(0, 0, 'Invalid input', 'test'), 'en', ROOT / 'test-output' / 'failures', source_audio=bad)
errors = []
worker.failed.connect(errors.append)
worker.finished.connect(application.quit)
worker.start(); application.exec(); worker.wait()
assert errors and worker.document.metadata['status'] == 'error'
assert bad.read_bytes() == b'not a WAV file'
print('PASS: decoder failure is visible and preserves the input', flush=True)

before = native_pids()
source = ROOT / 'transcripts' / '2026-10-15_15-37-35-706694' / 'Audio.wav'
worker = Recorder(Window(0, 0, 'Cancelled Nemotron job', 'test'), 'en', ROOT / 'test-output' / 'failures',
                  'nemotron35', 'cpu', source_audio=source)
errors = []
worker.failed.connect(errors.append)
worker.status.connect(lambda status: QTimer.singleShot(800, worker.cancel) if status.startswith('Running Nemotron') else None)
worker.finished.connect(application.quit)
worker.start(); application.exec(); worker.wait()
assert not errors, errors
assert worker.document.metadata['status'] == 'cancelled'
assert worker.process.poll() is not None
assert not (native_pids() - before), 'Native inference child survived cancellation'
print('PASS: cancellation stops native descendants and saves partial-session metadata', flush=True)

# Cancel a helper before it has even launched (common when a dialog closes).
job = HelperJob(['probe'])
job.cancel(); job.finished.connect(application.quit)
job.start(); application.exec(); job.wait()
assert not job.error and job.cancelled.is_set() and job.process.poll() is not None
print('PASS: early model/helper cancellation is safe', flush=True)
