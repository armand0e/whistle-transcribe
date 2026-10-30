# Windows executable releases

The initial stable executable release is `v0.1.0`. `src/version.py` is the version authority; the CI tag must match it. Assets are named `Whistle-Setup-<version>-x64.exe` and `SHA256SUMS.txt`.

## Payload and data

PyInstaller builds a windowed `Whistle.exe` and a console `WhistleWorker.exe` sharing one runtime. The installer includes Python, Qt, CPU ASR dependencies, the native capture helper, and a checksum-pinned Node runtime for YouTube. Phonon requires its CPU PyTorch/Transformers runtime, which is included rather than requiring the user to install packages. Model weights and downloaded native ASR runtimes remain on demand and are not collected from the developer's data folders.

Program files default to `%LOCALAPPDATA%\Programs\Whistle`; new-user data defaults to `%LOCALAPPDATA%\Whistle`. Setup recognizes an existing source-install shortcut and records its data directory without moving/deleting the library or caches. Source-updater migration does the same. `bootstrap.json` records that data-location choice. Uninstall leaves all user data intact.

NVIDIA acceleration requires a compatible driver and the CUDA/cuDNN libraries used by the backend. No other GPU backend is offered. The bundled CPU runtimes do not remove these optional NVIDIA requirements. The installer is unsigned, so unknown-publisher/SmartScreen notices are possible; no signing identity or private key is bundled.

## Release updates

The startup check uses the public latest-stable GitHub Release API, not repository HEAD. It compares numeric stable version tags, ignores drafts/prereleases, and never downgrades. Equal versions do not download assets. Responses use conditional ETags; verified installer downloads can be reused. New installers must match the repository, exact expected asset name, declared size, SHA-256 manifest, and GitHub asset digest when one is supplied. A partial or invalid download is not executed.

The app must be fully closed for installation; an existing recording/transcription is not interrupted. Setup waits for the launcher's PID to exit so its DLLs can be replaced. Failed/offline checks open the installed copy. Check and installer-in-progress locks prevent duplicate work. Same-origin hashes provide integrity against corruption, not an independent publisher signature. GitHub release access remains a trust boundary.

## Build and publication

Run `scripts/release/build.py` on Windows x64 with `requirements/release.txt` installed and an Inno Setup compiler. `install_compiler.ps1` downloads a pinned official compiler and checks its SHA-256. Build PATH is restricted so unrelated developer DLLs cannot enter the bundle. Dependency metadata/license files and the Node license are retained in the payload.

The release workflow builds on a clean Windows runner, runs off-screen regressions and frozen smoke tests, verifies isolated install/upgrade/uninstall, and uploads the installer/checksums. A separate publication job verifies artifact hashes and creates the GitHub Release. Build jobs have read-only repository permissions; only publication receives write permission. Official workflow actions are pinned to commit hashes. A manual dispatch produces artifacts without publishing; a matching stable version tag publishes after successful checks. Already published releases are not silently overwritten.

## Initial validation

- Offline release tests: version equality/numeric ordering, no downgrade, drafts/prereleases, ETag 304 cache, offline/no-release fallback, checksum/size/digest failures, foreign assets, cached installers, serialization, running-app deferral, and installer handoff without Git/pip/compiler execution.
- Frozen smoke: Tk startup-progress resources, Qt widgets, settings/library/pill construction, worker protocol/imports, real audio conversion, native helper startup, and bundled resources with isolated data. Smoke-test children run without visible consoles.
- Frozen real-model checks: Whisper Small.en, Whistle, Phonon-2 and Nemotron CPU on a short saved public video, with only Windows directories on PATH. Existing model weights were reused; these checks establish execution rather than perfect accuracy.
- Frozen YouTube import used bundled Node with no system Node/Python/Git on PATH. A fresh on-demand Whistle model/runtime download also passed.
- The actual installer passed fresh install, reinstall/upgrade, and uninstall in an isolated program/data location with separate test registration and no real shortcuts. The tests cover spaces in the installation path, legacy-shortcut data discovery, and a UTF-8/BOM bootstrap pointing at Unicode data. Original settings and sample-library bytes were checked after each step. Uninstall removed the program and preserved data.

Source tests and CI do not establish long-session capture alignment, normal interactive pill placement, arbitrary website compatibility, GPU performance, or accuracy of every model. The real installed-package check is bounded by the models and CPU paths above; medium/large model quality remains unbenchmarked. Earlier hardware evidence is recorded separately in `windows-validation.md`.
