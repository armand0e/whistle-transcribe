"""Real Windows endpoints, not stand-ins. Run --sender in a SEPARATE process tree first."""
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave
import winsound

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer
from capture_jobs import Recorder
from windows_audio import SYSTEM_AUDIO

OUTPUT = ROOT / 'test-output' / 'windows-sources'
OUTPUT.mkdir(parents=True, exist_ok=True)

def tone(path, frequency):
    samples = (np.sin(2 * np.pi * frequency * np.arange(44100) / 44100) * 5000).astype('<i2')
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(44100)
        audio.writeframes(samples.tobytes())

if '--sender' in sys.argv:
    for marker in ('play', 'stop'):
        (OUTPUT / marker).unlink(missing_ok=True)
    path = OUTPUT / 'external-440.wav'
    tone(path, 440)
    (OUTPUT / 'sender-ready').write_text(str(__import__('os').getpid()))
    print('Waiting for the separate system-capture test', flush=True)
    deadline = time.monotonic() + 100
    while not (OUTPUT / 'play').exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
    print('External 440 Hz playback started', flush=True)
    while not (OUTPUT / 'stop').exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    winsound.PlaySound(None, 0)
    print('External playback stopped', flush=True)
    sys.exit(0)

def native(arguments, seconds, on_ready=None):
    process = subprocess.Popen([str(ROOT / 'bin' / 'capture.exe'), *arguments], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    blocks = []
    def drain():
        while block := process.stdout.read1(32768):
            blocks.append(block)
    reader = threading.Thread(target=drain, daemon=True); reader.start()
    first = process.stderr.readline().decode('utf-8', 'replace').strip()
    if first != 'READY':
        process.wait(timeout=20); reader.join(timeout=3)
        return b'', first
    if on_ready:
        on_ready()
    start = time.monotonic()
    time.sleep(seconds)
    process.stdin.write(b'q\n'); process.stdin.flush()
    process.wait(timeout=8)
    reader.join(timeout=3)
    assert process.returncode == 0, process.returncode
    return b''.join(blocks), time.monotonic() - start

results = {}
try:
    assert (OUTPUT / 'sender-ready').is_file(), 'Run --sender as a separate tool process first'
    own = OUTPUT / 'own-660.wav'; tone(own, 660)
    def play():
        winsound.PlaySound(str(own), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        (OUTPUT / 'play').write_text('go')
    raw, elapsed = native(['--system', str(__import__('os').getpid())], 2.5, play)
    winsound.PlaySound(None, 0)
    assert isinstance(elapsed, float), elapsed
    samples = np.frombuffer(raw, '<i2').reshape(-1, 2).mean(axis=1)
    # Inspect the middle, after both playback devices have started.
    samples = samples[22050:-11025]
    frequencies = np.fft.rfftfreq(len(samples), 1 / 44100)
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    def amplitude(hz):
        return float(np.max(spectrum[np.abs(frequencies - hz) < 4]))
    external, excluded = amplitude(440), amplitude(660)
    assert external > 100000 and excluded < external * 0.03, (external, excluded)
    results['system'] = {'external_440': external, 'excluded_660': excluded, 'seconds': len(raw) / 176400}
    print('PASS: real system capture includes unrelated playback and excludes its own playback', flush=True)

    raw, elapsed = native(['--mic'], 1.5)
    if isinstance(elapsed, str):
        results['mic'] = {'available': False, 'message': Recorder.explain(elapsed)}
        print('MIC UNAVAILABLE:', results['mic']['message'], flush=True)
    else:
        seconds = len(raw) / 176400
        assert 1.2 < seconds < 2.0, seconds
        results['mic'] = {'available': True, 'seconds': seconds,
                          'rms': float(np.sqrt(np.mean(np.frombuffer(raw, '<i2').astype(float) ** 2)))}
        print('PASS: actual default microphone starts, emits PCM, and stops cleanly', flush=True)

    application = QCoreApplication([])
    job = Recorder(SYSTEM_AUDIO, 'en', OUTPUT / 'sessions', 'whistle', 'cpu', include_mic=results['mic']['available'])
    errors, checkpoints = [], []
    job.failed.connect(errors.append)
    def ready(status):
        if status == 'Recording':
            QTimer.singleShot(650, lambda: job.pause(True))
            QTimer.singleShot(850, lambda: checkpoints.append(job.recorded_seconds))
            QTimer.singleShot(1200, lambda: checkpoints.append(job.recorded_seconds))
            QTimer.singleShot(1300, lambda: job.pause(False))
            QTimer.singleShot(2100, job.stop)
    job.status.connect(ready)
    job.finished.connect(application.quit)
    job.start(); application.exec(); job.wait()
    assert not errors, errors
    assert len(checkpoints) == 2 and checkpoints[0] == checkpoints[1], checkpoints
    assert 1.1 < job.recorded_seconds < 1.8, job.recorded_seconds
    assert job.document.metadata['status'] == 'complete'
    results['recorder'] = {'include_mic': job.include_mic, 'seconds': job.recorded_seconds,
                           'paused_checkpoints': checkpoints, 'document': str(job.document.path)}
    print('PASS: real system/mic recorder pause, resume, stop, and final model pass', flush=True)
finally:
    winsound.PlaySound(None, 0)
    (OUTPUT / 'stop').write_text('stop')
    (OUTPUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
