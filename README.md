# Window transcription pill

A small always-on-top Windows app. **Choose a window → choose a model and CPU/GPU → Record → Stop.** It records audio first, then creates a timestamped transcript with your selected model. Transcription does not need to keep up during recording.

Double-click **Launch Whistle.vbs**, **Launch Whistle.cmd**, or the **Whistle** desktop shortcut. Click the model name to compare options and download models. The device selector offers **CPU** and **GPU (NVIDIA CUDA)** for supported models. Preferences are remembered. Small.en on CPU is the initial default.

The **▤** button opens the document; it also opens automatically when transcription finishes. **Cancel** during transcription stops the worker while preserving captured audio and partial text. Quitting cancels safely. Closing the source window finishes recording and starts transcription. Drag the pill by its border or timer.

Use **⋮ → Transcribe saved audio…** to run another model on an existing WAV. Each attempt creates a new transcript folder and references the original audio. It does not replace the earlier transcript or duplicate the recording.

## Models and devices

| Model | Download | Device | Guidance |
|---|---:|---|---|
| Whistle | 17 MB | CPU | Smallest, fast; technical vocabulary was less reliable in lecture tests |
| Whisper Small.en | 484 MB | CPU / CUDA | Balanced English default; tested on lecture recordings |
| Phonon-2 | 164 MB compressed | CPU | Fast CPU candidate; lecture tested; acronym errors remain |
| Nemotron 3.5 ASR 0.6B | 742 MB Q8_0 + runtime | CPU / CUDA | Fast native NVIDIA runtime; lecture tested |
| Whisper Medium.en | 1.53 GB | CPU / CUDA | More English capacity; download on demand; unbenchmarked here |
| Whisper Large-v3 | 3.09 GB | CPU / CUDA | Largest Whisper option, multilingual; download on demand; unbenchmarked here |

Quality/speed labels are guidance rather than verified accuracy rankings. The picker also shows local timings from one 56.14-second biology clip, including worker startup and model loading. Small.en was faster on CPU in this test; Nemotron was faster on CUDA. There is no automatic GPU-to-CPU fallback.

Native Windows Phonon uses its official CPU engine. Its published CUDA container is not integrated or claimed as tested here. Whistle is CPU-only. AMD/Vulkan/DirectML and Apple MLX are not offered.

Models are downloaded once. Larger models have a download button in the picker. Cancelled Hub downloads can be resumed. Audio never goes to an inference service; package telemetry is disabled.

## Saved files

Each capture or saved-audio transcription creates `transcripts/<date-and-time>/`:

- `Transcript.txt`: timestamped text, updated as final-pass sections finish.
- `Audio.wav`: captured audio, written before inference. For reruns, `session.json` references the existing WAV instead.
- `segments.jsonl`: recognized segments and available word timestamps.
- `session.json`: model, device, source, status, and measured inference time. Cancelled/error jobs are never marked complete.
- `inference.log`: backend diagnostics.

Recordings and transcripts remain until you delete them. The original lectures and comparison artifacts are preserved.

## Capture scope

Uses Windows process-loopback capture for the selected window's process and its children. Microphone audio and independent apps are excluded. Browsers can share a process tree across tabs/windows, so choosing Chrome can include other Chrome audio. Pause unrelated tabs or use a separately launched browser instance. Protected audio and audio rendered by an unrelated service may not be capturable.

## Setup and CUDA

Requires x64 Windows build 20348+, Python 3.12, and an audio output device. This machine uses Windows 11 build 26200.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_models.py
.\build-capture.cmd
.\.venv\Scripts\python.exe app.py
```

The capture helper build points to this machine's Visual Studio 2026 Community C++ tools and Windows SDK; adjust `build-capture.cmd` on another machine. Launchers use the project virtual environment.

Whisper CUDA needs an NVIDIA driver, CUDA 12 cuBLAS, and cuDNN 9 DLLs. The isolated worker searches installed CUDA toolkits and available PyTorch runtime DLL directories. Selecting GPU checks availability and reports missing dependencies. Inference checks free dedicated VRAM with a conservative reserve before loading. It does not deliberately spill models into shared system memory or alter other GPU jobs. GPU workers exit after each transcription to release model memory.

The RTX 5070 Ti was validated with Small.en and Nemotron on CUDA. Nemotron uses official NeMo-Speech.cpp 0.2.0 Windows CPU/CUDA binaries verified against release SHA-256 checksums; its download action installs them if missing. Phonon uses `fermion-research==0.2.11` and its verified model download.

## Verification

`tests/integration.py` exercises real app audio → WAV → final pass → saved document. `tests/idle.py` checks silence. `tests/isolation.py` checks unrelated-app exclusion at the Windows mixer dither floor. `tests/models_integration.py` runs six real model/device jobs and writes `models/benchmarks.json`. `tests/job_failures.py` checks decoder errors, cancellation, and native child-process cleanup. `tests/ui_smoke.py` exercises the pickers, preferences, model/device switching and actual CUDA availability check, and renders the widgets.

These checks prove the tested paths ran and saved transcripts; they do not establish perfect transcription or a general quality leaderboard. Earlier comparisons are in `transcripts/Quality Test Results.txt`.

## Sources and notices

[Whistle](https://huggingface.co/Cactus-Compute/whistle), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Nemotron 3.5](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b), [NVIDIA native runtime](https://github.com/NVIDIA/NeMo-Speech.cpp), [Phonon-2](https://huggingface.co/FermionResearch/Phonon-2), [Phonon runtime](https://github.com/fermionresearch/phonon), [Microsoft process-loopback documentation](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/).

Phonon-2 derives from NVIDIA Parakeet TDT 0.6B v3; its weights are CC-BY-4.0 and its CLI/runtime is Apache-2.0. Notices are retained in downloaded packages. Nemotron model terms are linked from its card; its native runtime is Apache-2.0. Keep this folder in place so the desktop shortcut continues to work.
