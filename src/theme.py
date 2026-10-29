"""Whistle's visual system: color tokens, type, stylesheet, vector icons, and native window chrome."""
import math
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap)

# Apple-style semantic colors, tuned for Windows.
LIGHT = {
    'window': '#FFFFFF', 'sidebar': '#F5F5F7', 'raised': '#FFFFFF', 'grouped': '#F2F2F7', 'field': '#EBEBF0',
    'control': '#E8E8ED', 'hover': 'rgba(0, 0, 0, 0.05)', 'pressed': 'rgba(0, 0, 0, 0.09)',
    'text': '#1D1D1F', 'secondary': '#6E6E73', 'tertiary': '#AEAEB2', 'separator': '#E3E3E8',
    'selection': '#E3E3E8', 'accent': '#007AFF', 'accent_hover': '#0069D9', 'on_accent': '#FFFFFF',
    'accent_soft': 'rgba(0, 122, 255, 0.10)', 'red': '#FF3B30', 'green': '#34C759', 'orange': '#FF9500',
    'find': '#FFE45C', 'scrollbar': 'rgba(0, 0, 0, 0.22)', 'shadow': 'rgba(0, 0, 0, 0.12)',
}
DARK = {
    'window': '#1E1E1E', 'sidebar': '#262626', 'raised': '#2C2C2E', 'grouped': '#1C1C1E', 'field': '#323234',
    'control': '#3A3A3C', 'hover': 'rgba(255, 255, 255, 0.07)', 'pressed': 'rgba(255, 255, 255, 0.12)',
    'text': '#F5F5F7', 'secondary': '#A1A1A6', 'tertiary': '#636366', 'separator': '#3A3A3C',
    'selection': '#3A3A3C', 'accent': '#0A84FF', 'accent_hover': '#3395FF', 'on_accent': '#FFFFFF',
    'accent_soft': 'rgba(10, 132, 255, 0.18)', 'red': '#FF453A', 'green': '#30D158', 'orange': '#FF9F0A',
    'find': '#8A6D00', 'scrollbar': 'rgba(255, 255, 255, 0.25)', 'shadow': 'rgba(0, 0, 0, 0.45)',
}
# The capture pill is always dark, like hardware.
PILL = {'fill': '#0B0B0C', 'border': 'rgba(255, 255, 255, 0.10)', 'text': '#FFFFFF', 'secondary': '#9A9AA0',
        'button': '#262628', 'button_hover': '#343437', 'red': '#FF453A', 'green': '#30D158', 'orange': '#FF9F0A'}

_appearance = 'system'

def set_appearance(value):
    global _appearance
    _appearance = value if value in ('system', 'light', 'dark') else 'system'

def is_dark():
    if _appearance != 'system':
        return _appearance == 'dark'
    application = QGuiApplication.instance()
    if application is None:
        return False
    scheme = application.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return application.palette().color(QPalette.ColorRole.Window).lightness() < 128

def tokens():
    return DARK if is_dark() else LIGHT

def color(name, alpha=None):
    value = tokens().get(name, PILL.get(name, name))
    result = parse(value)
    if alpha is not None:
        result.setAlphaF(alpha)
    return result

def parse(value):
    if isinstance(value, QColor):
        return QColor(value)
    if value.startswith('rgba'):
        r, g, b, a = (part.strip() for part in value[5:-1].split(','))
        result = QColor(int(r), int(g), int(b))
        result.setAlphaF(float(a))
        return result
    return QColor(value)

# --- Type ---------------------------------------------------------------------------------

TEXT_FAMILIES = ['Segoe UI Variable Text', 'Segoe UI', 'SF Pro Text', 'Inter', 'Helvetica Neue', 'Arial']
DISPLAY_FAMILIES = ['Segoe UI Variable Display', 'Segoe UI', 'SF Pro Display', 'Inter Display', 'Inter', 'Helvetica Neue']

def font(size=13, weight=QFont.Weight.Normal, display=False, tabular=False):
    result = QFont()
    result.setFamilies(DISPLAY_FAMILIES if display or size >= 20 else TEXT_FAMILIES)
    result.setPixelSize(size)
    result.setWeight(weight)
    result.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if tabular:
        try:
            result.setFeature(QFont.Tag('tnum'), 1)
        except (AttributeError, TypeError):
            pass
    return result

# --- Stylesheet ---------------------------------------------------------------------------

def _assets():
    folder = Path(tempfile.gettempdir()) / 'whistle-ui'
    folder.mkdir(exist_ok=True)
    return folder

def stylesheet():
    t = tokens()
    dark = 'dark' if is_dark() else 'light'
    chevron = _assets() / f'chevron-{dark}.png'
    pixmap(icon_name='chevron.updown', color=t['secondary'], size=12, ratio=2).save(str(chevron))
    chevron_url = chevron.as_posix()
    return f'''
* {{ outline: 0; }}
QWidget {{ color: {t['text']}; }}
QMainWindow, QDialog, #Surface {{ background: {t['window']}; }}
#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['separator']}; }}
#Grouped {{ background: {t['grouped']}; }}
#Card {{ background: {t['raised']}; border-radius: 12px; }}
#Hairline {{ background: {t['separator']}; min-height: 1px; max-height: 1px; border: 0; }}
#VHairline {{ background: {t['separator']}; min-width: 1px; max-width: 1px; border: 0; }}
QLabel {{ background: transparent; }}
QLabel[role="secondary"] {{ color: {t['secondary']}; }}
QLabel[role="tertiary"] {{ color: {t['tertiary']}; }}
QLabel[role="caption"] {{ color: {t['secondary']}; font-size: 12px; }}
QLabel[role="section"] {{ color: {t['secondary']}; font-size: 11px; font-weight: 600; }}
QLabel[role="error"] {{ color: {t['red']}; font-size: 12px; }}
QToolTip {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['separator']}; border-radius: 6px; padding: 5px 8px; }}
QLineEdit, QPlainTextEdit {{ background: {t['field']}; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {t['accent']}; background: {t['raised']}; }}
QLineEdit#TitleEdit {{ background: transparent; border: 1px solid transparent; padding: 2px 4px; margin-left: -5px; }}
QLineEdit#TitleEdit:hover {{ background: {t['hover']}; }}
QLineEdit#TitleEdit:focus {{ background: {t['field']}; border: 1px solid {t['accent']}; }}
QLineEdit#Search {{ padding-left: 6px; }}
QPushButton {{ background: {t['control']}; border: 0; border-radius: 7px; padding: 6px 14px; font-weight: 500; }}
QPushButton:hover {{ background: {t['pressed']}; }}
QPushButton:disabled {{ color: {t['tertiary']}; }}
QPushButton[kind="primary"] {{ background: {t['accent']}; color: {t['on_accent']}; }}
QPushButton[kind="primary"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[kind="primary"]:disabled {{ background: {t['control']}; color: {t['tertiary']}; }}
QPushButton[kind="soft"] {{ background: {t['accent_soft']}; color: {t['accent']}; border-radius: 13px; padding: 5px 14px; font-weight: 600; }}
QPushButton[kind="soft"]:hover {{ background: {t['accent']}; color: {t['on_accent']}; }}
QPushButton[kind="destructive"] {{ background: {t['red']}; color: white; }}
QPushButton[kind="plain"] {{ background: transparent; color: {t['accent']}; padding: 6px 8px; }}
QPushButton[kind="plain"]:hover {{ background: {t['accent_soft']}; }}
QToolButton {{ background: transparent; border: 0; border-radius: 7px; padding: 5px; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {t['pressed']}; }}
QToolButton:disabled {{ background: transparent; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QComboBox {{ background: {t['control']}; border: 0; border-radius: 7px; padding: 5px 28px 5px 11px; min-height: 18px; }}
QComboBox:hover {{ background: {t['pressed']}; }}
QComboBox::drop-down {{ border: 0; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{chevron_url}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['raised']}; border: 1px solid {t['separator']}; border-radius: 8px; padding: 4px;
    selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; }}
QMenu {{ background: {t['raised']}; border: 1px solid {t['separator']}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 5px; background: transparent; }}
QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
QMenu::item:disabled {{ color: {t['tertiary']}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {t['separator']}; margin: 5px 8px; }}
QMenu::right-arrow {{ width: 8px; height: 8px; }}
QScrollArea, QTextBrowser, QTextEdit, QListWidget, QListView {{ background: transparent; border: 0; }}
QTextBrowser, QTextEdit {{ selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 3px 2px 3px 2px; }}
QScrollBar::handle:vertical {{ background: {t['scrollbar']}; border-radius: 3px; min-height: 36px; margin: 0 1px; }}
QScrollBar::handle:vertical:hover {{ background: {t['secondary']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px 3px; }}
QScrollBar::handle:horizontal {{ background: {t['scrollbar']}; border-radius: 3px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['control']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['secondary']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #FFFFFF; border: 1px solid {t['separator']}; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 7px; }}
QProgressBar {{ background: {t['control']}; border: 0; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}
'''

def polish_menu(menu):
    """Rounded, borderless menus instead of square system frames."""
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return menu

# --- Icons --------------------------------------------------------------------------------
# Drawn in a 24-unit box with rounded strokes, in the spirit of SF Symbols.

def _stroke(painter, colour, width=1.8):
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

def _fill(painter, colour):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)

def _rounded(path, x, y, w, h, r):
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path

def draw_icon(painter, name, colour):
    p = painter
    if name == 'record':
        _fill(p, colour); p.drawEllipse(QPointF(12, 12), 7, 7)
    elif name == 'stop':
        _fill(p, colour); p.drawRoundedRect(QRectF(6, 6, 12, 12), 3, 3)
    elif name == 'pause':
        _fill(p, colour); p.drawRoundedRect(QRectF(6.5, 5, 4, 14), 1.5, 1.5); p.drawRoundedRect(QRectF(13.5, 5, 4, 14), 1.5, 1.5)
    elif name == 'play':
        _fill(p, colour)
        path = QPainterPath(QPointF(8, 5.2))
        path.cubicTo(QPointF(8, 4.4), QPointF(8.9, 3.9), QPointF(9.6, 4.3))
        path.lineTo(QPointF(19.2, 11.1)); path.cubicTo(QPointF(19.9, 11.5), QPointF(19.9, 12.5), QPointF(19.2, 12.9))
        path.lineTo(QPointF(9.6, 19.7)); path.cubicTo(QPointF(8.9, 20.1), QPointF(8, 19.6), QPointF(8, 18.8))
        path.closeSubpath(); p.drawPath(path)
    elif name in ('back15', 'forward15'):
        _stroke(p, colour, 1.7)
        forward = name == 'forward15'
        rect = QRectF(3.5, 3.5, 17, 17)
        p.drawArc(rect, (60 if forward else 120) * 16, (-300 if forward else 300) * 16)
        tip = QPointF(16.5, 4.8) if forward else QPointF(7.5, 4.8)
        direction = -1 if forward else 1
        p.drawLine(tip, tip + QPointF(direction * 3.2, -2.2)); p.drawLine(tip, tip + QPointF(direction * 2.6, 2.8))
        f = font(7, QFont.Weight.Bold); f.setPixelSize(7); p.setFont(f); p.setPen(colour)
        p.drawText(QRectF(4, 7, 16, 11), Qt.AlignmentFlag.AlignCenter, '15')
    elif name == 'xmark':
        _stroke(p, colour, 2); p.drawLine(QPointF(7, 7), QPointF(17, 17)); p.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == 'checkmark':
        _stroke(p, colour, 2.2)
        path = QPainterPath(QPointF(5.5, 12.5)); path.lineTo(QPointF(10, 17)); path.lineTo(QPointF(18.5, 7)); p.drawPath(path)
    elif name == 'plus':
        _stroke(p, colour, 2); p.drawLine(QPointF(12, 5), QPointF(12, 19)); p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == 'more':
        _fill(p, colour)
        for x in (6, 12, 18):
            p.drawEllipse(QPointF(x, 12), 1.7, 1.7)
    elif name == 'chevron.down':
        _stroke(p, colour, 2); path = QPainterPath(QPointF(7, 9.5)); path.lineTo(QPointF(12, 14.5)); path.lineTo(QPointF(17, 9.5)); p.drawPath(path)
    elif name == 'chevron.up':
        _stroke(p, colour, 2); path = QPainterPath(QPointF(7, 14.5)); path.lineTo(QPointF(12, 9.5)); path.lineTo(QPointF(17, 14.5)); p.drawPath(path)
    elif name == 'chevron.right':
        _stroke(p, colour, 2); path = QPainterPath(QPointF(9.5, 6.5)); path.lineTo(QPointF(15, 12)); path.lineTo(QPointF(9.5, 17.5)); p.drawPath(path)
    elif name == 'chevron.updown':
        _stroke(p, colour, 2.2)
        path = QPainterPath(QPointF(7.5, 9.5)); path.lineTo(QPointF(12, 5)); path.lineTo(QPointF(16.5, 9.5))
        path.moveTo(QPointF(7.5, 14.5)); path.lineTo(QPointF(12, 19)); path.lineTo(QPointF(16.5, 14.5)); p.drawPath(path)
    elif name == 'search':
        _stroke(p, colour, 2); p.drawEllipse(QPointF(10.5, 10.5), 5.5, 5.5); p.drawLine(QPointF(14.6, 14.6), QPointF(19, 19))
    elif name == 'doc':
        _stroke(p, colour, 1.7)
        path = QPainterPath(QPointF(14, 3.5)); path.lineTo(QPointF(8, 3.5)); path.quadTo(QPointF(5.5, 3.5), QPointF(5.5, 6))
        path.lineTo(QPointF(5.5, 18)); path.quadTo(QPointF(5.5, 20.5), QPointF(8, 20.5)); path.lineTo(QPointF(16, 20.5))
        path.quadTo(QPointF(18.5, 20.5), QPointF(18.5, 18)); path.lineTo(QPointF(18.5, 8)); path.closeSubpath()
        p.drawPath(path)
        for y in (11.5, 14.5, 17.5):
            p.drawLine(QPointF(9, y), QPointF(15, y))
    elif name == 'library':
        _stroke(p, colour, 1.7)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3.5, 3.5); p.drawLine(QPointF(9.5, 4.5), QPointF(9.5, 19.5))
        for y in (8.5, 11.5):
            p.drawLine(QPointF(5.8, y), QPointF(7.4, y))
    elif name == 'sliders':
        _stroke(p, colour, 1.8)
        for y, x in ((7, 15), (12, 9), (17, 13)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            _fill(p, colour); p.drawEllipse(QPointF(x, y), 2.6, 2.6); _stroke(p, colour, 1.8)
    elif name == 'mic':
        _stroke(p, colour, 1.8)
        p.drawRoundedRect(QRectF(9, 3.5, 6, 11), 3, 3)
        p.drawArc(QRectF(5.5, 6.5, 13, 12), 180 * 16, 180 * 16)
        p.drawLine(QPointF(12, 18.5), QPointF(12, 21)); p.drawLine(QPointF(9, 21), QPointF(15, 21))
    elif name == 'display':
        _stroke(p, colour, 1.8)
        p.drawRoundedRect(QRectF(3.5, 4.5, 17, 11.5), 2.5, 2.5)
        p.drawLine(QPointF(12, 16), QPointF(12, 19.5)); p.drawLine(QPointF(8, 19.5), QPointF(16, 19.5))
    elif name == 'window':
        _stroke(p, colour, 1.8)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 3, 3); p.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
    elif name == 'waveform':
        _stroke(p, colour, 2.2)
        for x, h in ((4, 3), (8, 8), (12, 14), (16, 9), (20, 4)):
            p.drawLine(QPointF(x, 12 - h / 2), QPointF(x, 12 + h / 2))
    elif name == 'trash':
        _stroke(p, colour, 1.7)
        p.drawLine(QPointF(4.5, 6.5), QPointF(19.5, 6.5))
        path = QPainterPath(QPointF(9.5, 6.5)); path.lineTo(QPointF(9.5, 4.5)); path.lineTo(QPointF(14.5, 4.5)); path.lineTo(QPointF(14.5, 6.5)); p.drawPath(path)
        path = QPainterPath(QPointF(6.5, 6.5)); path.lineTo(QPointF(7.4, 18.6)); path.quadTo(QPointF(7.6, 20.5), QPointF(9.5, 20.5))
        path.lineTo(QPointF(14.5, 20.5)); path.quadTo(QPointF(16.4, 20.5), QPointF(16.6, 18.6)); path.lineTo(QPointF(17.5, 6.5)); p.drawPath(path)
    elif name == 'share':
        _stroke(p, colour, 1.8)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14)); p.drawLine(QPointF(12, 3.5), QPointF(8.5, 7)); p.drawLine(QPointF(12, 3.5), QPointF(15.5, 7))
        path = QPainterPath(QPointF(9, 10)); path.lineTo(QPointF(7, 10)); path.quadTo(QPointF(5, 10), QPointF(5, 12))
        path.lineTo(QPointF(5, 18.5)); path.quadTo(QPointF(5, 20.5), QPointF(7, 20.5)); path.lineTo(QPointF(17, 20.5))
        path.quadTo(QPointF(19, 20.5), QPointF(19, 18.5)); path.lineTo(QPointF(19, 12)); path.quadTo(QPointF(19, 10), QPointF(17, 10))
        path.lineTo(QPointF(15, 10)); p.drawPath(path)
    elif name == 'copy':
        _stroke(p, colour, 1.7)
        p.drawRoundedRect(QRectF(8.5, 8.5, 11.5, 12), 2.5, 2.5)
        path = QPainterPath(QPointF(15.5, 8.5)); path.lineTo(QPointF(15.5, 6)); path.quadTo(QPointF(15.5, 3.5), QPointF(13, 3.5))
        path.lineTo(QPointF(6.5, 3.5)); path.quadTo(QPointF(4, 3.5), QPointF(4, 6)); path.lineTo(QPointF(4, 13))
        path.quadTo(QPointF(4, 15.5), QPointF(6.5, 15.5)); path.lineTo(QPointF(8.5, 15.5)); p.drawPath(path)
    elif name == 'folder':
        _stroke(p, colour, 1.7)
        path = QPainterPath(QPointF(3.5, 17.5)); path.lineTo(QPointF(3.5, 6.5)); path.quadTo(QPointF(3.5, 5), QPointF(5, 5))
        path.lineTo(QPointF(9.5, 5)); path.lineTo(QPointF(11.5, 7.5)); path.lineTo(QPointF(19, 7.5)); path.quadTo(QPointF(20.5, 7.5), QPointF(20.5, 9))
        path.lineTo(QPointF(20.5, 17.5)); path.quadTo(QPointF(20.5, 19), QPointF(19, 19)); path.lineTo(QPointF(5, 19))
        path.quadTo(QPointF(3.5, 19), QPointF(3.5, 17.5)); p.drawPath(path)
    elif name == 'pencil':
        _stroke(p, colour, 1.7)
        path = QPainterPath(QPointF(15.5, 4.8)); path.lineTo(QPointF(19.2, 8.5)); path.lineTo(QPointF(9, 18.7))
        path.lineTo(QPointF(4.5, 19.5)); path.lineTo(QPointF(5.3, 15)); path.closeSubpath(); p.drawPath(path)
        p.drawLine(QPointF(13.3, 7), QPointF(17, 10.7))
    elif name == 'arrow.clockwise':
        _stroke(p, colour, 1.8)
        p.drawArc(QRectF(4.5, 4.5, 15, 15), 75 * 16, -300 * 16)
        p.drawLine(QPointF(14.6, 3.8), QPointF(15.7, 7.6)); p.drawLine(QPointF(15.7, 7.6), QPointF(11.9, 8.4))
    elif name == 'download':
        _stroke(p, colour, 1.8)
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawLine(QPointF(12, 7.5), QPointF(12, 16)); p.drawLine(QPointF(8.5, 12.5), QPointF(12, 16)); p.drawLine(QPointF(15.5, 12.5), QPointF(12, 16))
    elif name == 'import':
        _stroke(p, colour, 1.8)
        p.drawLine(QPointF(12, 4), QPointF(12, 14.5)); p.drawLine(QPointF(8.5, 11), QPointF(12, 14.5)); p.drawLine(QPointF(15.5, 11), QPointF(12, 14.5))
        path = QPainterPath(QPointF(4.5, 14)); path.lineTo(QPointF(4.5, 17.5)); path.quadTo(QPointF(4.5, 20), QPointF(7, 20))
        path.lineTo(QPointF(17, 20)); path.quadTo(QPointF(19.5, 20), QPointF(19.5, 17.5)); path.lineTo(QPointF(19.5, 14)); p.drawPath(path)
    elif name == 'lock':
        _stroke(p, colour, 1.8)
        p.drawRoundedRect(QRectF(5.5, 10.5, 13, 10), 2.5, 2.5)
        p.drawArc(QRectF(8, 4, 8, 10), 0, 180 * 16); p.drawLine(QPointF(8, 9), QPointF(8, 10.5)); p.drawLine(QPointF(16, 9), QPointF(16, 10.5))
    elif name == 'bolt':
        _fill(p, colour)
        path = QPainterPath(QPointF(13.5, 3)); path.lineTo(QPointF(5.5, 13.5)); path.lineTo(QPointF(11.5, 13.5)); path.lineTo(QPointF(10.5, 21))
        path.lineTo(QPointF(18.5, 10.5)); path.lineTo(QPointF(12.5, 10.5)); path.closeSubpath(); p.drawPath(path)
    elif name == 'cpu':
        _stroke(p, colour, 1.7)
        p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2.5, 2.5); p.drawRoundedRect(QRectF(9.5, 9.5, 5, 5), 1, 1)
        for v in (9.5, 12, 14.5):
            p.drawLine(QPointF(v, 3.5), QPointF(v, 6.5)); p.drawLine(QPointF(v, 17.5), QPointF(v, 20.5))
            p.drawLine(QPointF(3.5, v), QPointF(6.5, v)); p.drawLine(QPointF(17.5, v), QPointF(20.5, v))
    elif name == 'exclamation':
        _fill(p, colour); p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
        _stroke(p, QColor('white'), 2.2); p.drawLine(QPointF(12, 7), QPointF(12, 13))
        _fill(p, QColor('white')); p.drawEllipse(QPointF(12, 16.6), 1.3, 1.3)
    elif name == 'sparkles':
        _fill(p, colour)
        def star(cx, cy, r):
            path = QPainterPath(QPointF(cx, cy - r))
            path.quadTo(QPointF(cx, cy), QPointF(cx + r, cy)); path.quadTo(QPointF(cx, cy), QPointF(cx, cy + r))
            path.quadTo(QPointF(cx, cy), QPointF(cx - r, cy)); path.quadTo(QPointF(cx, cy), QPointF(cx, cy - r))
            p.drawPath(path)
        star(10, 13, 7); star(18, 6, 3.5)
    elif name == 'globe':
        _stroke(p, colour, 1.6)
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5); p.drawEllipse(QRectF(8, 3.5, 8, 17))
        p.drawLine(QPointF(3.5, 12), QPointF(20.5, 12))
    elif name == 'textformat':
        _stroke(p, colour, 1.7)
        for y, x in ((6.5, 20), (10.5, 16), (14.5, 20), (18.5, 13)):
            p.drawLine(QPointF(4, y), QPointF(x, y))

def pixmap(icon_name, color='#000000', size=16, ratio=None):
    ratio = ratio or (QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 2)
    ratio = max(2.0, ratio)
    result = QPixmap(int(size * ratio), int(size * ratio))
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(size * ratio / 24, size * ratio / 24)
    draw_icon(painter, icon_name, parse(color) if isinstance(color, str) else color)
    painter.end()
    result.setDevicePixelRatio(ratio)
    return result

def icon(name, color=None, size=16, disabled=None):
    result = QIcon()
    result.addPixmap(pixmap(name, color or tokens()['text'], size), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, disabled or tokens()['tertiary'], size), QIcon.Mode.Disabled)
    return result

def app_icon(size=256):
    """A squircle with a white waveform on an indigo-to-blue gradient."""
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = size * 0.06
    box = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    gradient = QLinearGradient(box.topLeft(), box.bottomRight())
    gradient.setColorAt(0, QColor('#7B61FF'))
    gradient.setColorAt(1, QColor('#0A84FF'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(box, box.width() * 0.2237, box.width() * 0.2237)
    pen = QPen(QColor('white'), box.width() * 0.075)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    heights = (0.18, 0.40, 0.62, 0.42, 0.24)
    for index, height in enumerate(heights):
        x = box.left() + box.width() * (0.26 + index * 0.12)
        painter.drawLine(QPointF(x, box.center().y() - box.height() * height / 2),
                         QPointF(x, box.center().y() + box.height() * height / 2))
    painter.end()
    return result

def level_height(level):
    """Map RMS to a perceptual 0..1 bar height."""
    if level <= 0:
        return 0.0
    return max(0.0, min(1.0, (20 * math.log10(max(level, 1e-6)) + 52) / 46))

# --- Native window chrome -------------------------------------------------------------------

def apply_chrome(widget):
    """Windows 11: match the title bar to the window color and use rounded corners."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dark = ctypes.c_int(1 if is_dark() else 0)
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))  # immersive dark mode
        corner = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))  # round corners
        background = parse(tokens()['sidebar' if widget.property('chromeSidebar') else 'window'])
        caption = ctypes.c_uint(background.red() | background.green() << 8 | background.blue() << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))  # caption color
        border = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), ctypes.sizeof(border))
    except (AttributeError, OSError):
        pass
