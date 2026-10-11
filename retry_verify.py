#!/usr/bin/env python3
"""
Verify the retry now that the Spotify rate limit has lifted.
Read failed_search.txt and print it clearly so we can confirm
which tracks are queued, then launch a YouTube-only retry and
capture per-track progress/outcomes.
"""
import subprocess
import sys
import pathlib
import time

RETRY_DIR = pathlib.Path("C:/Users/admin/Desktop/Spotify_Liked_Songs_MP3/Spotify_Downloader_Retry")
FAILED_LIST = RETRY_DIR / "failed_search.txt"

def main() -> None:
    print("=== retry verify ===")
    print("folder:", RETRY_DIR)
    print("exists:", RETRY_DIR.exists())
    if not FAILED_LIST.exists():
        print("failed_search.txt missing:", FAILED_LIST)
        sys.exit(1)
    contents = FAILED_LIST.read_text(encoding="utf-8").strip()
    print("=== failed_search.txt contents ===")
    print(contents)
    if not contents:
        print("failed_search.txt is empty; nothing queued for retry")
        sys.exit(0)
    lines = [ln.strip() for ln in contents.splitlines() if ln.strip()]
    print("=== queued track count ===", len(lines))

if __name__ == "__main__":
    main()
