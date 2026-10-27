"""Download a single video/audio URL; decoding and ASR stay in the existing pipeline."""
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlsplit


def validate_url(value):
    value = value.strip()
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username
                 and not parsed.password and not any(char.isspace() for char in value))
        parsed.port  # Reject malformed port numbers as well.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Paste a complete http:// or https:// video URL.')
    return value


def download(url, directory, emit):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    url = validate_url(url)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)

    class Logger:
        def debug(self, message):
            print(message, file=sys.stderr)
        info = debug
        warning = debug
        error = debug

    last_progress = [0.0]
    def progress(event):
        if event.get('status') == 'downloading':
            now = time.monotonic()
            if now - last_progress[0] < 0.25:
                return
            last_progress[0] = now
            total = event.get('total_bytes') or event.get('total_bytes_estimate')
            if total:
                emit('progress', percent=min(99, round(100 * event.get('downloaded_bytes', 0) / total)))
            else:
                emit('status', text='Downloading audio…')

    def single_video(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
            return 'This is a live or upcoming stream. Import its replay after it ends.'
        return None

    # One playable stream needs no ffmpeg merge/extraction binary: PyAV decodes it later.
    options = {'format': 'bestaudio/best', 'outtmpl': str(directory / 'Source.%(ext)s'),
               'noplaylist': True, 'playlistend': 1, 'quiet': True, 'noprogress': True,
               'logger': Logger(), 'progress_hooks': [progress], 'match_filter': single_video,
               'socket_timeout': 20, 'retries': 2, 'fragment_retries': 2, 'cachedir': False,
               'windowsfilenames': True, 'overwrites': False}
    # yt-dlp enables Deno by default; explicitly enable installed Node too for YouTube.
    runtimes = {name: {'path': path} for name in ('deno', 'node') if (path := shutil.which(name))}
    if runtimes:
        options['js_runtimes'] = runtimes
    emit('status', text='Looking up video…')
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            # A playlist-only URL is deliberately bounded to its first video.
            if info and info.get('_type') in ('playlist', 'multi_video'):
                info = next((entry for entry in info.get('entries', []) if entry), None)
            if not info:
                raise RuntimeError('No downloadable video was found. For live streams, wait for the replay.')
            path = Path(downloader.prepare_filename(info)).resolve()
            if not path.is_relative_to(directory) or not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError('The video download did not produce usable audio. See inference.log for details.')
            title = str(info.get('title') or info.get('id') or urlsplit(url).hostname)
            emit('downloaded', path=str(path), title=title,
                 webpage_url=info.get('webpage_url') or url, duration=info.get('duration'))
    except DownloadError as exc:
        detail = str(exc).replace('\x1b', '')
        raise RuntimeError('Could not download this video. It may require a login, be restricted, '
                           'or use an unsupported player. Try importing a downloaded file instead.\n' + detail) from exc
