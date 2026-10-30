"""Shared frozen entry point: windowed launcher/app and console model worker."""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import traceback
import subprocess

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def smoke(report):
    from paths import ROOT, BIN, APP_DIR
    from version import VERSION
    import wave
    from PySide6.QtWidgets import QApplication
    from library import Library
    from pill import Pill
    from preferences import Preferences
    from settings_dialog import SettingsWindow
    import tkinter as tk
    startup = tk.Tk()
    startup.withdraw()
    startup.update_idletasks()
    startup.destroy()
    app = QApplication([])
    library = Library(ROOT / 'transcripts')
    pill = Pill()
    pill.place((500, 220)); pill.show_working('Transcribing', 'Small.en · 10%', 10)
    settings = SettingsWindow(Preferences())
    assert (BIN / 'capture.exe').is_file() and (BIN / 'node.exe').is_file()
    result = subprocess.run([str(BIN / 'capture.exe')], capture_output=True, timeout=15, creationflags=NO_WINDOW)
    assert result.returncode == 1 and b'Usage' in result.stderr
    worker = APP_DIR / 'WhistleWorker.exe'
    result = subprocess.run([str(worker), 'self-test'], capture_output=True, timeout=60, creationflags=NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    source = ROOT / 'smoke-source.wav'
    with wave.open(str(source), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x00\x00' * 1600)
    result = subprocess.run([str(worker), 'convert', '--audio', str(source), '--output', str(ROOT / 'smoke-converted.wav')],
                            capture_output=True, timeout=60, creationflags=NO_WINDOW)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    settings.close(); pill.close(); library.close()
    Path(report).write_text(json.dumps({'ok': True, 'version': VERSION, 'data_dir': str(ROOT),
                                       'worker': result.stdout.decode('utf-8', 'replace')}), encoding='utf-8')
    return 0

def main():
    multiprocessing.freeze_support()
    if '--smoke-test' in sys.argv:
        report = sys.argv[sys.argv.index('--smoke-test') + 1]
        try:
            return smoke(report)
        except Exception:
            Path(report).write_text(json.dumps({'ok': False, 'error': traceback.format_exc()}), encoding='utf-8')
            return 1
    if Path(sys.executable).stem.casefold() == 'whistleworker':
        from asr_worker import main as worker_main
        return worker_main()
    if '--app' in sys.argv:
        sys.argv.remove('--app')
        from app import main as app_main
        return app_main()
    from launch import main as launch_main
    return launch_main()

if __name__ == '__main__':
    raise SystemExit(main())
