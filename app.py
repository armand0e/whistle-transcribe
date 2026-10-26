"""Whistle: a small, always-on-top audio transcription pill for Windows."""
import logging
import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl, QLockFile, QStandardPaths
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget, QFileDialog)

from transcriber import ROOT, timestamp
from capture_jobs import Recorder, HelperJob
from model_catalog import BY_KEY, model_path, validate_choice
from model_picker import ModelPicker
from windows_audio import list_windows, window_exists, Window

STYLE = '''
QWidget { color: #f0f3f6; font-family: 'Segoe UI'; font-size: 13px; }
QDialog, QMenu, Document { background: #1a2029; }
QPushButton { border: 0; border-radius: 15px; padding: 8px 12px; background: #293240; }
QPushButton:hover { background: #37465a; }
QPushButton:disabled { color: #6b7787; }
QLineEdit, QListWidget, QTextEdit, QComboBox, QTreeWidget { background: #111720; border: 1px solid #344052; border-radius: 9px; padding: 10px; }
QHeaderView::section { background: #293240; padding: 8px; border: 0; color: #c9d6e2; }
QTreeWidget::item { padding: 8px 3px; }
QListWidget::item { padding: 10px; border-radius: 6px; }
QListWidget::item:selected { background: #214b48; }
QLabel#muted { color: #a7b3c2; }
QPushButton#record { color: #101e1c; background: #88e4cb; font-weight: 600; }
QPushButton#stop { color: #fff; background: #a94053; font-weight: 600; }
'''

class Picker(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Choose a window · Whistle')
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        heading = QLabel('Which window should Whistle listen to?')
        heading.setStyleSheet('font-size: 19px; font-weight: 600; padding: 8px 0;')
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search open windows…')
        layout.addWidget(self.search)
        self.windows = QListWidget()
        layout.addWidget(self.windows)
        note = QLabel('Captures the selected app and its child processes. Chrome and other\nbrowsers may share audio across tabs and windows. Microphone is off.')
        note.setObjectName('muted')
        layout.addWidget(note)
        row = QHBoxLayout()
        self.language = QComboBox()
        for label, value in [('Detect language', None), ('English', 'en'), ('German', 'de'), ('French', 'fr'), ('Spanish', 'es'), ('Italian', 'it'), ('Dutch', 'nl'), ('Polish', 'pl')]:
            self.language.addItem(label, value)
        row.addWidget(self.language)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        choose = QPushButton('Choose window')
        choose.setObjectName('record')
        choose.clicked.connect(self.accept_selected)
        row.addWidget(choose)
        layout.addLayout(row)
        self.search.textChanged.connect(self.filter)
        self.windows.itemDoubleClicked.connect(self.accept_selected)
        self.refresh()

    def refresh(self):
        self.windows.clear()
        for window in list_windows():
            item = QListWidgetItem(f'{window.title}\n{window.app}  ·  PID {window.pid}')
            item.setData(Qt.ItemDataRole.UserRole, window)
            self.windows.addItem(item)
        self.filter()

    def filter(self):
        query = self.search.text().casefold()
        for index in range(self.windows.count()):
            item = self.windows.item(index)
            item.setHidden(query not in item.text().casefold())

    def accept_selected(self, *_):
        item = self.windows.currentItem()
        if item and not item.isHidden():
            self.selected = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

class Document(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle('Transcript · Whistle')
        self.resize(750, 650)
        self.setStyleSheet(STYLE + 'Document { background: #1a2029; }')
        layout = QVBoxLayout(self)
        title = QLabel('Your transcript')
        title.setStyleSheet('font-size: 23px; font-weight: 600; margin: 12px;')
        layout.addWidget(title)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText('Record a window, then press Stop. Your chosen model will create a transcript here.')
        self.text.setStyleSheet('font-size: 16px; padding: 18px;')
        layout.addWidget(self.text)
        self.pending = QLabel('')
        self.pending.setWordWrap(True)
        self.pending.setObjectName('muted')
        layout.addWidget(self.pending)
        self.path = None
        row = QHBoxLayout()
        for label, callback in [('Open document', self.open_file), ('Show folder', self.open_folder)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def update_text(self, text, pending):
        scroll = self.text.verticalScrollBar()
        follow = scroll.value() >= scroll.maximum() - 30
        self.text.setPlainText(text)
        if follow:
            scroll.setValue(scroll.maximum())
        self.pending.setText(('Live: ' + pending) if pending else '')

    def open_file(self):
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def open_folder(self):
        folder = Path(self.path).parent if self.path else ROOT / 'transcripts'
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

class Pill(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('Whistle')
        self.setFixedSize(600, 64)
        self.window = None
        self.worker = None
        self.language = 'en'
        self.model_key = 'small_en'
        self.device_name = 'cpu'
        try:
            settings = json.loads((ROOT / 'settings.json').read_text(encoding='utf-8'))
            self.model_key = settings.get('model', 'small_en')
            self.device_name = settings.get('device', 'cpu')
            self.language = settings.get('language', 'en')
            validate_choice(self.model_key, self.device_name, self.language)
        except (OSError, ValueError, KeyError):
            self.model_key, self.device_name, self.language = 'small_en', 'cpu', 'en'
        self.gpu_ready = False
        self.probe_job = None
        self.started = None
        self.last_audio = None
        self.closing = False
        self.document = Document()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self.source = QPushButton('Choose window  ▾')
        self.source.setFixedWidth(130)
        self.source.clicked.connect(self.pick)
        layout.addWidget(self.source)
        self.model_button = QPushButton(BY_KEY[self.model_key].short + ' ▾')
        self.model_button.setFixedWidth(115)
        self.model_button.setToolTip('Choose model · quality and speed')
        self.model_button.clicked.connect(self.pick_model)
        layout.addWidget(self.model_button)
        self.device = QComboBox()
        self.device.addItem('CPU', 'cpu'); self.device.addItem('GPU', 'cuda')
        self.device.setFixedWidth(72)
        self.device.setStyleSheet('padding: 5px;')
        self.device.setToolTip('CPU or NVIDIA CUDA GPU. Whistle and native Windows Phonon use CPU.')
        self.device.setCurrentIndex(1 if self.device_name == 'cuda' else 0)
        self.device.setEnabled(self.model_key != 'whistle' and not BY_KEY[self.model_key].cpu_only)
        self.device.currentIndexChanged.connect(self.device_changed)
        layout.addWidget(self.device)
        self.info = QLabel('Ready')
        self.info.setFixedWidth(82)
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setObjectName('muted')
        layout.addWidget(self.info)
        self.record = QPushButton('● Record')
        self.record.setFixedWidth(80)
        self.record.setObjectName('record')
        self.record.clicked.connect(self.toggle)
        layout.addWidget(self.record)
        document = QPushButton('▤')
        document.setToolTip('Show transcription document')
        document.setFixedWidth(32)
        document.clicked.connect(self.show_document)
        layout.addWidget(document)
        more = QPushButton('⋮')
        more.setFixedWidth(22)
        more.setStyleSheet('border-radius: 12px; padding: 4px;')
        more.setToolTip('Menu')
        more.clicked.connect(self.menu)
        layout.addWidget(more)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - 110)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(500)
        self.drag = None
        self.write_ui_state()
        if self.device_name == 'cuda':
            QTimer.singleShot(0, self.check_gpu)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor('#3c4c5e'))
        painter.setBrush(QColor('#1a2029'))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 31, 31)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        self.drag = None

    def pick(self):
        picker = Picker(self)
        index = picker.language.findData(self.language)
        picker.language.setCurrentIndex(max(0, index))
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.window = picker.selected
            self.language = picker.language.currentData()
            title = self.window.title
            self.source.setText(title[:14] + ('…' if len(title) > 14 else '') + ' ▾')
            self.source.setToolTip(f'{title}\nAudio from {self.window.app} and its child processes')
            self.save_settings()

    def save_settings(self):
        temporary = ROOT / 'settings.tmp'
        temporary.write_text(json.dumps({'model': self.model_key, 'device': self.device_name, 'language': self.language}), encoding='utf-8')
        os.replace(temporary, ROOT / 'settings.json')

    def pick_model(self):
        picker = ModelPicker(self.model_key, self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.model_key = picker.selected
            self.model_button.setText(BY_KEY[self.model_key].short + ' ▾')
            cpu_only = self.model_key == 'whistle' or BY_KEY[self.model_key].cpu_only
            if cpu_only:
                self.device.setCurrentIndex(0)
            self.device.setEnabled(not cpu_only)
            if BY_KEY[self.model_key].english_only:
                self.language = 'en'
            self.save_settings()

    def device_changed(self):
        self.device_name = self.device.currentData()
        self.save_settings()
        if self.device_name == 'cuda':
            self.check_gpu()
        else:
            self.info.setText('Ready')

    def check_gpu(self):
        if self.probe_job and self.probe_job.isRunning():
            return
        self.record.setEnabled(False)
        self.info.setText('GPU check…')
        self.probe_job = HelperJob(['probe'])
        self.probe_job.event.connect(self.gpu_event)
        self.probe_job.failed.connect(lambda message: self.device.setToolTip(message))
        self.probe_job.finished.connect(self.gpu_checked)
        self.probe_job.start()

    def gpu_event(self, event):
        if event['kind'] == 'probe':
            self.gpu_ready = True
            self.device.setToolTip(f"NVIDIA CUDA: {event['name']} · {event['free_mb']} MB free VRAM")

    def gpu_checked(self):
        if self.probe_job.error:
            self.gpu_ready = False
        self.record.setEnabled(True)
        self.info.setText('Ready' if self.gpu_ready else 'GPU error')

    def write_ui_state(self):
        phase = self.worker.phase if self.worker and self.worker.isRunning() else 'idle'
        (ROOT / 'ui-state.json').write_text(json.dumps({'pid': os.getpid(), 'phase': phase, 'model': self.model_key, 'device': self.device_name}), encoding='utf-8')

    def toggle(self):
        if self.worker and self.worker.isRunning():
            if self.worker.phase == 'transcribing':
                self.info.setText('Cancelling…'); self.worker.cancel()
            else:
                self.info.setText('Saving…'); self.worker.stop()
            self.record.setEnabled(False)
            return
        if not self.window or not window_exists(self.window):
            self.pick()
        if not self.window or not window_exists(self.window):
            return
        self.start_job()

    def start_job(self, source_audio=None, window=None):
        try:
            validate_choice(self.model_key, self.device_name, self.language)
            if not model_path(self.model_key):
                self.pick_model()
                if not model_path(self.model_key):
                    return
            if self.device_name == 'cuda' and not self.gpu_ready:
                raise ValueError('NVIDIA CUDA is not ready. Check the GPU selector tooltip or choose CPU.')
        except ValueError as exc:
            self.error(str(exc)); return
        self.worker = Recorder(window or self.window, self.language, model_key=self.model_key,
                               device=self.device_name, source_audio=source_audio)
        self.worker.status.connect(self.status_changed)
        self.worker.transcript.connect(self.document.update_text)
        self.worker.level.connect(self.audio_level)
        self.worker.saved.connect(self.set_document)
        self.worker.phase_changed.connect(self.phase_changed)
        self.worker.progress.connect(self.show_progress)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.done)
        self.source.setEnabled(False)
        self.model_button.setEnabled(False); self.device.setEnabled(False)
        self.record.setText('■ Stop')
        self.record.setObjectName('stop')
        self.record.setStyleSheet('background: #a94053; color: white;')
        self.info.setText('Starting…')
        self.worker.start()

    def transcribe_saved(self):
        if self.worker and self.worker.isRunning():
            return
        filename, _ = QFileDialog.getOpenFileName(self, 'Transcribe saved audio', str(ROOT / 'transcripts'), 'WAV audio (*.wav)')
        if filename:
            title = Path(filename).stem
            try:
                metadata = json.loads((Path(filename).parent / 'session.json').read_text(encoding='utf-8'))
                title = metadata.get('source', title)
            except (OSError, ValueError):
                pass
            self.start_job(filename, Window(0, 0, title, 'saved audio'))

    def phase_changed(self, phase):
        self.started = None if phase != 'recording' else self.started
        if phase == 'transcribing':
            self.record.setText('Cancel'); self.record.setEnabled(True)
            self.document.pending.setText('Transcribing saved audio…')
        self.write_ui_state()

    def show_progress(self, percent):
        self.info.setText(f'{percent}% done')
        self.document.pending.setText(f'Transcribing · {percent}%')

    def set_document(self, path):
        self.document.path = path
        self.document.update_text(Path(path).read_text(encoding='utf-8'), '')

    def status_changed(self, status):
        if status == 'Recording':
            self.started = time.monotonic()
            self.last_audio = None
        self.info.setText('Working…' if len(status) > 14 else status)
        self.info.setToolTip(status)
        if status == 'Recording':
            self.document.pending.setText('Recording audio. Press Stop to create your transcript.')

    def audio_level(self, level):
        if level > 0.0004:
            self.last_audio = time.monotonic()

    def tick(self):
        if self.worker and self.worker.isRunning() and self.started and not self.worker.stopping.is_set():
            self.info.setText('● ' + timestamp(time.monotonic() - self.started))
            active = self.last_audio is not None and time.monotonic() - self.last_audio < 2
            self.info.setStyleSheet('color: #88e4cb;' if active else 'color: #a7b3c2;')
            self.info.setToolTip('Audio detected' if active else 'Waiting for audio from the selected app')
            if not window_exists(self.window):
                self.worker.stop()
                self.info.setText('Saving…')

    def done(self):
        self.started = None
        self.source.setEnabled(True)
        self.model_button.setEnabled(True)
        self.device.setEnabled(self.model_key != 'whistle' and not BY_KEY[self.model_key].cpu_only)
        self.record.setEnabled(True)
        self.record.setText('● Record')
        self.record.setObjectName('record')
        self.record.setStyleSheet('background: #88e4cb; color: #101e1c;')
        cancelled = self.worker.cancelled.is_set()
        audio_saved = bool(self.worker.source_audio or (self.worker.document and (self.worker.document.directory / 'Audio.wav').is_file()))
        if cancelled:
            message = 'Cancelled. Audio and any partial text are saved.' if audio_saved else 'Cancelled before recording started.'
        elif self.worker.error:
            message = 'Transcription failed. Audio is saved; retry from the menu.' if audio_saved else 'Recording could not start. See the error for details.'
        else:
            message = 'Transcript saved locally.'
        self.document.pending.setText(message)
        self.write_ui_state()
        if self.closing:
            QApplication.quit()
        elif not cancelled and not self.worker.error:
            self.show_document()

    def error(self, message):
        logging.error(message)
        QMessageBox.warning(self, 'Whistle', message)

    def show_document(self):
        self.document.show()
        self.document.raise_()
        self.document.activateWindow()

    def menu(self):
        menu = QMenu(self)
        action = menu.addAction('Transcribe saved audio…', self.transcribe_saved)
        action.setEnabled(not (self.worker and self.worker.isRunning()))
        action = menu.addAction('Choose model…', self.pick_model)
        action.setEnabled(not (self.worker and self.worker.isRunning()))
        menu.addAction('Open transcripts folder', self.document.open_folder)
        menu.addAction('Quit Whistle', self.close)
        menu.exec(self.mapToGlobal(self.rect().bottomRight()))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.closing = True
            self.worker.cancel()
            self.info.setText('Saving…')
            event.ignore()
        else:
            if self.probe_job and self.probe_job.isRunning():
                self.probe_job.cancel()
                self.probe_job.wait(3000)
            self.document.close()
            event.accept()
            QApplication.quit()

def main():
    logging.basicConfig(filename=ROOT / 'whistle.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    application = QApplication(sys.argv)
    application.setStyleSheet(STYLE)
    application.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT / 'whistle.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None, 'Whistle', 'Whistle is already running. Look for the pill near the bottom of your screen.')
        return 0
    icon = QPixmap(64, 64)
    icon.fill(Qt.GlobalColor.transparent)
    painter = QPainter(icon)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#88e4cb'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 15, 56, 34, 17, 17)
    painter.setPen(QColor('#172722'))
    font = painter.font(); font.setPixelSize(23); font.setBold(True); painter.setFont(font)
    painter.drawText(icon.rect(), Qt.AlignmentFlag.AlignCenter, 'w')
    painter.end()
    icon.save(str(ROOT / 'bin' / 'whistle.ico'))
    application.setWindowIcon(QIcon(icon))
    pill = Pill()
    pill.show()
    return application.exec()

if __name__ == '__main__':
    sys.exit(main())
