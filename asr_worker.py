"""Isolated model download / transcription process. stdout is JSON events."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import wave
import contextlib
import subprocess

from model_catalog import BY_KEY, CACHE, ROOT, model_path, validate_choice, nemo_executable

os.environ['NEEDLE_TELEMETRY'] = '0'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['NEEDLE3_LIB_PATH'] = str(ROOT / 'models' / 'libneedle.dll')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

def emit(kind, **data):
    print(json.dumps({'kind': kind, **data}, ensure_ascii=False), flush=True)

def download(key):
    if model_path(key) and (key != 'nemotron35' or (nemo_executable('cpu') and nemo_executable('cuda'))):
        emit('ready', model=key)
        return
    model = BY_KEY[key]
    if key == 'phonon2':
        os.environ['FERMION_CACHE_DIR'] = str(ROOT / 'models' / 'phonon')
        from fermion.transcribe import _resolve
        from fermion._speech import fetch
        repo, profile, pin, _ = _resolve('phonon-2')
        emit('status', text='Downloading Phonon-2 (164 MB)…')
        with contextlib.redirect_stdout(sys.stderr):
            fetch.ensure(repo, profile, pin)
        emit('ready', model=key)
        return
    if key == 'nemotron35':
        from setup_nemotron import install
        with contextlib.redirect_stdout(sys.stderr):
            install()
        from huggingface_hub import hf_hub_download
        emit('status', text='Downloading Nemotron Q8 model…')
        hf_hub_download(model.repo, 'nemotron-3.5-asr-streaming-0.6b.q8_0.gguf', cache_dir=str(CACHE))
        emit('ready', model=key)
        return
    if not model.repo:
        raise RuntimeError('Whistle files are missing. Run setup_models.py first.')
    emit('status', text=f'Downloading {model.name} ({model.size})…')
    from huggingface_hub import snapshot_download
    snapshot_download(model.repo, cache_dir=str(CACHE), max_workers=2,
                      allow_patterns=['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*'])
    if not model_path(key):
        raise RuntimeError('Model download is incomplete. Download again to resume.')
    emit('ready', model=key)

def transcribe(args):
    validate_choice(args.model, args.device, args.language)
    path = model_path(args.model)
    if path is None:
        raise RuntimeError('This model is not installed. Download it in the model picker, then retry your saved audio.')
    started = time.perf_counter()
    import numpy as np
    import soxr
    with wave.open(str(args.audio), 'rb') as file:
        if file.getsampwidth() != 2:
            raise RuntimeError('Choose a PCM16 WAV recording.')
        rate, channels = file.getframerate(), file.getnchannels()
        samples = np.frombuffer(file.readframes(file.getnframes()), dtype='<i2').reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768
    duration = len(samples) / rate
    if not len(samples) or float(np.max(np.abs(samples))) < 0.0001:
        emit('complete', duration=duration, elapsed_seconds=time.perf_counter() - started, device=args.device)
        return
    language = 'en' if BY_KEY[args.model].english_only else args.language
    if args.model == 'phonon2':
        os.environ['FERMION_DEVICE'] = 'cpu'
        os.environ['FERMION_CACHE_DIR'] = str(ROOT / 'models' / 'phonon')
        os.environ['FERMION_CPU_THREADS'] = '8'
        emit('status', text='Loading Phonon-2 on CPU…')
        with contextlib.redirect_stdout(sys.stderr):
            import fermion
            model = fermion.load_speech(str(path))
            details = model.transcribe_detailed(str(args.audio))
        if details.truncated:
            raise RuntimeError('Phonon reported a truncated transcription. Audio is saved; retry with another model.')
        for segment in details.segments:
            words = [word for word in details.words if segment['start'] <= word['start'] < segment['end']]
            emit('segment', result={'text': segment['text'], 'words': words, 'start': segment['start'], 'received': segment['end']})
            emit('progress', percent=min(99, round(100 * segment['end'] / duration)))
        compute_type = 'five-value CPU'
    elif args.model == 'nemotron35':
        binary = nemo_executable(args.device)
        if not binary:
            raise RuntimeError('Nemotron native runtime is missing. Download Nemotron again in the model picker.')
        if args.device == 'cuda':
            from gpu_support import configure_cuda, gpu_info
            info = gpu_info()
            if info['free_mb'] < BY_KEY[args.model].gpu_budget_mb + 1024:
                raise RuntimeError('Insufficient free NVIDIA VRAM for Nemotron. Select CPU or a smaller model.')
            configure_cuda()
        emit('status', text=f'Running Nemotron on {args.device.upper()}…')
        command = [str(binary), 'transcribe', str(args.audio.resolve()), '--model', str(path),
                   '--device', args.device, '--language', {'en': 'en-US', 'de': 'de-DE', 'fr': 'fr-FR', 'es': 'es-ES', 'it': 'it-IT', 'nl': 'nl-NL', 'pl': 'pl-PL'}.get(language, language or 'auto'), '--format', 'json']
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=sys.stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(f'Nemotron exited ({result.returncode}); see inference.log. Select CPU if CUDA is unavailable.')
        details = json.loads(result.stdout.decode('utf-8-sig'))
        emit('native_result', result=details)
        # Native JSON shape is normalized below after validating its schema.
        words = details.get('words') or []
        text = details.get('text', '')
        if not text and details.get('results'):
            text = ' '.join(item.get('text', '') for item in details['results'])
        if not text:
            raise RuntimeError('Nemotron returned no recognized transcript field. See saved worker output.')
        if words:
            sentence = []
            for index, word in enumerate(words):
                sentence.append(word)
                if word['word'].endswith(('.', '!', '?')) or word['end'] - sentence[0]['start'] > 30 or index == len(words) - 1:
                    emit('segment', result={'text': ' '.join(item['word'] for item in sentence), 'words': sentence,
                                           'start': sentence[0]['start'], 'received': sentence[-1]['end']})
                    emit('progress', percent=min(99, round(100 * sentence[-1]['end'] / duration)))
                    sentence = []
        else:
            emit('segment', result={'text': text.strip(), 'words': [], 'start': 0, 'received': duration})
        compute_type = 'Q8_0'
    elif args.model == 'whistle':
        from needle import Whistle
        model = Whistle(weights=path)
        samples = soxr.resample(samples, rate, 16000).astype(np.float32)
        position = 0
        while position < len(samples):
            end = min(position + 28 * 16000, len(samples))
            if end < len(samples):
                candidates = np.arange(position + 18 * 16000, end, 1600)
                energies = [np.mean(samples[p-1600:p+1600] ** 2) for p in candidates]
                end = int(candidates[int(np.argmin(energies))])
            result = model.transcribe(samples[position:end], language=language, word_timestamps=True)
            for word in result.get('words', []):
                word['start'] += position / 16000
                word['end'] += position / 16000
            result['received'] = end / 16000
            if not result.get('words'):
                result['start'] = position / 16000
            emit('segment', result=result)
            emit('progress', percent=round(100 * end / len(samples)))
            position = end
        compute_type = 'native'
    else:
        compute_type = 'int8'
        if args.device == 'cuda':
            from gpu_support import cuda_probe
            info = cuda_probe()
            required = BY_KEY[args.model].gpu_budget_mb + 1024
            if info['free_mb'] < required:
                raise RuntimeError(f"Not enough free NVIDIA VRAM for {BY_KEY[args.model].name}: {info['free_mb']} MB free; reserve at least {required} MB. Select CPU or a smaller model.")
            compute_type = info['compute_type']
        emit('status', text=f'Loading {BY_KEY[args.model].name} on {args.device.upper()}…')
        from faster_whisper import WhisperModel
        model = WhisperModel(str(path), device=args.device, compute_type=compute_type,
                             cpu_threads=min(8, max(2, (os.cpu_count() or 4) // 2)), num_workers=1)
        emit('status', text='Transcribing…')
        # VAD removes long silence while retaining original recording timestamps.
        audio_16k = soxr.resample(samples, rate, 16000).astype(np.float32) if rate != 16000 else samples
        segments, info = model.transcribe(audio_16k, language=language, beam_size=5,
                                         word_timestamps=True, vad_filter=True)
        for segment in segments:
            result = {'text': segment.text.strip(), 'words': [
                {'word': word.word.strip(), 'start': word.start, 'end': word.end, 'probability': word.probability}
                for word in (segment.words or [])], 'start': segment.start, 'received': segment.end,
                'language': info.language}
            emit('segment', result=result)
            emit('progress', percent=min(99, round(100 * segment.end / duration)))
    emit('complete', duration=duration, elapsed_seconds=time.perf_counter() - started,
         device=args.device, compute_type=compute_type)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['download', 'transcribe', 'probe'])
    parser.add_argument('--model', choices=BY_KEY, default='small_en')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--language')
    args = parser.parse_args()
    try:
        if args.action == 'probe':
            from gpu_support import cuda_probe
            emit('probe', **cuda_probe())
        elif args.action == 'download':
            download(args.model)
        else:
            if args.audio is None:
                raise ValueError('Select a saved WAV recording.')
            transcribe(args)
    except Exception as exc:
        emit('error', message=str(exc))
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
