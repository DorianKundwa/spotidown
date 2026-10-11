#!/usr/bin/env python3
"""
Retry the failed tracks using YouTube search only (no Spotify API calls),
so the Spotify rate limit cannot block it.

We launch a child script in the spotidown venv that imports spotdl's
Downloader and feeds fully-populated Song objects (all metadata fields set)
so the Spotify lookup path is skipped entirely. It searches YouTube and
downloads without touching the Spotify API.

Outcome files in the retry folder:
- retry_youtube_only.log
- retry_youtube_result.json
"""
from __future__ import annotations

import pathlib
import shlex
import subprocess
import sys
import time

RETRY_DIR = pathlib.Path(
    "C:/Users/admin/Desktop/Spotify_Liked_Songs_MP3/Spotify_Downloader_Retry"
)
FAILED_LIST = RETRY_DIR / "failed_search.txt"
LOG_PATH = RETRY_DIR / "retry_youtube_only.log"
RESULT_PATH = RETRY_DIR / "retry_youtube_result.json"

SPOTIDDOWN_DIR = pathlib.Path("C:/Users/admin/Documents/spotidown")
SPOTIDOWN_PY = SPOTIDDOWN_DIR / "env" / "Scripts" / "python.exe"

OUT_DIR = RETRY_DIR / "yt_retry_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHILD_SCRIPT = RETRY_DIR / "retry_youtube_child.py"


def log(text: str) -> None:
    ts = time.strftime("%T")
    line = f"[{ts}] {text}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    except OSError as exc:
        print(f"[!] Could not write log: {exc}")


def main() -> None:
    log("=== YouTube-only retry starting ===")
    if not FAILED_LIST.exists():
        log(f"failed_search.txt missing: {FAILED_LIST}")
        sys.exit(1)

    contents = FAILED_LIST.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in contents.splitlines() if ln.strip()]
    if not lines:
        log("failed_search.txt is empty; nothing queued for retry")
        sys.exit(0)

    log(f"queued track count: {len(lines)}")
    for idx, track in enumerate(lines, start=1):
        log(f"[{idx}/{len(lines)}] {shlex.quote(track)}")

    log("output folder: " + str(OUT_DIR))
    log("child script: " + str(CHILD_SCRIPT))
    log("spotdl Python path: " + str(SPOTIDOWN_PY))

    if not CHILD_SCRIPT.exists():
        log(f"[X] child script missing: {CHILD_SCRIPT}")
        sys.exit(2)

    args = [
        str(SPOTIDOWN_PY),
        str(CHILD_SCRIPT),
        str(OUT_DIR),
        str(FAILED_LIST),
        str(RESULT_PATH),
        str(LOG_PATH),
        "4",
        "180",
    ]

    log("launching child: " + shlex.join(args))
    t0 = time.time()
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(SPOTIDDOWN_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for raw in proc.stdout:
            stripped = raw.rstrip("\n")
            if stripped:
                log(stripped)
    except FileNotFoundError as exc:
        log(f"[X] child launch failed (python not found): {exc}")
        sys.exit(3)
    except OSError as exc:
        log(f"[X] child launch failed: {exc}")
        sys.exit(4)

    if proc.returncode is None:
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    elapsed = time.time() - t0
    exit_code = proc.returncode
    log(f"=== child exited: code {exit_code}, elapsed {elapsed:.0f}s ===")
    summarise()


def summarise() -> None:
    log("=== outcome summary ===")
    if not RESULT_PATH.exists():
        log(f"no result file: {RESULT_PATH}")
        log("check retry_youtube_only.log for details")
        return

    data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    if "error" in data:
        log(f"[X] child error: {data['error']}")
        return

    queued = data.get("queued", 0)
    downloaded = data.get("downloaded", 0)
    failed = data.get("failed", 0)
    log(f"queued: {queued}")
    log(f"downloaded: {downloaded}")
    log(f"failed: {failed}")
    results = data.get("results", [])
    if results:
        log("=== downloaded ===")
        for r in results:
            if r["status"] == "downloaded":
                log(f"- {r['query']} -> {r['path']}")
        log("=== still failed ===")
        for r in results:
            if r["status"] != "downloaded":
                log(f"- {r['query']} : {r['status']}")
    log("=== end summary ===")


if __name__ == "__main__":
    import json
    main()
