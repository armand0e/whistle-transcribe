"""A separate Windows app process used by the loopback integration check."""
import os
import sys
import time
import winsound
print(os.getpid(), flush=True)
sys.stdin.readline()
winsound.PlaySound(sys.argv[1], winsound.SND_FILENAME)
time.sleep(1)
