"""Durable transcript files and the local Whistle loader used by evaluation."""
import json
import os
import time
from pathlib import Path
from datetime import datetime

from paths import ROOT
os.environ['NEEDLE_TELEMETRY'] = '0'
os.environ['NEEDLE3_LIB_PATH'] = str(ROOT / 'models' / 'libneedle.dll')

def load_model():
    from needle import Whistle
    return Whistle(weights=ROOT / 'models' / 'whistle.cact')

def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'

def clock(seconds):
    """Compact player-style time: 4:07 or 1:02:09."""
    seconds = max(0, int(seconds))
    hours, minutes = seconds // 3600, seconds // 60 % 60
    return f'{hours}:{minutes:02}:{seconds % 60:02}' if hours else f'{minutes}:{seconds % 60:02}'

def segment_span(result):
    words = result.get('words') or []
    start = words[0].get('start', 0) if words else result.get('start', result.get('received', 0))
    end = words[-1].get('end', start) if words else result.get('received', start)
    return start, max(start, end)

def add_segment(paragraphs, result):
    """Group recognizer segments into readable paragraphs of [start, text, end]."""
    text = result.get('text', '').strip()
    if not text:
        return False
    start, end = segment_span(result)
    # Streaming commits are often only a few words; keep a sentence
    # together in the document instead of creating a line per commit.
    if (not paragraphs or paragraphs[-1][1].rstrip('"”').endswith(('.', '!', '?'))
            or start - paragraphs[-1][0] >= 30):
        paragraphs.append([start, text, end])
    else:
        paragraphs[-1][1] += ' ' + text
        paragraphs[-1][2] = max(paragraphs[-1][2], end)
    return True

def render_document(metadata, paragraphs):
    started = metadata.get('started')
    try:
        when = datetime.fromisoformat(started).strftime('%B %d, %Y at %I:%M %p')
    except (TypeError, ValueError):
        when = ''
    title = metadata.get('title') or metadata.get('source') or 'Untitled'
    lines = [title, ' · '.join(part for part in (metadata.get('app'), when) if part)]
    if metadata.get('model_name'):
        lines.append(f"{metadata['model_name']} · {metadata.get('device', 'cpu').upper()}")
    header = '\n'.join(line for line in lines if line) + '\n\n'
    return header + ''.join(f'[{timestamp(paragraph[0])}] {paragraph[1]}\n\n' for paragraph in paragraphs)

def write_atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    # Windows readers can briefly hold a handle without delete sharing while
    # the library refreshes. Keep the completed temporary file and retry the
    # atomic rename rather than turning a successful import into a failed job.
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            break
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32) or attempt == 5:
                raise
            time.sleep(0.01 * (2 ** attempt))

class Transcript:
    def __init__(self, window, language, output=ROOT / 'transcripts', model_key=None, device='cpu',
                 title=None, vocabulary=None):
        now = datetime.now().astimezone()
        self.directory = Path(output) / now.strftime('%Y-%m-%d_%H-%M-%S-%f')
        self.directory.mkdir(parents=True)
        self.path = self.directory / 'Transcript.txt'
        self.metadata = {'title': title or window.title, 'source': window.title, 'app': window.app, 'pid': window.pid,
                         'source_kind': getattr(window, 'kind', 'window'),
                         'started': now.isoformat(), 'language': language or 'auto',
                         'capture_scope': 'selected process and its children', 'status': 'recording'}
        if vocabulary:
            self.metadata['vocabulary'] = vocabulary
        self.paragraphs = []
        if model_key:
            from model_catalog import BY_KEY
            self.metadata.update(model=model_key, model_name=BY_KEY[model_key].name, device=device)
        self.events = (self.directory / 'segments.jsonl').open('a', encoding='utf-8')
        self.save()

    def save(self):
        write_atomic(self.path, self.render())
        write_atomic(self.directory / 'session.json', json.dumps(self.metadata, indent=2, ensure_ascii=False))

    def append(self, result):
        self.events.write(json.dumps(result, ensure_ascii=False) + '\n')
        self.events.flush()
        os.fsync(self.events.fileno())
        if add_segment(self.paragraphs, result):
            self.save()
        return self.render()

    def render(self):
        return render_document(self.metadata, self.paragraphs)

    def finish(self, error=None, status=None):
        self.metadata.update(status=status or ('error' if error else 'complete'), ended=datetime.now().astimezone().isoformat())
        if error:
            self.metadata['error'] = str(error)
        self.save()
        self.events.close()
