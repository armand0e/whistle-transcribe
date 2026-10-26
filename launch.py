"""Windows Search/desktop entry point: check updates before importing the app."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from auto_update import NO_WINDOW, ROOT, Updater

def open_app():
    if not (ROOT / 'app.py').is_file():
        raise RuntimeError('The app entry point is missing. Check the update log or restore app.py.')
    python = ROOT / '.venv' / ('Scripts/pythonw.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.Popen([str(python), str(ROOT / 'app.py')], cwd=ROOT, creationflags=NO_WINDOW)

def main():
    if '--no-gui' in sys.argv:
        outcome = Updater(progress=lambda text: print(text, flush=True)).run()
        if outcome.launch:
            open_app()
        return 0 if outcome.launch else 1
    # Tk is from Python's standard installation, so pip can replace Qt packages
    # without the launcher's own process keeping their DLLs loaded.
    try:
        import tkinter as tk
        from tkinter import ttk
        window = tk.Tk()
    except Exception:
        outcome = Updater().run()
        if outcome.launch:
            open_app()
            return 0
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, outcome.message + '\n\n' + str(ROOT / '.updates' / 'update.log'), 'Whistle update', 0x10)
        return 1
    window.title('Whistle')
    window.configure(background='#1e1e1e')
    width, height = 460, 170
    window.geometry(f'{width}x{height}+{(window.winfo_screenwidth()-width)//2}+{(window.winfo_screenheight()-height)//2}')
    window.resizable(False, False)
    try:
        window.iconbitmap(str(ROOT / 'bin' / 'whistle.ico'))
    except tk.TclError:
        pass
    text = tk.StringVar(value='Checking for Whistle updates…')
    tk.Label(window, text='Whistle', font=('Segoe UI', 17, 'bold'), fg='white', bg='#1e1e1e').pack(pady=(18, 8))
    tk.Label(window, textvariable=text, wraplength=420, font=('Segoe UI', 10), fg='#c8c8cc', bg='#1e1e1e').pack(padx=18)
    bar = ttk.Progressbar(window, mode='indeterminate', length=390)
    bar.pack(pady=14); bar.start(12)
    events = queue.Queue()
    def work():
        try:
            outcome = Updater(progress=lambda message: events.put(('message', message))).run()
            events.put(('done', outcome))
        except Exception as exc:
            events.put(('error', str(exc)))
    worker = threading.Thread(target=work, daemon=False)
    window.protocol('WM_DELETE_WINDOW', window.withdraw)  # Do not interrupt pip/build mid-write.
    failed = [False]
    def finish_error(message):
        failed[0] = True
        bar.stop(); bar.pack_forget()
        text.set(message)
        window.geometry(f'460x220')
        window.deiconify()
        buttons = tk.Frame(window, bg='#1e1e1e'); buttons.pack(pady=14)
        def log():
            path = ROOT / '.updates' / 'update.log'
            if sys.platform == 'win32' and path.exists():
                os.startfile(str(path))
        tk.Button(buttons, text='Open update log', command=log).pack(side='left', padx=6)
        tk.Button(buttons, text='Close', command=window.destroy).pack(side='left', padx=6)
        window.protocol('WM_DELETE_WINDOW', window.destroy)
    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'message':
                    text.set(value)
                elif kind == 'done':
                    if value.launch:
                        try:
                            open_app()
                            window.destroy()
                        except (OSError, RuntimeError) as exc:
                            finish_error('Whistle could not open: ' + str(exc))
                    elif value.status == 'busy':
                        text.set(value.message); window.after(1800, window.destroy)
                    else:
                        finish_error(value.message)
                    return
                else:
                    finish_error('Whistle could not start: ' + value)
                    return
        except queue.Empty:
            window.after(80, poll)
    worker.start(); window.after(80, poll); window.mainloop()
    worker.join()
    return 1 if failed[0] else 0

if __name__ == '__main__':
    sys.exit(main())
