"""Stands in for asr_worker.py: deterministic segments without a model; real conversion."""
import argparse
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

def emit(kind, **data):
    print(json.dumps({'kind': kind, **data}), flush=True)

parser = argparse.ArgumentParser()
parser.add_argument('action')
parser.add_argument('--model'); parser.add_argument('--device'); parser.add_argument('--language')
parser.add_argument('--audio', type=Path); parser.add_argument('--output', type=Path); parser.add_argument('--vocabulary')
parser.add_argument('--url')
args = parser.parse_args()
if args.action == 'import-url':
    from url_import import download
    try:
        download(args.url, args.output, emit)
    except Exception as exc:
        emit('error', message=str(exc))
        sys.exit(1)
    sys.exit(0)
if args.action == 'convert':
    import asr_worker
    try:
        asr_worker.convert(args.audio, args.output)
    except Exception as exc:
        emit('error', message=str(exc))
        sys.exit(1)
    sys.exit(0)
with wave.open(str(args.audio), 'rb') as file:
    duration = file.getnframes() / file.getframerate()
emit('status', text='Loading fake model…')
sentences = ['Hello from the fake model.', 'It counts the seconds', 'and finishes sentences.',
             f'Vocabulary was {args.vocabulary or "empty"}.']
for index, text in enumerate(sentences):
    start = duration * index / len(sentences)
    words = [{'word': word, 'start': start + i * 0.3, 'end': start + i * 0.3 + 0.25} for i, word in enumerate(text.split())]
    emit('segment', result={'text': text, 'words': words, 'start': start, 'received': start + 1})
    emit('progress', percent=round(100 * (index + 1) / len(sentences)))
emit('complete', duration=duration, elapsed_seconds=0.1, device=args.device, compute_type='fake', language='en')
