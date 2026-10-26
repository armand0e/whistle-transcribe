"""Render and exercise the actual Qt widgets without starting a recording."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QEventLoop, QTimer
from app import Pill, Picker

application = QApplication([])
from app import STYLE
application.setStyleSheet(STYLE)
pill = Pill()
pill.show()
application.processEvents()
assert pill.width() == 600 and pill.height() == 64
pill.grab().save(str(ROOT / 'test-output' / 'pill.png'))
picker = Picker(pill)
picker.show()
application.processEvents()
assert picker.windows.count() > 0, 'Window picker is empty'
picker.windows.setCurrentRow(0)
selected = picker.windows.currentItem().data(256)
picker.search.setText('no-window-can-match-this-test-string')
assert all(picker.windows.item(i).isHidden() for i in range(picker.windows.count()))
picker.search.clear()
picker.accept_selected()
assert picker.result() == QDialog.DialogCode.Accepted
assert picker.selected.pid > 0
picker.grab().save(str(ROOT / 'test-output' / 'picker.png'))
pill.document.update_text('WHISTLE TRANSCRIPT\n\nTest window\n\n[00:00:01] Hello from Whistle.', 'The next few words…')
pill.show_document()
application.processEvents()
assert 'Hello from Whistle.' in pill.document.text.toPlainText()
pill.document.grab().save(str(ROOT / 'test-output' / 'document.png'))
print(f'PASS: pill, picker search/selection ({picker.windows.count()} windows), live document')
from model_picker import ModelPicker
from model_catalog import MODELS
models = ModelPicker('small_en', pill)
models.show(); application.processEvents()
assert models.tree.topLevelItemCount() == len(MODELS) == 6
assert models.use.isEnabled()
models.grab().save(str(ROOT / 'test-output' / 'models.png'))
models.reject()
assert pill.device.count() == 2
print('PASS: six model choices, installed-model selection, CPU/CUDA selector')
pill.device.setCurrentIndex(1)
assert pill.device_name == 'cuda' and not pill.record.isEnabled()
loop = QEventLoop()
pill.probe_job.finished.connect(loop.quit)
QTimer.singleShot(15000, loop.quit)
loop.exec()
assert not pill.probe_job.isRunning() and pill.gpu_ready
assert pill.record.isEnabled()
pill.device.setCurrentIndex(0)
assert pill.device_name == 'cpu'
def select_whistle():
    dialog = application.activeModalWidget()
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    dialog.choose()
QTimer.singleShot(30, select_whistle)
pill.pick_model()
assert pill.model_key == 'whistle' and not pill.device.isEnabled()
def select_small():
    dialog = application.activeModalWidget()
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
    dialog.choose()
QTimer.singleShot(30, select_small)
pill.pick_model()
assert pill.model_key == 'small_en' and pill.device.isEnabled()
print('PASS: actual CUDA check, CPU/GPU selection, CPU-only model control, and preference updates')
pill.close()
