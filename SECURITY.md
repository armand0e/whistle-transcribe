# Security

Only the latest `main` revision is maintained. Report suspected vulnerabilities privately to the repository maintainer, using GitHub private vulnerability reporting if it is available. Do not post credentials, recordings, transcripts, or private video URLs in public issues.

Speech recognition runs locally. Downloading models, importing URLs, fetching GitHub updates, and installing dependencies use the network. URL imports do not automatically read browser cookies or log into sites. Session files and diagnostic logs can contain source URLs and transcription text; treat them as private.

Whistle runs with your Windows account's permissions. Its subprocess isolation provides cancellation and crash containment, not a sandbox for malicious media or downloaded runtimes. Automatic updates trust this repository's `main` branch and your configured Git/package transport. They are not signed release packages. Local changes and diverged history are never reset automatically.

Downloaded models and runtimes have independent upstream licenses and supply-chain risks. Hugging Face downloads use pinned revisions; NVIDIA runtime archives are checked against official release checksums. Cactus and Phonon runtime provisioning is delegated to the pinned upstream Python packages. This repository does not audit every transitive dependency or promise complete protection against hostile media.

See `docs/public-release-audit.md` for the scope and limits of the release review. Passing a scanner or CI is not a security certification.
