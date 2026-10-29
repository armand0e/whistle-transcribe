"""Whistle: record any app, your PC, or your microphone, and transcribe it locally."""
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Qt, QLockFile
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

import theme
from capture_jobs import HelperJob, Recorder
from library import Library
from model_catalog import BY_KEY, LANGUAGES, MODELS, ROOT, model_path, supports_language, validate_choice
from pill import Pill
from preferences import Preferences
from settings_dialog import SettingsWindow
from source_picker import SourcePicker, app_pixmap
from welcome import Welcome
from url_import import validate_url
from windows_audio import MICROPHONE, SYSTEM_AUDIO, Window, list_windows, window_exists

SERVER = 'whistle-' + hashlib.sha1(str(ROOT).casefold().encode(), usedforsecurity=False).hexdigest()[:12]
HOTKEY_ID = 0x5749

class Hotkey(QAbstractNativeEventFilter):
    """Ctrl+Alt+R from anywhere on Windows."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.hwnd = None

    def register(self, hwnd):
        if sys.platform != 'win32':
            return False
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.unregister()
        if user32.RegisterHotKey(hwnd, HOTKEY_ID, 0x0001 | 0x0002 | 0x4000, ord('R')):  # Alt | Ctrl | NoRepeat
            self.hwnd = hwnd
            return True
        return False

    def unregister(self):
        if self.hwnd is not None:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            self.hwnd = None

    def nativeEventFilter(self, event_type, message):
        name = event_type.data() if hasattr(event_type, 'data') else bytes(event_type)
        if self.hwnd is not None and name == b'windows_generic_MSG':
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

def palette():
    t = theme.tokens()
    result = QPalette()
    roles = {QPalette.ColorRole.Window: 'window', QPalette.ColorRole.WindowText: 'text', QPalette.ColorRole.Base: 'raised',
             QPalette.ColorRole.AlternateBase: 'grouped', QPalette.ColorRole.Text: 'text', QPalette.ColorRole.Button: 'control',
             QPalette.ColorRole.ButtonText: 'text', QPalette.ColorRole.Highlight: 'accent',
             QPalette.ColorRole.HighlightedText: 'on_accent', QPalette.ColorRole.ToolTipBase: 'raised',
             QPalette.ColorRole.ToolTipText: 'text', QPalette.ColorRole.PlaceholderText: 'tertiary',
             QPalette.ColorRole.Link: 'accent', QPalette.ColorRole.Mid: 'separator'}
    for role, name in roles.items():
        result.setColor(role, theme.parse(t[name]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        result.setColor(QPalette.ColorGroup.Disabled, role, theme.parse(t['tertiary']))
    return result

def alert(parent, title, text, buttons=(('OK', 'primary'),)):
    """A calm, app-styled alert. Returns the label of the chosen button."""
    box = QMessageBox(parent)
    box.setWindowTitle('Whistle')
    box.setIconPixmap(theme.app_icon(128).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    box.setText(title)
    box.setInformativeText(text)
    choices = {}
    for index, (text_label, kind) in enumerate(buttons):
        role = QMessageBox.ButtonRole.RejectRole if kind == 'cancel' else QMessageBox.ButtonRole.AcceptRole
        button = box.addButton(text_label, role)
        if kind in ('primary', 'destructive'):
            button.setProperty('kind', kind)
            box.setDefaultButton(button)
        choices[button] = text_label
    box.exec()
    return choices.get(box.clickedButton())

class Whistle(QObject):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.preferences = Preferences()
        self.job = None
        self.job_directory = None
        self.job_error = None
        self.job_title = ''
        self.queue = []
        self.closing = False
        self.gpu_state, self.gpu_detail = 'unknown', ''
        self.probe_job = None
        self.settings = None
        self.last_finished = None
        self.source = self._restore_source()
        self.include_mic = self.preferences['include_mic']

        self.apply_theme()
        self.pill = Pill(self.preferences['pill_on_top'])
        self.pill.source_clicked.connect(self.choose_source)
        self.pill.model_clicked.connect(self.model_menu)
        self.pill.record_clicked.connect(self.record)
        self.pill.stop_clicked.connect(self.stop)
        self.pill.pause_clicked.connect(self.pause)
        self.pill.cancel_clicked.connect(self.cancel)
        self.pill.library_clicked.connect(lambda: self.open_library())
        self.pill.menu_requested.connect(self.more_menu)
        self.pill.result_clicked.connect(lambda: self.open_library(self.last_finished))
        self.pill.moved.connect(lambda point: self.preferences.set(pill_position=[point.x(), point.y()]))
        self.library = Library()
        self.library.setWindowIcon(application.windowIcon())
        self.library.record_requested.connect(self.record)
        self.library.stop_requested.connect(self.stop)
        self.library.pause_requested.connect(self.pause)
        self.library.cancel_requested.connect(self.cancel)
        self.library.import_requested.connect(self.import_files)
        self.library.url_requested.connect(self.import_url)
        self.library.retranscribe_requested.connect(self.retranscribe)
        self.library.settings_requested.connect(lambda: self.open_settings())
        self.tray = self._build_tray()
        self.hotkey = Hotkey(self.toggle_recording)
        application.installNativeEventFilter(self.hotkey)
        self.apply_hotkey()
        application.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self.tick)
        self.ticker.start(200)
        self.refresh_pill()
        self.pill.place(self.preferences['pill_position'])
        self.pill.show()
        self.write_ui_state()
        if self.preferences['device'] == 'cuda':
            QTimer.singleShot(0, self.check_gpu)
        if not self.preferences['welcomed']:
            QTimer.singleShot(300, self.welcome)

    # --- Appearance ------------------------------------------------------------------

    def apply_theme(self):
        theme.set_appearance(self.preferences['appearance'])
        self.application.setPalette(palette())
        self.application.setStyleSheet(theme.stylesheet())
        for window in (getattr(self, 'library', None), self.settings):
            if window is not None:
                theme.apply_chrome(window)

    def welcome(self):
        Welcome().exec()
        self.preferences.set(welcomed=True)
        self.open_library()

    # --- Sources and models ----------------------------------------------------------

    def _restore_source(self):
        kind = self.preferences['source_kind']
        if kind == 'system':
            return SYSTEM_AUDIO
        if kind == 'mic':
            return MICROPHONE
        path = self.preferences['source_path']
        return next((window for window in list_windows() if path and window.path == path), None)

    def refresh_pill(self):
        model = BY_KEY[self.preferences['model']]
        device = 'GPU' if self.preferences['device'] == 'cuda' else 'CPU'
        self.pill.set_model(f'{model.short} · {device}')
        if self.source is None:
            self.pill.set_source('Choose a Source', 'An app, system audio, or mic', 'waveform')
            return
        mic = self.include_mic and self.source.kind != 'mic'
        subtitle = {'system': 'Everything on this PC', 'mic': 'Microphone only'}.get(self.source.kind, 'App audio')
        if mic:
            subtitle += ' + mic'
        title = self.source.title if self.source.kind != 'window' else self.source.app
        picture = app_pixmap(self.source, 20) if self.source.kind == 'window' and self.source.path else \
            {'system': 'display', 'mic': 'mic'}.get(self.source.kind, 'window')
        self.pill.set_source(title, subtitle if self.source.kind != 'window' else f'{subtitle} · {self.source.title}', picture)

    def choose_source(self):
        if self.busy():
            return False
        picker = SourcePicker(self.source, self.include_mic)
        picker.setWindowIcon(self.application.windowIcon())
        if picker.exec() != QDialog.DialogCode.Accepted:
            return False
        self.source, self.include_mic = picker.selected, picker.include_mic
        self.preferences.set(source_kind=self.source.kind, include_mic=self.include_mic, source_path=self.source.path)
        self.refresh_pill()
        return True

    def model_menu(self, position):
        menu = theme.polish_menu(QMenu())
        heading = menu.addAction('Model')
        heading.setEnabled(False)
        for model in MODELS:
            installed = model_path(model.key) is not None
            action = menu.addAction(model.name + ('' if installed else '  —  Download…'))
            action.setCheckable(True)
            action.setChecked(model.key == self.preferences['model'])
            action.triggered.connect(lambda _=False, key=model.key, ready=installed:
                                     self.set_preferences(model=key) if ready else self.open_settings('models'))
        menu.addSeparator()
        processor = theme.polish_menu(menu.addMenu('Processor'))
        cpu_only = BY_KEY[self.preferences['model']].cpu_only
        for device, name in (('cpu', 'CPU'), ('cuda', 'NVIDIA GPU')):
            action = processor.addAction(name, lambda device=device: self.set_preferences(device=device))
            action.setCheckable(True)
            action.setChecked(self.preferences['device'] == device)
            action.setEnabled(device == 'cpu' or not cpu_only)
        language = theme.polish_menu(menu.addMenu('Language'))
        for code, name in LANGUAGES:
            action = language.addAction(name, lambda code=code: self.set_preferences(language=code))
            action.setCheckable(True)
            action.setChecked(self.preferences['language'] == code)
            action.setEnabled(supports_language(self.preferences['model'], code))
        menu.addSeparator()
        menu.addAction('Model Settings…', lambda: self.open_settings('models'))
        menu.exec(position)

    def set_preferences(self, **values):
        if self.busy() and {'model', 'device', 'language'} & values.keys():
            return
        previous = dict(self.preferences)
        self.preferences.set(**values)
        if values.get('appearance') and values['appearance'] != previous['appearance']:
            self.apply_theme()
        if 'hotkey' in values:
            self.apply_hotkey()
        if 'pill_on_top' in values and values['pill_on_top'] != previous['pill_on_top']:
            self.pill.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, values['pill_on_top'])
            self.pill.show()
        if self.preferences['device'] == 'cuda' and previous['device'] != 'cuda':
            self.check_gpu()
        self.refresh_pill()
        if self.settings:
            self.settings.sync(self.gpu_state, self.gpu_detail)

    def apply_hotkey(self):
        if self.preferences['hotkey']:
            registered = self.hotkey.register(int(self.library.winId()))
            if not registered and sys.platform == 'win32':
                logging.warning('Ctrl+Alt+R is already used by another app.')
        else:
            self.hotkey.unregister()
        self.pill.record_button.setToolTip('Record  (Ctrl+Alt+R)' if self.hotkey.hwnd else 'Record')

    # --- GPU -------------------------------------------------------------------------

    def check_gpu(self):
        if self.probe_job and self.probe_job.isRunning():
            return
        self.gpu_state, self.gpu_detail = 'checking', ''
        self.probe_job = HelperJob(['probe'])
        self.probe_job.event.connect(self._gpu_event)
        self.probe_job.failed.connect(lambda message: setattr(self, 'gpu_detail', message))
        self.probe_job.finished.connect(self._gpu_done)
        self.probe_job.start()
        if self.settings:
            self.settings.sync(self.gpu_state, self.gpu_detail)

    def _gpu_event(self, event):
        if event['kind'] == 'probe':
            self.gpu_state = 'ready'
            self.gpu_detail = f"{event['name']} · {event['free_mb'] / 1024:.1f} GB free"

    def _gpu_done(self):
        if self.probe_job.error or self.gpu_state != 'ready':
            self.gpu_state = 'error'
            self.gpu_detail = self.gpu_detail or 'No usable NVIDIA GPU was found.'
        if self.settings:
            self.settings.sync(self.gpu_state, self.gpu_detail)

    # --- Recording -------------------------------------------------------------------

    def busy(self):
        return self.job is not None and self.job.isRunning()

    def toggle_recording(self):
        if self.busy() and self.job.phase == 'recording':
            self.stop()
        elif not self.busy():
            self.record()

    def ready_to_transcribe(self, model_key=None, device=None):
        model_key = model_key or self.preferences['model']
        model = BY_KEY[model_key]
        device = 'cpu' if model.cpu_only else (device or self.preferences['device'])
        if not model_path(model_key):
            choice = alert(None, f'{model.name} isn’t downloaded yet',
                           f'Download it once ({model.size}) and it stays on this PC.',
                           (('Not Now', 'cancel'), ('Show Models', 'primary')))
            if choice == 'Show Models':
                self.open_settings('models')
            return False
        if device == 'cuda' and self.gpu_state != 'ready':
            detail = 'Whistle is still checking your GPU.' if self.gpu_state == 'checking' else (self.gpu_detail or 'No usable NVIDIA GPU was found.')
            choice = alert(None, 'NVIDIA GPU isn’t available', detail, (('Cancel', 'cancel'), ('Use CPU', 'primary')))
            if choice != 'Use CPU':
                return False
            self.set_preferences(device='cpu')
        try:
            validate_choice(model_key, self.preferences['device'] if not model.cpu_only else 'cpu', self.preferences['language'])
        except ValueError as exc:
            alert(None, 'Choose another language or model', str(exc))
            return False
        return True

    def record(self):
        if self.busy():
            if self.job.phase == 'recording':
                self.stop()
            return
        if self.source is None or not window_exists(self.source):
            if self.source is not None and self.source.kind == 'window':
                self.source = self._find_reopened(self.source)
            if self.source is None or not window_exists(self.source):
                if not self.choose_source():
                    return
        if not self.ready_to_transcribe():
            return
        self.start_job(self.source, include_mic=self.include_mic)

    def _find_reopened(self, previous):
        return next((window for window in list_windows() if window.path and window.path == previous.path), None)

    def start_job(self, source, source_audio=None, model_key=None, title=None, include_mic=False, import_audio=False, source_url=None):
        model_key = model_key or self.preferences['model']
        device = 'cpu' if BY_KEY[model_key].cpu_only else self.preferences['device']
        language = self.preferences['language']
        if BY_KEY[model_key].english_only:
            language = 'en'
        self.job = Recorder(source, language, self.library.root, model_key=model_key, device=device, source_audio=source_audio,
                            include_mic=include_mic, vocabulary=self.preferences['vocabulary'], title=title,
                            import_audio=import_audio, source_url=source_url)
        self.job_error, self.job_directory, self.job_title = None, None, title or source.title
        self.job_model = BY_KEY[model_key]
        self.job_percent = None
        self.job.saved.connect(self._saved)
        self.job.phase_changed.connect(self._phase)
        self.job.level.connect(self.pill.push_level)
        self.job.updated.connect(self.library.set_live_paragraphs)
        self.job.progress.connect(self._progress)
        self.job.status.connect(self._status)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._done)
        if source_audio or source_url:
            self.pill.show_working('Preparing', self.job_title)
        self.job.start()
        self._update_tray()

    def _saved(self, path):
        self.job_directory = str(Path(path).parent)
        self.library.set_live(self.job_directory, self.job.phase if self.job else 'idle')

    def _phase(self, phase):
        if phase == 'recording':
            source = self.job.window
            self.pill.show_recording(source.app if source.kind == 'window' else source.title)
        elif phase == 'preparing':
            self.job_percent = None
            self.pill.show_working('Preparing Audio', self.job_title)
        elif phase == 'transcribing':
            self.job_percent = None
            self.pill.show_working('Transcribing', f'{self.job_model.short} · Starting…')
        if phase != 'idle' and self.job_directory:
            self.library.set_live(self.job_directory, phase)
        self.write_ui_state()
        self._update_tray()

    def _progress(self, percent):
        self.job_percent = percent
        self.pill.show_working(self.pill.working_title.text(), f'{self.job_model.short} · {percent}%', percent)
        if self.job_directory:
            self.library.set_live(self.job_directory, self.job.phase, percent)

    def _status(self, text):
        if self.job and self.job.phase in ('preparing', 'transcribing') and self.job_percent is None:
            self.pill.show_working(self.pill.working_title.text(), f'{self.job_model.short} · {text}')
            if self.job_directory:
                self.library.set_live(self.job_directory, self.job.phase, None, text)

    def _failed(self, message):
        logging.error(message)
        self.job_error = message

    def tick(self):
        if not self.busy() or self.job.phase != 'recording':
            return
        seconds = self.job.recorded_seconds
        self.pill.set_elapsed(seconds)
        self.library.set_live_elapsed(seconds, self.job.paused.is_set())
        if self.job.window.kind == 'window' and not self.job.stopping.is_set() and not window_exists(self.job.window):
            self.stop()  # The source app closed: finish and transcribe what was captured.

    def stop(self):
        if self.busy() and self.job.phase == 'recording':
            self.job.stop()
            self.pill.set_finishing()

    def pause(self):
        if self.busy() and self.job.phase == 'recording':
            paused = not self.job.paused.is_set()
            self.job.pause(paused)
            self.pill.set_paused(paused)
            self.library.set_live_elapsed(self.job.recorded_seconds, paused)

    def cancel(self):
        if self.busy():
            self.job.cancel()
            self.pill.show_working('Cancelling…', 'Audio is kept')

    def _done(self):
        job, directory = self.job, self.job_directory
        if job.source_url and job.document:
            self.job_title = job.document.metadata.get('title', self.job_title)
        self.last_finished = directory
        self.library.set_live(None, 'idle')
        self.library.refresh(select=directory if self.library.isVisible() else None)
        self.write_ui_state()
        self._update_tray()
        if self.closing:
            QApplication.quit()
            return
        audio_saved = bool(job.source_audio or (job.document and (job.document.directory / 'Audio.wav').is_file()))
        if job.cancelled.is_set():
            detail = ('Download cancelled; import the URL again to retry' if job.source_url and not audio_saved else
                      ('Audio and any partial text are saved' if audio_saved else 'Nothing was recorded'))
            self.pill.show_result(False, 'Cancelled', detail)
        elif job.error:
            title = 'Couldn’t Transcribe' if audio_saved else ('Couldn’t Import Video' if job.source_url else 'Couldn’t Record')
            self.pill.show_result(False, title, job.error.split('\n')[0], timeout=14000)
            if not directory:
                alert(None, title, job.error)
        else:
            self.pill.show_result(True, 'Transcript Ready', self.job_title)
            if self.preferences['notify_when_done'] and not self.library.isActiveWindow() and self.tray.isVisible():
                self.tray.showMessage('Transcript Ready', self.job_title, theme.icon('waveform', '#0A84FF', 32), 5000)
            if self.preferences['open_when_done'] and not self.queue:
                self.open_library(directory)
        if self.queue:
            QTimer.singleShot(400, self._next_import)

    # --- Imports ---------------------------------------------------------------------

    def import_files(self, paths):
        if not self.ready_to_transcribe():
            return
        self.queue.extend(paths)
        if not self.busy():
            self._next_import()

    def import_url(self, url):
        try:
            url = validate_url(url)
        except ValueError as exc:
            alert(self.library, 'Invalid video URL', str(exc))
            return
        if not self.ready_to_transcribe():
            return
        self.queue.append({'url': url})
        if not self.busy():
            self._next_import()

    def _next_import(self):
        if not self.queue or self.busy():
            return
        item = self.queue.pop(0)
        if isinstance(item, dict):
            from urllib.parse import urlsplit
            url = item['url']
            title = 'Video from ' + urlsplit(url).hostname
            source = Window(0, 0, title, urlsplit(url).hostname, kind='url')
            self.start_job(source, title=title, source_url=url)
            return
        path = Path(item)
        source = Window(0, 0, path.stem, 'Imported file', kind='file')
        self.start_job(source, source_audio=path, title=path.stem, import_audio=True)

    def retranscribe(self, session, model_key=None):
        if self.busy():
            alert(self.library, 'Whistle is busy', 'Wait for the current recording or transcription to finish.')
            return
        model_key = model_key or self.preferences['model']
        if session.audio_path is None or not self.ready_to_transcribe(model_key):
            return
        meta = session.metadata
        source = Window(0, 0, meta.get('source') or session.title, meta.get('app') or 'saved audio',
                        kind=meta.get('source_kind', 'file'))
        self.start_job(source, source_audio=session.audio_path, model_key=model_key, title=session.title)

    # --- Windows and menus -----------------------------------------------------------

    def open_library(self, directory=None):
        if directory:
            self.library.select(directory)
        else:
            self.library.refresh()
        if self.library.isMinimized():
            self.library.showNormal()
        self.library.show()
        self.library.raise_()
        self.library.activateWindow()

    def open_settings(self, page='general'):
        if self.settings is None:
            self.settings = SettingsWindow(self.preferences)
            self.settings.setWindowIcon(self.application.windowIcon())
            self.settings.changed.connect(lambda values: self.set_preferences(**values))
        self.settings.sync(self.gpu_state, self.gpu_detail)
        self.settings.show_page(page)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def more_menu(self, position):
        menu = theme.polish_menu(QMenu())
        menu.addAction(theme.icon('library', theme.tokens()['text']), 'Open Library', lambda: self.open_library())
        action = menu.addAction(theme.icon('import', theme.tokens()['text']), 'Import Audio or Video…', self.library.choose_import)
        action.setEnabled(not self.busy())
        action = menu.addAction(theme.icon('globe', theme.tokens()['text']), 'Import Video URL…', self.library.choose_url)
        action.setEnabled(not self.busy())
        menu.addAction(theme.icon('sliders', theme.tokens()['text']), 'Settings…', lambda: self.open_settings())
        menu.addSeparator()
        menu.addAction('Hide Pill', self.pill.hide)
        menu.addAction('Quit Whistle', self.quit)
        menu.exec(position)

    def _build_tray(self):
        tray = QSystemTrayIcon(self.application.windowIcon(), self)
        tray.setToolTip('Whistle')
        menu = theme.polish_menu(QMenu())
        self.tray_record = menu.addAction('Start Recording', self.toggle_recording)
        menu.addAction('Show Pill', lambda: (self.pill.show(), self.pill.raise_()))
        menu.addAction('Open Library', lambda: self.open_library())
        menu.addAction('Import Video URL…', self.library.choose_url)
        menu.addAction('Settings…', lambda: self.open_settings())
        menu.addSeparator()
        menu.addAction('Quit Whistle', self.quit)
        tray.setContextMenu(menu)
        self.tray_menu = menu
        tray.activated.connect(lambda reason: self.open_library() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.messageClicked.connect(lambda: self.open_library(self.last_finished))
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray.show()
        return tray

    def _update_tray(self):
        recording = self.busy() and self.job.phase == 'recording'
        self.tray_record.setText('Stop Recording' if recording else 'Start Recording')
        self.tray_record.setEnabled(recording or not self.busy())
        self.tray.setToolTip('Whistle — Recording' if recording else ('Whistle — Transcribing' if self.busy() else 'Whistle'))

    def write_ui_state(self):
        phase = self.job.phase if self.busy() else 'idle'
        try:
            (ROOT / 'ui-state.json').write_text(json.dumps({'pid': os.getpid(), 'phase': phase, 'model': self.preferences['model'],
                                                            'device': self.preferences['device']}), encoding='utf-8')
        except OSError:
            pass

    def quit(self):
        if self.busy():
            doing = 'recording' if self.job.phase == 'recording' else 'transcribing'
            choice = alert(None, f'Whistle is {doing}', 'Quit anyway? Audio captured so far is saved, and you can transcribe it later from the library.',
                           (('Keep Going', 'cancel'), ('Quit', 'destructive')))
            if choice != 'Quit':
                return
            self.closing = True
            self.job.cancel()
            return
        if self.settings:
            self.settings.models.shutdown()
        if self.probe_job and self.probe_job.isRunning():
            self.probe_job.cancel()
            self.probe_job.wait(3000)
        self.hotkey.unregister()
        self.library.close()
        self.tray.hide()
        QApplication.quit()

def handoff():
    """If Whistle is already running, ask it to come forward."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER)
    if socket.waitForConnected(300):
        socket.write(b'show')
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()
        return True
    return False

def main():
    logging.basicConfig(filename=ROOT / 'whistle.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Whistle.Transcribe')
        except (AttributeError, OSError):
            pass
    application = QApplication(sys.argv)
    application.setApplicationName('Whistle')
    application.setApplicationDisplayName('Whistle')
    application.setStyle('Fusion')
    application.setFont(theme.font(13))
    application.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT / 'whistle.lock'))
    if not lock.tryLock(100):
        if not handoff():
            QMessageBox.information(None, 'Whistle', 'Whistle is already running. Look for the pill near the bottom of your screen.')
        return 0
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(theme.app_icon(size))
    (ROOT / 'bin').mkdir(exist_ok=True)
    theme.app_icon(256).save(str(ROOT / 'bin' / 'whistle.ico'))
    application.setWindowIcon(icon)
    controller = Whistle(application)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER)
    server.listen(SERVER)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), controller.pill.show(), controller.open_library()))
    application.controller, application.server = controller, server
    return application.exec()

if __name__ == '__main__':
    sys.exit(main())
