"""Independent CPU ASR cross-check, without glossary hints; not ground truth."""
import json
import os
import argparse
from pathlib import Path
import time


def main():
    ROOT = Path(__file__).resolve().parents[2]
    os.environ['HF_HOME'] = str(ROOT / 'models' / 'crosscheck-hub')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    SOURCE = None
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True, help='Saved session directory containing Audio.wav')
    SOURCE = parser.parse_args().source.resolve()
    OUT = SOURCE / 'quality-comparison'
    OUT.mkdir(exist_ok=True)
    print('Loading independent faster-whisper library', flush=True)
    from faster_whisper import WhisperModel
    print('Loading small.en on CPU (int8); download if absent', flush=True)
    model = WhisperModel('small.en', device='cpu', compute_type='int8', cpu_threads=6,
                         download_root=str(ROOT / 'models' / 'crosscheck-hub'))
    started = time.perf_counter()
    segments, info = model.transcribe(str(SOURCE / 'Audio.wav'), language='en', beam_size=5,
                                      vad_filter=False, condition_on_previous_text=True)
    results = []
    with (OUT / 'independent_whisper_small_en.partial.jsonl').open('w', encoding='utf-8') as log:
        for segment in segments:
            item = {'start': segment.start, 'end': segment.end, 'text': segment.text}
            results.append(item)
            log.write(json.dumps(item, ensure_ascii=False) + '\n'); log.flush()
            print(round(segment.start, 1), segment.text, flush=True)
    (OUT / 'independent_whisper_small_en.json').write_text(json.dumps({
        'model': 'Systran/faster-whisper-small.en', 'device': 'cpu', 'compute_type': 'int8',
        'glossary': None, 'elapsed_seconds': time.perf_counter() - started,
        'note': 'Independent ASR hypothesis, not a human-verified reference.', 'segments': results
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    (OUT / 'independent_whisper_small_en.txt').write_text('\n'.join(
        f"[{item['start']:.2f}-{item['end']:.2f}] {item['text']}" for item in results), encoding='utf-8')
    (OUT / 'independent_whisper_small_en.partial.jsonl').unlink()
    print('Independent cross-check complete', flush=True)


if __name__ == '__main__':
    main()
