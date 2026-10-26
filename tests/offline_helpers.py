"""Shared setup for the offline tests: fake capture helpers, a fake model worker, and sample media."""
import math
from pathlib import Path
import shutil
import sys
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / 'test-output' / 'offline'

import capture_jobs

def fresh(name):
    folder = OUTPUT / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder

def fake_backends(failing_capture=False):
    """Route capture and inference to deterministic local stand-ins."""
    capture = str(ROOT / 'tests' / 'fake_capture.py')
    def commands(source, include_mic=False):
        if failing_capture:
            return [[sys.executable, '-c', "import sys; sys.stderr.write('Usage: capture.exe --app PID\\n'); sys.exit(1)"]]
        tone = {'mic': ['1000', '6000']}.get(source.kind, ['440', '8000'])
        result = [[sys.executable, '-u', capture, *tone]]
        if include_mic and source.kind != 'mic':
            result.append([sys.executable, '-u', capture, '1000', '6000'])
        return result
    capture_jobs.capture_commands = commands
    capture_jobs.helper_command = lambda arguments: [sys.executable, '-u', str(ROOT / 'tests' / 'fake_worker.py'), *arguments]
    capture_jobs.model_path = lambda key: ROOT

def tone_file(path, seconds=2.0, rate=22050):
    """A compressed (FLAC) file so imports exercise the decoder rather than the WAV fast path."""
    import av
    samples = (0.3 * np.sin(2 * math.pi * 330 * np.arange(int(seconds * rate)) / rate)).astype(np.float32)
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('flac', rate=rate)
        stream.layout = 'mono'
        frame = av.AudioFrame.from_ndarray((samples * 32767).astype('<i2').reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path

def wav_peaks(path):
    with wave.open(str(path), 'rb') as file:
        rate, channels = file.getframerate(), file.getnchannels()
        samples = np.frombuffer(file.readframes(file.getnframes()), dtype='<i2').reshape(-1, channels)[:, 0].astype(np.float32)
    spectrum = np.abs(np.fft.rfft(samples))
    frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
    return {round(float(frequency)) for frequency in frequencies[np.argsort(spectrum)[-6:]]}, len(samples) / rate
