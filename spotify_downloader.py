"""Spotify playlist -> MP3 downloader powered by spotDL.

This module is the download engine: dependency setup, spotDL process control and
progress parsing. web_server.py provides the local browser UI and JSON API on top of it.

The job runs in three phases:
  1. Metadata  - read the playlist and fetch every track's metadata up front.
  2. Download  - fetch the audio, searching each configured platform per track.
  3. Fallback  - re-search any track no platform matched, using the saved metadata.

Run with:  python spotify_downloader.py   (Python 3.10 or newer)
"""

import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

OUTPUT_FOLDER_NAME = "Spotify_Liked_Songs_MP3"
MIN_PYTHON = (3, 10)          # spotDL's audio providers fail on Python 3.9
MAX_RETRIES_PER_TRACK = 3     # passed to spotDL
STALL_TIMEOUT_SECONDS = 300   # restart spotDL if it prints no track output for this long
METADATA_TIMEOUT_SECONDS = 3600  # big playlists can take a long time before spotDL reports the track count
MAX_ATTEMPTS = 5              # consecutive spotDL runs that record no new track before giving up
RETRY_DELAY_SECONDS = 5
PARALLEL_DOWNLOADS = 4        # simultaneous tracks, passed to spotDL --threads
# Audio platforms to try for every track, in fallback order. spotDL asks each
# provider in turn and downloads from the first one that has a match, so a song
# missing from YouTube is searched on SoundCloud, then Bandcamp, then Piped using the
# Spotify metadata we already hold (title, artists and ISRC when present).
# 'youtube-music' is intentionally left out: spotDL aborts the whole run with a hard
# error whenever YouTube Music is unreachable from the user's network.
AUDIO_PROVIDERS = ("youtube", "soundcloud", "bandcamp", "piped")
# Order used for the second pass over whatever the first pass could not download.
FALLBACK_PROVIDERS = ("soundcloud", "bandcamp", "piped", "youtube")
METADATA_FILENAME = "playlist_metadata.spotdl"   # all tracks, fetched before downloading
RETRY_FILENAME = "fallback_playlist.spotdl"      # tracks the first pass could not match
SPOTDL_ERRORS_FILENAME = "spotdl_errors.txt"     # raw spotDL failures (URL + reason)
RETRY_ERRORS_FILENAME = "fallback_errors.txt"    # failures still left after the fallback pass
# UI label -> (spotDL --format, spotDL --bitrate)
AUDIO_FORMATS = {
    "MP3 320 kbps": ("mp3", "320k"),
    "M4A 256 kbps": ("m4a", "256k"),
    "Opus 256 kbps": ("opus", "256k"),
    "FLAC (lossless)": ("flac", "disable"),
    "WAV (lossless)": ("wav", "disable"),
}
DEFAULT_FORMAT = "MP3 320 kbps"
# UI label -> spotDL --output template (the file extension is appended automatically)
FILENAME_TEMPLATES = {
    "Artist - Song": "{artists} - {title}",
    "Song - Artist": "{title} - {artists}",
    "Song only": "{title}",
    "Numbered (playlist order)": "{list-position} - {artists} - {title}",
}
DEFAULT_TEMPLATE = "Artist - Song"
SETTINGS_PATH = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "SpotifyDownloader", "settings.json")

# Accepts open.spotify.com/{playlist,track}/<id> (optional intl-xx path, www, query)
# or the spotify:{playlist,track}:<id> forms.
SPOTIFY_LINK_PATTERN = re.compile(
    r"^(?:(?:https?://)?(?:www\.)?open\.spotify\.com/(?:intl-[a-z]{2}/)?|spotify:)"
    r"(playlist|track)[/:]([A-Za-z0-9]{22})(?:[/?#]\S*)?$",
    re.IGNORECASE,
)
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
INVISIBLE_PATTERN = re.compile(r"[\u200b-\u200d\ufeff]")
FOUND_PATTERN = re.compile(r"Found (\d+) songs? in ")
PROGRESS_PATTERN = re.compile(r"(\d+)/(\d+) complete")
DOWNLOADED_PATTERN = re.compile(r'Downloaded "(?P<name>.+?)":')
SKIPPED_PATTERN = re.compile(r"Skipping (?P<name>.+?) \((?:file already exists|skip file found)\)")
NO_MATCH_PATTERN = re.compile(r"No results found for song:\s*(?P<name>.+?)\s*$")
FAILED_PATTERN = re.compile(r"LookupError|\bError\b|\bFailed\b")
SPOTDL_CHILD_FLAG = "--run-spotdl"  # frozen exe re-launches itself with this flag to run spotDL
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # no console flashes from the GUI


# ---------------------------------------------------------------- backend

class DownloadProgress:
    """Tracks unique tracks so spotDL restarts never double-count songs."""

    def __init__(self, log, on_progress):
        self.total = 0  # unknown until spotDL reports the playlist size
        self.results = {}  # track name -> "downloaded" | "skipped" | "failed"
        self._log = log
        self._on_progress = on_progress

    def set_total(self, total):
        if total > 0 and total != self.total:
            self.total = total
            self._on_progress(len(self.results), self.total)

    def record(self, name, status):
        is_new = name not in self.results
        self.results[name] = status
        if is_new:
            done = len(self.results)
            self.total = max(self.total, done)
            label = {"downloaded": "DONE", "skipped": "SKIP", "failed": "FAIL"}[status]
            self._log(f"[{done:>5,} of {self.total:,}] {label} {name}")
            self._on_progress(done, self.total)

    def handle_line(self, raw_line):
        """Parse one spotDL output line. Returns True when the line shows spotDL is reporting tracks."""
        line = ANSI_PATTERN.sub("", raw_line).strip()
        if not line:
            return False
        found = FOUND_PATTERN.search(line) or PROGRESS_PATTERN.search(line)
        if found:
            self.set_total(int(found.groups()[-1]))
            return True
        downloaded = DOWNLOADED_PATTERN.search(line)
        if downloaded:
            self.record(downloaded.group("name"), "downloaded")
            return True
        skipped = SKIPPED_PATTERN.search(line)
        if skipped:
            self.record(skipped.group("name"), "skipped")
            return True
        no_match = NO_MATCH_PATTERN.search(line)
        if no_match:
            # 'No results found for song: <name>' -> record against the track itself, so a
            # later success on another platform replaces this entry instead of adding a new one.
            self.record(no_match.group("name"), "failed")
            return True
        if FAILED_PATTERN.search(line):
            self.record(line, "failed")
            return True
        return False


def validate_spotify_link(raw):
    """Return a normalized playlist or track URL, or None if the text is neither."""
    cleaned = INVISIBLE_PATTERN.sub("", raw).strip().strip("\"'").strip()
    match = SPOTIFY_LINK_PATTERN.match(cleaned)
    if not match:
        return None
    return f"https://open.spotify.com/{match.group(1).lower()}/{match.group(2)}"


def output_directory():
    """Return the download folder on the Desktop (OneDrive-aware), else in the working directory."""
    home = os.path.expanduser("~")
    for desktop in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(desktop):
            return os.path.join(desktop, OUTPUT_FOLDER_NAME)
    return os.path.join(os.getcwd(), OUTPUT_FOLDER_NAME)


def load_settings():
    """Return the saved UI choices. A missing or unreadable file gives defaults."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data):
    """Save the UI choices. Returns False if the settings file could not be written."""
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except OSError:
        return False
    return True


def log_tail(text, log, lines=5):
    for line in text.strip().splitlines()[-lines:]:
        log("    " + line)


def spotdl_command(*args):
    """Command line that runs spotDL. A frozen exe runs itself in spotDL mode; source runs use python -m."""
    if getattr(sys, "frozen", False):
        return [sys.executable, SPOTDL_CHILD_FLAG, *args]
    return [sys.executable, "-m", "spotdl", *args]


def ensure_spotdl(log):
    """Install spotDL with pip if it is not importable. Returns True when spotDL is available."""
    if importlib.util.find_spec("spotdl") is not None:
        log("[OK] spotDL is installed.")
        return True
    if getattr(sys, "frozen", False):
        log("[X] spotDL is missing from this build. Rebuild the exe with spotDL bundled.")
        return False
    log("[!] spotDL not found. Installing with pip (this can take a minute)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "spotdl"],
            creationflags=NO_WINDOW,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        log(f"[X] Could not run pip: {exc}")
        return False
    if result.returncode != 0:
        log("[X] pip install spotdl failed:")
        log_tail(result.stderr or result.stdout, log)
        return False
    log("[OK] spotDL installed.")
    return True


def ensure_ffmpeg(log):
    """Run 'spotdl --download-ffmpeg'. A failure is logged as a warning, not a fatal error."""
    log("Setting up FFmpeg (spotdl --download-ffmpeg)...")
    try:
        result = subprocess.run(
            spotdl_command("--download-ffmpeg"),
            creationflags=NO_WINDOW,
            input="n\n",  # answers 'keep existing FFmpeg' if spotDL asks
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        log(f"[!] Could not run FFmpeg setup: {exc}")
        return
    if result.returncode != 0:
        log("[!] FFmpeg setup reported an error. Conversion may fail if FFmpeg is missing.")
        log_tail(result.stderr or result.stdout, log, lines=3)
    else:
        log("[OK] FFmpeg is ready.")


def stop_process(proc):
    """Terminate spotDL and any child processes such as FFmpeg."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
            check=False,
        )
    try:
        proc.kill()
    except OSError:
        pass
    proc.wait()


def run_spotdl(args, cwd, progress, cancel_event, log):
    """Run spotDL once and stream its output.

    progress may be a DownloadProgress (download passes) or None (the metadata pass,
    which only needs its output relayed to the log).
    Returns (exit_code, outcome) where outcome is "finished", "stalled", "cancelled" or "error".
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            creationflags=NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        log(f"[X] Could not start spotDL: {exc}")
        return None, "error"

    lines = queue.Queue()

    def pump():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    last_output = time.monotonic()
    tracks_reported = False
    while True:
        if cancel_event.is_set():
            stop_process(proc)
            return None, "cancelled"
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            # Silence while fetching the playlist can be long for big playlists; allow more time there.
            limit = STALL_TIMEOUT_SECONDS if tracks_reported else METADATA_TIMEOUT_SECONDS
            if time.monotonic() - last_output > limit:
                log(f"[!] No output for {limit}s. Restarting spotDL...")
                stop_process(proc)
                return None, "stalled"
            continue
        if line is None:
            break
        last_output = time.monotonic()
        if progress is not None:
            if progress.handle_line(line):
                tracks_reported = True
        elif line.strip():
            # The metadata pass has no counter; any output means spotDL is still alive.
            tracks_reported = True
    return proc.wait(), "finished"


def print_summary(progress, output_dir, log, total=None, failed_names=None):
    """Log totals and save failed track names to failed_tracks.txt.

    When failed_names is given the summary is driven by the track list we fetched from
    Spotify rather than the streamed output, so it stays correct after the fallback pass
    (spotDL also prints raw error lines, which are not real track entries).
    """
    log("-" * 60)
    if failed_names is None and not progress.results:
        log("[!] spotDL reported no tracks. Check the link and your internet connection.")
        return
    skipped = sum(1 for status in progress.results.values() if status == "skipped")
    if failed_names is None:
        failed_names = [name for name, status in progress.results.items() if status == "failed"]
        downloaded = sum(1 for status in progress.results.values() if status == "downloaded")
    else:
        downloaded = max(0, (total or 0) - skipped - len(failed_names))
    log(
        f"Downloaded: {downloaded:,} | Already present: {skipped:,} "
        f"| Failed: {len(failed_names):,}"
    )
    if failed_names:
        log_path = os.path.join(output_dir, "failed_tracks.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(failed_names) + "\n")
            log(f"Failed track list saved to: {log_path}")
        except OSError as exc:
            log(f"[!] Could not save failed track list: {exc}")


# ------------------------------------------------------------ pipeline steps

def song_label(song):
    """Return 'Artist - Title' for a saved metadata entry."""
    artists = song.get("artists") or []
    if not artists and song.get("artist"):
        artists = [song["artist"]]
    artist = ", ".join(name for name in artists if name) or "Unknown artist"
    return f"{artist} - {song.get('name') or 'Unknown title'}"


def audio_args(providers):
    """spotDL takes one --audio flag followed by every provider it may use, in order."""
    return ["--audio", *providers]


def load_metadata_songs(metadata_path):
    """Read the .spotdl file written by 'spotdl save'. Returns a list of dicts or None."""
    try:
        with open(metadata_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [entry for entry in data if isinstance(entry, dict)]


def fetch_metadata(playlist_url, metadata_path, log, cancel_event):
    """Fetch every track's metadata for the playlist into metadata_path.

    Returns the list of song dicts, or None when the metadata could not be read.
    """
    try:
        os.remove(metadata_path)
    except OSError:
        pass
    command = spotdl_command(
        "save", playlist_url,
        "--save-file", metadata_path,
        *audio_args(AUDIO_PROVIDERS),
        "--lyrics",  # empty value: skip the per-track lyrics lookup for this pass
        "--threads", str(PARALLEL_DOWNLOADS),
        "--simple-tui",
    )
    cwd = os.path.dirname(os.path.abspath(metadata_path)) or "."
    _, outcome = run_spotdl(command, cwd, None, cancel_event, log)
    if outcome == "cancelled":
        return None
    return load_metadata_songs(metadata_path)


def read_failed_urls(errors_path):
    """Collect the track URLs spotDL reported as failed in its --save-errors file."""
    urls = set()
    try:
        with open(errors_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("http") and " - " in line:
                    urls.add(line.split(" - ", 1)[0].strip())
    except OSError:
        pass
    return urls


def build_download_args(source, format_label, template_label, providers, errors_path=None, dont_filter=False):
    """Build a 'spotdl download' command for a playlist URL or a .spotdl metadata file."""
    audio_format, bitrate = AUDIO_FORMATS[format_label]
    name_template = FILENAME_TEMPLATES[template_label]
    command = spotdl_command(
        "download", source,
        *audio_args(providers),
        "--format", audio_format,
        "--bitrate", bitrate,
        "--output", name_template + ".{output-ext}",
        "--threads", str(PARALLEL_DOWNLOADS),
        "--overwrite", "skip",  # resume: never re-download finished files
        "--max-retries", str(MAX_RETRIES_PER_TRACK),
        "--simple-tui",
    )
    if errors_path:
        command += ["--save-errors", errors_path]
    if dont_filter:
        command += ["--dont-filter-results"]  # looser match for the fallback pass
    return command


def run_with_retries(command, output_dir, progress, cancel_event, log):
    """Run spotDL, retrying while it fails or stalls. Returns True when a run exits cleanly."""
    run_number = 0
    idle_runs = 0  # runs in a row that recorded no new track
    while True:
        run_number += 1
        tracks_before = len(progress.results)
        exit_code, outcome = run_spotdl(command, output_dir, progress, cancel_event, log)
        if outcome == "cancelled":
            log("[!] Stopped by user.")
            return False
        if outcome == "finished" and exit_code == 0:
            return True
        # Big playlists can stall many times while still making progress, so only idle runs count against the limit.
        idle_runs = 0 if len(progress.results) > tracks_before else idle_runs + 1
        reason = "stalled" if outcome == "stalled" else f"failed (exit code {exit_code})"
        if idle_runs >= MAX_ATTEMPTS:
            log(f"[X] spotDL {reason}. Giving up after {MAX_ATTEMPTS} runs with no new tracks.")
            return False
        log(f"[!] spotDL {reason}. Retrying (run {run_number + 1}); finished tracks are skipped.")
        if cancel_event.wait(RETRY_DELAY_SECONDS):
            log("[!] Stopped by user.")
            return False


def retry_failed_songs(songs, failed_urls, output_dir, format_label, template_label, progress, cancel_event, log, errors_path):
    """Re-search the tracks no platform matched, using their saved metadata, on the others."""
    retry_songs = [song for song in songs if song.get("url") in failed_urls]
    if not retry_songs:
        return False
    retry_path = os.path.join(output_dir, RETRY_FILENAME)
    try:
        with open(retry_path, "w", encoding="utf-8") as handle:
            json.dump(retry_songs, handle, indent=2, ensure_ascii=False)
    except OSError as exc:
        log(f"[!] Could not write the fallback metadata file: {exc}")
        return False
    log("-" * 60)
    log(f"[*] Fallback: re-searching {len(retry_songs)} failed track(s) on "
        f"{' -> '.join(FALLBACK_PROVIDERS)} using their metadata...")
    command = build_download_args(
        retry_path, format_label, template_label, FALLBACK_PROVIDERS,
        errors_path=errors_path, dont_filter=True)
    return run_with_retries(command, output_dir, progress, cancel_event, log)


def process_playlist(playlist_url, output_dir, format_label, template_label, log, on_progress, cancel_event):
    """Fetch all metadata, download with a per-track platform fallback, then retry failures."""
    log(f"Saving to: {output_dir}")
    metadata_path = os.path.join(output_dir, METADATA_FILENAME)
    errors_path = os.path.join(output_dir, SPOTDL_ERRORS_FILENAME)
    retry_errors_path = os.path.join(output_dir, RETRY_ERRORS_FILENAME)
    for stale in (errors_path, retry_errors_path):
        try:
            os.remove(stale)
        except OSError:
            pass

    # 1. Metadata: read the playlist and resolve every track before downloading anything.
    log("-" * 60)
    log("[*] Step 1/3: Fetching metadata for every track in the playlist...")
    songs = fetch_metadata(playlist_url, metadata_path, log, cancel_event)
    progress = DownloadProgress(log, on_progress)
    if cancel_event.is_set():
        log("[!] Stopped by user.")
        return False

    source = playlist_url
    total = None
    if songs:
        total = len(songs)
        source = metadata_path  # download the resolved track list, not the raw link
        progress.set_total(total)
        log(f"[OK] {total} track(s) to download:")
        for index, song in enumerate(songs, 1):
            log(f"      {index:>5}. {song_label(song)}")
    else:
        log("[!] Could not read the track metadata for this link.")
        log("[*] Falling back to the playlist link directly; tracks are still matched per platform.")

    # 2. Download: spotDL searches the platforms in order for every track.
    log("-" * 60)
    log(f"[*] Step 2/3: Downloading with per-track fallback ({' -> '.join(AUDIO_PROVIDERS)})...")
    command = build_download_args(source, format_label, template_label, AUDIO_PROVIDERS, errors_path)
    ran_cleanly = run_with_retries(command, output_dir, progress, cancel_event, log)
    if cancel_event.is_set():
        log("[!] Stopped by user.")
        print_summary(progress, output_dir, log, total=total)
        return False

    # 3. Fallback: whatever no platform matched is re-searched on the others.
    if songs:
        failed_urls = read_failed_urls(errors_path)
        failed_names = []
        if failed_urls:
            failed_songs = [song for song in songs if song.get("url") in failed_urls]
            log("-" * 60)
            log(f"[!] {len(failed_songs)} track(s) were not found on the first pass:")
            for song in failed_songs:
                log(f"[X]       {song_label(song)}")
            retried = retry_failed_songs(
                songs, failed_urls, output_dir, format_label, template_label,
                progress, cancel_event, log, retry_errors_path)
            if retried or os.path.exists(retry_errors_path):
                still_failed = read_failed_urls(retry_errors_path)
            else:
                # The fallback could not run at all; the original failures still stand.
                still_failed = failed_urls
            failed_names = [song_label(song) for song in songs if song.get("url") in still_failed]
        else:
            log("-" * 60)
            log("[OK] Every requested track was matched by a platform.")
        print_summary(progress, output_dir, log, total=total, failed_names=failed_names)
        return not failed_names

    print_summary(progress, output_dir, log, total=total)
    return ran_cleanly


def run_download_job(playlist_url, output_dir, format_label, template_label, log, on_progress, cancel_event):
    """Full backend job: check Python, set up dependencies, then run the pipeline. Returns True on success."""
    if sys.version_info < MIN_PYTHON:
        log(f"[X] Python {sys.version.split()[0]} is too old. spotDL needs Python 3.10 or newer.")
        return False
    if not ensure_spotdl(log):
        return False
    ensure_ffmpeg(log)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        log(f"[X] Could not create folder {output_dir}: {exc}")
        return False
    return process_playlist(
        playlist_url, output_dir, format_label, template_label, log, on_progress, cancel_event)


# ----------------------------------------------------------- entry point

def main(argv):
    """Start the local web app. Pass --no-browser to skip opening the browser."""
    if getattr(sys, "frozen", False) and sys.stdout is None:
        # The windowed exe has no console, so send server output to a log file.
        log_dir = os.path.dirname(SETTINGS_PATH)
        os.makedirs(log_dir, exist_ok=True)
        log_stream = open(os.path.join(log_dir, "server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log_stream
    import web_server  # imported here so the download engine does not depend on Flask
    web_server.run_server(open_browser="--no-browser" not in argv)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == SPOTDL_CHILD_FLAG:
        # Frozen exe acting as the spotDL engine (see spotdl_command).
        from spotdl.console import console_entry_point
        sys.argv = ["spotdl", *sys.argv[2:]]
        console_entry_point()
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
