"""A small URL import sheet."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QVBoxLayout
import theme
from url_import import validate_url
from widgets import label


class UrlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Transcribe a Video URL')
        self.setObjectName('Grouped')
        self.setMinimumWidth(520)
        self.resize(560, 280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label('Transcribe a Video URL', size=20))
        layout.addWidget(label('Paste a YouTube link or another supported video/audio URL. '
                               'Whistle downloads the audio and transcribes it with your selected model.',
                               'caption', wrap=True))
        self.field = QLineEdit()
        self.field.setPlaceholderText('https://www.youtube.com/watch?v=…')
        self.field.setAccessibleName('Video URL')
        self.field.setClearButtonEnabled(True)
        layout.addWidget(self.field)
        self.note = label('One video per import. Playlist links use the first video. '
                          'Live streams and videos requiring a login may not work.', 'caption', wrap=True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.submit = buttons.addButton('Transcribe', QDialogButtonBox.ButtonRole.AcceptRole)
        self.submit.setProperty('kind', 'primary')
        self.submit.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.field.textChanged.connect(self.check)
        self.field.returnPressed.connect(lambda: self.accept() if self.submit.isEnabled() else None)
        theme.apply_chrome(self)

    def check(self):
        try:
            validate_url(self.field.text())
            valid = True
        except ValueError:
            valid = False
        self.submit.setEnabled(valid)

    @property
    def url(self):
        return validate_url(self.field.text())
