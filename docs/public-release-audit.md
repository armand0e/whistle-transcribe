# Public-release review — October 29, 2026

This review covers the source-layout migration, repository hygiene, startup/import flows, transcript persistence, and automated checks. It is a bounded engineering review, not a security certification or a claim of perfect transcription.

## Structure and compatibility

- Runtime code moved to `src/`; setup and optional evaluation tools moved to `scripts/`.
- Shared source/data paths live in `src/paths.py`. Models, recordings, transcripts, settings, environments, and generated native files retain their existing locations.
- Root `app.py` and `launch.py` remain small compatibility shims. An isolated real-Git test loaded the actual pre-migration `d967215` updater/launcher, pulled a source-layout change, and successfully opened the new entry point. Installer/build steps in that migration fixture were stand-ins; the actual environment was also installed and audited separately.
- Evaluation and hardware scripts now require explicit sample inputs rather than assuming personal lecture directories. Benchmarks write to test output unless replacing model-picker timings is explicitly requested.
- Added MIT licensing, third-party notices, contributor guidance, and security/architecture documentation. Python test requirements reuse production constraints. CI has read-only repository permissions and updated checkout/setup actions.

## Bugs fixed

1. The transcript toolbar's three-dot button forwarded Qt's `clicked(False)` argument as a menu position. Its handler now drops that unrelated argument. Popup tests click the real button, check the model actions, open the right-click menu, and exercise all export-format actions.
2. Malformed settings values, including non-string model/language fields and invalid saved coordinates, could crash startup. Invalid fields now recover independently while valid preferences survive.
3. Mixed naive/aware session timestamps could break library sorting, and invalid duration fields could crash display. Loading now normalizes timestamp comparisons and ignores unusable duration values. Non-object session metadata is skipped without modifying the original file.
4. Renaming a live transcript could overwrite metadata being written by its worker. The title is read-only during a live job and the rename handler also rejects stale/programmatic edits until the worker finishes.

## Security and repository checks

- Gitleaks 8.30.1, downloaded from its official release and checksum-verified, scanned all 14 reachable pre-cleanup commits: no credential findings. A separate source-tree scan covers the public cleanup. No history was rewritten; ordinary author metadata and historical source paths remain public.
- The installed environment initially had advisory findings for `filelock`, `setuptools`, and `pip`. Requirements now pin patched versions. Re-scanning all 66 installed distributions with pip-audit reported no known vulnerabilities and no skipped distributions. `pip check` passed. These are advisory-database results at review time, not guarantees about undiscovered issues.
- Bandit review found no remaining medium/high severity findings. Low-severity findings for intentional subprocess use, desktop file opening, and evaluation assertions were reviewed rather than hidden. Commands use argument lists; URL text is not interpolated into a shell.
- Hugging Face downloads now specify immutable upstream revisions. NVIDIA runtime archive checksums remain enforced. The per-checkout IPC name still uses SHA-1 solely as a non-security identifier, now marked explicitly so FIPS/audit tools do not mistake it for a security hash.
- Models, recordings, transcripts, settings, logs, environments, and downloaded executables remain Git-excluded. Documentation screenshots were spot-reviewed for exposed credentials/private filesystem paths. Original local data/model files were hashed before and after the review: all 169 files were unchanged.

## Validation

- Full Windows off-screen suite: source/worker paths, legacy entry points, settings/session recovery, exports, stand-in capture/model flows, pause/resume, cancellation, queued imports, actual local HTTP downloads, real decoding, popup menus, both themes, pill-center regression, and Git updater fixtures.
- Real short YouTube URL → download → WAV → Whisper Small.en on CPU → saved transcript passed using the reorganized source paths.
- An isolated MSVC capture-helper build and usage/startup check passed without replacing the installed executable or recording microphone/system audio.
- Python compilation and Ruff syntax/undefined-name checks passed. Windows/Linux CI runs the regression suite and Windows native compilation on this change.

## Remaining limits

No new microphone, process-loopback, long-session synchronization, GPU-backend, or normal interactive pill-movement qualification was performed. Earlier hardware evidence and its limits remain in `windows-validation.md`; passing off-screen geometry tests does not replace the user's normal-use retest. Medium.en/Large-v3 quality remains unbenchmarked here.

URL support depends on upstream sites and access restrictions. Updates trust GitHub `main` and the package/model providers; there are no signed release installers. Cactus and Phonon runtime provisioning remains delegated to their pinned upstream packages. Third-party licenses are linked separately and are not replaced by MIT. Dependency advisories and model/site behavior can change after this review.
