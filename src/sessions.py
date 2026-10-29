"""Saved transcript sessions: listing, editing, and export. Qt-free so it is easy to test."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import math
import wave

from transcriber import ROOT, add_segment, clock, render_document, segment_span, timestamp, write_atomic

TRANSCRIPTS = ROOT / 'transcripts'
LIVE_STATUSES = ('recording', 'preparing', 'transcribing')
AUDIO_TYPES = ('.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.wma', '.webm', '.mp4', '.mov', '.mkv')
EXPORTS = {'txt': 'Plain Text', 'md': 'Markdown', 'srt': 'SubRip Subtitles', 'vtt': 'WebVTT Subtitles', 'json': 'JSON'}

@dataclass
class Session:
    directory: Path
    metadata: dict
    _paragraphs: list | None = field(default=None, repr=False)

    @property
    def title(self):
        return self.metadata.get('title') or self.metadata.get('source') or 'Untitled'

    @property
    def started(self):
        try:
            value = datetime.fromisoformat(self.metadata['started'])
            return value.astimezone()  # Normalize older naive timestamps before sorting with aware ones.
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return datetime.fromtimestamp(self.directory.stat().st_mtime).astimezone()

    @property
    def status(self):
        return self.metadata.get('status', 'complete')

    def display_status(self, live_directory=None):
        """Live statuses on disk without a running job mean the app quit mid-way."""
        if self.status in LIVE_STATUSES and Path(self.directory) != Path(live_directory or ''):
            return 'interrupted'
        return self.status

    @property
    def audio_path(self):
        local = self.directory / 'Audio.wav'
        if local.is_file():
            return local
        source = self.metadata.get('source_audio')
        return Path(source) if source and Path(source).is_file() else None

    @property
    def duration(self):
        inference = self.metadata.get('inference')
        inference = inference if isinstance(inference, dict) else {}
        for candidate in (self.metadata.get('duration'), inference.get('duration')):
            try:
                value = float(candidate)
                if math.isfinite(value) and value >= 0:
                    return value
            except (TypeError, ValueError, OverflowError):
                pass
        audio = self.audio_path
        if audio and audio.suffix.lower() == '.wav':
            try:
                with wave.open(str(audio), 'rb') as file:
                    return file.getnframes() / file.getframerate()
            except (OSError, EOFError, wave.Error, ZeroDivisionError):
                pass
        return None

    @property
    def edited(self):
        return (self.directory / 'edits.json').is_file()

    def segments(self):
        results = []
        try:
            with (self.directory / 'segments.jsonl').open(encoding='utf-8') as file:
                for line in file:
                    try:
                        results.append(json.loads(line))
                    except ValueError:
                        pass  # A crash can leave a torn final line.
        except OSError:
            pass
        return results

    def paragraphs(self, reload=False):
        if self._paragraphs is None or reload:
            try:
                edits = json.loads((self.directory / 'edits.json').read_text(encoding='utf-8'))
                self._paragraphs = [[float(item['start']), str(item['text']), float(item.get('end', item['start']))]
                                    for item in edits['paragraphs']]
            except (OSError, ValueError, KeyError, TypeError):
                self._paragraphs = []
                for result in self.segments():
                    add_segment(self._paragraphs, result)
        return self._paragraphs

    def text(self):
        return '\n\n'.join(paragraph[1] for paragraph in self.paragraphs())

    def matches(self, query):
        query = query.casefold().strip()
        if not query:
            return True
        fields = (self.title, self.metadata.get('app', ''), self.metadata.get('model_name', ''))
        return any(query in str(value).casefold() for value in fields) or query in self.text().casefold()

    def save_metadata(self):
        write_atomic(self.directory / 'session.json', json.dumps(self.metadata, indent=2, ensure_ascii=False))
        write_atomic(self.directory / 'Transcript.txt', render_document(self.metadata, self.paragraphs()))

    def rename(self, title):
        title = ' '.join(title.split())
        if title and title != self.title:
            self.metadata['title'] = title
            self.save_metadata()

    def save_paragraphs(self, paragraphs):
        """Store user edits beside the original recognizer output, which is never rewritten."""
        self._paragraphs = [[float(start), text.strip(), float(end)] for start, text, end in paragraphs if text.strip()]
        payload = {'edited': datetime.now().astimezone().isoformat(),
                   'paragraphs': [{'start': start, 'end': end, 'text': text} for start, text, end in self._paragraphs]}
        write_atomic(self.directory / 'edits.json', json.dumps(payload, indent=2, ensure_ascii=False))
        self.save_metadata()

    def related(self, sessions):
        """Other sessions that reference this session's recording."""
        audio = self.directory / 'Audio.wav'
        return [other for other in sessions if other.directory != self.directory
                and other.metadata.get('source_audio') and Path(other.metadata['source_audio']) == audio]

def load_session(directory):
    directory = Path(directory)
    try:
        metadata = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(metadata, dict):
        return None
    for key in ('title', 'source', 'app', 'model', 'model_name', 'device', 'language',
                'status', 'source_kind', 'source_audio', 'source_url'):
        if key in metadata and not isinstance(metadata[key], str):
            metadata.pop(key)
    return Session(directory, metadata)

def list_sessions(root=TRANSCRIPTS):
    root = Path(root)
    if not root.is_dir():
        return []
    sessions = [session for session in map(load_session, (path for path in root.iterdir() if path.is_dir())) if session]
    return sorted(sessions, key=lambda session: session.started, reverse=True)

def date_group(when, now=None):
    now = now or datetime.now().astimezone()
    day = when.astimezone(now.tzinfo).date()
    today = now.date()
    if day == today:
        return 'Today'
    if day == today - timedelta(days=1):
        return 'Yesterday'
    if day > today - timedelta(days=7):
        return 'Previous 7 Days'
    if day > today - timedelta(days=30):
        return 'Previous 30 Days'
    return when.strftime('%B %Y') if day.year != today.year else when.strftime('%B')

# --- Export -------------------------------------------------------------------------------

def _cue_time(seconds, separator):
    milliseconds = max(0, round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, milliseconds = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}'

def _split_timed(text, start, end, limit=84):
    """Split text into subtitle-sized pieces, sharing the span by length."""
    pieces, current = [], ''
    for word in text.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f'{current} {word}'.strip()
        if current.endswith(('.', '!', '?')) and len(current) > limit // 2:
            pieces.append(current)
            current = ''
    if current:
        pieces.append(current)
    total = sum(len(piece) for piece in pieces) or 1
    span, position, cues = max(end - start, 0.5 * len(pieces)), start, []
    for piece in pieces:
        length = span * len(piece) / total
        cues.append((position, position + length, piece))
        position += length
    return cues

def cues(session):
    """Subtitle cues: word timings when the text is unedited, otherwise paragraph spans."""
    output = []
    if not session.edited:
        for result in session.segments():
            words = [word for word in result.get('words') or [] if str(word.get('word', '')).strip()]
            if not words:
                if result.get('text', '').strip():
                    start, end = segment_span(result)
                    output.extend(_split_timed(result['text'].strip(), start, end))
                continue
            group = []
            for word in words:
                if group and (len(' '.join(item['word'].strip() for item in group + [word])) > 84
                              or word['end'] - group[0]['start'] > 6 or word['start'] - group[-1]['end'] > 1.2):
                    output.append((group[0]['start'], group[-1]['end'], ' '.join(item['word'].strip() for item in group)))
                    group = []
                group.append(word)
                if word['word'].strip().endswith(('.', '!', '?')) and word['end'] - group[0]['start'] > 1.5:
                    output.append((group[0]['start'], group[-1]['end'], ' '.join(item['word'].strip() for item in group)))
                    group = []
            if group:
                output.append((group[0]['start'], group[-1]['end'], ' '.join(item['word'].strip() for item in group)))
        if output:
            return output
    for index, (start, text, end) in enumerate(session.paragraphs()):
        following = session.paragraphs()[index + 1][0] if index + 1 < len(session.paragraphs()) else None
        if end <= start:
            end = following if following and following > start else start + max(2, len(text) / 15)
        output.extend(_split_timed(text, start, end))
    return output

def wrap_lines(text, width=42):
    if len(text) <= width:
        return text
    middle = len(text) // 2
    left, right = text.rfind(' ', 0, middle + 1), text.find(' ', middle)
    split = min((point for point in (left, right) if point > 0), key=lambda point: abs(point - middle), default=-1)
    return text if split < 0 else text[:split] + '\n' + text[split + 1:]

def export_text(session, kind):
    paragraphs = session.paragraphs()
    meta = session.metadata
    if kind == 'txt':
        return render_document(meta, paragraphs)
    if kind == 'md':
        details = [session.started.strftime('%B %d, %Y at %I:%M %p')]
        if meta.get('app'):
            details.insert(0, meta['app'])
        if meta.get('model_name'):
            details.append(f"{meta['model_name']} ({meta.get('device', 'cpu').upper()})")
        body = ''.join(f'**{timestamp(start)}** {text}\n\n' for start, text, _ in paragraphs)
        return f'# {session.title}\n\n*{" · ".join(details)}*\n\n{body}'
    if kind in ('srt', 'vtt'):
        items = cues(session)
        if kind == 'srt':
            return ''.join(f'{index}\n{_cue_time(start, ",")} --> {_cue_time(max(end, start + 0.3), ",")}\n{wrap_lines(text)}\n\n'
                           for index, (start, end, text) in enumerate(items, 1))
        return 'WEBVTT\n\n' + ''.join(f'{_cue_time(start, ".")} --> {_cue_time(max(end, start + 0.3), ".")}\n{wrap_lines(text)}\n\n'
                                      for start, end, text in items)
    if kind == 'json':
        return json.dumps({'title': session.title, 'metadata': meta,
                           'paragraphs': [{'start': start, 'end': end, 'text': text} for start, text, end in paragraphs]},
                          indent=2, ensure_ascii=False)
    raise ValueError(f'Unknown export format: {kind}')

def export_filename(session, kind):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', ' ', session.title).strip(' .') or 'Transcript'
    return f'{safe[:80]}.{kind}'

def describe(session):
    """One-line summary for list rows and headers."""
    parts = [session.started.strftime('%I:%M %p').lstrip('0')]
    if session.duration:
        parts.append(clock(session.duration))
    return ' · '.join(parts)
