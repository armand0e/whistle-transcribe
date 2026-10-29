"""Small custom controls with native-feeling motion: switches, segmented controls, meters."""
from collections import deque

from PySide6.QtCore import (Property, QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

import theme

def label(text='', role=None, size=None, weight=None, wrap=False, display=False, tabular=False):
    result = QLabel(text)
    if role:
        result.setProperty('role', role)
    if size or weight or tabular:
        result.setFont(theme.font(size or 13, weight or QFont.Weight.Normal, display, tabular))
    result.setWordWrap(wrap)
    return result

def hairline(vertical=False):
    line = QFrame()
    line.setObjectName('VHairline' if vertical else 'Hairline')
    return line

class IconButton(QToolButton):
    """A flat symbol button that re-tints itself when the theme changes."""

    def __init__(self, name, tooltip='', size=18, role='secondary', parent=None):
        super().__init__(parent)
        self.icon_name, self.role, self.glyph = name, role, size
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip or name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(size, size))
        self.setFixedSize(size + 14, size + 14)
        self.retint()

    def set_icon_name(self, name):
        self.icon_name = name
        self.retint()

    def retint(self):
        colour = theme.tokens().get(self.role, self.role)
        self.setIcon(theme.icon(self.icon_name, colour, self.glyph))

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.retint()
        super().changeEvent(event)

class Switch(QAbstractButton):
    """An iOS-style toggle with a sliding knob."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 24)
        self._offset = 1.0 if checked else 0.0
        self.animation = QPropertyAnimation(self, b'offset', self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked):
        self.animation.stop()
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def sizeHint(self):
        return QSize(40, 24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = theme.color('control'), theme.color('green')
        blend = lambda a, b: int(a + (b - a) * self._offset)
        track = QColor(blend(off.red(), on.red()), blend(off.green(), on.green()), blend(off.blue(), on.blue()))
        if not self.isEnabled():
            track.setAlphaF(0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, 40, 24), 12, 12)
        x = 2 + self._offset * 16
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(x, 2.6, 20, 20))
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawEllipse(QRectF(x, 2, 20, 20))

class Segmented(QWidget):
    """A segmented control with a sliding selection, like UISegmentedControl."""
    changed = Signal(object)

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self.options = list(options)  # [(value, label)]
        self.disabled = set()
        self.index = next((i for i, (key, _) in enumerate(self.options) if key == value), 0)
        self._position = float(self.index)
        self.animation = QPropertyAnimation(self, b'position', self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        self.setFont(theme.font(12, QFont.Weight.Medium))
        metrics = QFontMetrics(self.font())
        self.setMinimumWidth(sum(metrics.horizontalAdvance(text) + 28 for _, text in self.options))

    def value(self):
        return self.options[self.index][0]

    def set_value(self, value, animate=True):
        for i, (key, _) in enumerate(self.options):
            if key == value:
                self._select(i, animate, notify=False)

    def set_disabled(self, values):
        self.disabled = set(values)
        self.update()

    def get_position(self):
        return self._position

    def set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, get_position, set_position)

    def _select(self, index, animate=True, notify=True):
        if index == self.index and notify:
            return
        self.index = index
        self.animation.stop()
        if animate and self.isVisible():
            self.animation.setEndValue(float(index))
            self.animation.start()
        else:
            self.set_position(float(index))
        if notify:
            self.changed.emit(self.value())

    def mousePressEvent(self, event):
        width = self.width() / len(self.options)
        index = min(len(self.options) - 1, int(event.position().x() // width))
        if self.options[index][0] not in self.disabled and self.isEnabled():
            self._select(index)

    def keyPressEvent(self, event):
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(event.key())
        if step:
            index = self.index + step
            while 0 <= index < len(self.options) and self.options[index][0] in self.disabled:
                index += step
            if 0 <= index < len(self.options):
                self._select(index)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color('field'))
        painter.drawRoundedRect(QRectF(self.rect()), 8, 8)
        width = self.width() / len(self.options)
        knob = QRectF(2 + self._position * width, 2, width - 4, self.height() - 4)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawRoundedRect(knob.translated(0, 0.6), 6.5, 6.5)
        painter.setBrush(theme.color('raised') if not theme.is_dark() else theme.color('#636366'))
        painter.drawRoundedRect(knob, 6.5, 6.5)
        for i, (key, text) in enumerate(self.options):
            colour = theme.color('tertiary') if key in self.disabled or not self.isEnabled() else theme.color('text')
            painter.setPen(colour)
            painter.drawText(QRectF(i * width, 0, width, self.height()), Qt.AlignmentFlag.AlignCenter, text)

class Waveform(QWidget):
    """Scrolling live level bars."""

    def __init__(self, bars=28, colour='#FFFFFF', parent=None):
        super().__init__(parent)
        self.levels = deque([0.0] * bars, maxlen=bars)
        self.colour = QColor(colour)
        self.setMinimumSize(bars * 4, 26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, level):
        self.levels.append(theme.level_height(level))
        self.update()

    def clear(self):
        self.levels.extend([0.0] * self.levels.maxlen)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        count = len(self.levels)
        step = self.width() / count
        bar = max(2.0, step * 0.5)
        middle = self.height() / 2
        for index, value in enumerate(self.levels):
            height = max(bar, value * self.height())
            colour = QColor(self.colour)
            colour.setAlphaF(0.35 + 0.65 * (index + 1) / count)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(QRectF(index * step + (step - bar) / 2, middle - height / 2, bar, height), bar / 2, bar / 2)

class ProgressRing(QWidget):
    """Determinate ring, or a spinning arc when the value is None."""

    def __init__(self, size=24, colour='#FFFFFF', track='rgba(255, 255, 255, 0.18)', parent=None):
        super().__init__(parent)
        self.value = None
        self.angle = 0
        self.colour, self.track = theme.parse(colour), theme.parse(track)
        self.setFixedSize(size, size)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._spin)

    def set_value(self, value):
        self.value = value
        self._run()
        self.update()

    def _run(self):
        # Spin only while indeterminate and on screen.
        if self.value is None and self.isVisible():
            self.timer.start(16)
        else:
            self.timer.stop()

    def showEvent(self, event):
        self._run()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _spin(self):
        self.angle = (self.angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = max(2.5, self.width() / 9)
        rect = QRectF(self.rect()).adjusted(width / 2 + 1, width / 2 + 1, -width / 2 - 1, -width / 2 - 1)
        pen = QPen(self.track, width)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        pen.setColor(self.colour)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self.value is None:
            painter.drawArc(rect, int(-self.angle * 16), int(100 * 16))
        else:
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * max(0.02, min(1, self.value / 100))))

class ElidedLabel(QLabel):
    """A label that ends with … instead of growing its window."""

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full = text
        self._elide()

    def text(self):
        return self.full

    def resizeEvent(self, event):
        self._elide()
        super().resizeEvent(event)

    def _elide(self):
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self.full, Qt.TextElideMode.ElideRight, max(10, self.width())))

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())

class GroupedCard(QFrame):
    """An inset grouped list section, as in iOS Settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Card')
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(0)

    def add_row(self, title, control=None, caption=None, stretch=True):
        if self.rows.count():
            line = hairline()
            wrapper = QHBoxLayout()
            wrapper.setContentsMargins(16, 0, 0, 0)
            wrapper.addWidget(line)
            self.rows.addLayout(wrapper)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 14, 10)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = label(title)
        text.addWidget(heading)
        detail = None
        if caption is not None:
            detail = label(caption, 'caption', wrap=True)
            text.addWidget(detail)
        layout.addLayout(text, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.rows.addWidget(row)
        row.heading, row.detail = heading, detail
        return row
