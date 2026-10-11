#!/usr/bin/env bash
set -euo pipefail
echo "=== YouTube-only retry of failed tracks ==="
echo "failed_search.txt:"
cat "C:/Users/admin/Desktop/Spotify_Liked_Songs_MP3/Spotify_Downloader_Retry/failed_search.txt"
echo "=== launch in spotidown env ==="
cd "C:/Users/admin/Documents/spotidown"
./env/Scripts/python -m spotdl download \
  --audio youtube \
  --format mp3 \
  --bitrate 320k \
  --threads 4 \
  --overwrite skip \
  --simple-tui \
  -- \
  $(cat "C:/Users/admin/Desktop/Spotify_Liked_Songs_MP3/Spotify_Downloader_Retry/failed_search.txt")
echo "=== retry complete ==="
