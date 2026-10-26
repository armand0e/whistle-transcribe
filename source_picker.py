"""Choose what Whistle records: one app, everything on the PC, or the microphone."""
from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileIconProvider, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout)

import theme
from widgets import Switch, hairline, label
from windows_audio import MICROPHONE, SYSTEM_AUDIO, is_browser, list_windows

ROLE = Qt.ItemDataRole.UserRole
HEADER = Qt.ItemDataRole.UserRole + 1
_icons = {}

def app_pixmap(window, size=32):
    """The executable's own icon, or a symbol tile for system sources."""
    key = (window.kind, window.path, size)
    if key in _icons:
        return _icons[key]
    picture = None
    if window.kind == 'window' and window.path:
        icon = QFileIconProvider().icon(QFileInfo(window.path))
        if not icon.isNull():
            picture = icon.pixmap(QSize(size, size), 2.0)
    if picture is None or picture.isNull():
        picture = symbol_tile({'system': 'display', 'mic': 'mic'}.get(window.kind, 'window'),
                              {'system': '#0A84FF', 'mic': '#FF9F0A'}.get(window.kind, '#8E8E93'), size)
    _icons[key] = picture
    return picture

def symbol_tile(symbol, fill, size=32):
    """A rounded colored tile with a white glyph, like macOS Settings icons."""
    ratio = 2
    result = QPixmap(size * ratio, size * ratio)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(ratio, ratio)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    glyph = theme.pixmap(symbol, '#FFFFFF', int(size * 0.62))
    painter.drawPixmap(int(size * 0.19), int(size * 0.19), glyph)
    painter.end()
    result.setDevicePixelRatio(ratio)
    return result

class SourceDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 54 if index.data(ROLE) is not None else 34)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)
        source = index.data(ROLE)
        if source is None:
            painter.setFont(theme.font(12, QFont.Weight.DemiBold))
            painter.setPen(theme.color('secondary'))
            painter.drawText(rect.adjusted(12, 10, -12, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             index.data(Qt.ItemDataRole.DisplayRole))
            painter.restore()
            return
        selected = option.state & QStyle.StateFlag.State_Selected
        hovered = option.state & QStyle.StateFlag.State_MouseOver
        card = rect.adjusted(4, 2, -4, -2)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color('accent') if selected else theme.color('hover'))
            painter.drawRoundedRect(card, 8, 8)
        painter.drawPixmap(int(card.left() + 10), int(card.center().y() - 16), app_pixmap(source))
        text = card.adjusted(54, 7, -12, -7)
        painter.setFont(theme.font(13, QFont.Weight.Medium))
        painter.setPen(QColor('white') if selected else theme.color('text'))
        metrics = painter.fontMetrics()
        title = source.title if source.kind != 'window' else source.app
        painter.drawText(QRectF(text.left(), text.top(), text.width(), 20), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(text.width())))
        painter.setFont(theme.font(12))
        painter.setPen(QColor(255, 255, 255, 210) if selected else theme.color('secondary'))
        metrics = painter.fontMetrics()
        detail = index.data(Qt.ItemDataRole.ToolTipRole)
        painter.drawText(QRectF(text.left(), text.top() + 20, text.width(), 18), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(detail, Qt.TextElideMode.ElideRight, int(text.width())))
        painter.restore()

class SourcePicker(QDialog):
    def __init__(self, current=None, include_mic=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Choose a Source')
        self.resize(540, 640)
        self.selected = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(6)
        layout.addWidget(label('What should Whistle listen to?', size=20, weight=QFont.Weight.DemiBold, display=True))
        layout.addWidget(label('Whistle records first, then transcribes on this PC. Nothing leaves your computer.', 'secondary', wrap=True))
        layout.addSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('Search apps and windows')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(theme.icon('search', theme.tokens()['secondary'], 14), QLineEdit.ActionPosition.LeadingPosition)
        layout.addWidget(self.search)
        layout.addSpacing(4)
        self.list = QListWidget()
        self.list.setItemDelegate(SourceDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list, 1)
        self.browser_note = label('Browsers share audio across tabs and windows, so other tabs may be recorded too. '
                                  'Pause them, or use a separate browser window.', 'caption', wrap=True)
        self.browser_note.setStyleSheet(f"color: {theme.tokens()['orange']};")
        self.browser_note.hide()
        layout.addWidget(self.browser_note)
        layout.addWidget(hairline())
        mic_row = QHBoxLayout()
        mic_row.setContentsMargins(0, 8, 0, 8)
        mic_text = QVBoxLayout()
        mic_text.setSpacing(1)
        mic_text.addWidget(label('Include my microphone', size=13, weight=QFont.Weight.Medium))
        self.mic_caption = label('Mix your voice into the recording. Ideal for calls and meetings.', 'caption', wrap=True)
        mic_text.addWidget(self.mic_caption)
        mic_row.addLayout(mic_text, 1)
        self.mic = Switch(include_mic)
        mic_row.addWidget(self.mic)
        layout.addLayout(mic_row)
        buttons = QHBoxLayout()
        refresh = QPushButton('Refresh')
        refresh.setProperty('kind', 'plain')
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        buttons.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.choose = QPushButton('Choose')
        self.choose.setProperty('kind', 'primary')
        self.choose.setDefault(True)
        self.choose.clicked.connect(self.accept_selected)
        buttons.addWidget(self.choose)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.filter)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.list.itemDoubleClicked.connect(self.accept_selected)
        self.current = current
        self.refresh()
        theme.apply_chrome(self)

    def _add(self, source, detail):
        item = QListWidgetItem(source.title)
        item.setData(ROLE, source)
        item.setToolTip(detail)
        self.list.addItem(item)
        return item

    def _header(self, text):
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(HEADER, True)
        self.list.addItem(item)

    def refresh(self):
        current = self.list.currentItem().data(ROLE) if self.list.currentItem() else self.current
        self.list.clear()
        self._header('Everything')
        system = self._add(SYSTEM_AUDIO, 'Everything playing on this PC, except Whistle')
        microphone = self._add(MICROPHONE, 'In-person meetings, lectures, and dictation')
        selected = {'system': system, 'mic': microphone}.get(getattr(current, 'kind', None))
        self._header('Open Apps')
        windows = list_windows()
        for window in windows:
            item = self._add(window, window.title)
            if current and current.kind == 'window' and (window.hwnd, window.pid) == (current.hwnd, current.pid):
                selected = item
        if not windows:
            item = QListWidgetItem('No app windows are open')
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.setCurrentItem(selected or system)
        self.filter()

    def filter(self):
        query = self.search.text().casefold().strip()
        header, visible = None, False
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(HEADER):
                if header is not None:
                    header.setHidden(not visible)
                header, visible = item, False
                continue
            source = item.data(ROLE)
            match = not query or query in f'{item.text()} {item.toolTip()} {getattr(source, "app", "")}'.casefold()
            item.setHidden(not match)
            visible = visible or (match and source is not None)
        if header is not None:
            header.setHidden(not visible)

    def selection_changed(self, item, previous=None):
        source = item.data(ROLE) if item else None
        self.choose.setEnabled(source is not None)
        self.browser_note.setVisible(bool(source and source.kind == 'window' and is_browser(source)))
        microphone_only = bool(source and source.kind == 'mic')
        self.mic.setEnabled(not microphone_only)
        self.mic_caption.setText('The microphone is already the source.' if microphone_only
                                 else 'Mix your voice into the recording. Ideal for calls and meetings.')

    def accept_selected(self, *_):
        item = self.list.currentItem()
        if item and not item.isHidden() and item.data(ROLE) is not None:
            self.selected = item.data(ROLE)
            self.include_mic = self.mic.isChecked() and self.selected.kind != 'mic'
            self.accept()
