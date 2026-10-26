"""Durable transcript files and the local Whistle loader used by evaluation."""
import json
import os
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.environ['NEEDLE_TELEMETRY'] = '0'
os.environ['NEEDLE3_LIB_PATH'] = str(ROOT / 'models' / 'libneedle.dll')

def load_model():
    from needle import Whistle
    return Whistle(weights=ROOT / 'models' / 'whistle.cact')

def timestamp(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'

class Transcript:
    def __init__(self, window, language, output=ROOT / 'transcripts', model_key=None, device='cpu'):
        now = datetime.now().astimezone()
        self.directory = Path(output) / now.strftime('%Y-%m-%d_%H-%M-%S-%f')
        self.directory.mkdir(parents=True)
        self.path = self.directory / 'Transcript.txt'
        self.metadata = {'source': window.title, 'app': window.app, 'pid': window.pid,
                         'started': now.isoformat(), 'language': language or 'auto',
                         'capture_scope': 'selected process and its children', 'status': 'recording'}
        self.header = f'WHISTLE TRANSCRIPT\n\n{window.title}\n{window.app} · {now:%B %d, %Y at %I:%M %p}\n\n'
        self.paragraphs = []
        if model_key:
            from model_catalog import BY_KEY
            self.metadata.update(model=model_key, model_name=BY_KEY[model_key].name, device=device)
            self.header += f'Model: {BY_KEY[model_key].name} · {device.upper()}\n\n'
        self.events = (self.directory / 'segments.jsonl').open('a', encoding='utf-8')
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as file:
            file.write(self.render())
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.path)
        (self.directory / 'session.json').write_text(json.dumps(self.metadata, indent=2, ensure_ascii=False), encoding='utf-8')

    def append(self, result):
        self.events.write(json.dumps(result, ensure_ascii=False) + '\n')
        self.events.flush()
        os.fsync(self.events.fileno())
        text = result.get('text', '').strip()
        if text:
            words = result.get('words') or []
            seconds = words[0].get('start', 0) if words else result.get('start', result.get('received', 0))
            # Streaming commits are often only a few words; keep a sentence
            # together in the document instead of creating a line per commit.
            if (not self.paragraphs or self.paragraphs[-1][1].rstrip('\"”').endswith(('.', '!', '?'))
                    or seconds - self.paragraphs[-1][0] >= 30):
                self.paragraphs.append([seconds, text])
            else:
                self.paragraphs[-1][1] += ' ' + text
            self.save()
        return self.render()

    def render(self):
        return self.header + ''.join(f'[{timestamp(seconds)}] {text}\n\n' for seconds, text in self.paragraphs)

    def finish(self, error=None, status=None):
        self.metadata.update(status=status or ('error' if error else 'complete'), ended=datetime.now().astimezone().isoformat())
        if error:
            self.metadata['error'] = str(error)
        self.save()
        self.events.close()
