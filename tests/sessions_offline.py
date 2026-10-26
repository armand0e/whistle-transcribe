"""Session files, edits, exports, and preferences, without audio hardware or models."""
from datetime import datetime, timedelta
import json
import re

from offline_helpers import fresh
from model_catalog import validate_choice, supports_language
from preferences import Preferences
from sessions import cues, date_group, export_text, export_filename, list_sessions, load_session
from transcriber import Transcript
from windows_audio import Window

folder = fresh('sessions')
document = Transcript(Window(0, 42, 'Lecture: Genomes', 'Google Chrome', kind='window'), 'en', folder, 'small_en', 'cpu',
                      vocabulary='tRNAscan-SE, RNAmmer')
segments = [
    {'text': 'Welcome to the course.', 'words': [{'word': w, 'start': 1 + i * 0.4, 'end': 1.3 + i * 0.4}
                                                 for i, w in enumerate('Welcome to the course.'.split())]},
    {'text': 'Today we cover', 'start': 4.0, 'received': 5.0, 'words': []},
    {'text': 'genome annotation.', 'start': 5.0, 'received': 6.5, 'words': []},
    {'text': ' ', 'start': 7, 'received': 7},
    {'text': 'A much later thought.', 'start': 50, 'received': 52, 'words': []},
]
for segment in segments:
    document.append(segment)
document.metadata['duration'] = 60.0
document.finish()
session = load_session(document.directory)
assert session.title == 'Lecture: Genomes' and session.status == 'complete'
assert [p[1] for p in session.paragraphs()] == ['Welcome to the course.', 'Today we cover genome annotation.', 'A much later thought.']
assert session.paragraphs()[1][0] == 4.0 and session.paragraphs()[1][2] == 6.5
assert session.duration == 60.0 and session.metadata['vocabulary'] == 'tRNAscan-SE, RNAmmer'
assert session.matches('ANNOTATION') and session.matches('chrome') and not session.matches('kubernetes')
print('PASS: live segments group into timed paragraphs and reload identically', flush=True)

session.rename('  Genomes   101 ')
session.save_paragraphs([[1.0, 'Welcome to the course!', 2.5], [4.0, 'Today we cover genome annotation.', 6.5], [50, '  ', 52]])
again = load_session(document.directory)
assert again.title == 'Genomes 101' and again.edited
assert [p[1] for p in again.paragraphs()] == ['Welcome to the course!', 'Today we cover genome annotation.']
text = (document.directory / 'Transcript.txt').read_text(encoding='utf-8')
assert text.startswith('Genomes 101\n') and '[00:00:01] Welcome to the course!' in text
assert 'Welcome to the course.' in (document.directory / 'segments.jsonl').read_text(encoding='utf-8'), 'Recognizer output must stay untouched'
print('PASS: rename and edits persist beside the untouched recognizer output', flush=True)

srt = export_text(again, 'srt')
blocks = [block for block in srt.strip().split('\n\n') if block]
assert blocks[0].startswith('1\n00:00:01,000 --> ')
times = [re.findall(r'(\d\d):(\d\d):(\d\d),(\d{3})', block.split('\n')[1]) for block in blocks]
starts = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for (h, m, s, ms), _ in times]
assert starts == sorted(starts) and len(blocks) == 2
vtt = export_text(again, 'vtt')
assert vtt.startswith('WEBVTT\n\n00:00:01.000 --> ')
assert json.loads(export_text(again, 'json'))['paragraphs'][0]['text'] == 'Welcome to the course!'
assert export_text(again, 'md').startswith('# Genomes 101\n\n*Google Chrome')
assert export_text(again, 'txt') == text
(document.directory / 'edits.json').unlink()
word_cues = cues(load_session(document.directory))
assert word_cues[0][0] == 1 and word_cues[0][2] == 'Welcome to the course.', word_cues[0]
assert export_filename(session, 'srt') == 'Genomes 101.srt'
print('PASS: text, Markdown, SRT, WebVTT, and JSON exports', flush=True)

session.metadata['status'] = 'transcribing'
assert session.display_status() == 'interrupted' and session.display_status(document.directory) == 'transcribing'
(folder / 'not-a-session').mkdir()
(folder / 'broken').mkdir()
(folder / 'broken' / 'session.json').write_text('{', encoding='utf-8')
assert [item.directory for item in list_sessions(folder)] == [document.directory]
now = datetime(2026, 10, 26, 12).astimezone()
assert date_group(now, now) == 'Today' and date_group(now - timedelta(days=1), now) == 'Yesterday'
assert date_group(now - timedelta(days=3), now) == 'Previous 7 Days' and date_group(now - timedelta(days=20), now) == 'Previous 30 Days'
assert date_group(now - timedelta(days=60), now) == 'August'
print('PASS: interrupted sessions, unreadable folders, and date groups', flush=True)

for bad in (('phonon2', 'cuda', 'en'), ('small_en', 'cpu', 'de'), ('whistle', 'cpu', 'ja')):
    try:
        validate_choice(*bad)
        raise AssertionError(f'accepted {bad}')
    except ValueError:
        pass
validate_choice('large_v3', 'cuda', 'ja')
assert supports_language('large_v3', None) and not supports_language('small_en', 'fr')
preferences = Preferences(folder / 'settings.json')
preferences.set(model='whistle', device='cuda', language='en')
assert preferences['device'] == 'cpu', 'CPU-only models force CPU'
preferences.set(model='small_en', language='de')
assert preferences['language'] == 'en', 'English-only models force English'
(folder / 'settings.json').write_text('{"model": "missing", "device": "cuda", "unknown": 1}', encoding='utf-8')
assert Preferences(folder / 'settings.json')['model'] == 'small_en'
print('PASS: model/device/language rules and preference recovery', flush=True)
