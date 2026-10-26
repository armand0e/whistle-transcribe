"""Model comparison and on-demand downloads for the pill."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QHeaderView
from capture_jobs import HelperJob
from model_catalog import MODELS, BY_KEY, ROOT, model_path

class ModelPicker(QDialog):
    def __init__(self, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Transcription models · Whistle')
        self.resize(850, 490)
        self.selected = selected
        self.job = None
        self.closing = False
        layout = QVBoxLayout(self)
        heading = QLabel('Choose your transcription model')
        heading.setStyleSheet('font-size: 21px; font-weight: 600; padding: 8px 0;')
        layout.addWidget(heading)
        note = QLabel('Quality and speed are relative guidance, not guaranteed scores.\nWhistle, Small.en, Phonon-2 and Nemotron were tried on your lecture audio. Larger Whisper options are unbenchmarked here.')
        note.setObjectName('muted'); note.setWordWrap(True)
        layout.addWidget(note)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Model', 'Quality guidance', 'Speed guidance', 'Device', 'Download', 'Status'])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        for model in MODELS:
            item = QTreeWidgetItem([model.name, model.quality, model.speed,
                                   'CPU' if model.key == 'whistle' or model.cpu_only else 'CPU / CUDA', model.size, ''])
            item.setData(0, Qt.ItemDataRole.UserRole, model.key)
            self.tree.addTopLevelItem(item)
            if model.key == selected:
                self.tree.setCurrentItem(item)
        layout.addWidget(self.tree)
        self.description = QLabel('')
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(48)
        layout.addWidget(self.description)
        self.status = QLabel('Models run locally. Downloads happen once; recordings stay on this computer.')
        self.status.setObjectName('muted'); self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.download = QPushButton('Download model')
        self.download.clicked.connect(self.download_selected)
        row.addWidget(self.download)
        row.addStretch()
        self.use = QPushButton('Use model'); self.use.setObjectName('record')
        self.use.clicked.connect(self.choose)
        row.addWidget(self.use)
        layout.addLayout(row)
        self.tree.currentItemChanged.connect(self.refresh)
        self.tree.itemDoubleClicked.connect(lambda *_: self.choose())
        self.refresh()

    def current_key(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else self.selected

    def refresh(self, *_):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setText(5, 'Ready' if model_path(item.data(0, Qt.ItemDataRole.UserRole)) else 'Not downloaded')
        model = BY_KEY[self.current_key()]
        description = model.description + (' English only.' if model.english_only else '')
        try:
            measured = json.loads((ROOT / 'models' / 'benchmarks.json').read_text(encoding='utf-8'))['results'].get(model.key, {})
            if measured:
                description += '\nLocal 56s clip, including startup: ' + ' · '.join(f'{device.upper()} {run["elapsed_seconds"]:.1f}s' for device, run in measured.items())
        except (OSError, ValueError, KeyError):
            pass
        self.description.setText(description)
        busy = self.job is not None and self.job.isRunning()
        ready = model_path(model.key) is not None
        self.use.setEnabled(ready and not busy)
        self.download.setEnabled(not ready or busy)
        self.download.setText('Cancel download' if busy else f'Download {model.size}')

    def choose(self):
        if self.use.isEnabled():
            self.selected = self.current_key()
            self.accept()

    def download_selected(self):
        if self.job and self.job.isRunning():
            self.job.cancel()
            self.status.setText('Cancelling download… Partial downloads can be resumed.')
            return
        key = self.current_key()
        self.job = HelperJob(['download', '--model', key])
        self.job.event.connect(self.on_event)
        self.job.failed.connect(lambda message: self.status.setText(message))
        self.job.finished.connect(self.download_done)
        self.tree.setEnabled(False); self.use.setEnabled(False)
        self.download.setText('Cancel download'); self.download.setEnabled(True)
        self.status.setText(f'Downloading {BY_KEY[key].name} ({BY_KEY[key].size})…')
        self.job.start()

    def on_event(self, event):
        if event['kind'] == 'status':
            self.status.setText(event['text'])
        elif event['kind'] == 'ready':
            self.status.setText('Download complete. Ready to use.')

    def download_done(self):
        self.tree.setEnabled(True)
        if self.job.cancelled.is_set():
            self.status.setText('Download cancelled. Choose Download to resume later.')
        self.refresh()
        if self.closing:
            super().reject()

    def reject(self):
        if self.job and self.job.isRunning():
            self.closing = True
            self.job.cancel()
            self.status.setText('Cancelling download…')
        else:
            super().reject()

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            event.ignore(); self.reject()
        else:
            event.accept()
