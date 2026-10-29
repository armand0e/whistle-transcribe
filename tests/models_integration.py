"""Real final-pass jobs on a fixed saved recording, for CPU and NVIDIA CUDA."""
import hashlib
import json
from pathlib import Path
import sys
import argparse
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtCore import QCoreApplication
from capture_jobs import Recorder
from windows_audio import Window


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audio', type=Path, required=True, help='Existing PCM16 WAV to test without modifying it')
parser.add_argument('--expect', action='append', default=[], help='Optional expected text fragment')
parser.add_argument('--write-benchmarks', action='store_true', help='Explicitly replace models/benchmarks.json')
args = parser.parse_args()

application = QCoreApplication([])
source = args.audio.resolve()
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
    for phrase in args.expect:
        assert phrase.casefold() in text.casefold(), text
    assert 'transcribing' in phases and 'recording' not in phases
    assert updates
    assert not (document.directory / 'Audio.wav').exists(), 'Saved-audio rerun should reference the original without copying it'
    results.setdefault(model, {})[device] = {'elapsed_seconds': round(elapsed, 2),
        'inference': document.metadata['inference'], 'transcript': str(document.path),
        'source': str(source), 'audio_seconds': document.metadata['inference']['duration']}
    print(f'PASS {model}/{device}: {elapsed:.2f} s; {document.path}', flush=True)
assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
(ROOT / ('models' if args.write_benchmarks else 'test-output') / 'benchmarks.json').write_text(json.dumps({
    'note': 'One user-supplied WAV clip. Elapsed includes process startup/model load. Not a verified quality ranking.',
    'source_sha256': original_hash, 'results': results}, indent=2), encoding='utf-8')
print('PASS: six real model/device jobs; model metadata, document persistence, and original audio integrity verified')
