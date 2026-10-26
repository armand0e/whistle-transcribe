"""Real final-pass jobs on a fixed saved recording, for CPU and NVIDIA CUDA."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication
from capture_jobs import Recorder
from windows_audio import Window

application = QCoreApplication([])
source = ROOT / 'transcripts' / '2026-10-15_15-53-15-462103' / 'Audio.wav'
original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
results = {}
for model, device in [('whistle', 'cpu'), ('small_en', 'cpu'), ('small_en', 'cuda'),
                      ('phonon2', 'cpu'), ('nemotron35', 'cpu'), ('nemotron35', 'cuda')]:
    worker = Recorder(Window(0, 0, 'Normal-speed lecture model test', 'saved audio'), 'en',
                      ROOT / 'test-output' / 'models', model, device, source_audio=source)
    errors, phases, updates = [], [], []
    worker.failed.connect(errors.append)
    worker.phase_changed.connect(phases.append)
    worker.transcript.connect(lambda text, pending: updates.append(text))
    worker.finished.connect(application.quit)
    start = time.perf_counter()
    worker.start(); application.exec(); worker.wait()
    elapsed = time.perf_counter() - start
    assert not errors, (model, device, errors)
    document = worker.document
    assert document.metadata['status'] == 'complete', document.metadata
    assert document.metadata['model'] == model and document.metadata['device'] == device
    text = document.path.read_text(encoding='utf-8')
    assert 'genome annotation pipeline' in text.lower(), text
    assert 'coding sequence' in text.lower(), text
    assert 'transcribing' in phases and 'recording' not in phases
    assert updates
    assert not (document.directory / 'Audio.wav').exists(), 'Saved-audio rerun should reference the original without copying it'
    results.setdefault(model, {})[device] = {'elapsed_seconds': round(elapsed, 2),
        'inference': document.metadata['inference'], 'transcript': str(document.path),
        'source': str(source), 'audio_seconds': 56.14}
    print(f'PASS {model}/{device}: {elapsed:.2f} s; {document.path}', flush=True)
assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
(ROOT / 'models' / 'benchmarks.json').write_text(json.dumps({
    'note': 'One 56.14-second biology lecture clip. Elapsed includes process startup/model load. Not a verified quality ranking.',
    'source_sha256': original_hash, 'results': results}, indent=2), encoding='utf-8')
print('PASS: six real model/device jobs; model metadata, document persistence, and original audio integrity verified')
