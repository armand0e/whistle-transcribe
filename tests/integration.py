"""Exercise actual Windows process audio, Whistle streaming, and saved documents."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QTimer
from capture_jobs import Recorder
from windows_audio import Window

application = QCoreApplication([])
player = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'play_audio.py'),
                           str(ROOT / 'test-output' / 'speech.wav')],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
pid = int(player.stdout.readline())
worker = Recorder(Window(0, pid, 'Integration speech playback', 'test player'), 'en', ROOT / 'test-output' / 'sessions', model_key='whistle')
errors = []
saved = []
updates = []
started = time.monotonic()

def status(message):
    print('STATUS', message, flush=True)
    if message == 'Recording':
        player.stdin.write('go\n'); player.stdin.flush()
        QTimer.singleShot(14500, worker.stop)

worker.status.connect(status)
worker.failed.connect(lambda message: (errors.append(message), print('ERROR', message, flush=True)))
worker.saved.connect(saved.append)
worker.transcript.connect(lambda text, pending: (updates.append((text, pending)), print('UPDATE', pending[-100:], flush=True)))
worker.finished.connect(application.quit)
worker.start()
QTimer.singleShot(45000, worker.stop)
application.exec()
worker.wait()
player.wait(timeout=5)
assert not errors, errors
assert saved, 'No document saved'
text = Path(saved[0]).read_text(encoding='utf-8')
assert 'quick brown fox' in text.casefold(), text
assert 'transcription' in text.casefold(), text
session = json.loads((Path(saved[0]).parent / 'session.json').read_text(encoding='utf-8'))
assert session['status'] == 'complete', session
assert (Path(saved[0]).parent / 'Audio.wav').stat().st_size > 44100 * 4
print('PASS: process loopback -> saved WAV -> final transcription -> saved document')
print(text)
print('Elapsed', round(time.monotonic() - started, 2), 'seconds')
