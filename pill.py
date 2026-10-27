"""The capture pill: a small dark capsule that morphs between idle, recording, and transcribing."""
import math
import time

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QGraphicsOpacityEffect, QHBoxLayout, QStackedWidget,
                               QVBoxLayout, QWidget)

import theme
from theme import PILL
from transcriber import clock
from widgets import ElidedLabel, ProgressRing, Waveform

SHADOW = 16
HEIGHT = 56

def text_width(font, text):
    return QFontMetrics(font).horizontalAdvance(text)

def pill_label(text, size, weight=QFont.Weight.Normal, colour=PILL['text'], tabular=False):
    result = ElidedLabel(text)
    result.setFont(theme.font(size, weight, tabular=tabular))
    result.setStyleSheet(f'color: {colour}; background: transparent;')
    return result

class PillButton(QAbstractButton):
    """Circular controls drawn like hardware buttons."""

    def __init__(self, kind, tooltip, size=36, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self.hover = False

    def enterEvent(self, event):
        self.hover = True; self.update()

    def leaveEvent(self, event):
        self.hover = False; self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        centre = rect.center()
        enabled = self.isEnabled()
        if self.kind in ('record', 'stop'):
            ring = QColor('#FFFFFF' if enabled else '#5A5A5E')
            painter.setPen(QPen(ring, 2.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect.adjusted(1.1, 1.1, -1.1, -1.1))
            red = QColor(PILL['red'] if enabled else '#5A5A5E')
            if self.hover and enabled:
                red = red.lighter(112)
            if self.isDown():
                red = red.darker(115)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(red)
            if self.kind == 'record':
                radius = rect.width() / 2 - 5
                painter.drawEllipse(centre, radius, radius)
            else:
                side = rect.width() * 0.36
                painter.drawRoundedRect(QRectF(centre.x() - side / 2, centre.y() - side / 2, side, side), 3.5, 3.5)
            return
        fill = QColor(PILL['button_hover'] if self.hover else PILL['button'])
        if self.kind.startswith('ghost'):
            fill.setAlpha(255 if self.hover else 0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(rect)
        glyph = self.kind.split(':')[-1]
        size = rect.width() * 0.5
        icon = theme.pixmap(glyph, '#FFFFFF' if enabled else '#5A5A5E', int(size))
        painter.drawPixmap(QPointF(centre.x() - size / 2, centre.y() - size / 2), icon)

class SourceButton(QAbstractButton):
    """The app or device being recorded: icon, name, and capture mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Choose what to record')
        self.setAccessibleName('Choose what to record')
        self.title, self.subtitle, self.picture = 'Choose a Source', 'App, system audio, or mic', None
        self.hover = False
        self.setFixedHeight(42)
        self.setMinimumWidth(150)

    def set_source(self, title, subtitle, picture):
        self.title, self.subtitle, self.picture = title, subtitle, picture
        self.setToolTip(f'{title}\n{subtitle}\nClick to choose another source')
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        title = text_width(theme.font(13, QFont.Weight.DemiBold), self.title)
        subtitle = text_width(theme.font(11), self.subtitle)
        return QSize(min(250, max(title, subtitle) + 72), 42)

    def enterEvent(self, event):
        self.hover = True; self.update()

    def leaveEvent(self, event):
        self.hover = False; self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.hover and self.isEnabled():
            painter.setBrush(QColor(255, 255, 255, 18))
            painter.drawRoundedRect(QRectF(self.rect()), 21, 21)
        painter.setBrush(QColor(PILL['button']))
        painter.drawEllipse(QRectF(4, 4, 34, 34))
        if isinstance(self.picture, QPixmap) and not self.picture.isNull():
            painter.drawPixmap(QRect(11, 11, 20, 20), self.picture)
        else:
            painter.drawPixmap(QPointF(12, 12), theme.pixmap(self.picture or 'waveform', '#FFFFFF', 18))
        width = self.width() - 70
        painter.setFont(theme.font(13, QFont.Weight.DemiBold))
        painter.setPen(QColor(PILL['text'] if self.isEnabled() else PILL['secondary']))
        metrics = painter.fontMetrics()
        painter.drawText(QRectF(46, 3, width, 20), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, width))
        painter.setFont(theme.font(11))
        painter.setPen(QColor(PILL['secondary']))
        metrics = painter.fontMetrics()
        painter.drawText(QRectF(46, 21, width, 17), Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(self.subtitle, Qt.TextElideMode.ElideRight, width))
        chevron = theme.pixmap('chevron.down', PILL['secondary'], 12)
        painter.drawPixmap(QPointF(self.width() - 20, 15), chevron)

class ChipButton(QAbstractButton):
    """A compact capsule showing the model and processor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Model, processor, and language')
        self.setAccessibleName('Model, processor, and language')
        self.setFont(theme.font(12, QFont.Weight.Medium))
        self.setFixedHeight(28)
        self.hover = False

    def sizeHint(self):
        return QSize(text_width(self.font(), self.text()) + 24, 28)

    def setText(self, text):
        super().setText(text)
        self.updateGeometry()

    def enterEvent(self, event):
        self.hover = True; self.update()

    def leaveEvent(self, event):
        self.hover = False; self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PILL['button_hover'] if self.hover else PILL['button']))
        painter.drawRoundedRect(QRectF(self.rect()), 14, 14)
        painter.setPen(QColor(PILL['text'] if self.isEnabled() else PILL['secondary']))
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.text())

class RecordingDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.paused = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(PILL['secondary'] if self.paused else PILL['red'])
        if not self.paused:
            colour.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.sin(time.monotonic() * 4)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QRectF(1, 1, 8, 8))

class Pill(QWidget):
    source_clicked = Signal()
    model_clicked = Signal(QPoint)
    record_clicked = Signal()
    stop_clicked = Signal()
    pause_clicked = Signal()
    cancel_clicked = Signal()
    library_clicked = Signal()
    menu_requested = Signal(QPoint)
    result_clicked = Signal()
    moved = Signal(QPoint)

    def __init__(self, on_top=True):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('Whistle')
        self.state = 'idle'
        self.drag = None
        self._anchor = None
        self._resizing = False
        self.capsule_width = 420
        self.level_peak = 0.0
        self.last_sound = None
        self.recording_subtitle = ''
        self.result_timer = QTimer(self)
        self.result_timer.setSingleShot(True)
        self.result_timer.timeout.connect(self.show_idle)

        self.stack = QStackedWidget(self)
        self.stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stack.setStyleSheet('background: transparent;')
        self._build_idle()
        self._build_recording()
        self._build_working()
        self._build_result()
        self.fade = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(self.fade)
        self.fade_animation = QVariantAnimation(self)
        self.fade_animation.setDuration(220)
        self.fade_animation.setStartValue(0.0)
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.valueChanged.connect(self.fade.setOpacity)
        self.fade_animation.finished.connect(lambda: self.fade.setEnabled(False))
        self.fade.setEnabled(False)
        self.morph = QVariantAnimation(self)
        self.morph.setDuration(420)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(0.9)
        self.morph.setEasingCurve(curve)
        self.morph.valueChanged.connect(self._apply_width)

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(50)
        self.stack.setCurrentWidget(self.idle)
        self._apply_width(self._target_width())

    # --- Pages -----------------------------------------------------------------------

    def _page(self):
        page = QWidget()
        page.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.stack.addWidget(page)
        return page, layout

    def _build_idle(self):
        self.idle, layout = self._page()
        self.source_button = SourceButton()
        self.source_button.clicked.connect(self.source_clicked)
        layout.addWidget(self.source_button, 1)
        self.chip = ChipButton()
        self.chip.clicked.connect(lambda: self.model_clicked.emit(self.chip.mapToGlobal(QPoint(0, self.chip.height() + 6))))
        layout.addWidget(self.chip)
        self.record_button = PillButton('record', 'Record  (Ctrl+Alt+R)', 38)
        self.record_button.clicked.connect(self.record_clicked)
        layout.addWidget(self.record_button)
        self.library_button = PillButton('ghost:library', 'Open Library', 32)
        self.library_button.clicked.connect(self.library_clicked)
        layout.addWidget(self.library_button)
        self.more_button = PillButton('ghost:more', 'More', 32)
        self.more_button.clicked.connect(lambda: self.menu_requested.emit(self.more_button.mapToGlobal(QPoint(0, self.more_button.height() + 6))))
        layout.addWidget(self.more_button)

    def _build_recording(self):
        self.recording, layout = self._page()
        layout.addSpacing(8)
        self.dot = RecordingDot()
        layout.addWidget(self.dot)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.timer_label = pill_label('0:00', 17, QFont.Weight.DemiBold, tabular=True)
        self.timer_label.setFixedWidth(72)
        text.addWidget(self.timer_label)
        self.recording_detail = pill_label('', 11, colour=PILL['secondary'])
        self.recording_detail.setFixedWidth(128)
        text.addWidget(self.recording_detail)
        layout.addLayout(text)
        self.waveform = Waveform(30, PILL['red'])
        self.waveform.setFixedWidth(118)
        layout.addWidget(self.waveform)
        layout.addSpacing(4)
        self.pause_button = PillButton('pause', 'Pause', 34)
        self.pause_button.clicked.connect(self.pause_clicked)
        layout.addWidget(self.pause_button)
        self.stop_button = PillButton('stop', 'Stop and transcribe  (Ctrl+Alt+R)', 38)
        self.stop_button.clicked.connect(self.stop_clicked)
        layout.addWidget(self.stop_button)

    def _build_working(self):
        self.working, layout = self._page()
        layout.addSpacing(10)
        self.ring = ProgressRing(26)
        layout.addWidget(self.ring)
        layout.addSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.working_title = pill_label('Transcribing', 13, QFont.Weight.DemiBold)
        self.working_detail = pill_label('', 11, colour=PILL['secondary'], tabular=True)
        for widget in (self.working_title, self.working_detail):
            widget.setFixedWidth(210)
            text.addWidget(widget)
        layout.addLayout(text)
        self.cancel_button = PillButton('xmark', 'Cancel transcription — audio is kept', 30)
        self.cancel_button.clicked.connect(self.cancel_clicked)
        layout.addWidget(self.cancel_button)

    def _build_result(self):
        self.result, layout = self._page()
        layout.addSpacing(8)
        self.result_glyph = QWidget()
        self.result_glyph.setFixedSize(30, 30)
        self.result_glyph.paintEvent = self._paint_result_glyph
        self.result_ok = True
        layout.addWidget(self.result_glyph)
        layout.addSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.result_title = pill_label('', 13, QFont.Weight.DemiBold)
        self.result_detail = pill_label('', 11, colour=PILL['secondary'])
        for widget in (self.result_title, self.result_detail):
            widget.setFixedWidth(220)
            text.addWidget(widget)
        layout.addLayout(text)
        self.open_button = PillButton('ghost:chevron.right', 'Open in Library', 30)
        self.open_button.clicked.connect(self.result_clicked)
        layout.addWidget(self.open_button)
        dismiss = PillButton('ghost:xmark', 'Dismiss', 26)
        dismiss.clicked.connect(self.show_idle)
        layout.addWidget(dismiss)

    def _paint_result_glyph(self, event):
        painter = QPainter(self.result_glyph)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PILL['green'] if self.result_ok else PILL['orange']))
        painter.drawEllipse(QRectF(1, 1, 28, 28))
        glyph = 'checkmark' if self.result_ok else 'exclamation'
        if self.result_ok:
            painter.drawPixmap(QPointF(7, 7), theme.pixmap(glyph, '#FFFFFF', 16))
        else:
            painter.drawPixmap(QPointF(3, 3), theme.pixmap(glyph, PILL['orange'], 24))

    # --- State -----------------------------------------------------------------------

    def _target_width(self):
        page = self.stack.currentWidget()
        return page.sizeHint().width() + 24

    def _switch(self, page, state):
        self.state = state
        self.result_timer.stop()
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            self.fade_animation.stop()
            self.fade.setEnabled(True)
            self.fade_animation.start()
        target = self._target_width()
        if self.morph.state() == QAbstractAnimation.State.Running and self.morph.endValue() == float(target):
            return  # Progress text changed, but the resize already has the right destination.
        if self.isVisible() and abs(target - self.capsule_width) > 1:
            self.morph.stop()
            self.morph.setStartValue(float(self.capsule_width))
            self.morph.setEndValue(float(target))
            self.morph.start()
        else:
            self.morph.stop()
            self._apply_width(target)

    def _apply_width(self, width):
        self.capsule_width = width
        total = int(round(width)) + 2 * SHADOW
        # QRect.center() uses inclusive integer coordinates. Recomputing it on
        # each frame and subtracting width // 2 loses a pixel for even widths.
        # Keep one continuous center instead; only round the final window origin.
        self._resizing = True
        try:
            self.setFixedSize(total, HEIGHT + 2 * SHADOW)
            self.stack.setGeometry(SHADOW + 12, SHADOW + 7, int(round(width)) - 24, HEIGHT - 14)
            if self._anchor is not None:
                self.move(round(self._anchor.x() - total / 2), round(self._anchor.y() - self.height() / 2))
        finally:
            self._resizing = False
        self.update()

    def set_source(self, title, subtitle, picture=None):
        self.source_button.set_source(title, subtitle, picture)
        self.recording_subtitle = title
        if self.state == 'idle':
            self._switch(self.idle, 'idle')

    def set_model(self, text):
        self.chip.setText(text)
        if self.state == 'idle':
            self._switch(self.idle, 'idle')

    def show_idle(self):
        self._switch(self.idle, 'idle')

    def show_recording(self, subtitle):
        self.recording_subtitle = subtitle
        self.recording_detail.setText(subtitle)
        self.last_sound = time.monotonic()
        self.waveform.clear()
        self.set_paused(False)
        self.set_elapsed(0)
        self.stop_button.setEnabled(True)
        self._switch(self.recording, 'recording')

    def set_paused(self, paused):
        self.dot.paused = paused
        self.pause_button.kind = 'play' if paused else 'pause'
        self.pause_button.setToolTip('Resume' if paused else 'Pause')
        self.waveform.colour = QColor(PILL['secondary'] if paused else PILL['red'])
        self.recording_detail.setText('Paused' if paused else self.recording_subtitle)
        self.pause_button.update()

    def set_finishing(self):
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.recording_detail.setText('Finishing…')

    def set_elapsed(self, seconds):
        self.timer_label.setText(clock(seconds))

    def push_level(self, level):
        self.level_peak = max(self.level_peak, level)
        if level > 0.0004:
            self.last_sound = time.monotonic()

    def show_working(self, title, detail='', percent=None):
        self.working_title.setText(title)
        self.working_detail.setText(detail)
        self.ring.set_value(percent)
        self._switch(self.working, 'working')

    def show_result(self, ok, title, detail, timeout=9000):
        self.result_ok = ok
        self.result_title.setText(title)
        self.result_detail.setText(detail)
        self.result_glyph.update()
        self._switch(self.result, 'result')
        self.result_timer.start(timeout)

    def _tick(self):
        if self.state != 'recording':
            return
        self.waveform.push(self.level_peak)
        self.level_peak = 0.0
        self.dot.update()
        if self.pause_button.isEnabled() and not self.dot.paused and self.last_sound and time.monotonic() - self.last_sound > 3:
            self.recording_detail.setText('Waiting for audio…')
        elif self.pause_button.isEnabled() and not self.dot.paused:
            self.recording_detail.setText(self.recording_subtitle)

    # --- Window ----------------------------------------------------------------------

    def place(self, position=None):
        screen = QGuiApplication.screenAt(QPoint(*position)) if position else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            position = (area.center().x(), area.bottom() - 70)
        area = screen.availableGeometry()
        x = min(max(position[0] - self.width() // 2, area.left()), area.right() - self.width())
        y = min(max(position[1] - self.height() // 2, area.top()), area.bottom() - self.height())
        self.move(x, y)
        self._anchor = QPointF(x + self.width() / 2, y + self.height() / 2)

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._resizing:
            self._anchor = QPointF(self.x() + self.width() / 2, self.y() + self.height() / 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        capsule = QRectF(SHADOW, SHADOW, self.capsule_width, HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(SHADOW, 0, -2):  # Soft ambient shadow.
            shade = QColor(0, 0, 0, int(30 * (1 - step / SHADOW) ** 2))
            painter.setBrush(shade)
            grow = step * 0.8
            painter.drawRoundedRect(capsule.adjusted(-grow, -grow + 3, grow, grow + 3), HEIGHT / 2 + grow, HEIGHT / 2 + grow)
        painter.setBrush(QColor(PILL['fill']))
        painter.setPen(QPen(theme.parse(PILL['border']), 1))
        painter.drawRoundedRect(capsule.adjusted(0.5, 0.5, -0.5, -0.5), HEIGHT / 2, HEIGHT / 2)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            center = self._anchor if self._anchor is not None else QRectF(self.geometry()).center()
            self.drag = event.globalPosition() - center
        elif event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            center = event.globalPosition() - self.drag
            self.move(round(center.x() - self.width() / 2), round(center.y() - self.height() / 2))
            self._anchor = center

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.drag = None
            self.moved.emit(self._anchor.toPoint())

    def mouseDoubleClickEvent(self, event):
        if self.state == 'result':
            self.result_clicked.emit()
