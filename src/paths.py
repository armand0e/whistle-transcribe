"""Stable locations shared by the app, workers, setup, and updater.

Source moves independently of user data. Keep existing local sessions, models,
settings, and environments at the checkout root across upgrades.
"""
from pathlib import Path
import json
import os
import sys

SRC = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, 'frozen', False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else SRC.parent
CONFIG_DIR = Path(os.environ.get('WHISTLE_CONFIG_DIR') or
                  (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'Whistle'))

def installed_directory():
    return Path(os.environ.get('WHISTLE_INSTALL_DIR') or
                (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'Programs' / 'Whistle'))

def installed_executable():
    path = (APP_DIR if FROZEN else installed_directory()) / 'Whistle.exe'
    return path if path.is_file() else None

def data_directory():
    override = os.environ.get('WHISTLE_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if not FROZEN:
        return SRC.parent
    try:
        settings = json.loads((CONFIG_DIR / 'bootstrap.json').read_text(encoding='utf-8-sig'))
        value = settings.get('data_dir') if isinstance(settings, dict) else None
        if isinstance(value, str) and Path(value).is_absolute():
            return Path(value).resolve()
    except (OSError, ValueError):
        pass
    return CONFIG_DIR

ROOT = data_directory()
BIN = SRC / 'bin' if FROZEN else APP_DIR / 'bin'
if FROZEN or os.environ.get('WHISTLE_DATA_DIR'):
    ROOT.mkdir(parents=True, exist_ok=True)
