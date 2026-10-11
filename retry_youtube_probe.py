import pathlib
import sys
import time
import traceback

import spotdl
from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptionalOptions
from spotdl.types.song import Song

OUT_DIR = pathlib.Path("C:/Users/admin/Desktop/Spotify_Liked_Songs_MP3/Spotify_Downloader_Retry/yt_probe_full")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG = OUT_DIR / "probe.log"
RESULT = OUT_DIR / "probe_result.json"

def log(text: str) -> None:
    ts = time.strftime("%T")
    line = f"[{ts}] {text}"
    print(line, flush=True)
    try:
        LOG.write_text(LOG.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
    except OSError:
        pass

log("start")
t0 = time.time()
try:
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
        "threads": 4,
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
    log("creating Downloader")
    d = Downloader(settings=settings)
    log("Downloader created in %.1fs" % (time.time() - t0))

    song = Song(
        name="Drake - Dust",
        artists=["Drake"],
        artist="Drake",
        genres=["rap"],
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
    log("song album_id empty string: %r (falsy but not None)" % song.album_id)
    log("song missing any of genres/disc_count/tracks_count/track_number/album_id/album_artist: %s"
        % any(x is None for x in [song.genres, song.disc_count, song.tracks_count,
                                   song.track_number, song.album_id, song.album_artist]))

    log("calling search_and_download")
    t1 = time.time()
    result = d.search_and_download(song)
    log("search_and_download returned in %.1fs" % (time.time() - t1))
    if result:
        s, p = result
        log("got song %r path %r" % (s.name, p))
        RESULT.write_text(
            '{"status":"ok","name":%r,"path":%r}' % (s.name, str(p)),
            encoding="utf-8",
        )
    else:
        log("no result")
        RESULT.write_text('{"status":"no_result"}', encoding="utf-8")
except Exception as exc:
    traceback.print_exc()
    RESULT.write_text('{"status":"error","error":%r}' % exc, encoding="utf-8")
log("done in %.1fs" % (time.time() - t0))
