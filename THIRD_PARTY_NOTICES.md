# Third-party notices

The MIT license in this repository covers application code. It does not replace licenses for installed Python packages, model weights, or downloaded native runtimes. Model weights and the separately fetched Cactus/NVIDIA engines are not committed or included in the installer. Windows releases bundle Python/runtime dependencies (including Phonon's CPU engine) and Node; their license/metadata files are retained in the installed payload. Review upstream terms before redistributing them yourself.

| Component | Upstream terms |
|---|---|
| Python | [Python license](https://docs.python.org/3/license.html) |
| Frozen executable | [PyInstaller license and bootloader exception](https://pyinstaller.org/en/stable/license.html) |
| Bundled YouTube JavaScript runtime | [Node.js license](https://github.com/nodejs/node/blob/v24.22.2/LICENSE) |
| Phonon CPU dependencies | [PyTorch](https://github.com/pytorch/pytorch), [Transformers](https://github.com/huggingface/transformers) |
| PySide6 / Qt | [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) |
| Cactus Whistle model | [Model card and Apache 2.0 license](https://huggingface.co/Cactus-Compute/whistle) |
| Cactus runtime | [cactus-needle package](https://pypi.org/project/cactus-needle/) |
| Whisper / faster-whisper | [OpenAI Whisper](https://github.com/openai/whisper), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2) |
| Phonon-2 | [Model card](https://huggingface.co/FermionResearch/Phonon-2), [runtime](https://github.com/fermionresearch/phonon) |
| Nemotron 3.5 model | [NVIDIA model card and additional terms](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) |
| NVIDIA native runtime | [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp) |
| yt-dlp and solver scripts | [yt-dlp](https://github.com/yt-dlp/yt-dlp), [yt-dlp-ejs](https://github.com/yt-dlp/ejs) |
| Media decoding and resampling | [PyAV](https://github.com/PyAV-Org/PyAV), [python-soxr](https://github.com/dofuuz/python-soxr) |

For the full dependency set and installed license metadata, inspect `requirements.txt` and each installed distribution. Model downloads retain their upstream repository metadata; NVIDIA installations include a local runtime manifest. Model licenses may differ from the license of their inference runtime.
