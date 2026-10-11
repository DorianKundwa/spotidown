# SpotiDown

A Spotify playlist and track downloader powered by `spotDL` with a modern web interface and local engine.

## Features

- **Web UI & Local API**: Clean browser interface served via Flask at `http://127.0.0.1:8765`.
- **Format Options**:
  - MP3 (320 kbps)
  - M4A (256 kbps)
  - Opus (256 kbps)
  - FLAC (Lossless)
  - WAV (Lossless)
- **Customizable Naming Templates**:
  - `Artist - Song`
  - `Song - Artist`
  - `Song only`
  - `Numbered (playlist order)`
- **Robust Queue & Process Control**: Automatic retries, stall detection, and cancel support.
- **Standalone Packaging**: PyInstaller spec provided for single-executable builds.

## Requirements

- Python 3.10+
- FFmpeg installed and available on PATH
- Dependencies:
  ```bash
  pip install -r requirements.txt
  ```

## Running the Web UI

```bash
python web_server.py
```
This starts the local web server and opens the browser interface automatically.
