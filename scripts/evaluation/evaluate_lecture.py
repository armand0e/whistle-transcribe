"""Controlled local Whistle comparison; never modifies the source recording."""
import argparse
import hashlib
import json
import time
import wave
from pathlib import Path

import numpy as np
import soxr
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from transcriber import load_model, timestamp

ROOT = Path(__file__).resolve().parents[2]
SOURCE = None
OUT = None
# Lecture-informed development vocabulary, fixed before generating variants.
# Broad terminology plus tools named in the existing draft; not a held-out test.
GLOSSARY = [
    'DNA', 'RNA', 'genome', 'gene', 'genes', 'genomics', 'bioinformatics',
    'prokaryotes', 'prokaryotic', 'eukaryotes', 'eukaryotic', 'bacteria',
    'archaea', 'Eukarya', 'coding sequence', 'CDS', 'open reading frame', 'ORF',
    'operon', 'annotation', 'structural RNA', 'non-coding RNA', 'ncRNA',
    'transfer RNA', 'tRNA', 'tRNAs', 'messenger RNA', 'mRNA', 'ribosomal RNA',
    'rRNA', 'rRNAs', 'small RNA', 'sRNA', 'regulatory RNA', 'long non-coding RNA',
    'spliceosomal RNA', 'riboswitches', 'ribosome', 'peptide bond', 'codon',
    'anticodon', 'anticodon stem loop', 'cloverleaf', 'stem', 'loop',
    '16S', '23S', '5S', '5.8S', '18S', '28S', 'tRNAscan-SE', 'Todd Lowe',
    'RNAmmer', 'BLAST', 'protein', 'nucleotide', 'transcription', 'translation',
]

def load_audio():
    with wave.open(str(SOURCE / 'Audio.wav')) as audio:
        if audio.getsampwidth() != 2:
            raise ValueError('Choose a PCM16 WAV recording.')
        channels = audio.getnchannels()
        rate = audio.getframerate()
        raw = audio.readframes(audio.getnframes())
    mono = np.frombuffer(raw, dtype='<i2').reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768
    return mono, rate

def stream_chunks(mono, rate):
    resampler = soxr.ResampleStream(rate, 16000, 1, dtype='float32')
    for start in range(0, len(mono), rate):
        end = min(start + rate, len(mono))
        yield resampler.resample_chunk(mono[start:end], last=end == len(mono))

def sections(samples):
    # Shared 18-28 second sections, with cuts at low-energy 200 ms regions.
    # Windows are contiguous, with no duplicated or discarded samples.
    boundaries = [0]
    start = 0
    while len(samples) - start > 28 * 16000:
        candidates = np.arange(start + 18 * 16000, start + 28 * 16000, 1600)
        energies = [np.mean(samples[p-1600:p+1600] ** 2) for p in candidates]
        # Among similarly quiet locations, prefer a longer context.
        minimum = min(energies)
        quiet = [int(p) for p, energy in zip(candidates, energies) if energy <= minimum * 1.2 + 1e-9]
        start = quiet[-1]
        boundaries.append(start)
    boundaries.append(len(samples))
    return list(zip(boundaries[:-1], boundaries[1:]))

def save_text(name, results, mode):
    header = f'WHISTLE COMPARISON: {name}\nSource: {SOURCE.name}\n\n'
    paragraphs = []
    for item in results:
        text = item.get('text', '').strip()
        if not text:
            continue
        words = item.get('words') or []
        sec = item.get('section_start', words[0].get('start', 0) if words else item.get('received', 0))
        if mode == 'long' or not paragraphs or paragraphs[-1][1].rstrip('\"”').endswith(('.', '!', '?')):
            paragraphs.append([sec, text])
        else:
            paragraphs[-1][1] += ' ' + text
    (OUT / f'{name}.txt').write_text(header + ''.join(f'[{timestamp(sec)}] {text}\n\n' for sec, text in paragraphs), encoding='utf-8')

def main():
    global SOURCE, OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['all', 'stream', 'long'], default='all')
    parser.add_argument('--source', type=Path, required=True, help='Saved session directory containing Audio.wav')
    args = parser.parse_args()
    SOURCE = args.source.resolve()
    OUT = SOURCE / 'quality-comparison'
    OUT.mkdir(exist_ok=True)
    mono, rate = load_audio()
    samples = soxr.resample(mono, rate, 16000).astype(np.float32)
    spans = sections(samples)
    manifest = {'source_sha256': hashlib.sha256((SOURCE / 'Audio.wav').read_bytes()).hexdigest(),
                'original_transcript_sha256': hashlib.sha256((SOURCE / 'Transcript.txt').read_bytes()).hexdigest(),
                'duration_seconds': len(mono) / rate, 'glossary': GLOSSARY,
                'sections_seconds': [[a / 16000, b / 16000] for a, b in spans],
                'notes': 'Lecture-informed development comparison. Playback speed is baked into recording. No ground-truth WER.'}
    (OUT / 'experiment.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    model = load_model()
    for mode in ['stream', 'long']:
        if args.mode not in ('all', mode):
            continue
        for label, language, glossary in [('auto', None, None), ('english', 'en', None), ('english_biology', 'en', GLOSSARY)]:
            name = f'{mode}_{label}'
            if (OUT / f'{name}.json').exists():
                print('Already complete:', name, flush=True)
                continue
            results = []
            started = time.perf_counter()
            print('START', name, flush=True)
            with (OUT / f'{name}.partial.jsonl').open('w', encoding='utf-8') as log:
                if mode == 'stream':
                    iterator = model.stream(stream_chunks(mono, rate), language=language, keywords=glossary)
                else:
                    def long_results():
                        for a, b in spans:
                            result = model.transcribe(samples[a:b], language=language, keywords=glossary, word_timestamps=True)
                            result.update(section_start=a / 16000, section_end=b / 16000)
                            yield result
                    iterator = long_results()
                for index, result in enumerate(iterator):
                    results.append(result)
                    log.write(json.dumps(result, ensure_ascii=False) + '\n'); log.flush()
                    if (mode == 'stream' and index % 60 == 0) or mode == 'long':
                        print(name, index, result.get('text', '')[:100], flush=True)
            elapsed = time.perf_counter() - started
            (OUT / f'{name}.json').write_text(json.dumps({'elapsed_seconds': elapsed, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
            save_text(name, results, mode)
            (OUT / f'{name}.partial.jsonl').unlink()
            print('DONE', name, round(elapsed, 2), 'seconds', flush=True)

if __name__ == '__main__':
    main()
