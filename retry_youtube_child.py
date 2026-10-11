import json
import pathlib
import sys
import time
from typing import List, Optional, Tuple

import spotdl
from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptionalOptions
from spotdl.types.song import Song

if __name__ != "__main__":
    raise SystemExit("child must be run as script")

OUT_DIR = pathlib.Path(sys.argv[1])
QUERY_FILE = pathlib.Path(sys.argv[2])
RESULT_FILE = pathlib.Path(sys.argv[3])
LOG_FILE = pathlib.Path(sys.argv[4])
MAX_WORKERS = int(sys.argv[5])
TIMEOUT = int(sys.argv[6])

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def log(line: str) -> None:
    ts = time.strftime("%T")
    msg = f"[{ts}] {line}"
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(msg + "\n")
            handle.flush()
    except OSError as exc:
        sys.stderr.write(f"[!] log write failed: {exc}\n")
        sys.stderr.flush()

def make_song(name: str) -> Song:
    artists = []
    title = name
    if " - " in name:
        split_at = name.index(" - ")
        artists_part = name[:split_at].strip()
        title = name[split_at + 3:].strip()
        if artists_part:
            artists = [a.strip() for a in artists_part.split(",") if a.strip()]
    return Song(
        name=title,
        artists=artists,
        artist=", ".join(artists) if artists else "",
        genres=[""],
        disc_number=1,
        disc_count=1,
        album_name="",
        album_artist="",
        duration=200,
        year=2024,
        date="2024-01-01",
        track_number=1,
        tracks_count=1,
        song_id="",
        explicit=False,
        publisher="",
        url="",
        isrc=None,
        cover_url=None,
        copyright_text=None,
        download_url=None,
        lyrics=None,
        popularity=None,
        album_id="",
        list_name=None,
        list_url=None,
        list_position=None,
        list_length=None,
        artist_id=None,
        album_type=None,
    )

log("child starting, out_dir=%s query_file=%s result_file=%s max_workers=%s timeout=%s"
    % (OUT_DIR, QUERY_FILE, RESULT_FILE, MAX_WORKERS, TIMEOUT))

if not QUERY_FILE.exists():
    log("query file missing: %s" % QUERY_FILE)
    RESULT_FILE.write_text(json.dumps({"error": "query file missing"}), encoding="utf-8")
    sys.exit(2)

names = [ln.strip() for ln in QUERY_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
if not names:
    log("query file empty")
    RESULT_FILE.write_text(json.dumps({"error": "query file empty"}), encoding="utf-8")
    sys.exit(3)

log("queued %d names" % len(names))

settings: DownloaderOptionalOptions = {
    "audio_providers": ["youtube"],
    "lyrics_providers": [],
    "genius_token": "",
    "playlist_numbering": False,
    "playlist_retain_track_cover": False,
    "scan_for_songs": False,
    "m3u": None,
    "output": str(OUT_DIR / "{artists} - {title}.{output-ext}"),
    "overwrite": "skip",
    "search_query": None,
    "ffmpeg": "ffmpeg",
    "bitrate": "320k",
    "ffmpeg_args": None,
    "format": "mp3",
    "save_file": None,
    "filter_results": True,
    "album_type": None,
    "threads": MAX_WORKERS,
    "cookie_file": None,
    "restrict": None,
    "print_errors": True,
    "sponsor_block": False,
    "preload": False,
    "archive": None,
    "load_config": False,
    "log_level": "INFO",
    "simple_tui": False,
    "fetch_albums": False,
    "id3_separator": " - ",
    "ytm_data": False,
    "add_unavailable": False,
    "generate_lrc": False,
    "force_update_metadata": False,
    "only_verified_results": False,
    "sync_without_deleting": False,
    "max_filename_length": None,
    "yt_dlp_args": None,
    "detect_formats": None,
    "save_errors": None,
    "proxy": None,
    "skip_explicit": False,
    "log_format": None,
    "redownload": False,
    "skip_album_art": False,
    "create_skip_file": False,
    "respect_skip_file": False,
    "sync_remove_lrc": False,
}

log("creating Downloader", flush=True)
downloader = Downloader(settings=settings)
log("Downloader created", flush=True)

results: List[dict] = []
downloaded = 0
failed = 0

for name in names:
    log("START %s" % name)
    try:
        song = make_song(name)
        result = downloader.search_and_download(song)
    except Exception as exc:
        log("FAIL %s : error: %r" % (name, exc))
        results.append({"query": name, "status": "error:%r" % exc, "path": None})
        failed += 1
        continue

    if result is None:
        log("FAIL %s : no result" % name)
        results.append({"query": name, "status": "failed:no_result", "path": None})
        failed += 1
        continue

    downloaded_song, path = result
    if path is None:
        log("FAIL %s : no path (search returned no yt match)" % name)
        results.append({"query": name, "status": "failed:no_path", "path": None})
        failed += 1
        continue

    downloaded += 1
    log("OK  %s -> %s" % (name, path))
    results.append({"query": name, "status": "downloaded", "path": str(path)})

summary = {
    "queued": len(names),
    "downloaded": downloaded,
    "failed": failed,
    "results": results,
}

log("writing result file: %s" % RESULT_FILE)
RESULT_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
log("child done: %d downloaded, %d failed" % (downloaded, failed))
