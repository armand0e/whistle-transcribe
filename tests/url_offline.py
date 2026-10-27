"""Real local HTTP downloads and decoding through the controller; only ASR is a stand-in."""
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from offline_helpers import fake_backends, fresh, tone_file
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog
from url_import import validate_url
from url_dialog import UrlDialog
import app as whistle
import library
import preferences

folder = fresh('url')
media = tone_file(folder / 'lecture.flac', seconds=3)
original = hashlib.sha256(media.read_bytes()).hexdigest()
started_slow = threading.Event()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(folder), **kwargs)
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.path != '/slow.flac':
            return super().do_GET()
        data = media.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'audio/flac')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        started_slow.set()
        try:
            for index in range(0, len(data), 128):
                self.wfile.write(data[index:index + 128]); self.wfile.flush()
                time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
application = QApplication([])
library.TRANSCRIPTS = folder / 'transcripts'
preferences.PATH = folder / 'settings.json'
preferences.PATH.write_text(json.dumps({'welcomed': True, 'vocabulary': 'tRNAscan-SE'}))
fake_backends()
whistle.model_path = lambda key: Path('.')
controller = whistle.Whistle(application)

def wait(condition, timeout=40):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError('URL flow timed out')
        loop = QEventLoop(); QTimer.singleShot(20, loop.quit); loop.exec()

try:
    for value in ('file:///c:/secret.wav', 'javascript:alert(1)', 'not a url', 'https://',
                  'https://example.com:bad/a', 'https://user:password@example.com/a'):
        try:
            validate_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
    dialog = UrlDialog()
    assert not dialog.submit.isEnabled()
    dialog.field.setText('  ' + base + '/lecture.flac  ')
    assert dialog.submit.isEnabled() and dialog.url == base + '/lecture.flac'
    dialog.field.setText('file:///local.mp4')
    assert not dialog.submit.isEnabled()
    dialog.close()
    print('PASS: URL sheet and validation accept HTTP(S), reject malformed/local/credential URLs', flush=True)

    # Drive the actual dialog, its signal, and the controller from one import action.
    def submit():
        active = application.activeModalWidget()
        assert isinstance(active, UrlDialog)
        active.field.setText(base + '/lecture.flac')
        active.submit.click()
    QTimer.singleShot(100, submit)
    controller.library.choose_url()
    wait(lambda: controller.pill.state == 'result')
    job = controller.job
    assert job.error is None, job.error
    metadata = job.document.metadata
    assert metadata['status'] == 'complete' and metadata['title'] == 'lecture'
    assert metadata['source_url'] == base + '/lecture.flac'
    assert metadata['capture_scope'] == 'downloaded video audio'
    assert (job.document.directory / 'Audio.wav').is_file()
    assert not list(job.document.directory.glob('Source.*'))
    assert 'Vocabulary was tRNAscan-SE.' in job.document.render()
    assert controller.library.session.title == 'lecture'
    assert hashlib.sha256(media.read_bytes()).hexdigest() == original
    print('PASS: URL dialog → real HTTP download → WAV → model → saved, titled library transcript', flush=True)

    (folder / 'lecture.html').write_text('<html><title>Biology lecture</title><body>'
                                       '<video src="lecture.flac" controls></video>'
                                       '<video src="missing.flac" controls></video></body></html>')
    controller.import_url(base + '/lecture.html')
    wait(lambda: controller.pill.state == 'result')
    assert controller.job.error is None, controller.job.error
    assert controller.job.document.metadata['source_url'].endswith('/lecture.html')
    print('PASS: embedded media webpage imports only its first video', flush=True)

    controller.import_url(base + '/lecture.flac')
    queued = controller.job
    controller.import_files([str(media)])
    wait(lambda: controller.job is not queued and controller.pill.state == 'result' and not controller.queue)
    assert queued.error is None and controller.job.error is None
    print('PASS: URL and local file imports share the serial queue', flush=True)

    controller.import_url(base + '/missing.flac')
    wait(lambda: controller.pill.state == 'result')
    assert controller.job.error and controller.job.document.metadata['status'] == 'error'
    assert not controller.pill.result_ok
    assert controller.library.banner.button.text() == 'Retry URL Import'
    # Make the missing URL available, then retry from the error session's banner.
    (folder / 'missing.flac').write_bytes(media.read_bytes())
    controller.library.banner.button.click()
    wait(lambda: controller.pill.state == 'result')
    assert controller.job.error is None, controller.job.error
    print('PASS: HTTP failure creates an error session rather than a successful transcript', flush=True)

    controller.import_url(base + '/slow.flac')
    wait(started_slow.is_set)
    controller.cancel()
    wait(lambda: controller.pill.state == 'result')
    job = controller.job
    assert job.document.metadata['status'] == 'cancelled'
    assert job.process.poll() is not None
    assert not (job.document.directory / 'Audio.wav').exists()
    print('PASS: cancelling a download stops the worker and never reports success', flush=True)
finally:
    if controller.busy():
        controller.job.cancel(); controller.job.wait(10000)
    controller.quit()
    server.shutdown(); server.server_close()
