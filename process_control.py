"""Cancel only an owned worker and its descendants (native ASR helpers included)."""
import subprocess
import sys

# Helpers run without flashing a console window on Windows.
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def terminate_tree(process):
    if process is None or process.poll() is not None:
        return
    if sys.platform != 'win32':
        process.kill()
        return
    result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                            capture_output=True, timeout=15, creationflags=NO_WINDOW)
    if result.returncode and process.poll() is None:
        process.terminate()
