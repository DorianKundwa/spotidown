"""Local web interface for the Spotify downloader.

Serves the UI from web/ and a small JSON API. Listens on 127.0.0.1 only, and
rejects cross-site requests so other websites cannot start downloads.
"""

import os
import socket
import sys
import threading
import uuid
import webbrowser

from flask import Flask, abort, jsonify, request, send_from_directory

import spotify_downloader as engine

WEB_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "web")
PREFERRED_PORT = 8765

app = Flask(__name__, static_folder=None)
PORT = PREFERRED_PORT
_state_lock = threading.Lock()
_current_job = None


class Job:
    """One download. Engine callbacks write here; the API reads snapshots."""

    def __init__(self, url, format_label, template_label):
        self.id = uuid.uuid4().hex
        self.url = url
        self.format_label = format_label
        self.template_label = template_label
        self.status = "running"  # running | finished | failed | stopped
        self.done = 0
        self.total = 0  # unknown until spotDL reports the playlist size
        self.log_lines = []
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

    def add_log(self, text):
        with self.lock:
            self.log_lines.append(text)

    def set_progress(self, done, total):
        with self.lock:
            self.done, self.total = done, total

    def snapshot(self, after):
        with self.lock:
            return {
                "id": self.id,
                "status": self.status,
                "done": self.done,
                "total": self.total,
                "log": self.log_lines[after:],
                "next": len(self.log_lines),
            }

    def is_running(self):
        with self.lock:
            return self.status == "running"


def _run_job(job):
    try:
        ok = engine.run_download_job(
            job.url, engine.output_directory(), job.format_label, job.template_label,
            job.add_log, job.set_progress, job.cancel_event)
        outcome = "stopped" if job.cancel_event.is_set() else ("finished" if ok else "failed")
    except Exception as exc:  # report unexpected errors in the UI instead of dying silently
        job.add_log(f"[X] Unexpected error: {exc}")
        outcome = "failed"
    with job.lock:
        job.status = outcome


def start_job(url, format_label, template_label):
    """Start a download unless one is already running. Returns the Job or None."""
    global _current_job
    with _state_lock:
        if _current_job is not None and _current_job.is_running():
            return None
        job = Job(url, format_label, template_label)
        _current_job = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return job


def _job_by_id(job_id):
    with _state_lock:
        job = _current_job
    if job is None or job.id != job_id:
        abort(404)
    return job


def _allowed_hosts():
    return {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@app.before_request
def _check_request_origin():
    """Block DNS-rebinding and cross-site requests. Only the local app may call the API."""
    if request.host not in _allowed_hosts():
        abort(403)
    if request.method != "GET":
        origin = request.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in _allowed_hosts()}:
            abort(403)


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html", max_age=0)


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(WEB_DIR, filename, max_age=0)


@app.get("/api/options")
def options():
    settings = engine.load_settings()
    saved_format = settings.get("format")
    saved_template = settings.get("template")
    return jsonify({
        "formats": list(engine.AUDIO_FORMATS),
        "templates": list(engine.FILENAME_TEMPLATES),
        "format": saved_format if saved_format in engine.AUDIO_FORMATS else engine.DEFAULT_FORMAT,
        "template": saved_template if saved_template in engine.FILENAME_TEMPLATES else engine.DEFAULT_TEMPLATE,
        "output_dir": engine.output_directory(),
        "parallel_downloads": engine.PARALLEL_DOWNLOADS,
    })


@app.post("/api/jobs")
def create_job():
    body = request.get_json(silent=True) or {}
    url = engine.validate_spotify_link(str(body.get("url", "")))
    if url is None:
        return jsonify({"error": "That is not a valid Spotify playlist or song link."}), 400
    format_label = body.get("format")
    template_label = body.get("template")
    if format_label not in engine.AUDIO_FORMATS or template_label not in engine.FILENAME_TEMPLATES:
        return jsonify({"error": "Unknown format or file name option."}), 400
    job = start_job(url, format_label, template_label)
    if job is None:
        return jsonify({"error": "A download is already running. Stop it or wait for it to finish."}), 409
    warning = None
    if not engine.save_settings({"format": format_label, "template": template_label}):
        warning = "Could not save your format and file name choices."
    return jsonify({"id": job.id, "warning": warning}), 201


@app.get("/api/jobs/current")
def current_job():
    with _state_lock:
        job = _current_job
    if job is None:
        return jsonify({"id": None})
    return jsonify({"id": job.id, "running": job.is_running()})


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    job = _job_by_id(job_id)
    try:
        after = max(0, int(request.args.get("after", 0)))
    except ValueError:
        abort(400)
    return jsonify(job.snapshot(after))


@app.post("/api/jobs/<job_id>/stop")
def stop_job(job_id):
    job = _job_by_id(job_id)
    if not job.is_running():
        return jsonify({"status": job.status})
    job.cancel_event.set()
    return jsonify({"status": "stopping"})


@app.post("/api/open-folder")
def open_folder():
    folder = engine.output_directory()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return jsonify({"error": f"Could not create {folder}: {exc}"}), 500
    if os.name != "nt":
        return jsonify({"error": "Opening folders is only supported on Windows."}), 501
    os.startfile(folder)  # Windows-only; guarded above
    return jsonify({"path": folder})


def find_free_port(preferred):
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(f"No free port found between {preferred} and {preferred + 19}.")


def run_server(open_browser=True):
    global PORT
    PORT = find_free_port(PREFERRED_PORT)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Spotify Downloader is running at {url}  (press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)
