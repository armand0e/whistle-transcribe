"""Download the official model and Windows CPU runtime into this app folder."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ['NEEDLE_TELEMETRY'] = '0'
os.environ['HF_HOME'] = str(ROOT / 'models' / 'hub')
from huggingface_hub import hf_hub_download
from needle.agent import fetch
import shutil
import hashlib
import json

dest = ROOT / 'models'
dest.mkdir(exist_ok=True)
model = hf_hub_download('Cactus-Compute/whistle', 'whistle.cact')
shutil.copyfile(model, dest / 'whistle.cact')
fetch.fetch_library(dest_dir=str(dest), generation=3)
manifest = {}
for path in (dest / 'whistle.cact', dest / 'libneedle.dll'):
    manifest[path.name] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
(dest / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps(manifest, indent=2))
