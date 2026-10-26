# Windows hardware validation

Reviewed PR #1 at `2e3c39fe7472d7f5824957421ef49e68eeaee9b0`, then added two regression fixes to the same PR.

Validation ran on October 26, 2026 in an isolated Windows worktree with its own Python environment and newly compiled capture helper. Original recordings, transcripts, model weights and the installed app checkout were preserved. Existing model caches were reused; generated test results and microphone samples stay local and are excluded from Git.

## Results

| Check | Evidence |
|---|---|
| MSVC build | Updated `native/capture.cpp` compiled using `build-capture.cmd` |
| Offline suite | All 20 checks passed after adding the two regression cases; these use stand-ins |
| `tests/integration.py` | Actual process-loopback speech playback, captured WAV, real Whistle final pass and saved text passed |
| `tests/idle.py` | Silent app capture and clean completion passed |
| `tests/isolation.py` | Unrelated app speech remained excluded at the Windows PCM mixer dither floor |
| `tests/models_integration.py` | Whistle CPU, Small.en CPU/CUDA, Phonon-2 CPU and Nemotron CPU/CUDA completed real model jobs |
| `tests/job_failures.py` | Decoder failure and cancellation passed, including native descendant cleanup |
| `tests/ui_smoke.py` | Real window list/names/icons, library/settings rendering, NVIDIA probe and processor/model controls passed |
| System audio | Real native capture retained an unrelated 440 Hz playback and excluded its own process's 660 Hz playback |
| Microphone | Actual default microphone started, emitted 44.1 kHz stereo PCM16 for approximately 1.5 seconds, and stopped cleanly |
| System + microphone | Real dual-source recorder passed pause/resume, stop and a final model pass; approximately 1.46 seconds were saved from 2.1 seconds with a 0.65-second pause |
| Global shortcut | Computer-use input sent Ctrl+Alt+R from a separate application process; actual app state changed to recording, then the second chord produced a completed 6.51-second library session |

The additional native endpoint checks are in `tests/windows_sources.py`. Start its `--sender` mode in an **independent process tree**, then run the script normally. A child playback process of the recorder is intentionally excluded from system capture, so both commands must not be parent/child processes. The sender plays a modest test tone and stops when the receiver finishes or its safety timeout expires.

The global-shortcut test used the actual native event filter, not a direct controller-method call. The real library was inspected after completion. No Windows security/privacy settings were changed.

## Fixed during review

1. **Unsaved edits could be lost when a library search hid every session.** The no-results branch replaced the current session without the selection callback that normally saves edits. Filtering now finishes/saves editing before changing the selection. The UI regression test covers hiding and restoring the edited session.
2. **PCM16 WAV imports depended on the external source file.** Compressed imports were library-owned, but valid WAV imports took the re-transcription fast path and referenced the external file. Imports now explicitly create library-owned audio even for WAV; re-transcriptions still reuse the existing library recording. The UI test checks audio ownership and the unchanged source hash.

## Limits

- Microphone startup/PCM delivery was tested; voice intelligibility and speech recognition through that microphone were not scored.
- Physical microphone unplugging and deliberate microphone privacy denial were not induced. Their handling remains code-reviewed rather than hardware-verified.
- One short real mixed-source test does not establish long-session clock drift or alignment under every device/driver.
- The model checks validate execution and persistence, not a general quality leaderboard. Medium.en and Large-v3 were not downloaded or benchmarked.
- Test output, audio, environments and model files are excluded from the PR.
