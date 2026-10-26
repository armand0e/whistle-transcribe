"""Record first, then transcribe in an isolated cancellable process."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

import numpy as np
from PySide6.QtCore import QThread, Signal
from model_catalog import BY_KEY, ROOT, model_path, validate_choice
from transcriber import Transcript
from process_control import NO_WINDOW, terminate_tree

RATE, FRAME = 44100, 4  # Native capture: 44.1 kHz stereo PCM16.
MAX_SKEW = RATE * FRAME // 2  # Pad a stalled source after half a second.
CAPTURE_EXE = ROOT / 'bin' / 'capture.exe'

def helper_command(arguments):
    executable = Path(sys.executable)
    if sys.platform == 'win32':
        executable = executable.with_name('python.exe')  # pythonw has no stdout pipe.
    return [str(executable), '-u', str(ROOT / 'asr_worker.py'), *arguments]

def capture_commands(source, include_mic=False):
    """One native capture process per stream; streams are mixed while recording."""
    executable = str(CAPTURE_EXE)
    if source.kind == 'mic':
        return [[executable, '--mic']]
    if source.kind == 'system':
        # Everything except Whistle itself, so playback in the library is never recorded.
        commands = [[executable, '--system', str(os.getpid())]]
    else:
        commands = [[executable, '--app', str(source.pid)]]
    if include_mic:
        commands.append([executable, '--mic'])
    return commands

def capture_scope(source, include_mic=False):
    scope = {'system': 'all system audio except Whistle', 'mic': 'default microphone'}.get(
        source.kind, 'selected process and its children')
    return scope + (' + microphone' if include_mic and source.kind != 'mic' else '')

def is_pcm16_wav(path):
    try:
        with wave.open(str(path), 'rb') as file:
            return file.getsampwidth() == 2 and file.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False

def mix(chunks):
    if len(chunks) == 1:
        return chunks[0]
    total = sum(np.frombuffer(chunk, dtype='<i2').astype(np.int32) for chunk in chunks)
    return np.clip(total, -32768, 32767).astype('<i2').tobytes()

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
            (ROOT / 'models').mkdir(exist_ok=True)
            with (ROOT / 'models' / 'worker.log').open('ab') as log:
                self.process = subprocess.Popen(helper_command(self.arguments), stdout=subprocess.PIPE, stderr=log,
                                                creationflags=NO_WINDOW)
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
    updated = Signal(list)
    level = Signal(float)
    saved = Signal(str)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, window, language=None, output=None, model_key='small_en', device='cpu', source_audio=None,
                 include_mic=False, vocabulary='', title=None):
        super().__init__()
        self.window, self.language = window, language
        self.model_key, self.device = model_key, device
        self.include_mic = include_mic and window.kind != 'mic'
        self.vocabulary = ' '.join(vocabulary.split()) if vocabulary else ''
        self.title = title
        self.output = output or ROOT / 'transcripts'
        self.source_audio = Path(source_audio).resolve() if source_audio else None
        self.stopping = threading.Event()
        self.cancelled = threading.Event()
        self.paused = threading.Event()
        self.process = None
        self.captures = []
        self.frames = 0
        self.warnings = []
        self.document = None
        self.phase = 'idle'
        self.error = None

    @property
    def recorded_seconds(self):
        return self.frames / RATE

    def set_phase(self, phase):
        self.phase = phase
        self.phase_changed.emit(phase)

    def pause(self, paused=True):
        if paused:
            self.paused.set()
        else:
            self.paused.clear()

    def stop(self):
        self.stopping.set()
        if self.phase == 'recording':
            for process in list(self.captures):
                if process.poll() is None:
                    try:
                        process.stdin.write(b'q\n'); process.stdin.flush()
                    except (OSError, ValueError):
                        pass

    def cancel(self):
        self.cancelled.set()
        self.stop()
        if self.phase in ('preparing', 'transcribing') and self.process and self.process.poll() is None:
            try:
                terminate_tree(self.process)
            except OSError:
                pass

    @staticmethod
    def explain(message):
        if message.startswith('Usage'):
            return 'The capture helper is out of date. Run build-capture.cmd, then try again.'
        if 'microphone access denied' in message.casefold():
            return ('Windows blocked microphone access. Turn on Settings › Privacy & security › Microphone › '
                    'Let desktop apps access your microphone.')
        return message or 'Windows audio capture could not start.'

    def start_captures(self):
        for command in capture_commands(self.window, self.include_mic):
            if not Path(command[0]).is_file():
                raise RuntimeError('The capture helper is missing. Run build-capture.cmd, then try again.')
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=NO_WINDOW)
            self.captures.append(process)
            first = process.stderr.readline().decode('utf-8', 'replace').strip()
            if first != 'READY':
                detail = (first + ' ' + process.stderr.read().decode('utf-8', 'replace')).strip() if process.poll() is not None else first
                raise RuntimeError(self.explain(detail))

    def capture(self, audio_path):
        self.set_phase('recording')
        self.start_captures()
        if self.stopping.is_set():
            self.stop()
        self.status.emit('Recording')
        buffers = [bytearray() for _ in self.captures]
        ended = [False] * len(self.captures)
        lock = threading.Lock()
        def read(index, process):
            while True:
                block = process.stdout.read1(32768)
                if not block:
                    break
                with lock:
                    buffers[index].extend(block)
            with lock:
                ended[index] = True
        readers = [threading.Thread(target=read, args=item, daemon=True) for item in enumerate(self.captures)]
        for reader in readers:
            reader.start()
        # Only capture here: inference cannot block audio collection.
        with audio_path.open('wb') as storage, wave.open(storage, 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(RATE)
            while True:
                time.sleep(0.03)
                with lock:
                    finished = all(ended)
                    lengths = [len(buffer) // FRAME * FRAME for buffer in buffers]
                    take = min(lengths)
                    if len(buffers) > 1:
                        # A source that ended or stalled is treated as silence, keeping the mix in time.
                        longest = max(lengths)
                        for index, buffer in enumerate(buffers):
                            if lengths[index] < longest and (ended[index] or longest - lengths[index] > MAX_SKEW):
                                buffer.extend(bytes(longest - lengths[index]))
                                lengths[index] = longest
                        take = min(lengths)
                    chunks = [bytes(buffer[:take]) for buffer in buffers]
                    for buffer in buffers:
                        del buffer[:take]
                    leftover = any(buffers)
                if take:
                    frames = mix(chunks)
                    samples = np.frombuffer(frames, dtype='<i2').astype(np.float32) / 32768
                    self.level.emit(0.0 if self.paused.is_set() else float(np.sqrt(np.mean(samples * samples))))
                    if not self.paused.is_set():
                        audio.writeframes(frames)
                        storage.flush()
                        self.frames += len(frames) // FRAME
                if finished:
                    if leftover and len(buffers) == 1:
                        self.warnings.append('Audio ended with an incomplete frame; the complete frames were saved.')
                    break
        for process in self.captures:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                terminate_tree(process)
                process.wait()
        problems = [self.explain(process.stderr.read().decode('utf-8', 'replace').strip()
                                 or f'Audio capture exited with code {process.returncode}.')
                    for process in self.captures if process.returncode]
        self.document.metadata['capture_ended'] = datetime.now().astimezone().isoformat()
        self.document.metadata['duration'] = self.recorded_seconds
        if problems and not self.frames:
            raise RuntimeError(problems[0])
        # Keep what was captured; a mid-recording device loss should not discard the session.
        self.warnings.extend(problems)

    def run_helper(self, arguments, log_name, handle):
        completed = False
        with (self.document.directory / log_name).open('ab') as log:
            self.process = subprocess.Popen(helper_command(arguments), stdout=subprocess.PIPE, stderr=log,
                                            creationflags=NO_WINDOW)
            if self.cancelled.is_set():
                self.cancel()
            for line in self.process.stdout:
                event = json.loads(line.decode('utf-8'))
                kind = event.get('kind')
                if kind == 'progress':
                    self.progress.emit(event['percent'])
                elif kind == 'status':
                    self.status.emit(event['text'])
                elif kind == 'error':
                    raise RuntimeError(event['message'])
                elif handle(event):
                    completed = True
            code = self.process.wait()
        return code, completed

    def convert(self, source, target):
        self.set_phase('preparing')
        self.document.metadata['status'] = 'preparing'
        self.document.save()
        self.status.emit('Preparing audio…')
        code, completed = self.run_helper(['convert', '--audio', str(source), '--output', str(target)], 'inference.log',
                                          lambda event: event.get('kind') == 'converted')
        if not self.cancelled.is_set() and (code or not completed):
            raise RuntimeError(f'Whistle could not read this file ({code}). See inference.log for details.')
        self.document.metadata['converted_audio'] = str(target)

    def final_pass(self, audio_path):
        self.set_phase('transcribing')
        self.document.metadata['status'] = 'transcribing'
        self.document.save()
        self.status.emit('Loading model…')
        arguments = ['transcribe', '--model', self.model_key, '--device', self.device, '--audio', str(audio_path)]
        if self.language:
            arguments.extend(['--language', self.language])
        if self.vocabulary and BY_KEY[self.model_key].vocabulary:
            arguments.extend(['--vocabulary', self.vocabulary])
        def handle(event):
            if event.get('kind') == 'segment':
                self.transcript.emit(self.document.append(event['result']), '')
                self.updated.emit([list(paragraph) for paragraph in self.document.paragraphs])
            elif event.get('kind') == 'complete':
                details = {key: value for key, value in event.items() if key != 'kind'}
                self.document.metadata['inference'] = details
                self.document.metadata.setdefault('duration', details.get('duration'))
                if details.get('language') and self.document.metadata.get('language') == 'auto':
                    self.document.metadata['detected_language'] = details['language']
                return True
            return False
        code, completed = self.run_helper(arguments, 'inference.log', handle)
        if not self.cancelled.is_set() and (code or not completed):
            raise RuntimeError(f'Transcription stopped unexpectedly ({code}). Captured audio is saved; transcribe it again from the library.')

    def run(self):
        try:
            validate_choice(self.model_key, self.device, self.language)
            if not model_path(self.model_key):
                raise RuntimeError('Download this model in Settings › Models before recording.')
            self.document = Transcript(self.window, self.language, self.output, self.model_key, self.device,
                                       title=self.title, vocabulary=self.vocabulary or None)
            self.document.metadata['capture_scope'] = capture_scope(self.window, self.include_mic)
            self.saved.emit(str(self.document.path))
            if self.source_audio:
                audio_path = self.source_audio
                self.document.metadata['source_audio'] = str(audio_path)
                self.document.metadata['capture_scope'] = 'saved audio'
                if not is_pcm16_wav(audio_path):
                    audio_path = self.document.directory / 'Audio.wav'
                    self.convert(self.source_audio, audio_path)
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
            for process in [self.process, *self.captures]:
                if process and process.poll() is None:
                    terminate_tree(process)
                    process.wait()
            if self.document:
                if self.warnings:
                    self.document.metadata['warnings'] = self.warnings
                try:
                    self.document.finish(self.error, 'cancelled' if self.cancelled.is_set() else None)
                except Exception as exc:
                    self.error = str(exc)
                    self.failed.emit(f'Could not finish saving: {exc}')
            self.set_phase('idle')
            self.status.emit('Cancelled' if self.cancelled.is_set() else ('Error' if self.error else 'Saved'))
