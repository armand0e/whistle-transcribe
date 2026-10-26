"""Drive the real app controller offscreen: record, pause, stop, review, edit, re-transcribe, import, theme."""
import json
from pathlib import Path
import time

from offline_helpers import OUTPUT, fake_backends, fresh, tone_file
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

application = QApplication([])
application.setStyle('Fusion')
import app as whistle
import library
import preferences
import theme

folder = fresh('ui')
library.TRANSCRIPTS = folder / 'transcripts'
preferences.PATH = folder / 'settings.json'
preferences.PATH.write_text(json.dumps({'welcomed': True, 'vocabulary': 'Figma'}), encoding='utf-8')
fake_backends()
whistle.model_path = lambda key: Path('.')
application.setFont(theme.font(13))
controller = whistle.Whistle(application)
pill, shelf = controller.pill, controller.library

def wait(condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError('Timed out waiting for the app')
        loop = QEventLoop()
        QTimer.singleShot(30, loop.quit)
        loop.exec()

def shoot(widget, name):
    widget.grab().save(str(OUTPUT / f'{name}.png'))

assert pill.isVisible() and pill.state == 'idle' and pill.source_button.title == 'Choose a Source'
assert pill.chip.text() == 'Small.en · CPU'
assert shelf.pages.currentWidget() is shelf.placeholder and shelf.placeholder.title.text() == 'No Transcripts Yet'
print('PASS: first launch shows the pill and an empty library', flush=True)

controller.source = whistle.SYSTEM_AUDIO
controller.include_mic = True
controller.refresh_pill()
assert pill.source_button.subtitle == 'Everything on this PC + mic'
controller.open_library()
controller.record()
wait(lambda: pill.state == 'recording' and controller.job.recorded_seconds > 0.6)
assert shelf.body.currentWidget() is shelf.live and shelf.list.count() == 2  # header + live session
shoot(pill, 'pill-recording')
controller.pause()
assert pill.dot.paused and controller.job.paused.is_set()
wait(lambda: shelf.live.title.text() == 'Paused')
time.sleep(0.2)  # A block already being mixed when Pause was pressed may still land.
paused_at = controller.job.recorded_seconds
time.sleep(0.6)
controller.tick()
assert controller.job.recorded_seconds == paused_at, 'Paused time must not count'
controller.pause()
wait(lambda: controller.job.recorded_seconds > paused_at + 0.4)
controller.toggle_recording()  # the global shortcut path
wait(lambda: pill.state == 'result', 60)
assert pill.result_ok and pill.result_title.text() == 'Transcript Ready'
session = shelf.session
assert session and session.status == 'complete' and shelf.isVisible()
assert len(shelf.view.paragraphs) == 3 and 'Vocabulary was Figma.' in shelf.view.toPlainText()
assert shelf.player.isVisible() and not shelf.banner.isVisible()
shoot(pill, 'pill-result')
shoot(shelf, 'library-light')
print('PASS: record → pause → resume → stop (shortcut) → transcript opens in the library', flush=True)

assert shelf.view.find('fake') == 1 and shelf.view.find('zzz') == 0
shelf.title.setText('Design Review')
shelf.title.editingFinished.emit()
assert session.title == 'Design Review' and json.loads((session.directory / 'session.json').read_text())['title'] == 'Design Review'
shelf.toggle_edit()
assert shelf.body.currentWidget() is shelf.editor
cursor = shelf.editor.textCursor()
cursor.movePosition(cursor.MoveOperation.End)
cursor.insertBlock()
cursor.insertText('A sentence I added myself.')
shelf.editor.document().setModified(True)
shelf.toggle_edit()
assert session.edited and session.paragraphs()[-1][1] == 'A sentence I added myself.'
assert session.paragraphs()[-1][0] == session.paragraphs()[-2][0], 'New paragraphs inherit the previous timestamp'
assert 'A sentence I added myself.' in (session.directory / 'Transcript.txt').read_text(encoding='utf-8')
shelf.copy_text()
assert QApplication.clipboard().text().endswith('A sentence I added myself.')
print('PASS: find, rename, inline edit, and copy', flush=True)

shelf.toggle_edit()
cursor = shelf.editor.textCursor()
cursor.movePosition(cursor.MoveOperation.End)
cursor.insertText(' Saved even when search hides this transcript.')
shelf.editor.document().setModified(True)
shelf.search.setText('query-that-matches-no-transcript')
wait(lambda: shelf.session is None)
assert not shelf.editing
assert 'Saved even when search hides this transcript.' in (session.directory / 'edits.json').read_text(encoding='utf-8')
shelf.search.clear()
wait(lambda: shelf.session is not None)
assert 'Saved even when search hides this transcript.' in shelf.session.text()
print('PASS: filtering to zero results preserves in-progress edits', flush=True)

controller.retranscribe(session, 'whistle')
wait(lambda: not controller.busy() and pill.state == 'result', 60)
rerun = shelf.session
assert rerun.directory != session.directory and rerun.metadata['model'] == 'whistle' and rerun.title == 'Design Review'
assert rerun.audio_path == session.directory / 'Audio.wav'
print('PASS: transcribe again with another model keeps one recording', flush=True)

clips = [tone_file(folder / 'interview.flac'), tone_file(folder / 'memo.flac', 1.0)]
controller.import_files([str(path) for path in clips])
wait(lambda: not controller.queue and not controller.busy() and pill.state == 'result', 90)
titles = [item.title for item in library.list_sessions(shelf.root)]
assert 'interview' in titles and 'memo' in titles, titles
assert len(titles) == 4
print('PASS: queued imports of compressed media', flush=True)

# A WAV imported from outside the library must be owned just like a FLAC.
# Re-transcribing an existing session must still reuse that owned recording.
import shutil
import hashlib
external_wav = folder / 'external-recording.wav'
shutil.copyfile(session.audio_path, external_wav)
original_hash = hashlib.sha256(external_wav.read_bytes()).hexdigest()
controller.import_files([str(external_wav)])
wait(lambda: not controller.queue and not controller.busy() and pill.state == 'result', 60)
imported = shelf.session
assert imported.audio_path == imported.directory / 'Audio.wav'
assert imported.audio_path != external_wav and imported.audio_path.is_file()
assert hashlib.sha256(external_wav.read_bytes()).hexdigest() == original_hash
print('PASS: PCM16 WAV imports own their audio without changing the source', flush=True)

controller.set_preferences(model='whistle', device='cuda')
assert controller.preferences['device'] == 'cpu' and pill.chip.text() == 'Whistle · CPU'
controller.open_settings('models')
settings = controller.settings
assert 'cuda' in settings.device.disabled and settings.models.rows['whistle'].radio.checked
controller.set_preferences(model='small_en')
assert not settings.device.disabled
shoot(settings, 'settings-models')
controller.set_preferences(appearance='dark')
assert theme.is_dark() and '#1E1E1E' in application.styleSheet()
shelf.select(session.directory)
shoot(shelf, 'library-dark')
controller.set_preferences(appearance='light')
assert not theme.is_dark()
print('PASS: model rules, settings sync, and live appearance switching', flush=True)

assert pill.state in ('result', 'idle')
pill.show_idle()
controller.quit()
print('PASS: clean quit', flush=True)
