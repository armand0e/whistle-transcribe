"""Model cards with on-demand downloads, shown in Settings › Models."""
import json

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

import theme
from capture_jobs import HelperJob
from model_catalog import BY_KEY, MODELS, ROOT, model_path
from widgets import ProgressRing, label

def benchmarks():
    try:
        return json.loads((ROOT / 'models' / 'benchmarks.json').read_text(encoding='utf-8'))['results']
    except (OSError, ValueError, KeyError):
        return {}

class Radio(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.checked = False
        self.available = True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color('accent'))
            painter.drawEllipse(QRectF(1, 1, 20, 20))
            painter.drawPixmap(4, 4, theme.pixmap('checkmark', '#FFFFFF', 14))
        else:
            painter.setPen(QPen(theme.color('tertiary' if self.available else 'separator'), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(1.5, 1.5, 19, 19))

class ModelRow(QFrame):
    clicked = Signal(str)
    download = Signal(str)

    def __init__(self, model, measured):
        super().__init__()
        self.key = model.key
        self.setObjectName('Card')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        self.radio = Radio()
        layout.addWidget(self.radio, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(label(model.name, size=14, weight=QFont.Weight.DemiBold))
        if model.key == 'small_en':
            badge = label('Recommended', size=11, weight=QFont.Weight.DemiBold)
            badge.setStyleSheet(f"color: {theme.tokens()['accent']}; background: {theme.tokens()['accent_soft']};"
                                'border-radius: 6px; padding: 1px 6px;')
            heading.addWidget(badge)
        heading.addStretch()
        text.addLayout(heading)
        facts = [model.size, 'CPU' if model.cpu_only else 'CPU or GPU',
                 'English' if model.english_only else ('Multilingual' if len(model.languages) > 8 else 'European languages'),
                 f'Quality: {model.quality}', f'Speed: {model.speed}']
        if model.vocabulary:
            facts.append('Vocabulary')
        text.addWidget(label('  ·  '.join(facts), 'caption', wrap=True))
        description = model.description
        if measured:
            description += '  Local 56 s clip: ' + ', '.join(f'{device.upper()} {run["elapsed_seconds"]:.1f} s'
                                                            for device, run in measured.items()) + '.'
        text.addWidget(label(description, 'caption', wrap=True))
        layout.addLayout(text, 1)
        self.action = QPushButton()
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(lambda: self.download.emit(self.key))
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.ring = ProgressRing(20, theme.tokens()['accent'], theme.tokens()['control'])
        self.ring.hide()
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        self.installed = False

    def update_state(self, selected, installed, downloading, busy):
        self.installed = installed
        self.radio.checked = selected
        self.radio.available = installed
        self.radio.update()
        self.ring.setVisible(downloading)
        if downloading:
            self.ring.colour, self.ring.track = theme.color('accent'), theme.color('control')
            self.ring.set_value(None)
        self.action.setVisible(not installed or downloading)
        self.action.setText('Cancel' if downloading else 'Get')
        self.action.setToolTip('' if downloading else 'Download this model')
        self.action.setProperty('kind', 'plain' if downloading else 'soft')
        self.action.style().unpolish(self.action)
        self.action.style().polish(self.action)
        self.action.setEnabled(downloading or not busy)
        self.setToolTip('' if installed else 'Download this model to use it')
        selected_border = theme.tokens()['accent'] if selected else 'transparent'
        self.setStyleSheet(f'#Card {{ border: 1.5px solid {selected_border}; }}')

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.installed:
            self.clicked.emit(self.key)

class ModelList(QWidget):
    """Every model as a card. Selecting needs the model installed; downloads are resumable."""
    selected_changed = Signal(str)
    status = Signal(str)

    def __init__(self, selected, parent=None):
        super().__init__(parent)
        self.selected = selected
        self.job = None
        self.job_key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        measured = benchmarks()
        self.rows = {}
        for model in MODELS:
            row = ModelRow(model, measured.get(model.key, {}))
            row.clicked.connect(self.choose)
            row.download.connect(self.toggle_download)
            layout.addWidget(row)
            self.rows[model.key] = row
        self.message = label('Models run on this PC. Each downloads once; audio never leaves your computer.', 'caption', wrap=True)
        layout.addWidget(self.message)
        self.refresh()

    def busy(self):
        return self.job is not None and self.job.isRunning()

    def refresh(self):
        for key, row in self.rows.items():
            row.update_state(key == self.selected, model_path(key) is not None, self.busy() and key == self.job_key, self.busy())

    def choose(self, key):
        if model_path(key) is None:
            return
        self.selected = key
        self.refresh()
        self.selected_changed.emit(key)

    def toggle_download(self, key):
        if self.busy():
            if key == self.job_key:
                self.job.cancel()
                self.message.setText('Cancelling… Partial downloads resume next time.')
            return
        self.job_key = key
        self.job = HelperJob(['download', '--model', key])
        self.job.event.connect(self._event)
        self.job.failed.connect(lambda message: self.message.setText(message))
        self.job.finished.connect(self._done)
        self.message.setText(f'Downloading {BY_KEY[key].name} ({BY_KEY[key].size})…')
        self.job.start()
        self.refresh()

    def _event(self, event):
        if event['kind'] == 'status':
            self.message.setText(event['text'])
        elif event['kind'] == 'ready':
            self.message.setText(f'{BY_KEY[self.job_key].name} is ready.')

    def _done(self):
        key, job = self.job_key, self.job
        if job.cancelled.is_set():
            self.message.setText('Download cancelled. Choose Download to resume later.')
        self.refresh()
        if not job.error and not job.cancelled.is_set() and model_path(key):
            self.choose(key)

    def shutdown(self):
        if self.busy():
            self.job.cancel()
            self.job.wait(5000)
