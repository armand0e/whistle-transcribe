"""Check that unrelated app playback is excluded and idle capture stops cleanly."""
from pathlib import Path
import subprocess
import sys
import argparse
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audio', type=Path, required=True, help='Speech WAV to play for the capture test')
args = parser.parse_args()
# Target stays silent. The separate player is deliberately outside its tree.
target = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
capture = subprocess.Popen([str(ROOT / 'bin' / 'capture.exe'), str(target.pid)],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    assert capture.stderr.readline().strip() == b'READY'
    player = subprocess.Popen([sys.executable, str(ROOT / 'tests' / 'play_audio.py'),
                               str(args.audio.resolve())],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    player.stdout.readline()
    player.stdin.write('go\n'); player.stdin.flush()
    time.sleep(4)
    raw, errors = capture.communicate(b'q\n', timeout=5)
    assert capture.returncode == 0, errors
    samples = np.frombuffer(raw, dtype='<i2')
    peak = int(np.max(np.abs(samples.astype(np.int32)))) if len(samples) else 0
    # Windows' PCM16 mixer can dither digital silence to +/-1 least-significant bit.
    assert peak <= 1, f'Unrelated audio leaked into target: peak {peak}'
    print(f'PASS: unrelated speech excluded; {len(raw)} bytes, peak {peak}/32768; idle capture stopped cleanly')
    player.terminate(); player.wait()
finally:
    if capture.poll() is None:
        capture.kill(); capture.wait()
    target.terminate(); target.wait()
    if 'player' in globals() and player.poll() is None:
        player.terminate(); player.wait()
