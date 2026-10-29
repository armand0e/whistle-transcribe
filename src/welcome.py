"""First-run welcome sheet."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import theme
from source_picker import symbol_tile
from widgets import label

FEATURES = (
    ('waveform', '#FF453A', 'Transcribe anything you hear',
     'Record one app, everything playing on your PC, or your microphone — or mix your voice into a call.'),
    ('lock', '#30D158', 'Private by design',
     'Recording and transcription run entirely on this computer. Nothing is uploaded.'),
    ('library', '#0A84FF', 'A library that remembers',
     'Search every transcript, click any line to hear it, edit, and export to text or subtitles.'),
)

class Welcome(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Welcome to Whistle')
        self.setFixedWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 32)
        layout.setSpacing(0)
        picture = QLabel()
        picture.setPixmap(theme.app_icon(160).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(picture)
        layout.addSpacing(18)
        title = label('Welcome to Whistle', size=28, weight=QFont.Weight.Bold, display=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(28)
        for symbol, fill, heading, body in FEATURES:
            row = QHBoxLayout()
            row.setSpacing(16)
            tile = QLabel()
            tile.setPixmap(symbol_tile(symbol, fill, 40))
            tile.setFixedSize(40, 40)
            row.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(label(heading, size=14, weight=QFont.Weight.DemiBold))
            text.addWidget(label(body, 'secondary', wrap=True))
            row.addLayout(text, 1)
            layout.addLayout(row)
            layout.addSpacing(20)
        layout.addSpacing(12)
        hint = label('The pill near the bottom of your screen starts a recording. Press Ctrl+Alt+R from anywhere.',
                     'caption', wrap=True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addSpacing(16)
        start = QPushButton('Continue')
        start.setProperty('kind', 'primary')
        start.setMinimumHeight(36)
        start.setDefault(True)
        start.clicked.connect(self.accept)
        layout.addWidget(start)
        theme.apply_chrome(self)
