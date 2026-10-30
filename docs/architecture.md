# Architecture

`src/app.py` owns the Qt controller, tray, global shortcut, library, and one active recording/import/transcription job. `pill.py`, `library.py`, and the dialogs share controls in `widgets.py` and colors/icons in `theme.py`.

`capture_jobs.py` orchestrates native capture streams and isolated `asr_worker.py` subprocesses. Audio is saved before final recognition. `native/capture.cpp` supplies process-loopback, system, and microphone PCM. Imports use the existing decoder; URL imports use `url_import.py` in the worker before decoding and recognition. Cancellation targets owned worker processes and descendants.

`transcriber.py` writes raw recognizer segments and timestamped text. `sessions.py` loads the library, stores edits separately, and exports formats. A re-transcription references the original saved audio; a new file import owns a converted WAV. Preserve this distinction when changing storage or deletion behavior.

`paths.py` separates immutable program files from data. Source checkouts keep their existing data at the checkout root. Frozen installs use `%LOCALAPPDATA%\Whistle`, or a preserved existing data location recorded in `bootstrap.json`; program files default to `%LOCALAPPDATA%\Programs\Whistle`. `WHISTLE_DATA_DIR` can select an explicit data location. Source workers launch by absolute Python paths; frozen builds use a console `WhistleWorker.exe`, with argument lists and no command shell. Native capture and Node are bundled; model/native-ASR downloads stay in the writable data folder.

`src/launch.py` uses the standard library and Tk to run `release_update.py` before importing Qt. The updater compares the installed version to GitHub's latest stable release, skips equal/older versions, uses ETags, verifies installer hashes/size, and serializes checks. If the app is running, installation is deferred. Setup waits for the launcher process to exit before replacing program files. Offline/hash errors keep the installed copy usable. No Git/pip/compiler is invoked by this path. The former Git updater remains opt-in with `--dev-update` for source developers; it is not the installed application's update mechanism.

Tests exercise source paths and legacy entry points, sessions/exports/settings recovery, real decoding and local HTTP URL downloads, stand-in capture/model orchestration, off-screen UI and pill anchoring, and real temporary Git repositories. Hardware/model checks are separate and require explicit inputs.
