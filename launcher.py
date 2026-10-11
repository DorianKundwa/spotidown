#!/usr/bin/env python3
"""SpotiDown Launcher

Unified launcher to start SpotiDown's backend (Flask API + spotDL download engine)
and frontend (web application).

Features:
- Automatic Python version check (requires Python 3.10+) with auto-re-execution on newer Python if available
- Dependency verification (Flask, spotDL, FFmpeg)
- Automated browser launch for frontend UI
- Graceful shutdown handling
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

MIN_PYTHON_VERSION = (3, 10)
BANNER = r"""
  ____              _   _ ____                      
 / ___| _ __   ___ | |_(_)  _ \  _____      ___ __  
 \___ \| '_ \ / _ \| __| | | | |/ _ \ \ /\ / / '_ \ 
  ___) | |_) | (_) | |_| | |_| | (_) \ V  V /| | | |
 |____/| .__/ \___/ \__|_|____/ \___/ \_/\_/ |_| |_|
       |_|                                          
"""

# Ensure UTF-8 output on Windows consoles if possible
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Color helpers
USE_COLOR = os.isatty(sys.stdout.fileno()) if hasattr(sys.stdout, "fileno") else True
GREEN = "\033[92m" if USE_COLOR else ""
CYAN = "\033[96m" if USE_COLOR else ""
YELLOW = "\033[93m" if USE_COLOR else ""
RED = "\033[91m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


def log_ok(msg):
    print(f" {GREEN}[OK]{RESET} {msg}")


def log_info(msg):
    print(f" {CYAN}[*]{RESET} {msg}")


def log_warn(msg):
    print(f" {YELLOW}[!]{RESET} {msg}")


def log_err(msg):
    print(f" {RED}[X]{RESET} {msg}")


def try_find_modern_python():
    """Try to find a Python >= 3.10 interpreter.
    
    Prefers an interpreter that already has flask and spotdl installed.
    """
    candidates = [
        ["py", "-3.12"],
        ["py", "-3.11"],
        ["py", "-3.10"],
        ["py", "-3.13"],
        ["py", "-3.14"],
        ["py", "-3"],
        ["python3.12"],
        ["python3.11"],
        ["python3.10"],
        ["python3"],
    ]

    # First pass: look for modern Python with dependencies already installed
    for cmd in candidates:
        try:
            res = subprocess.run(
                [*cmd, "-c", "import sys, flask, spotdl; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                parts = [int(p) for p in res.stdout.strip().split(".")[:2]]
                if tuple(parts) >= MIN_PYTHON_VERSION:
                    return cmd
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            continue

    # Second pass: any modern Python >= 3.10
    for cmd in candidates:
        try:
            res = subprocess.run(
                [*cmd, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                parts = [int(p) for p in res.stdout.strip().split(".")[:2]]
                if tuple(parts) >= MIN_PYTHON_VERSION:
                    return cmd
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            continue
    return None


def ensure_python_version():
    """Ensure we are running on Python 3.10+; auto-reexec if an older Python started us."""
    if sys.version_info >= MIN_PYTHON_VERSION:
        return

    modern_py = try_find_modern_python()
    if modern_py:
        print(f"Current Python ({sys.version.split()[0]}) is too old. Switching to {' '.join(modern_py)}...")
        try:
            proc = subprocess.run([*modern_py, os.path.abspath(__file__), *sys.argv[1:]])
            sys.exit(proc.returncode)
        except Exception as exc:
            print(f"Failed to re-launch: {exc}")
            sys.exit(1)

    log_err(
        f"Python {sys.version.split()[0]} is unsupported. SpotiDown requires Python 3.10 or newer."
    )
    print("Please install Python 3.10+ from https://www.python.org/ or run with: py -3.12 launcher.py")
    sys.exit(1)


def check_dependencies(auto_install=False, check_only=False):
    """Verify that required Python packages are installed."""
    missing = []
    try:
        import flask
    except ImportError:
        missing.append("flask")

    try:
        import spotdl
    except ImportError:
        missing.append("spotdl")

    if not missing:
        return True

    log_warn(f"Missing required Python dependencies: {', '.join(missing)}")
    if check_only:
        return False

    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    should_install = auto_install

    if not should_install and sys.stdin.isatty():
        try:
            ans = input("Install missing dependencies now? [Y/n]: ").strip().lower()
            should_install = ans in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            should_install = False

    if should_install:
        log_info("Installing dependencies via pip...")
        target = ["-r", req_file] if os.path.isfile(req_file) else missing
        cmd = [sys.executable, "-m", "pip", "install", *target]
        ret = subprocess.run(cmd).returncode
        if ret == 0:
            log_ok("Dependencies installed successfully.")
            return True
        log_err("Failed to install dependencies.")
        return False
    return False


def check_ffmpeg():
    """Verify FFmpeg availability."""
    if shutil.which("ffmpeg"):
        return True
    log_warn("FFmpeg was not detected on your system PATH.")
    print("      spotDL uses FFmpeg for audio conversion and metadata tagging.")
    print("      Please install FFmpeg or place ffmpeg.exe in your PATH if conversions fail.")
    return False


def main():
    ensure_python_version()

    parser = argparse.ArgumentParser(description="SpotiDown Launcher (Backend & Frontend)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the web browser")
    parser.add_argument("--check-only", action="store_true", help="Only check requirements and exit")
    parser.add_argument("--auto-install", action="store_true", help="Automatically install missing dependencies")
    parser.add_argument("--port", type=int, default=None, help="Preferred port for backend server (default: 8765)")
    args = parser.parse_args()

    # Clear terminal title / header if on Windows
    if os.name == "nt":
        os.system("title SpotiDown Launcher")

    print(f"{CYAN}{BANNER}{RESET}")
    print(f"{BOLD}SpotiDown Full-Stack Launcher{RESET} {DIM}(Backend API + Frontend Web UI){RESET}")
    print("-" * 55)

    # 1. Environment Checks
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    log_ok(f"Python Runtime: {BOLD}{py_ver}{RESET}")

    if not check_dependencies(auto_install=args.auto_install, check_only=args.check_only):
        sys.exit(1)
    log_ok("Python Dependencies: Flask & spotDL ready")

    has_ffmpeg = check_ffmpeg()
    if has_ffmpeg:
        log_ok("Audio Processor: FFmpeg detected on PATH")

    if args.check_only:
        print("\nAll pre-flight checks completed.")
        sys.exit(0)

    # 2. Import application modules
    import spotify_downloader as engine
    import web_server

    if args.port:
        web_server.PREFERRED_PORT = args.port

    output_dir = engine.output_directory()
    log_ok(f"Download Directory: {output_dir}")

    print("-" * 55)
    log_info("Starting Backend Server (Flask REST API + spotDL worker pool)...")
    log_info("Preparing Frontend Web Interface (HTML5 / Vanilla CSS / JS)...")

    # Determine free port and prepare URL
    port = web_server.find_free_port(web_server.PREFERRED_PORT)
    web_server.PORT = port
    app_url = f"http://127.0.0.1:{port}/"

    print(f"\n {GREEN}{BOLD}>>> SpotiDown is LIVE! <<<{RESET}")
    print(f" {BOLD}Frontend Interface:{RESET} {CYAN}{app_url}{RESET}")
    print(f" {BOLD}Backend API:{RESET}        {CYAN}{app_url}api/options{RESET}")
    print(f" {DIM}Press Ctrl+C in this window at any time to stop the server.{RESET}\n")

    # 3. Launch Frontend in browser
    if not args.no_browser:
        log_info(f"Opening {app_url} in your default browser...")
        threading.Timer(0.8, webbrowser.open, args=(app_url,)).start()

    # 4. Run Backend Server
    try:
        web_server.app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[*] Shutting down SpotiDown launcher gracefully... Goodbye!{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
