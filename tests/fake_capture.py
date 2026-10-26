"""Stands in for bin/capture.exe: real-time 44.1 kHz stereo PCM16 tone until stdin closes or sends a byte."""
import math
import sys
import threading
import time

import numpy as np

frequency, amplitude = float(sys.argv[1]), int(sys.argv[2])
stop = threading.Event()
threading.Thread(target=lambda: (sys.stdin.read(1), stop.set()), daemon=True).start()
sys.stderr.write('READY\n'); sys.stderr.flush()
rate, block, written, started = 44100, 2205, 0, time.monotonic()
while not stop.is_set():
    index = np.arange(written, written + block)
    tone = (amplitude * np.sin(2 * math.pi * frequency * index / rate)).astype('<i2')
    sys.stdout.buffer.write(np.repeat(tone, 2).tobytes())
    sys.stdout.buffer.flush()
    written += block
    time.sleep(max(0, started + written / rate - time.monotonic()))
