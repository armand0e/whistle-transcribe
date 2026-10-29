"""Click transcript toolbar buttons and inspect actual Qt popup menus off-screen."""
import wave
from unittest.mock import patch

from offline_helpers import fresh
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QMenu
from library import Library
from model_catalog import MODELS
from transcriber import Transcript
from windows_audio import Window

application = QApplication([])
folder = fresh('menus')
document = Transcript(Window(0, 0, 'Menu example', 'Test', kind='file'), 'en', folder, 'small_en', 'cpu')
document.finish()
with wave.open(str(document.directory / 'Audio.wav'), 'wb') as audio:
    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
    audio.writeframes(b'\0\0' * 1600)
shelf = Library(folder)
shelf.select(document.directory)
shelf.show()
application.processEvents()

def popup(click):
    opened, errors = [], []
    def inspect():
        menu = application.activePopupWidget()
        if isinstance(menu, QMenu):
            opened.append(menu)
            menu.close()
        else:
            errors.append('Button did not expose a Qt popup menu')
            for widget in application.topLevelWidgets():
                if isinstance(widget, QMenu):
                    widget.close()
    QTimer.singleShot(20, inspect)
    click()
    assert not errors and len(opened) == 1, errors or 'No popup opened'
    return opened[0]

try:
    requests = []
    shelf.retranscribe_requested.connect(lambda session, model: requests.append((session, model)))
    with patch('library.model_path', return_value=folder):
        more = popup(shelf.more_button.click)
        assert {'Show in Explorer', 'Open Transcript.txt', 'Delete…'} <= {a.text() for a in more.actions()}
        models = more.actions()[0].menu().actions()
        for action, model in zip(models, MODELS):
            action.trigger()
            assert requests[-1][0].directory == document.directory and requests[-1][1] == model.key
        # The same menu can also be opened with an explicit right-click position.
        popup(lambda: shelf._more_menu(QPoint(80, 80)))
    print('PASS: transcript three-dot click and context menu open; every model action uses its selected model', flush=True)
    exported = []
    shelf.export = exported.append
    export = popup(shelf.share_button.click)
    for action in export.actions():
        action.trigger()
    assert exported == ['txt', 'md', 'srt', 'vtt', 'json'], exported
    print('PASS: export toolbar opens and all menu actions select the correct format', flush=True)
finally:
    shelf.close()
