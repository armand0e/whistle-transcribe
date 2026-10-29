# Architecture

`src/app.py` owns the Qt controller, tray, global shortcut, library, and one active recording/import/transcription job. `pill.py`, `library.py`, and the dialogs share controls in `widgets.py` and colors/icons in `theme.py`.

`capture_jobs.py` orchestrates native capture streams and isolated `asr_worker.py` subprocesses. Audio is saved before final recognition. `native/capture.cpp` supplies process-loopback, system, and microphone PCM. Imports use the existing decoder; URL imports use `url_import.py` in the worker before decoding and recognition. Cancellation targets owned worker processes and descendants.

`transcriber.py` writes raw recognizer segments and timestamped text. `sessions.py` loads the library, stores edits separately, and exports formats. A re-transcription references the original saved audio; a new file import owns a converted WAV. Preserve this distinction when changing storage or deletion behavior.

`paths.py` is the only source of the checkout and source directory paths. Code lives in `src/`; local data, settings, native build outputs, and environments stay at the checkout root. Workers are launched by absolute source paths with argument lists, without a command shell.

`src/launch.py` uses the standard library and Tk to run `auto_update.py` before importing Qt. The updater serializes startup checks, skips running/modified/development checkouts, and applies only fast-forward changes from the expected origin. It records successful requirements/build hashes, stages native builds, and preserves the last helper when compilation fails. Failures leave logs in `.updates/` and retry on the next full launch. Root compatibility shims allow older launchers, already loaded before a pull, to find the reorganized app.

Tests exercise source paths and legacy entry points, sessions/exports/settings recovery, real decoding and local HTTP URL downloads, stand-in capture/model orchestration, off-screen UI and pill anchoring, and real temporary Git repositories. Hardware/model checks are separate and require explicit inputs.
