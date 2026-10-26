"""Cancel only an owned worker and its descendants (native ASR helpers included)."""
import subprocess

def terminate_tree(process):
    if process is None or process.poll() is not None:
        return
    result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode and process.poll() is None:
        process.terminate()
