Whistle for Windows x64: record an app, all system audio, or a microphone; import a file or video URL; and save editable transcripts using local models.

Download **Whistle-Setup-@VERSION@-x64.exe** and run it. Python, Git, Node, and C++ build tools are bundled or unnecessary. Models download on demand. CPU inference is ready to use; NVIDIA acceleration still needs the NVIDIA driver and compatible CUDA 12/cuDNN 9 libraries for Whisper.

The launcher checks the latest stable GitHub Release and compares version tags. Equal/older versions are skipped, downloads are SHA-256 verified, and updates wait while Whistle is running. Recordings, transcripts, settings, and model caches are kept separately from program files.

New installs use `%LOCALAPPDATA%\Whistle` for data. An existing source-install shortcut is recognized so its library and caches can be reused without moving or deleting them. Uninstall removes the program and leaves user data intact.

The installer is not code-signed; Windows may show an unknown-publisher warning. SHA-256 checksums are supplied as `SHA256SUMS.txt`. GitHub Releases and package providers remain the update trust boundary; these checksums are not a publisher signature.

See the repository README for supported capture scope, model guidance, runtime requirements, and validation limits.
