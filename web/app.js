(() => {
  // Same rule as the server (spotify_downloader.SPOTIFY_LINK_PATTERN); the server still validates.
  const LINK_PATTERN = /^(?:(?:https?:\/\/)?(?:www\.)?open\.spotify\.com\/(?:intl-[a-z]{2}\/)?|spotify:)(playlist|track)[\/:]([A-Za-z0-9]{22})(?:[\/?#]\S*)?$/i;
  const POLL_MS = 700;
  const TOAST_MS = 6000;
  const LOG_CLASSES = [
    [/\bFAIL\b|\[X\]|LookupError|\bError\b/, "fail"],
    [/\bDONE\b/, "done"],
    [/\bSKIP\b/, "skip"],
    [/\[!\]/, "warn"],
  ];

  const $ = (id) => document.getElementById(id);
  const els = {
    link: $("link"),
    paste: $("paste"),
    hint: $("hint"),
    format: $("format"),
    template: $("template"),
    start: $("start"),
    stop: $("stop"),
    openFolder: $("open-folder"),
    clearLog: $("clear-log"),
    log: $("log"),
    progressFill: $("progress-fill"),
    progressText: $("progress-text"),
    progressPercent: $("progress-percent"),
    progressBar: document.querySelector(".bar"),
    pill: $("status-pill"),
    outputDir: $("output-dir"),
    toast: $("toast"),
  };

  let jobId = null;
  let after = 0;
  let timer = null;
  let toastTimer = null;

  function setPill(kind, text) {
    els.pill.className = `pill ${kind}`;
    els.pill.textContent = text;
  }

  function toast(message, kind = "error") {
    els.toast.textContent = message;
    els.toast.className = `toast ${kind === "warn" ? "warn" : ""}`;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, TOAST_MS);
  }

  function setHint(message, kind) {
    els.hint.textContent = message;
    els.hint.className = `hint ${kind || ""}`;
  }

  function cleanLink(raw) {
    return raw.trim().replace(/^["']+|["']+$/g, "");
  }

  function validateLink() {
    const raw = cleanLink(els.link.value);
    if (!raw) {
      setHint("", "");
      return false;
    }
    if (LINK_PATTERN.test(raw)) {
      setHint("Looks good.", "ok");
      return true;
    }
    setHint("That is not a Spotify playlist or song link.", "bad");
    return false;
  }

  function setBusy(busy) {
    els.start.disabled = busy;
    els.stop.disabled = !busy;
    els.link.disabled = busy;
    els.format.disabled = busy;
    els.template.disabled = busy;
  }

  function fillSelect(select, values, selected) {
    select.replaceChildren(...values.map((value) => new Option(value, value, false, value === selected)));
  }

  function appendLog(text) {
    const line = document.createElement("div");
    line.className = "line";
    const match = LOG_CLASSES.find(([pattern]) => pattern.test(text));
    if (match) line.classList.add(match[1]);
    line.textContent = text;
    const nearBottom = els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 40;
    els.log.appendChild(line);
    if (nearBottom) els.log.scrollTop = els.log.scrollHeight;
  }

  function updateProgress(done, total) {
    if (total <= 0) {
      els.progressFill.style.width = "0%";
      els.progressText.textContent = "Preparing...";
      els.progressPercent.textContent = "";
      els.progressBar.setAttribute("aria-valuenow", "0");
      return;
    }
    const percent = Math.min(100, Math.round((done / total) * 100));
    els.progressFill.style.width = `${percent}%`;
    els.progressText.textContent = `${done.toLocaleString()} of ${total.toLocaleString()} tracks`;
    els.progressPercent.textContent = `${percent}%`;
    els.progressBar.setAttribute("aria-valuenow", String(percent));
  }

  function schedulePoll(delay = POLL_MS) {
    clearTimeout(timer);
    timer = setTimeout(poll, delay);
  }

  function finish(status) {
    clearTimeout(timer);
    jobId = null;
    setBusy(false);
    if (status === "finished") {
      setPill("done", "Done");
      toast("Download finished. Files are in the output folder.", "warn");
    } else if (status === "stopped") {
      setPill("stopped", "Stopped");
    } else {
      setPill("failed", "Finished with errors");
      toast("The download finished with errors. See the log.");
    }
  }

  async function poll() {
    if (!jobId) return;
    try {
      const response = await fetch(`/api/jobs/${jobId}?after=${after}`, { cache: "no-store" });
      if (response.status === 404) {
        setPill("failed", "Lost job");
        finish("failed");
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      data.log.forEach(appendLog);
      after = data.next;
      updateProgress(data.done, data.total);
      if (data.status === "running") {
        setPill("running", "Running");
        schedulePoll();
      } else {
        finish(data.status);
      }
    } catch (error) {
      setPill("stopped", "Connection lost");
      schedulePoll(2000);
    }
  }

  async function startDownload() {
    if (!validateLink()) {
      toast("Paste a valid Spotify playlist or song link first.");
      els.link.focus();
      return;
    }
    els.log.replaceChildren();
    after = 0;
    updateProgress(0, 0);
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: cleanLink(els.link.value),
          format: els.format.value,
          template: els.template.value,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast(data.error || "Could not start the download.");
        return;
      }
      if (data.warning) toast(data.warning, "warn");
      jobId = data.id;
      setBusy(true);
      setPill("running", "Running");
      schedulePoll(0);
    } catch (error) {
      toast("Could not reach the downloader. Is it still running?");
    }
  }

  async function stopDownload() {
    if (!jobId) return;
    els.stop.disabled = true;
    setPill("stopped", "Stopping...");
    try {
      const response = await fetch(`/api/jobs/${jobId}/stop`, { method: "POST" });
      if (!response.ok) toast("Could not stop the download.");
    } catch (error) {
      toast("Could not reach the downloader to stop it.");
    }
  }

  async function openFolder() {
    try {
      const response = await fetch("/api/open-folder", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) toast(data.error || "Could not open the folder.");
    } catch (error) {
      toast("Could not reach the downloader.");
    }
  }

  async function init() {
    const response = await fetch("/api/options", { cache: "no-store" });
    const options = await response.json();
    fillSelect(els.format, options.formats, options.format);
    fillSelect(els.template, options.templates, options.template);
    els.outputDir.textContent = options.output_dir;

    // Reconnect to a download that is still running, e.g. after a page reload.
    const current = await (await fetch("/api/jobs/current", { cache: "no-store" })).json();
    if (current.id && current.running) {
      jobId = current.id;
      after = 0;
      setBusy(true);
      setPill("running", "Running");
      schedulePoll(0);
    } else {
      setPill("idle", "Idle");
      updateProgress(0, 0);
      els.progressText.textContent = "Waiting for a link";
    }
  }

  els.link.addEventListener("input", validateLink);
  els.link.addEventListener("keydown", (event) => {
    if (event.key === "Enter") startDownload();
  });
  els.paste.addEventListener("click", async () => {
    try {
      els.link.value = await navigator.clipboard.readText();
      validateLink();
    } catch (error) {
      toast("Clipboard access was blocked. Paste the link with Ctrl+V.");
    }
  });
  els.start.addEventListener("click", startDownload);
  els.stop.addEventListener("click", stopDownload);
  els.openFolder.addEventListener("click", openFolder);
  els.clearLog.addEventListener("click", () => els.log.replaceChildren());

  init().catch(() => toast("Could not load the downloader. Restart the app and reload this page."));
})();
