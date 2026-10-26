"""Record first, then transcribe in an isolated cancellable process."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import threading
import wave

import numpy as np
from PySide6.QtCore import QThread, Signal
from model_catalog import BY_KEY, ROOT, model_path, validate_choice
from transcriber import Transcript
from process_control import terminate_tree

def helper_command(arguments):
    executable = Path(sys.executable).with_name('python.exe')
    return [str(executable), '-u', str(ROOT / 'asr_worker.py'), *arguments]

class HelperJob(QThread):
    event = Signal(dict)
    failed = Signal(str)

    def __init__(self, arguments):
        super().__init__()
        self.arguments = arguments
        self.process = None
        self.cancelled = threading.Event()
        self.error = None

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            try:
                terminate_tree(self.process)
            except OSError:
                pass

    def run(self):
        try:
            with (ROOT / 'models' / 'worker.log').open('ab') as log:
                self.process = subprocess.Popen(helper_command(self.arguments), stdout=subprocess.PIPE, stderr=log,
                                                creationflags=subprocess.CREATE_NO_WINDOW)
                if self.cancelled.is_set():
                    self.cancel()
                reported = False
                for line in self.process.stdout:
                    result = json.loads(line.decode('utf-8'))
                    if result.get('kind') == 'error':
                        reported = True
                        raise RuntimeError(result['message'])
                    self.event.emit(result)
                code = self.process.wait()
                if code and not self.cancelled.is_set() and not reported:
                    raise RuntimeError(f'Model worker exited ({code}). Details are in models/worker.log.')
        except Exception as exc:
            if not self.cancelled.is_set():
                self.error = str(exc)
                self.failed.emit(self.error)
        finally:
            if self.process:
                if self.process.poll() is None:
                    terminate_tree(self.process)
                self.process.wait()

class Recorder(QThread):
    status = Signal(str)
    phase_changed = Signal(str)
    transcript = Signal(str, str)
    level = Signal(float)
    saved = Signal(str)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, window, language=None, output=None, model_key='small_en', device='cpu', source_audio=None):
        super().__init__()
        self.window, self.language = window, language
        self.model_key, self.device = model_key, device
        self.output = output or ROOT / 'transcripts'
        self.source_audio = Path(source_audio).resolve() if source_audio else None
        self.stopping = threading.Event()
        self.cancelled = threading.Event()
        self.process = None
        self.document = None
        self.phase = 'idle'
        self.error = None

    def set_phase(self, phase):
        self.phase = phase
        self.phase_changed.emit(phase)

    def stop(self):
        self.stopping.set()
        if self.phase == 'recording' and self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(b'q\n'); self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def cancel(self):
        self.cancelled.set()
        self.stop()
        if self.phase == 'transcribing' and self.process and self.process.poll() is None:
            try:
                terminate_tree(self.process)
            except OSError:
                pass

    def capture(self, audio_path):
        self.set_phase('recording')
        self.process = subprocess.Popen([str(ROOT / 'bin' / 'capture.exe'), str(self.window.pid)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        first = self.process.stderr.readline().decode('utf-8', 'replace').strip()
        if first != 'READY':
            raise RuntimeError(first or 'Windows audio capture could not start.')
        if self.stopping.is_set():
            self.stop()
        self.status.emit('Recording')
        # Only capture here: inference cannot block audio collection.
        with audio_path.open('wb') as storage, wave.open(storage, 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(44100)
            pending = b''
            while True:
                block = self.process.stdout.read1(32768)
                if not block:
                    break
                pending += block
                aligned = len(pending) // 4 * 4
                if aligned:
                    frames, pending = pending[:aligned], pending[aligned:]
                    audio.writeframes(frames)
                    storage.flush()
                    samples = np.frombuffer(frames, dtype='<i2').astype(np.float32) / 32768
                    self.level.emit(float(np.sqrt(np.mean(samples * samples))))
            if pending:
                raise RuntimeError('Audio ended with an incomplete frame; the complete frames were saved.')
        self.process.wait(timeout=5)
        detail = self.process.stderr.read().decode('utf-8', 'replace').strip()
        if self.process.returncode:
            raise RuntimeError(detail or f'Audio capture exited with code {self.process.returncode}.')
        self.document.metadata['capture_ended'] = datetime.now().astimezone().isoformat()

    def final_pass(self, audio_path):
        self.set_phase('transcribing')
        self.document.metadata['status'] = 'transcribing'
        self.document.save()
        self.status.emit('Loading model…')
        arguments = ['transcribe', '--model', self.model_key, '--device', self.device, '--audio', str(audio_path)]
        if self.language:
            arguments.extend(['--language', self.language])
        completed = False
        with (self.document.directory / 'inference.log').open('wb') as log:
            self.process = subprocess.Popen(helper_command(arguments), stdout=subprocess.PIPE, stderr=log,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
            if self.cancelled.is_set():
                self.cancel()
            for line in self.process.stdout:
                event = json.loads(line.decode('utf-8'))
                kind = event.get('kind')
                if kind == 'segment':
                    self.transcript.emit(self.document.append(event['result']), '')
                elif kind == 'progress':
                    self.progress.emit(event['percent'])
                elif kind == 'status':
                    self.status.emit(event['text'])
                elif kind == 'complete':
                    self.document.metadata['inference'] = {key: value for key, value in event.items() if key != 'kind'}
                    completed = True
                elif kind == 'error':
                    raise RuntimeError(event['message'])
            code = self.process.wait()
        if not self.cancelled.is_set() and (code or not completed):
            raise RuntimeError(f'Transcription stopped unexpectedly ({code}). Captured audio is saved; retry it from the menu.')

    def run(self):
        try:
            validate_choice(self.model_key, self.device, self.language)
            if not model_path(self.model_key):
                raise RuntimeError('Download this model in the model picker before recording.')
            self.document = Transcript(self.window, self.language, self.output, self.model_key, self.device)
            self.saved.emit(str(self.document.path))
            if self.source_audio:
                audio_path = self.source_audio
                self.document.metadata['source_audio'] = str(audio_path)
                self.document.metadata['capture_scope'] = 'saved audio'
            else:
                audio_path = self.document.directory / 'Audio.wav'
                self.capture(audio_path)
            if not self.cancelled.is_set():
                self.final_pass(audio_path)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.error = str(exc)
                self.failed.emit(self.error)
        finally:
            if self.process and self.process.poll() is None:
                terminate_tree(self.process)
                self.process.wait()
            if self.document:
                try:
                    self.document.finish(self.error, 'cancelled' if self.cancelled.is_set() else None)
                except Exception as exc:
                    self.error = str(exc)
                    self.failed.emit(f'Could not finish saving: {exc}')
            self.set_phase('idle')
            self.status.emit('Cancelled' if self.cancelled.is_set() else ('Error' if self.error else 'Saved'))
