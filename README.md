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

## Quick Start & Launcher

You can start both the backend API and the frontend web interface with the launcher:

### 1. Windows 1-Click Launch
Double-click `launch.bat` or run:
```cmd
launch.bat
```

### 2. Cross-Platform Python Launcher
```bash
python launcher.py
```
> **Tip**: If you have multiple Python versions installed, the launcher automatically selects Python 3.10+ (e.g. `py -3.12 launcher.py`).

### 3. PowerShell
```powershell
.\launch.ps1
```

### Launcher CLI Options
- `--no-browser`: Start the server without opening the default web browser.
- `--port <PORT>`: Specify a custom port (default: `8765`).
- `--check-only`: Perform environment and dependency checks without starting the server.
- `--auto-install`: Automatically install any missing requirements.

