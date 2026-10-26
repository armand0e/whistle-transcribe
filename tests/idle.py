"""Stopping an app that never plays audio must still finish its document."""
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QTimer
from capture_jobs import Recorder
from windows_audio import Window
application = QCoreApplication([])
target = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
worker = Recorder(Window(0, target.pid, 'Silent test app', 'test'), 'en', ROOT / 'test-output' / 'idle', model_key='whistle')
errors = []
worker.failed.connect(errors.append)
worker.status.connect(lambda status: QTimer.singleShot(1200, worker.stop) if status == 'Recording' else None)
worker.finished.connect(application.quit)
worker.start()
QTimer.singleShot(20000, worker.stop)
application.exec()
worker.wait()
target.terminate(); target.wait()
assert not errors, errors
assert worker.document is not None
assert worker.document.metadata['status'] == 'complete'
assert not worker.document.paragraphs
print('PASS: silent app stops, flushes without hallucinated words, and saves a complete document')
