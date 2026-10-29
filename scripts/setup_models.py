"""Download the official Whistle weights and Windows CPU runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_catalog import MODEL_REVISIONS
from paths import ROOT


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    os.environ['NEEDLE_TELEMETRY'] = '0'
    os.environ['HF_HOME'] = str(ROOT / 'models' / 'hub')
    from huggingface_hub import hf_hub_download
    from needle.agent import fetch
    dest = ROOT / 'models'
    dest.mkdir(exist_ok=True)
    model = hf_hub_download('Cactus-Compute/whistle', 'whistle.cact', revision=MODEL_REVISIONS['whistle'])
    if Path(model).resolve() != (dest / 'whistle.cact').resolve():
        shutil.copyfile(model, dest / 'whistle.cact')
    fetch.fetch_library(dest_dir=str(dest), generation=3)
    manifest = {}
    for item in (dest / 'whistle.cact', dest / 'libneedle.dll'):
        manifest[item.name] = {'bytes': item.stat().st_size, 'sha256': hashlib.sha256(item.read_bytes()).hexdigest()}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
