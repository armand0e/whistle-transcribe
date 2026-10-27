"""Repeated pill resizing must preserve its center, including between animation frames."""
from offline_helpers import fresh
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from pill import Pill
import theme

application = QApplication([])
application.setStyle('Fusion')
application.setFont(theme.font(13))
fresh('pill-position')
pill = Pill()
pill.place((500, 220))
pill.show()
application.processEvents()

def center():
    return QRectF(pill.geometry()).center()

def anchored(expected):
    actual = center()
    assert abs(actual.x() - expected.x()) <= 0.5 and abs(actual.y() - expected.y()) <= 0.5, (expected, actual)

def finish_morph(expected):
    for elapsed in (0, 35, 90, 160, 240, 330, 420):
        pill.morph.setCurrentTime(elapsed)
        application.processEvents()
        anchored(expected)

try:
    expected = center()
    pill.show_working('Transcribing', 'Starting…')
    pill.morph.setCurrentTime(120)
    elapsed = pill.morph.currentTime()
    pill.show_working('Transcribing', 'Small.en · 1%', 1)
    assert pill.morph.currentTime() == elapsed, 'Progress must not restart an unchanged resize animation'
    finish_morph(expected)
    print('PASS: progress updates let an existing resize finish instead of restarting it', flush=True)
    for location in ((320, 220), (-450, 80), (1400, 400)):
        pill.move(*location)
        application.processEvents()
        expected = center()
        pill.show_working('Transcribing', 'Whisper Small.en · Starting…')
        finish_morph(expected)
        # Same-size updates also used to creep one pixel left each time.
        for index in range(250):
            pill.show_working('Transcribing', f'Whisper Small.en · {index % 101}%', index % 101)
            finish_morph(expected)
        for action in (lambda: pill.show_result(True, 'Transcript Ready', 'Biology lecture'),
                       pill.show_idle, lambda: pill.set_model('Nemotron 3.5 · CUDA'),
                       lambda: pill.set_source('Google Chrome', 'Module 5 — Biology lecture'),
                       lambda: pill.show_recording('Google Chrome'),
                       lambda: pill.set_paused(True), lambda: pill.set_paused(False),
                       lambda: pill.set_elapsed(700),
                       lambda: pill.show_working('Preparing Audio', 'Downloading video audio…')):
            action(); finish_morph(expected)
    print('PASS: 750 progress updates and all pill states keep their center through every resize frame', flush=True)

    # Begin dragging while a morph is active, then resize before the next pointer
    # event. The grab point must remain relative to the center, not the old edge.
    saved = []
    pill.moved.connect(saved.append)
    local = QPointF(18, 18)
    pointer = QPointF(pill.pos()) + local
    grab_offset = pointer - center()
    def mouse(kind, point, button, buttons):
        event = QMouseEvent(kind, point - QPointF(pill.pos()), point, button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(pill, event)
        application.processEvents()
    mouse(QEvent.Type.MouseButtonPress, pointer, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    pill.show_idle()
    pill.morph.setCurrentTime(120)
    pointer += QPointF(130, -40)
    mouse(QEvent.Type.MouseMove, pointer, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    expected = pointer - grab_offset
    finish_morph(expected)
    mouse(QEvent.Type.MouseButtonRelease, pointer, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert len(saved) == 1
    assert abs(saved[0].x() - expected.x()) <= 0.5 and abs(saved[0].y() - expected.y()) <= 0.5
    for index in range(100):
        pill.show_working('Transcribing', f'Whisper Small.en · {index}%', index)
        finish_morph(expected)
    assert len(saved) == 1, 'Progress updates must not overwrite the saved drag position'
    print('PASS: dragging during a resize sets the new anchor; later updates keep it and do not save extra moves', flush=True)
finally:
    pill.close()
