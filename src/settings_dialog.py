"""Settings, laid out as inset grouped cards."""
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QPlainTextEdit, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

import theme
from auto_update import ROOT, update_status
from version import VERSION
from model_catalog import BY_KEY, LANGUAGES, supports_language
from model_picker import ModelList
from sessions import TRANSCRIPTS
from widgets import GroupedCard, Segmented, Switch, label

class SettingsWindow(QDialog):
    changed = Signal(dict)
    gpu_check = Signal()

    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.setWindowTitle('Settings')
        self.setObjectName('Grouped')
        self.resize(640, 720)
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 16, 0, 0)
        outer.setSpacing(12)
        self.tabs = Segmented([('general', 'General'), ('models', 'Models'), ('vocabulary', 'Vocabulary')], 'general')
        self.tabs.setFixedWidth(330)
        outer.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignHCenter)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.pages.addWidget(self._scroll(self._general()))
        self.models = ModelList(preferences['model'])
        self.models.selected_changed.connect(lambda key: self._set(model=key))
        self.pages.addWidget(self._scroll(self._models()))
        self.pages.addWidget(self._scroll(self._vocabulary()))
        self.tabs.changed.connect(lambda value: self.pages.setCurrentIndex([key for key, _ in self.tabs.options].index(value)))
        self.sync()
        theme.apply_chrome(self)

    def _scroll(self, content):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.setObjectName('Grouped')
        area.setWidget(content)
        return area

    def _page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 8, 28, 28)
        layout.setSpacing(6)
        return page, layout

    def _section(self, layout, title, card, footer=None):
        heading = label(title, 'section')
        heading.setContentsMargins(16, 14, 0, 2)
        layout.addWidget(heading)
        layout.addWidget(card)
        if footer:
            note = label(footer, 'caption', wrap=True)
            note.setContentsMargins(16, 2, 16, 0)
            layout.addWidget(note)

    def _general(self):
        page, layout = self._page()
        card = GroupedCard()
        self.language = QComboBox()
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setMinimumWidth(190)
        self.language.currentIndexChanged.connect(lambda: self._set(language=self.language.currentData()))
        self.language_row = card.add_row('Spoken language', self.language, '')
        self.device = Segmented([('cpu', 'CPU'), ('cuda', 'NVIDIA GPU')], self.preferences['device'])
        self.device.setFixedWidth(200)
        self.device.changed.connect(lambda value: self._set(device=value))
        self.device_row = card.add_row('Processor', self.device, '')
        self._section(layout, 'TRANSCRIPTION', card)

        card = GroupedCard()
        self.hotkey = Switch(self.preferences['hotkey'])
        self.hotkey.toggled.connect(lambda value: self._set(hotkey=value))
        self.hotkey_row = card.add_row('Keyboard shortcut', self.hotkey, 'Press Ctrl+Alt+R anywhere to start or stop recording.')
        self.on_top = Switch(self.preferences['pill_on_top'])
        self.on_top.toggled.connect(lambda value: self._set(pill_on_top=value))
        card.add_row('Keep the pill above other windows', self.on_top)
        self._section(layout, 'RECORDING', card)

        card = GroupedCard()
        self.open_done = Switch(self.preferences['open_when_done'])
        self.open_done.toggled.connect(lambda value: self._set(open_when_done=value))
        card.add_row('Open the transcript', self.open_done)
        self.notify = Switch(self.preferences['notify_when_done'])
        self.notify.toggled.connect(lambda value: self._set(notify_when_done=value))
        card.add_row('Show a notification', self.notify)
        self._section(layout, 'WHEN A TRANSCRIPT IS READY', card)

        card = GroupedCard()
        self.appearance = Segmented([('system', 'Automatic'), ('light', 'Light'), ('dark', 'Dark')], self.preferences['appearance'])
        self.appearance.setFixedWidth(250)
        self.appearance.changed.connect(lambda value: self._set(appearance=value))
        card.add_row('Appearance', self.appearance)
        self._section(layout, 'APPEARANCE', card)

        card = GroupedCard()
        reveal = QPushButton('Show in Explorer')
        reveal.clicked.connect(lambda: (TRANSCRIPTS.mkdir(exist_ok=True), QDesktopServices.openUrl(QUrl.fromLocalFile(str(TRANSCRIPTS)))))
        card.add_row('Transcripts folder', reveal, str(TRANSCRIPTS))
        self._section(layout, 'STORAGE', card, 'Recordings and transcripts stay on this PC until you delete them.')

        card = GroupedCard()
        log = QPushButton('Open update log')
        log_path = ROOT / '.updates' / 'update.log'
        log.setEnabled(log_path.is_file())
        log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path))))
        status = update_status()
        detail = 'Version ' + VERSION + '\n' + status.get('message', 'Checks the latest stable GitHub Release when launched.')
        if status.get('checked'):
            detail += '\nLast check: ' + status['checked']
        card.add_row('Automatic updates', log, detail)
        self._section(layout, 'UPDATES', card,
                      'Updates install published stable releases, not individual commits. '
                      'Quit Whistle from the tray, then reopen it to check. Saved data stays in place.')
        layout.addStretch()
        return page

    def _models(self):
        page, layout = self._page()
        intro = label('Quality and speed are guidance from local tests, not guaranteed scores. Larger models are '
                      'usually more accurate and slower.', 'caption', wrap=True)
        intro.setContentsMargins(4, 8, 4, 6)
        layout.addWidget(intro)
        layout.addWidget(self.models)
        layout.addStretch()
        return page

    def _vocabulary(self):
        page, layout = self._page()
        card = GroupedCard()
        self.vocabulary = QPlainTextEdit(self.preferences['vocabulary'])
        self.vocabulary.setPlaceholderText('e.g. Kubernetes, Dr. Nakamura, tRNAscan-SE, OKRs, Figma')
        self.vocabulary.setMinimumHeight(170)
        self.vocabulary.setStyleSheet('QPlainTextEdit { border-radius: 12px; padding: 12px; background: transparent; }')
        card.rows.addWidget(self.vocabulary)
        self.vocabulary_timer = QTimer(self)
        self.vocabulary_timer.setSingleShot(True)
        self.vocabulary_timer.timeout.connect(lambda: self._set(vocabulary=self.vocabulary.toPlainText().strip()))
        self.vocabulary.textChanged.connect(lambda: self.vocabulary_timer.start(400))
        self.vocabulary_note = label('', 'caption', wrap=True)
        self._section(layout, 'NAMES, JARGON, AND ACRONYMS', card,
                      'Separate terms with commas. Whistle nudges supported models toward these spellings, which helps '
                      'with names and technical terms.')
        self.vocabulary_note.setContentsMargins(16, 6, 16, 0)
        layout.addWidget(self.vocabulary_note)
        layout.addStretch()
        return page

    def show_page(self, name):
        self.tabs.set_value(name, animate=False)
        self.pages.setCurrentIndex([key for key, _ in self.tabs.options].index(name))

    def _set(self, **values):
        self.changed.emit(values)

    def sync(self, gpu_state=None, gpu_detail=''):
        """Reflect current preferences and GPU state without re-emitting changes."""
        preferences = self.preferences
        model = BY_KEY[preferences['model']]
        self.language.blockSignals(True)
        self.language.setCurrentIndex(max(0, self.language.findData(preferences['language'])))
        for index in range(self.language.count()):
            item = self.language.model().item(index)
            item.setEnabled(supports_language(model.key, self.language.itemData(index)))
        self.language.blockSignals(False)
        self.language_row.detail.setText(f'{model.name} understands English only.' if model.english_only else
                                         'Detection works best with longer recordings.')
        self.device.set_disabled({'cuda'} if model.cpu_only else set())
        self.device.set_value(preferences['device'])
        if model.cpu_only:
            detail = f'{model.name} runs on the CPU.'
        elif preferences['device'] == 'cuda':
            detail = {'checking': 'Checking your NVIDIA GPU…', 'ready': gpu_detail or 'NVIDIA GPU ready.',
                      'error': gpu_detail or 'NVIDIA GPU unavailable. Choose CPU.'}.get(gpu_state, 'NVIDIA CUDA acceleration.')
        else:
            detail = 'Works on every PC. Choose NVIDIA GPU for faster Whisper and Nemotron.'
        self.device_row.detail.setText(detail)
        self.device_row.detail.setProperty('role', 'error' if gpu_state == 'error' and preferences['device'] == 'cuda' else 'caption')
        self.device_row.detail.style().unpolish(self.device_row.detail)
        self.device_row.detail.style().polish(self.device_row.detail)
        self.appearance.set_value(preferences['appearance'])
        self.models.selected = preferences['model']
        self.models.refresh()
        self.vocabulary_note.setText(f'{model.name} uses your vocabulary.' if model.vocabulary else
                                     f'{model.name} does not use custom vocabulary. Whisper and Whistle models do.')

    def closeEvent(self, event):
        if self.vocabulary_timer.isActive():
            self.vocabulary_timer.stop()
            self._set(vocabulary=self.vocabulary.toPlainText().strip())
        super().closeEvent(event)
