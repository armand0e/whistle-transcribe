"""Remembered choices, stored beside the app in settings.json."""
import json
import os
import math
from pathlib import Path

from model_catalog import BY_KEY, LANGUAGES, ROOT, validate_choice

PATH = ROOT / 'settings.json'
DEFAULTS = {
    'model': 'small_en', 'device': 'cpu', 'language': 'en', 'appearance': 'system',
    'source_kind': 'window', 'source_path': '', 'include_mic': False, 'vocabulary': '',
    'open_when_done': True, 'notify_when_done': True, 'hotkey': True, 'pill_on_top': True,
    'pill_position': None, 'welcomed': False,
}

class Preferences(dict):
    def __init__(self, path=None):
        super().__init__(DEFAULTS)
        self.path = Path(path) if path else PATH
        try:
            stored = json.loads(self.path.read_text(encoding='utf-8'))
            for key, value in stored.items():
                if key not in DEFAULTS:
                    continue
                default = DEFAULTS[key]
                if isinstance(default, bool) and type(value) is not bool:
                    continue
                if isinstance(default, str) and not isinstance(value, str):
                    continue
                if key == 'language' and value is not None and not isinstance(value, str):
                    continue
                if key == 'pill_position' and value is not None:
                    if (not isinstance(value, (list, tuple)) or len(value) != 2
                            or any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 1_000_000 for n in value)):
                        continue
                    value = [round(n) for n in value]
                self[key] = value
        except (OSError, ValueError, AttributeError):
            pass
        for key, choices in (('appearance', ('system', 'light', 'dark')),
                             ('source_kind', ('window', 'system', 'mic')),
                             ('language', tuple(code for code, _ in LANGUAGES))):
            if self[key] not in choices:
                self[key] = DEFAULTS[key]
        try:
            validate_choice(self['model'], self['device'], self['language'])
        except (ValueError, KeyError):
            self.update(model='small_en', device='cpu', language='en')

    def set(self, **values):
        self.update(values)
        model = BY_KEY[self['model']]
        if model.cpu_only:
            self['device'] = 'cpu'
        if model.english_only and self['language'] not in (None, 'en'):
            self['language'] = 'en'
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(self), indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
