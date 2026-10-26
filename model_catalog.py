"""Local model choices. Quality/speed labels are guidance, not benchmark scores."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / 'models' / 'crosscheck-hub'

LANGUAGES = (
    (None, 'Detect automatically'), ('en', 'English'), ('de', 'German'), ('fr', 'French'),
    ('es', 'Spanish'), ('it', 'Italian'), ('nl', 'Dutch'), ('pl', 'Polish'), ('pt', 'Portuguese'),
    ('ja', 'Japanese'), ('zh', 'Chinese'), ('ko', 'Korean'),
)
LANGUAGE_NAMES = dict(LANGUAGES)

@dataclass(frozen=True)
class Model:
    key: str
    name: str
    short: str
    repo: str | None
    size: str
    quality: str
    speed: str
    description: str
    english_only: bool = False
    gpu_budget_mb: int = 0
    cpu_only: bool = False
    vocabulary: bool = False
    languages: tuple = ('en', 'de', 'fr', 'es', 'it', 'nl', 'pl')

    @property
    def devices(self):
        return ('cpu',) if self.cpu_only else ('cpu', 'cuda')

MODELS = (
    Model('whistle', 'Whistle', 'Whistle', None, '17 MB', 'Lightweight', 'Fastest',
          'Tiny CPU model. Lecture tested; technical terminology was less reliable.', cpu_only=True, vocabulary=True),
    Model('small_en', 'Whisper Small.en', 'Small.en', 'Systran/faster-whisper-small.en',
          '484 MB', 'Good', 'Fast', 'Balanced default. Recognized the key terms in your normal-speed clip.', True, 2500,
          vocabulary=True),
    Model('phonon2', 'Phonon-2', 'Phonon-2', 'FermionResearch/Phonon-2',
          '164 MB', 'Promising', 'Very fast CPU', 'Lecture tested on CPU. Fast local option; some acronym errors remain. Windows CUDA is not supported by this integration.', True, 0, True),
    Model('nemotron35', 'Nemotron 3.5 ASR 0.6B', 'Nemotron', 'nvidia/nemotron-3.5-asr-streaming-0.6b',
          '742 MB Q8', 'Promising', 'Very fast GPU', 'Lecture tested with the official NVIDIA Q8_0 runtime. Fast CPU/CUDA option; some acronym errors remain.', False, 5000),
    Model('medium_en', 'Whisper Medium.en', 'Medium.en', 'Systran/faster-whisper-medium.en',
          '1.53 GB', 'Higher expected', 'Slower', 'More capacity for English lectures. Not benchmarked on your recordings.', True, 5000,
          vocabulary=True),
    Model('large_v3', 'Whisper Large-v3', 'Large-v3', 'Systran/faster-whisper-large-v3',
          '3.09 GB', 'Top Whisper', 'Slowest expected', 'Largest Whisper option; multilingual. Not benchmarked on your recordings.', False, 10000,
          vocabulary=True, languages=tuple(code for code, _ in LANGUAGES if code)),
)
BY_KEY = {model.key: model for model in MODELS}

def model_path(key):
    model = BY_KEY[key]
    if key == 'whistle':
        path = ROOT / 'models' / 'whistle.cact'
        return path if path.is_file() and (path.parent / 'libneedle.dll').is_file() else None
    if key == 'phonon2':
        for manifest in (ROOT / 'models' / 'phonon' / 'speech' / 'FermionResearch__Phonon-2').glob('*/packed_manifest.json'):
            if (manifest.parent / 'config.json').is_file():
                return manifest.parent
        return None
    repository = CACHE / ('models--' + model.repo.replace('/', '--'))
    ref = repository / 'refs' / 'main'
    snapshots = []
    if ref.is_file():
        snapshots.append(repository / 'snapshots' / ref.read_text().strip())
    snapshots.extend(sorted((repository / 'snapshots').glob('*'), key=lambda path: path.stat().st_mtime, reverse=True))
    for path in snapshots:
        if key == 'nemotron35':
            weights = path / 'nemotron-3.5-asr-streaming-0.6b.q8_0.gguf'
            if weights.is_file():
                return weights
            continue
        if all((path / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
            return path
    return None

def nemo_executable(device):
    return next((ROOT / 'bin' / f'nemo-{device}').glob('**/nemo-speech.exe'), None)

def supports_language(key, language):
    model = BY_KEY[key]
    if model.english_only:
        return language in (None, 'en')
    return language is None or language in model.languages

def validate_choice(key, device, language):
    if key not in BY_KEY:
        raise ValueError('Choose a valid transcription model.')
    if device not in ('cpu', 'cuda'):
        raise ValueError('Choose CPU or NVIDIA CUDA.')
    model = BY_KEY[key]
    if model.cpu_only and device != 'cpu':
        raise ValueError(f'{model.name} runs on CPU in this app. Select a Whisper or Nemotron model to use NVIDIA CUDA.')
    if model.english_only and language not in (None, 'en'):
        raise ValueError(f'{model.name} is English-only. Choose English or a multilingual model.')
    if not supports_language(key, language):
        raise ValueError(f'{model.name} does not support {LANGUAGE_NAMES.get(language, language)}. Choose Whisper Large-v3.')
