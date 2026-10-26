"""The library: every transcript, searchable, playable, editable, and exportable."""
import html
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QEvent, QFile, QPropertyAnimation, QRectF, QSize, QStandardPaths, Qt, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPen, QShortcut, QTextBlockFormat,
                           QTextCharFormat, QTextCursor)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

import theme
from model_catalog import BY_KEY, LANGUAGE_NAMES, MODELS, model_path
from sessions import (AUDIO_TYPES, EXPORTS, TRANSCRIPTS, date_group, describe, export_filename, export_text,
                      list_sessions)
from transcriber import clock
from widgets import IconButton, ProgressRing, hairline, label

ROLE = Qt.ItemDataRole.UserRole
HEADER = Qt.ItemDataRole.UserRole + 1
STATUS_TEXT = {'recording': 'Recording', 'preparing': 'Preparing', 'transcribing': 'Transcribing',
               'interrupted': 'Interrupted', 'error': 'Failed', 'cancelled': 'Cancelled'}

def human_duration(seconds):
    seconds = int(round(seconds or 0))
    if seconds < 60:
        return f'{seconds} sec'
    minutes = round(seconds / 60)
    return f'{minutes} min' if minutes < 60 else f'{minutes // 60} hr {minutes % 60} min'.replace(' 0 min', '')

class SessionDelegate(QStyledItemDelegate):
    def __init__(self, library):
        super().__init__(library.list)
        self.library = library

    def sizeHint(self, option, index):
        return QSize(0, 34 if index.data(HEADER) else 60)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect)
        if index.data(HEADER):
            painter.setFont(theme.font(12, QFont.Weight.DemiBold))
            painter.setPen(theme.color('secondary'))
            painter.drawText(rect.adjusted(18, 12, -12, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             index.data(Qt.ItemDataRole.DisplayRole))
            painter.restore()
            return
        session = index.data(ROLE)
        card = rect.adjusted(8, 1, -8, -1)
        selected = option.state & QStyle.StateFlag.State_Selected
        if selected:
            focused = self.library.list.hasFocus()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color('accent') if focused else theme.color('selection'))
            painter.drawRoundedRect(card, 8, 8)
        on_accent = selected and self.library.list.hasFocus()
        live = self.library._is_live(session)
        status = self.library.live_phase if live else session.display_status(self.library.live_directory)
        badge = STATUS_TEXT.get(status, '')
        if status in ('preparing', 'transcribing') and self.library.live_percent is not None:
            badge = f'{badge} {self.library.live_percent}%'
        text = card.adjusted(12, 9, -12, -9)
        painter.setFont(theme.font(13, QFont.Weight.DemiBold))
        painter.setPen(QColor('white') if on_accent else theme.color('text'))
        metrics = painter.fontMetrics()
        painter.drawText(QRectF(text.left(), text.top(), text.width(), 20), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(session.title, Qt.TextElideMode.ElideRight, int(text.width())))
        painter.setFont(theme.font(12))
        detail = describe(session)
        if session.metadata.get('model'):
            detail += f" · {BY_KEY.get(session.metadata['model']).short if session.metadata['model'] in BY_KEY else ''}"
        metrics = painter.fontMetrics()
        badge_width = 0
        if badge:
            colour = {'recording': 'red', 'interrupted': 'orange', 'error': 'red'}.get(status, 'secondary')
            painter.setFont(theme.font(11, QFont.Weight.DemiBold))
            badge_metrics = painter.fontMetrics()
            badge_width = badge_metrics.horizontalAdvance(badge) + (14 if status == 'recording' else 0)
            painter.setPen(QColor('white') if on_accent else theme.color(colour))
            badge_rect = QRectF(text.right() - badge_width, text.top() + 21, badge_width, 18)
            if status == 'recording':
                painter.setBrush(QColor('white') if on_accent else theme.color('red'))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(badge_rect.left(), badge_rect.center().y() - 3.5, 7, 7))
                painter.setPen(QColor('white') if on_accent else theme.color(colour))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, badge)
            painter.setFont(theme.font(12))
        painter.setPen(QColor(255, 255, 255, 215) if on_accent else theme.color('secondary'))
        painter.drawText(QRectF(text.left(), text.top() + 21, text.width() - badge_width - 8, 18), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(detail, Qt.TextElideMode.ElideRight, int(text.width() - badge_width - 8)))
        painter.restore()

def column_margin(width):
    """Side margin that keeps text in a comfortable reading column."""
    return max(40, (width - 720) // 2)

class TranscriptView(QTextBrowser):
    """Readable transcript with clickable timestamps, playback highlight, and find highlights."""
    seek = Signal(float)
    margin_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._clicked)
        self.paragraphs = []
        self.current = -1
        self.matches = []
        self.match_index = -1
        self.document().setDefaultFont(theme.font(15))
        self.document().setDocumentMargin(0)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    def _clicked(self, url):
        if url.scheme() == 't':
            self.seek.emit(float(url.path()))

    def set_paragraphs(self, paragraphs, follow=False):
        scroll = self.verticalScrollBar()
        at_end = scroll.value() >= scroll.maximum() - 40
        position = scroll.value()
        self.paragraphs = [list(paragraph) for paragraph in paragraphs]
        t = theme.tokens()
        blocks = []
        for start, text, _ in self.paragraphs:
            blocks.append(f'<p style="margin: 0 0 22px 0; line-height: 150%;">'
                          f'<a href="t:{start:.3f}" style="color: {t["secondary"]}; text-decoration: none; '
                          f'font-size: 12px; font-weight: 600;">{clock(start)}</a><br/>'
                          f'<span style="color: {t["text"]};">{html.escape(text)}</span></p>')
        self.setHtml(''.join(blocks))
        self._margins()
        self.current = -1
        self.matches = []
        if follow and at_end:
            scroll.setValue(scroll.maximum())
        else:
            scroll.setValue(position)
        self._decorate()

    def _margins(self):
        side = column_margin(self.viewport().width())
        frame = self.document().rootFrame()
        fmt = frame.frameFormat()
        fmt.setLeftMargin(side)
        fmt.setRightMargin(side)
        fmt.setTopMargin(8)
        fmt.setBottomMargin(48)
        frame.setFrameFormat(fmt)
        self.margin_changed.emit(side)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._margins()

    def highlight_time(self, seconds):
        index = -1
        for i, (start, _, _) in enumerate(self.paragraphs):
            if start <= seconds + 0.05:
                index = i
            else:
                break
        if index != self.current:
            self.current = index
            self._decorate()
            if index >= 0:
                block = self.document().findBlockByNumber(index)
                rect = self.document().documentLayout().blockBoundingRect(block)
                scroll = self.verticalScrollBar()
                if rect.top() < scroll.value() or rect.bottom() > scroll.value() + self.viewport().height():
                    animation = QPropertyAnimation(scroll, b'value', self)
                    animation.setDuration(300)
                    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                    animation.setEndValue(int(max(0, rect.top() - self.viewport().height() / 3)))
                    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def clear_highlight(self):
        self.current = -1
        self._decorate()

    def find(self, query):
        self.matches, self.match_index = [], -1
        if query:
            cursor = QTextCursor(self.document())
            while True:
                cursor = self.document().find(query, cursor)
                if cursor.isNull():
                    break
                self.matches.append(QTextCursor(cursor))
            if self.matches:
                self.match_index = 0
        self._decorate(scroll_to_match=True)
        return len(self.matches)

    def step_match(self, step):
        if self.matches:
            self.match_index = (self.match_index + step) % len(self.matches)
            self._decorate(scroll_to_match=True)

    def _decorate(self, scroll_to_match=False):
        selections = []
        if self.current >= 0:
            block = self.document().findBlockByNumber(self.current)
            if block.isValid():
                selection = QTextEdit.ExtraSelection()
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setBackground(theme.color('accent_soft'))
                selection.format = fmt
                selections.append(selection)
        for index, match in enumerate(self.matches):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = match
            fmt = QTextCharFormat()
            fmt.setBackground(theme.color('orange') if index == self.match_index else theme.color('find'))
            if index == self.match_index:
                fmt.setForeground(QColor('#000000'))
            selection.format = fmt
            selections.append(selection)
        self.setExtraSelections(selections)
        if scroll_to_match and 0 <= self.match_index < len(self.matches):
            cursor = QTextCursor(self.matches[self.match_index])
            cursor.clearSelection()
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

class TranscriptEditor(QTextEdit):
    """Plain paragraph editing; each block remembers which timed paragraph it came from."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDefaultFont(theme.font(15))
        self.original = []

    def load(self, paragraphs):
        self.original = [list(paragraph) for paragraph in paragraphs]
        self.clear()
        cursor = QTextCursor(self.document())
        spacing = QTextBlockFormat()
        spacing.setBottomMargin(16)
        spacing.setLineHeight(150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        for index, (_, text, _) in enumerate(self.original):
            if index:
                cursor.insertBlock(spacing)
            else:
                cursor.setBlockFormat(spacing)
            cursor.insertText(text)
            cursor.block().setUserState(index)
        self._margins()
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.document().setModified(False)

    def _margins(self):
        side = column_margin(self.viewport().width())
        frame = self.document().rootFrame()
        fmt = frame.frameFormat()
        fmt.setLeftMargin(side); fmt.setRightMargin(side); fmt.setTopMargin(30); fmt.setBottomMargin(48)
        frame.setFrameFormat(fmt)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._margins()

    def paragraphs(self):
        result, used = [], set()
        block = self.document().firstBlock()
        while block.isValid():
            text = ' '.join(block.text().split())
            state = block.userState()
            if text:
                if 0 <= state < len(self.original) and state not in used:
                    used.add(state)
                    start, end = self.original[state][0], self.original[state][2]
                elif result:
                    start, end = result[-1][0], result[-1][2]
                else:
                    start, end = (self.original[0][0], self.original[0][2]) if self.original else (0.0, 0.0)
                result.append([start, text, end])
            block = block.next()
        return result

class PlayerBar(QWidget):
    position_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.speeds = [1.0, 1.25, 1.5, 2.0, 0.75]
        self.seeking = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 24, 12)
        layout.setSpacing(6)
        self.back = IconButton('back15', 'Back 15 seconds', 20, 'text')
        self.play = IconButton('play', 'Play  (Space)', 22, 'text')
        self.forward = IconButton('forward15', 'Forward 15 seconds', 20, 'text')
        for button in (self.back, self.play, self.forward):
            layout.addWidget(button)
        layout.addSpacing(8)
        self.elapsed = label('0:00', 'secondary', 12, tabular=True)
        self.elapsed.setMinimumWidth(44)
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.elapsed)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.slider, 1)
        self.remaining = label('-0:00', 'secondary', 12, tabular=True)
        self.remaining.setMinimumWidth(48)
        layout.addWidget(self.remaining)
        self.speed = QPushButton('1×')
        self.speed.setProperty('kind', 'plain')
        self.speed.setToolTip('Playback speed')
        self.speed.setFixedWidth(52)
        layout.addWidget(self.speed)
        self.back.clicked.connect(lambda: self.skip(-15))
        self.forward.clicked.connect(lambda: self.skip(15))
        self.play.clicked.connect(self.toggle)
        self.speed.clicked.connect(self.next_speed)
        self.slider.sliderPressed.connect(lambda: setattr(self, 'seeking', True))
        self.slider.sliderReleased.connect(self._released)
        self.slider.sliderMoved.connect(lambda value: self.elapsed.setText(clock(value / 1000)))
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self._duration)
        self.player.playbackStateChanged.connect(self._state)

    def load(self, path):
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)) if path else QUrl())
        self.slider.setValue(0)
        self.elapsed.setText('0:00')

    def unload(self):
        self.player.stop()
        self.player.setSource(QUrl())

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, seconds, play=True):
        self.player.setPosition(int(max(0, seconds) * 1000))
        if play:
            self.player.play()

    def skip(self, seconds):
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + int(seconds * 1000))))

    def next_speed(self):
        current = self.player.playbackRate()
        index = (self.speeds.index(current) + 1) % len(self.speeds) if current in self.speeds else 0
        self.player.setPlaybackRate(self.speeds[index])
        self.speed.setText(f'{self.speeds[index]:g}×')

    def _released(self):
        self.seeking = False
        self.player.setPosition(self.slider.value())

    def _position(self, position):
        if not self.seeking:
            self.slider.setValue(position)
            self.elapsed.setText(clock(position / 1000))
        self.remaining.setText('-' + clock(max(0, self.player.duration() - position) / 1000))
        self.position_changed.emit(position / 1000)

    def _duration(self, duration):
        self.slider.setRange(0, duration)
        self.remaining.setText('-' + clock(duration / 1000))

    def _state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.set_icon_name('pause' if playing else 'play')
        self.play.setToolTip('Pause  (Space)' if playing else 'Play  (Space)')

class Banner(QFrame):
    """An inline status message with an optional action, instead of a modal alert."""
    action = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)
        self.ring = ProgressRing(18, theme.tokens()['accent'], theme.tokens()['control'])
        layout.addWidget(self.ring)
        self.glyph = QLabel()
        layout.addWidget(self.glyph)
        self.text = label('', wrap=True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text, 1)
        self.button = QPushButton()
        self.button.clicked.connect(self.action)
        layout.addWidget(self.button)
        self.hide()

    def show_message(self, text, tone='info', button=None, busy=False, percent=None):
        t = theme.tokens()
        tint = {'info': t['accent_soft'], 'warning': 'rgba(255, 149, 0, 0.14)', 'error': 'rgba(255, 59, 48, 0.12)',
                'neutral': t['field']}[tone]
        self.setStyleSheet(f'Banner {{ background: {tint}; border-radius: 10px; }}')
        self.text.setText(text)
        self.ring.colour = theme.color('accent')
        self.ring.track = theme.color('control')
        self.ring.setVisible(busy)
        if busy:
            self.ring.set_value(percent)
        symbol = {'warning': ('exclamation', t['orange']), 'error': ('exclamation', t['red'])}.get(tone)
        self.glyph.setVisible(bool(symbol) and not busy)
        if symbol:
            self.glyph.setPixmap(theme.pixmap(symbol[0], symbol[1], 18))
        self.button.setVisible(bool(button))
        self.button.setText(button or '')
        self.show()

class Placeholder(QWidget):
    """Centered empty and in-progress states."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.content = QWidget()
        self.scroll.setWidget(self.content)
        self.content.setAutoFillBackground(False)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(0)
        layout.addStretch(3)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.picture)
        layout.addSpacing(14)
        self.title = label('', size=22, weight=QFont.Weight.DemiBold, display=True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addSpacing(6)
        self.big = label('', size=40, weight=QFont.Weight.Light, display=True, tabular=True)
        self.big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.big)
        layout.addSpacing(6)
        self.body = label('', 'secondary', wrap=True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(18)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)  # Nested layouts inherit the parent's zero spacing.
        self.buttons.addStretch()
        self.primary = QPushButton()
        self.primary.setProperty('kind', 'primary')
        self.secondary = QPushButton()
        self.buttons.addWidget(self.secondary)
        self.buttons.addWidget(self.primary)
        self.buttons.addStretch()
        layout.addLayout(self.buttons)
        layout.addStretch(4)
        self.scroll.viewport().installEventFilter(self)

    def fit_body(self):
        # Word-wrapped QLabel's default minimum is only one line. Reserve the
        # actual wrapped height so the layout cannot crop its last line.
        width = min(420, max(1, self.scroll.viewport().width() - 40))
        self.body.setFixedWidth(width)
        self.body.ensurePolished()
        self.body.setMinimumHeight(max(0, self.body.heightForWidth(width)))
        self.content.updateGeometry()

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self.fit_body()
        return super().eventFilter(watched, event)

    def show_state(self, picture, title, body, big='', primary=None, secondary=None):
        self.picture.setPixmap(picture)
        self.title.setText(title)
        self.big.setText(big)
        self.big.setVisible(bool(big))
        self.body.setText(body)
        self.fit_body()
        for button, text in ((self.primary, primary), (self.secondary, secondary)):
            button.setVisible(bool(text))
            button.setText(text or '')

class Toast(QLabel):
    """A brief confirmation that fades away."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFont(theme.font(13, QFont.Weight.Medium))
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b'opacity', self)
        self.fade.setDuration(260)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.fade.finished.connect(lambda: self.hide() if self.effect.opacity() < 0.05 else None)
        self.hide()

    def show_text(self, text, area=None):
        fill = '#48484A' if theme.is_dark() else 'rgba(28, 28, 30, 0.92)'
        self.setStyleSheet(f'background: {fill}; color: white; border-radius: 15px; padding: 7px 16px;')
        self.setText(text)
        self.adjustSize()
        area = area or self.parentWidget().rect()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 84)
        self.raise_()
        self.show()
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity() if self.isVisible() else 0.0)
        self.fade.setEndValue(1.0)
        self.fade.start()
        self.timer.start(1600)

    def _fade_out(self):
        self.fade.stop()
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.start()

class DropOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = theme.color('window')
        fill.setAlphaF(0.88)
        painter.fillRect(self.rect(), fill)
        pen = QPen(theme.color('accent'), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(theme.color('accent_soft'))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(18, 18, -18, -18), 18, 18)
        painter.drawPixmap(self.width() // 2 - 24, self.height() // 2 - 60, theme.pixmap('import', theme.tokens()['accent'], 48))
        painter.setPen(theme.color('text'))
        painter.setFont(theme.font(18, QFont.Weight.DemiBold, display=True))
        painter.drawText(QRectF(0, self.height() / 2, self.width(), 30), Qt.AlignmentFlag.AlignCenter, 'Drop to Transcribe')
        painter.setPen(theme.color('secondary'))
        painter.setFont(theme.font(13))
        painter.drawText(QRectF(0, self.height() / 2 + 30, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                         'Audio and video files are transcribed with your current model.')

class Library(QMainWindow):
    record_requested = Signal()
    stop_requested = Signal()
    pause_requested = Signal()
    cancel_requested = Signal()
    import_requested = Signal(list)
    retranscribe_requested = Signal(object, object)
    settings_requested = Signal()

    def __init__(self, root=None):
        super().__init__()
        self.root = Path(root) if root else TRANSCRIPTS
        self.setWindowTitle('Whistle')
        self.resize(1080, 720)
        self.setMinimumSize(760, 480)
        self.setAcceptDrops(True)
        self.sessions = []
        self.session = None
        self.live_directory = None
        self.live_phase = 'idle'
        self.live_percent = None
        self.live_status = ''
        self.live_paragraphs = []
        self.editing = False

        container = QWidget()
        self.setCentralWidget(container)
        splitter = QSplitter()
        splitter.setHandleWidth(0)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_detail())
        splitter.setSizes([290, 790])
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        # Floating layers live on the container: a splitter would turn them into panes.
        self.overlay = DropOverlay(container)
        self.toast = Toast(container)
        self._shortcuts()
        self.refresh()
        theme.apply_chrome(self)

    # --- Construction ----------------------------------------------------------------

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sidebar.setMinimumWidth(240)
        sidebar.setMaximumWidth(380)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(18, 0, 10, 0)
        top.addWidget(label('Transcripts', size=17, weight=QFont.Weight.Bold, display=True))
        top.addStretch()
        importer = IconButton('import', 'Import Audio or Video…  (Ctrl+O)', 17)
        importer.clicked.connect(self.choose_import)
        top.addWidget(importer)
        layout.addLayout(top)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(12, 0, 12, 4)
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('Search')
        self.search.setClearButtonEnabled(True)
        self.search_icon = self.search.addAction(theme.icon('search', theme.tokens()['secondary'], 14),
                                                 QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda: self.filter_timer.start(150))
        search_row.addWidget(self.search)
        layout.addLayout(search_row)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.filter)
        self.list = QListWidget()
        self.list.setItemDelegate(SessionDelegate(self))
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.list.currentItemChanged.connect(self._selected)
        layout.addWidget(self.list, 1)
        layout.addWidget(hairline())
        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 6, 10, 8)
        self.new_button = QPushButton('  New Recording')
        self.new_button.setProperty('kind', 'plain')
        self.new_button.setIcon(theme.icon('record', theme.tokens()['red'], 14))
        self.new_button.setToolTip('Record with your current source  (Ctrl+N)')
        self.new_button.clicked.connect(self.record_requested)
        bottom.addWidget(self.new_button)
        bottom.addStretch()
        settings = IconButton('sliders', 'Settings  (Ctrl+,)', 17)
        settings.clicked.connect(self.settings_requested)
        bottom.addWidget(settings)
        layout.addLayout(bottom)
        return sidebar

    def notify(self, text):
        self.toast.show_text(text, self.detail.geometry())

    def _build_detail(self):
        self.detail = detail = QWidget()
        detail.setObjectName('Surface')
        detail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        self.placeholder = Placeholder()
        self.placeholder.primary.clicked.connect(self._placeholder_primary)
        self.placeholder.secondary.clicked.connect(self._placeholder_secondary)
        self.pages.addWidget(self.placeholder)

        page = QWidget()
        self.pages.addWidget(page)
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        header = QWidget()
        self.header_layout = header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 22, 28, 10)
        header_layout.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.title = QLineEdit()
        self.title.setObjectName('TitleEdit')
        self.title.setFont(theme.font(26, QFont.Weight.Bold, display=True))
        self.title.setToolTip('Rename')
        self.title.editingFinished.connect(self._rename)
        row.addWidget(self.title, 1)
        row.addSpacing(12)
        self.find_button = IconButton('search', 'Find in Transcript  (Ctrl+F)', 17)
        self.find_button.clicked.connect(self.show_find)
        self.edit_button = IconButton('pencil', 'Edit Transcript  (Ctrl+E)', 17)
        self.edit_button.clicked.connect(self.toggle_edit)
        self.copy_button = IconButton('copy', 'Copy Transcript', 17)
        self.copy_button.clicked.connect(self.copy_text)
        self.share_button = IconButton('share', 'Export', 17)
        self.share_button.clicked.connect(self._export_menu)
        self.more_button = IconButton('more', 'More', 17)
        self.more_button.clicked.connect(self._more_menu)
        for button in (self.find_button, self.edit_button, self.copy_button, self.share_button, self.more_button):
            row.addWidget(button)
        self.done_button = QPushButton('Done')
        self.done_button.setProperty('kind', 'primary')
        self.done_button.clicked.connect(self.toggle_edit)
        self.done_button.hide()
        row.addWidget(self.done_button)
        header_layout.addLayout(row)
        self.meta = label('', 'secondary', wrap=True)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(self.meta)
        column.addWidget(header)
        self.banner_row = banner_row = QHBoxLayout()
        banner_row.setContentsMargins(36, 6, 28, 6)
        self.banner = Banner()
        self.banner.action.connect(self._banner_action)
        banner_row.addWidget(self.banner)
        column.addLayout(banner_row)
        self.find_bar = QWidget()
        self.find_layout = find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(36, 4, 28, 8)
        self.find_field = QLineEdit()
        self.find_field.setObjectName('Search')
        self.find_field.setPlaceholderText('Find in transcript')
        self.find_field.addAction(theme.icon('search', theme.tokens()['secondary'], 14), QLineEdit.ActionPosition.LeadingPosition)
        self.find_field.textChanged.connect(self._find)
        self.find_field.returnPressed.connect(lambda: self.view.step_match(1))
        find_layout.addWidget(self.find_field, 1)
        self.find_count = label('', 'secondary', 12, tabular=True)
        self.find_count.setMinimumWidth(70)
        find_layout.addWidget(self.find_count)
        previous = IconButton('chevron.up', 'Previous Match', 14)
        previous.clicked.connect(lambda: self.view.step_match(-1))
        following = IconButton('chevron.down', 'Next Match', 14)
        following.clicked.connect(lambda: self.view.step_match(1))
        find_layout.addWidget(previous)
        find_layout.addWidget(following)
        close = QPushButton('Done')
        close.setProperty('kind', 'plain')
        close.clicked.connect(self.hide_find)
        find_layout.addWidget(close)
        self.find_bar.hide()
        column.addWidget(self.find_bar)
        self.body = QStackedWidget()
        self.view = TranscriptView()
        self.view.seek.connect(self._seek)
        self.view.margin_changed.connect(self._align)
        self.editor = TranscriptEditor()
        self.live = Placeholder()
        self.live.primary.setProperty('kind', 'destructive')
        self.live.primary.clicked.connect(self.stop_requested)
        self.live.secondary.clicked.connect(self.pause_requested)
        for widget in (self.view, self.editor, self.live):
            self.body.addWidget(widget)
        column.addWidget(self.body, 1)
        self.player_line = hairline()
        column.addWidget(self.player_line)
        self.player = PlayerBar()
        self.player.position_changed.connect(self._playing)
        column.addWidget(self.player)
        return detail

    def _align(self, side):
        """Line the title, banners, and find bar up with the reading column."""
        right = max(28, side - 40)
        self.header_layout.setContentsMargins(side - 4, 22, right, 10)
        self.banner_row.setContentsMargins(side - 8, 6, right, 6)
        self.find_layout.setContentsMargins(side - 8, 4, right, 8)

    def _shortcuts(self):
        for keys, callback in ((QKeySequence.StandardKey.Find, self.show_find), ('Ctrl+E', self.toggle_edit),
                               ('Ctrl+O', self.choose_import), ('Ctrl+N', self.record_requested.emit),
                               ('Ctrl+,', self.settings_requested.emit), ('Escape', self._escape),
                               (QKeySequence.StandardKey.Save, self._save_shortcut), ('Delete', self._delete_shortcut)):
            QShortcut(QKeySequence(keys), self, callback)
        space = QShortcut(QKeySequence('Space'), self, self._space)
        space.setContext(Qt.ShortcutContext.WindowShortcut)

    # --- Sidebar ---------------------------------------------------------------------

    def refresh(self, select=None):
        current = select or (self.session.directory if self.session else None)
        self.sessions = list_sessions(self.root)
        self.filter(select=current)

    def filter(self, select=None):
        # Filtering may remove every row without a selection-change signal.
        # Save against the current session before replacing that selection.
        if self.editing:
            self._finish_edit(save=True)
        select = select or (self.session.directory if self.session else None)
        query = self.search.text()
        self.list.blockSignals(True)
        self.list.clear()
        group = None
        chosen = None
        for session in self.sessions:
            if not session.matches(query):
                continue
            heading = date_group(session.started)
            if heading != group:
                header = QListWidgetItem(heading)
                header.setData(HEADER, True)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
                group = heading
            item = QListWidgetItem(session.title)
            item.setData(ROLE, session)
            self.list.addItem(item)
            if select and Path(session.directory) == Path(select):
                chosen = item
        self.list.blockSignals(False)
        if chosen is None:
            chosen = next((self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(ROLE)), None)
        if chosen:
            self.list.setCurrentItem(chosen)
            self._selected(chosen)
        else:
            self._show_session(None)

    def select(self, directory):
        for index in range(self.list.count()):
            session = self.list.item(index).data(ROLE)
            if session and Path(session.directory) == Path(directory):
                self.list.setCurrentRow(index)
                return
        self.search.clear()
        self.refresh(select=directory)

    def _selected(self, item, previous=None):
        session = item.data(ROLE) if item else None
        if self.editing and self.session is not session:
            self._finish_edit(save=True)
        self._show_session(session)

    def _list_menu(self, position):
        item = self.list.itemAt(position)
        if item and item.data(ROLE):
            self.list.setCurrentItem(item)
            self._more_menu(self.list.viewport().mapToGlobal(position))

    # --- Detail ----------------------------------------------------------------------

    def _show_session(self, session):
        self.session = session
        self.hide_find()
        if session is None:
            self.player.unload()
            self.pages.setCurrentWidget(self.placeholder)
            if self.search.text().strip():
                self.placeholder.show_state(theme.pixmap('search', theme.tokens()['tertiary'], 56), 'No Results',
                                            f'Nothing matches “{self.search.text().strip()}”.')
            else:
                self.placeholder.show_state(theme.app_icon(96).scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                                      Qt.TransformationMode.SmoothTransformation),
                                            'No Transcripts Yet',
                                            'Record an app, your whole PC, or your microphone, or drop an audio or video file here. '
                                            'Everything stays on this computer.', primary='New Recording',
                                            secondary='Import File…')
            return
        self.pages.setCurrentWidget(self.pages.widget(1))
        if not self.title.hasFocus():
            self.title.setText(session.title)
        self.title.setCursorPosition(0)
        self._update_meta()
        live = self._is_live(session)
        audio = session.audio_path
        if live or not audio:
            self.player.unload()
        elif self.player.player.source() != QUrl.fromLocalFile(str(audio)):
            self.player.load(audio)
        self.player.setVisible(bool(audio) and not live)
        self.player_line.setVisible(self.player.isVisible())
        for button in (self.edit_button, self.copy_button, self.share_button):
            button.setEnabled(not live)
        self._update_body()

    def _is_live(self, session):
        return bool(session and self.live_directory and Path(session.directory) == Path(self.live_directory)
                    and self.live_phase != 'idle')

    def _update_meta(self):
        session = self.session
        meta = session.metadata
        parts = [session.started.strftime('%A, %B %d, %Y at %I:%M %p').replace(' 0', ' ')]
        if session.duration:
            parts.append(human_duration(session.duration))
        if meta.get('model_name'):
            parts.append(f"{meta['model_name']} on {'GPU' if meta.get('device') == 'cuda' else 'CPU'}")
        language = meta.get('detected_language') or meta.get('language')
        if language and language != 'auto':
            parts.append(LANGUAGE_NAMES.get(language, language))
        if meta.get('source_kind') in ('system', 'mic') and meta.get('capture_scope') != 'saved audio':
            parts.append(meta.get('source', ''))
        elif meta.get('app') and meta.get('capture_scope') != 'saved audio':
            parts.append(meta['app'])
        elif meta.get('source_audio'):
            parts.append(Path(meta['source_audio']).name)
        if session.edited:
            parts.append('Edited')
        self.meta.setText('  ·  '.join(parts))

    def _update_body(self):
        session = self.session
        if session is None:
            return
        live = self._is_live(session)
        status = session.display_status(self.live_directory)
        if live and self.live_phase == 'recording':
            self.banner.hide()
            self.body.setCurrentWidget(self.live)
            self.live.show_state(theme.pixmap('waveform', theme.tokens()['red'], 56), 'Recording', 
                                 'Your transcript will appear here after you stop. Recording continues if you close this window.',
                                 big=clock(0), primary='Stop', secondary='Pause')
            return
        if self.editing:
            return
        paragraphs = self.live_paragraphs if live else session.paragraphs(reload=True)
        self.body.setCurrentWidget(self.view)
        self.view.set_paragraphs(paragraphs, follow=live)
        if live:
            model = BY_KEY.get(session.metadata.get('model'))
            what = 'Preparing audio' if self.live_phase == 'preparing' else f'Transcribing with {model.name if model else "your model"}'
            detail = f' · {self.live_percent}%' if self.live_percent is not None else (f' · {self.live_status}' if self.live_status else '')
            self.banner.show_message(what + detail, 'info', 'Cancel', busy=True, percent=self.live_percent)
        elif status == 'interrupted':
            self.banner.show_message('Whistle closed before this finished. The audio is saved.', 'warning',
                                     'Transcribe Again' if session.audio_path else None)
        elif status == 'error':
            self.banner.show_message(session.metadata.get('error') or 'Transcription failed. The audio is saved.', 'error',
                                     'Transcribe Again' if session.audio_path else None)
        elif status == 'cancelled':
            self.banner.show_message('Transcription was cancelled. The audio is saved.', 'neutral',
                                     'Transcribe Again' if session.audio_path else None)
        elif not paragraphs:
            self.banner.show_message('No speech was detected. Try another model, or check that the source was playing audio.',
                                     'neutral', 'Transcribe Again' if session.audio_path else None)
        elif session.metadata.get('warnings'):
            self.banner.show_message(' '.join(session.metadata['warnings']), 'warning')
        else:
            self.banner.hide()

    def _banner_action(self):
        if self._is_live(self.session):
            self.cancel_requested.emit()
        elif self.session:
            self.retranscribe_requested.emit(self.session, None)

    def _placeholder_primary(self):
        self.record_requested.emit()

    def _placeholder_secondary(self):
        self.choose_import()

    def _rename(self):
        if self.session and self.title.text().strip():
            self.session.rename(self.title.text())
            self.title.setText(self.session.title)
            self.list.viewport().update()
            self._update_meta()
        elif self.session:
            self.title.setText(self.session.title)

    # --- Live job --------------------------------------------------------------------

    def set_live(self, directory, phase, percent=None, status=''):
        changed = directory != self.live_directory or phase != self.live_phase
        self.live_directory, self.live_phase = directory, phase
        self.live_percent, self.live_status = percent, status
        if phase == 'idle':
            self.live_paragraphs = []
        if changed:
            known = {str(session.directory) for session in self.sessions}
            if directory and str(Path(directory)) not in known:
                self.refresh(select=directory if self.isVisible() else None)
            else:
                self.list.viewport().update()
                if self.session:
                    self._show_session(self.session)
        else:
            self.list.viewport().update()
            if self._is_live(self.session):
                self._update_body()

    def set_live_paragraphs(self, paragraphs):
        self.live_paragraphs = paragraphs
        if self._is_live(self.session) and self.body.currentWidget() is self.view:
            self.view.set_paragraphs(paragraphs, follow=True)

    def set_live_elapsed(self, seconds, paused=False):
        if self._is_live(self.session) and self.body.currentWidget() is self.live:
            self.live.big.setText(clock(seconds))
            self.live.title.setText('Paused' if paused else 'Recording')
            self.live.secondary.setText('Resume' if paused else 'Pause')

    # --- Actions ---------------------------------------------------------------------

    def toggle_edit(self):
        if not self.session or self._is_live(self.session):
            return
        if self.editing:
            self._finish_edit(save=True)
        else:
            self.editing = True
            self.editor.load(self.session.paragraphs())
            self.body.setCurrentWidget(self.editor)
            self.editor.setFocus()
            self.done_button.show()
            for button in (self.find_button, self.edit_button, self.copy_button, self.share_button, self.more_button):
                button.hide()

    def _finish_edit(self, save=True):
        if not self.editing:
            return
        session = self.session
        self.editing = False
        if save and session and self.editor.document().isModified():
            session.save_paragraphs(self.editor.paragraphs())
            self.notify('Changes Saved')
        self.done_button.hide()
        for button in (self.find_button, self.edit_button, self.copy_button, self.share_button, self.more_button):
            button.show()
        if session is self.session:
            self._update_meta()
            self._update_body()

    def show_find(self):
        if not self.session or self.editing or self.body.currentWidget() is not self.view:
            return
        self.find_bar.show()
        self.find_field.setFocus()
        self.find_field.selectAll()
        self._find()

    def hide_find(self):
        if self.find_bar.isVisible():
            self.find_bar.hide()
            self.view.find('')

    def _find(self):
        query = self.find_field.text()
        count = self.view.find(query)
        self.find_count.setText('' if not query else ('Not found' if not count else f'{count} match{"es" if count != 1 else ""}'))

    def _escape(self):
        if self.find_bar.isVisible():
            self.hide_find()
        elif self.editing:
            self._finish_edit(save=True)

    def _save_shortcut(self):
        if self.editing:
            self._finish_edit(save=True)

    def _delete_shortcut(self):
        if self.list.hasFocus() and self.session:
            self.delete_session()

    def _space(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not isinstance(focus, QTextBrowser):
            return
        if self.player.isVisible():
            self.player.toggle()

    def _seek(self, seconds):
        if self.player.isVisible():
            self.player.seek(seconds)

    def _playing(self, seconds):
        if self.body.currentWidget() is self.view and self.player.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.view.highlight_time(seconds)

    def copy_text(self):
        if self.session:
            QApplication.clipboard().setText(self.session.text())
            self.notify('Copied to Clipboard')

    def _export_menu(self):
        menu = theme.polish_menu(QMenu(self))
        for kind, name in EXPORTS.items():
            menu.addAction(f'{name} (.{kind})', lambda kind=kind: self.export(kind))
        menu.exec(self.share_button.mapToGlobal(self.share_button.rect().bottomLeft()))

    def export(self, kind):
        if not self.session:
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        suggested = str(Path(folder) / export_filename(self.session, kind))
        path, _ = QFileDialog.getSaveFileName(self, 'Export Transcript', suggested, f'{EXPORTS[kind]} (*.{kind})')
        if path:
            try:
                Path(path).write_text(export_text(self.session, kind), encoding='utf-8')
            except OSError as exc:
                QMessageBox.warning(self, 'Whistle', f'Could not export: {exc}')
                return
            self.notify(f'Exported {Path(path).name}')

    def _more_menu(self, position=None):
        if not self.session:
            return
        session = self.session
        live = self._is_live(session)
        menu = theme.polish_menu(QMenu(self))
        again = theme.polish_menu(menu.addMenu(theme.icon('arrow.clockwise', theme.tokens()['text'], 16), 'Transcribe Again With'))
        for model in MODELS:
            installed = model_path(model.key) is not None
            action = again.addAction(model.name + ('' if installed else '  —  not downloaded'),
                                     lambda key=model.key: self.retranscribe_requested.emit(session, key))
            action.setEnabled(installed and session.audio_path is not None and not live)
            action.setCheckable(True)
            action.setChecked(session.metadata.get('model') == model.key)
        again.setEnabled(session.audio_path is not None and not live)
        menu.addSeparator()
        menu.addAction(theme.icon('folder', theme.tokens()['text'], 16), 'Show in Explorer',
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(session.directory))))
        menu.addAction(theme.icon('doc', theme.tokens()['text'], 16), 'Open Transcript.txt',
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(session.directory / 'Transcript.txt'))))
        menu.addSeparator()
        delete = menu.addAction(theme.icon('trash', theme.tokens()['red'], 16), 'Delete…', self.delete_session)
        delete.setEnabled(not live)
        if position is None:
            position = self.more_button.mapToGlobal(self.more_button.rect().bottomLeft())
        menu.exec(position)

    def delete_session(self):
        session = self.session
        if not session or self._is_live(session):
            return
        related = session.related(self.sessions)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setIconPixmap(theme.app_icon(128).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        box.setWindowTitle('Delete Transcript')
        box.setText(f'Delete “{session.title}”?')
        detail = 'The recording and transcript will be moved to the Recycle Bin.'
        if related:
            detail += f' {len(related)} other transcript{"s" if len(related) != 1 else ""} made from this recording will no longer be able to play it.'
        box.setInformativeText(detail)
        delete = box.addButton('Delete', QMessageBox.ButtonRole.DestructiveRole)
        delete.setProperty('kind', 'destructive')
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not delete:
            return
        self.player.unload()
        QFile.moveToTrash(str(session.directory))
        if session.directory.exists():
            QMessageBox.warning(self, 'Whistle', 'Whistle could not move this transcript to the Recycle Bin. '
                                                 'Close any program using its files and try again.')
            return
        index = self.list.currentRow()
        self.session = None
        self.sessions = [other for other in self.sessions if other.directory != session.directory]
        self.filter()
        rows = [i for i in range(self.list.count()) if self.list.item(i).data(ROLE)]
        if rows:
            self.list.setCurrentRow(min(rows, key=lambda row: abs(row - index)))
        self.notify('Moved to Recycle Bin')

    def choose_import(self):
        patterns = ' '.join(f'*{suffix}' for suffix in AUDIO_TYPES)
        files, _ = QFileDialog.getOpenFileNames(self, 'Import Audio or Video', str(self.root),
                                                f'Audio and video ({patterns});;All files (*)')
        if files:
            self.import_requested.emit(files)

    # --- Window ----------------------------------------------------------------------

    def _audio_files(self, event):
        return [url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in AUDIO_TYPES]

    def dragEnterEvent(self, event):
        if self._audio_files(event):
            event.acceptProposedAction()
            self.overlay.setGeometry(self.centralWidget().rect())
            self.overlay.raise_()
            self.overlay.show()

    def dragLeaveEvent(self, event):
        self.overlay.hide()

    def dropEvent(self, event):
        self.overlay.hide()
        files = self._audio_files(event)
        if files:
            event.acceptProposedAction()
            self.import_requested.emit(files)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.StyleChange:
            for field in (self.search, self.find_field):
                for action in field.actions():
                    action.setIcon(theme.icon('search', theme.tokens()['secondary'], 14))
            self.new_button.setIcon(theme.icon('record', theme.tokens()['red'], 14))
            if self.session and self.body.currentWidget() is self.view:
                self.view.set_paragraphs(self.view.paragraphs)
            elif self.session is None:
                self._show_session(None)
            theme.apply_chrome(self)
        elif event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.list.viewport().update()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.editing:
            self._finish_edit(save=True)
        self.player.player.pause()
        super().closeEvent(event)
