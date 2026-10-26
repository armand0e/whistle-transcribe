"""Wrapped state text remains readable at compact sizes, in both themes."""
from offline_helpers import fresh
from PySide6.QtCore import QPoint, QTimer, QEventLoop, Qt
from PySide6.QtWidgets import QApplication
import theme
from library import Placeholder
from app import palette

application = QApplication([])
application.setStyle('Fusion')
application.setFont(theme.font(13))
output = fresh('layout')
body = 'Your transcript will appear here after you stop. Recording continues if you close this window.'
for appearance in ('light', 'dark'):
    theme.set_appearance(appearance)
    application.setPalette(palette())
    application.setStyleSheet(theme.stylesheet())
    for width, height in ((471, 322), (420, 280), (320, 240), (760, 400)):
        for state in ('Recording', 'Paused'):
            widget = Placeholder()
            widget.setObjectName('Surface')
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            widget.primary.setProperty('kind', 'destructive')
            widget.resize(width, height)
            widget.show_state(theme.pixmap('waveform', theme.tokens()['red'], 56), state, body,
                              big='0:03', primary='Stop', secondary='Resume' if state == 'Paused' else 'Pause')
            widget.show()
            # Allow scrollbar visibility and height-for-width layout to settle.
            loop = QEventLoop(); QTimer.singleShot(40, loop.quit); loop.exec()
            required = widget.body.heightForWidth(widget.body.width())
            assert widget.body.height() >= required, (appearance, width, height, widget.body.height(), required)
            assert widget.body.width() <= widget.scroll.viewport().width() - 40
            body_bottom = widget.body.mapTo(widget.content, QPoint(0, widget.body.height())).y()
            buttons_top = min(button.mapTo(widget.content, QPoint(0, 0)).y() for button in (widget.primary, widget.secondary))
            assert body_bottom <= buttons_top, (body_bottom, buttons_top)
            assert widget.scroll.horizontalScrollBar().maximum() == 0
            if (width, height, state) == (471, 322, 'Paused'):
                assert widget.scroll.verticalScrollBar().maximum() == 0
                widget.grab().save(str(output / f'paused-{appearance}.png'))
            widget.close()
print('PASS: recording/paused text and controls fit compact light/dark layouts without clipping', flush=True)
