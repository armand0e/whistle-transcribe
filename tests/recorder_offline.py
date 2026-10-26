"""The real Recorder, end to end, with fake capture helpers and a fake model worker."""
import wave

from offline_helpers import fake_backends, fresh, tone_file, wav_peaks
from PySide6.QtCore import QCoreApplication, QTimer
from capture_jobs import Recorder
from windows_audio import MICROPHONE, SYSTEM_AUDIO, Window

application = QCoreApplication([])
fake_backends()

def run(worker, script=None, timeout=60000):
    record = {'errors': [], 'phases': [], 'progress': [], 'updates': []}
    worker.failed.connect(record['errors'].append)
    worker.phase_changed.connect(record['phases'].append)
    worker.progress.connect(record['progress'].append)
    worker.updated.connect(record['updates'].append)
    if script:
        worker.status.connect(lambda status: script(worker) if status == 'Recording' else None)
    worker.finished.connect(application.quit)
    QTimer.singleShot(timeout, worker.cancel)
    worker.start(); application.exec(); worker.wait()
    return record

# System audio + microphone, with a pause in the middle.
folder = fresh('recorder')
worker = Recorder(SYSTEM_AUDIO, 'en', folder, 'small_en', 'cpu', include_mic=True, vocabulary=' Kubernetes,  OKRs ')
def script(worker):
    QTimer.singleShot(1200, lambda: worker.pause(True))
    QTimer.singleShot(2200, lambda: worker.pause(False))
    QTimer.singleShot(3400, worker.stop)
record = run(worker, script)
assert not record['errors'], record['errors']
assert record['phases'] == ['recording', 'transcribing', 'idle'], record['phases']
metadata = worker.document.metadata
assert metadata['status'] == 'complete' and metadata['capture_scope'] == 'all system audio except Whistle + microphone'
assert 1.7 < worker.recorded_seconds < 3.2, worker.recorded_seconds
peaks, seconds = wav_peaks(worker.document.directory / 'Audio.wav')
assert abs(seconds - worker.recorded_seconds) < 0.05 and abs(metadata['duration'] - seconds) < 0.05
assert any(abs(peak - 440) < 3 for peak in peaks) and any(abs(peak - 1000) < 3 for peak in peaks), peaks
text = worker.document.path.read_text(encoding='utf-8')
assert 'Vocabulary was Kubernetes, OKRs.' in text, text
assert [p[1] for p in worker.document.paragraphs][1] == 'It counts the seconds and finishes sentences.'
assert record['progress'][-1] == 100 and record['updates'][-1] == worker.document.paragraphs
print(f'PASS: two streams mixed live; pause excluded {3.4 - worker.recorded_seconds:.1f} s; vocabulary reached the model', flush=True)

# Microphone only.
worker = Recorder(MICROPHONE, None, folder, 'small_en', 'cpu', include_mic=True)
record = run(worker, lambda worker: QTimer.singleShot(800, worker.stop))
peaks, _ = wav_peaks(worker.document.directory / 'Audio.wav')
assert not record['errors'] and not worker.include_mic and worker.document.metadata['capture_scope'] == 'default microphone'
assert any(abs(peak - 1000) < 3 for peak in peaks) and not any(abs(peak - 440) < 3 for peak in peaks), peaks
print('PASS: microphone-only capture', flush=True)

# Cancel while recording keeps the audio.
worker = Recorder(SYSTEM_AUDIO, 'en', folder, 'small_en', 'cpu')
record = run(worker, lambda worker: QTimer.singleShot(700, worker.cancel))
assert not record['errors'] and worker.document.metadata['status'] == 'cancelled'
assert (worker.document.directory / 'Audio.wav').stat().st_size > 44
assert all(process.poll() is not None for process in worker.captures)
print('PASS: cancelling a recording stops helpers and keeps captured audio', flush=True)

# Import any media file: it is decoded to 16 kHz mono WAV, then transcribed.
source = tone_file(folder / 'clip.flac')
worker = Recorder(Window(0, 0, 'clip', 'Imported file', kind='file'), 'en', folder, 'small_en', 'cpu', source_audio=source)
record = run(worker)
assert not record['errors'], record['errors']
assert record['phases'] == ['preparing', 'transcribing', 'idle'], record['phases']
converted = worker.document.directory / 'Audio.wav'
with wave.open(str(converted), 'rb') as file:
    assert (file.getframerate(), file.getnchannels(), file.getsampwidth()) == (16000, 1, 2)
    assert abs(file.getnframes() / 16000 - 2.0) < 0.05
peaks, _ = wav_peaks(converted)
assert any(abs(peak - 330) < 3 for peak in peaks), peaks
assert worker.document.metadata['source_audio'] == str(source.resolve()) and source.is_file()
print('PASS: compressed import converted to WAV and transcribed; original untouched', flush=True)

# A saved WAV is referenced, not copied.
worker = Recorder(Window(0, 0, 'rerun', 'saved audio', kind='file'), 'en', folder, 'whistle', 'cpu', source_audio=converted)
record = run(worker)
assert not record['errors'] and record['phases'] == ['transcribing', 'idle']
assert not (worker.document.directory / 'Audio.wav').exists()
assert 'Vocabulary was empty.' in worker.document.path.read_text(encoding='utf-8')
print('PASS: WAV re-transcription references the original recording', flush=True)

# Unreadable files and broken helpers fail visibly, never as "complete".
bad = folder / 'invalid.mp3'
bad.write_bytes(b'not audio at all')
worker = Recorder(Window(0, 0, 'bad', 'Imported file', kind='file'), 'en', folder, 'small_en', 'cpu', source_audio=bad)
record = run(worker)
assert record['errors'] and worker.document.metadata['status'] == 'error', record
assert bad.read_bytes() == b'not audio at all'
fake_backends(failing_capture=True)
worker = Recorder(SYSTEM_AUDIO, 'en', folder, 'small_en', 'cpu')
record = run(worker)
assert record['errors'] and 'out of date' in record['errors'][0], record['errors']
assert worker.document.metadata['status'] == 'error'
print('PASS: unreadable media and an outdated capture helper report clear errors', flush=True)
