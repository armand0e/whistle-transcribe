"""On-demand Whistle model/runtime provisioning for source and installed builds."""
import os
from pathlib import Path
import shutil
from model_catalog import MODEL_REVISIONS, ROOT

def install():
    os.environ['NEEDLE_TELEMETRY'] = '0'
    from huggingface_hub import hf_hub_download
    from needle.agent import fetch
    dest = ROOT / 'models'
    dest.mkdir(parents=True, exist_ok=True)
    model = hf_hub_download('Cactus-Compute/whistle', 'whistle.cact',
                            revision=MODEL_REVISIONS['whistle'], cache_dir=str(dest / 'hub'))
    if Path(model).resolve() != (dest / 'whistle.cact').resolve():
        shutil.copyfile(model, dest / 'whistle.cact')
    fetch.fetch_library(dest_dir=str(dest), generation=3)
