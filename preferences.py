"""Remembered choices, stored beside the app in settings.json."""
import json
import os

from model_catalog import BY_KEY, ROOT, validate_choice

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
        self.path = path or PATH
        try:
            stored = json.loads(self.path.read_text(encoding='utf-8'))
            self.update({key: value for key, value in stored.items() if key in DEFAULTS})
        except (OSError, ValueError, AttributeError):
            pass
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
