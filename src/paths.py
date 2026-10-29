"""Stable locations shared by the app, workers, setup, and updater.

Source moves independently of user data. Keep existing local sessions, models,
settings, and environments at the checkout root across upgrades.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
