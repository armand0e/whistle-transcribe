"""Windows: drive the real app with live windows and the actual CUDA check, without recording."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

application = QApplication([])
application.setStyle('Fusion')
import app as whistle
import preferences
import theme
from source_picker import ROLE, SourcePicker

output = ROOT / 'test-output'
output.mkdir(exist_ok=True)
preferences.PATH = output / 'ui-smoke-settings.json'
preferences.PATH.write_text(json.dumps({'welcomed': True}), encoding='utf-8')
application.setFont(theme.font(13))
controller = whistle.Whistle(application)

def wait(condition, timeout=20):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    assert condition(), 'Timed out'

picker = SourcePicker()
picker.show(); application.processEvents()
windows = [picker.list.item(i) for i in range(picker.list.count())
           if picker.list.item(i).data(ROLE) is not None and picker.list.item(i).data(ROLE).kind == 'window']
assert windows, 'Source picker lists no app windows'
picker.list.setCurrentItem(windows[0])
picker.search.setText('no-window-can-match-this-test-string')
assert all(item.isHidden() for item in windows)
picker.search.clear()
picker.accept_selected()
assert picker.selected.pid > 0 and picker.selected.path, picker.selected
picker.grab().save(str(output / 'picker.png'))
controller.source = picker.selected
controller.refresh_pill()
assert controller.pill.source_button.title == picker.selected.app
controller.pill.grab().save(str(output / 'pill.png'))
print(f'PASS: source picker shows {len(windows)} app windows with names and icons; pill shows the choice')

controller.open_library()
application.processEvents()
controller.library.grab().save(str(output / 'library.png'))
controller.open_settings('models')
assert len(controller.settings.models.rows) == 6
controller.settings.grab().save(str(output / 'models.png'))
print('PASS: library and model settings render')

controller.set_preferences(model='small_en', device='cuda')
wait(lambda: controller.gpu_state in ('ready', 'error'), 30)
assert controller.gpu_state == 'ready', controller.gpu_detail
print(f'PASS: CUDA check — {controller.gpu_detail}')
controller.set_preferences(model='whistle')
assert controller.preferences['device'] == 'cpu' and 'cuda' in controller.settings.device.disabled
controller.set_preferences(model='small_en', device='cpu')
assert not controller.settings.device.disabled
print('PASS: CPU-only models force CPU; preferences update the pill and settings')
controller.quit()
