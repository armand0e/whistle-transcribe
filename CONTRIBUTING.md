# Contributing

Whistle is a Windows desktop app. Python 3.12 and Microsoft C++ Build Tools are used for development. Linux CI runs the offline suite; it does not qualify Linux audio capture or a Linux desktop release.

## Setup and checks

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\build-capture.cmd
.\.venv\Scripts\python.exe src\app.py
```

For tests without model packages, install `requirements-test.txt` into a separate environment. Run `python tests/offline.py`; its UI tests run off-screen. Do not run the pill stress test visibly on someone's desktop. Hardware checks are opt-in and documented in the README and `docs/windows-validation.md`.

Keep application code in `src/`, native capture in `native/`, developer tools in `scripts/`, and regressions in `tests/`. Shared paths come from `src/paths.py`; user data must remain at the checkout root. Preserve the two compatibility entry points so a pre-layout updater can finish launching after it pulls new code.

Add regression coverage for behavior changes. Stand-in capture/model tests verify orchestration and persistence, not microphone quality, transcription accuracy, or GPU support. Report separately which real devices/models were tested.

Never commit recordings, transcripts, settings, logs, environments, downloaded model weights, or secrets. Screenshots should use demonstration content. Do not include user audio or private URLs in issues or pull requests. New model/runtime downloads should use immutable revisions/checksums and retain upstream terms.

The launcher updates from published stable GitHub Releases, not source commits. Start `src/app.py` directly while developing to bypass release checks. The old clean-checkout Git updater is opt-in with `src/launch.py --dev-update`. To publish, update `src/version.py`, push a matching stable version tag, and let the release workflow build/test before publishing assets.
