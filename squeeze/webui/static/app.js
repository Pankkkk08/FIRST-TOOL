/* Squeeze frontend. Talks to the Python backend via `pywebview.api.*`
 * (each call returns a Promise). Progress is polled every 300ms rather
 * than pushed — keeps this side to one loop instead of a second
 * communication channel back into the page. When running outside a real
 * pywebview window (e.g. this file opened directly for testing), a
 * small mock API is installed instead — see bottom of file.
 */

const NO_PROFILE = "(default)";
const CUSTOM_PRESET = "Custom (set below)";

const PROFILES_BY_CODEC = {
  libx264: [NO_PROFILE, "main", "high"],
  libx265: [NO_PROFILE, "main", "main10"],
  libsvtav1: [NO_PROFILE],
};
const SPEEDS_X26X = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"];
const SPEEDS_AV1 = Array.from({ length: 14 }, (_, i) => String(i));

let CAPS = null; // filled in by init() from get_capabilities()

// ---------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------

document.querySelectorAll(".tab-pill").forEach((pill) => {
  pill.addEventListener("click", () => {
    document.querySelectorAll(".tab-pill").forEach((p) => p.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    document.getElementById(`tab-${pill.dataset.tab}`).classList.add("active");
  });
});

// ---------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------

function basename(path) {
  return path.split(/[\\/]/).pop();
}

function el(id) {
  return document.getElementById(id);
}

function fillSelect(select, options) {
  select.innerHTML = "";
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = opt;
    o.textContent = opt;
    select.appendChild(o);
  }
}

/** Generic multi-select list backed by a Set of paths, rendered into a
 * <tbody> (table tabs) or <ul> (archive tab's plain file list).
 */
class Queue {
  constructor({ selectedClass = "selected" } = {}) {
    this.items = []; // ordered list of paths
    this.selected = new Set();
    this.selectedClass = selectedClass;
  }
  add(paths) {
    for (const p of paths) {
      if (!this.items.includes(p)) this.items.push(p);
    }
  }
  removeSelected() {
    this.items = this.items.filter((p) => !this.selected.has(p));
    this.selected.clear();
  }
  clear() {
    this.items = [];
    this.selected.clear();
  }
  toggleSelect(path, rowEl) {
    if (this.selected.has(path)) {
      this.selected.delete(path);
      rowEl.classList.remove(this.selectedClass);
    } else {
      this.selected.add(path);
      rowEl.classList.add(this.selectedClass);
    }
  }
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------

async function init() {
  CAPS = await window.pywebview.api.get_capabilities();
  setupVideoTab();
  setupPhotoTab();
  setupArchiveTab();
}

// ---------------------------------------------------------------------
// Video tab
// ---------------------------------------------------------------------

function setupVideoTab() {
  const queue = new Queue();
  const tbody = document.querySelector("#video-table tbody");

  const codecSelect = el("video-codec");
  const speedSelect = el("video-speed");
  const crfInput = el("video-crf");
  const profileSelect = el("video-profile");
  const presetSelect = el("video-preset");

  fillSelect(presetSelect, [CUSTOM_PRESET, ...Object.keys(CAPS.quality_presets)]);
  fillSelect(codecSelect, Object.keys(CAPS.video_codecs));
  fillSelect(speedSelect, SPEEDS_X26X);
  fillSelect(profileSelect, PROFILES_BY_CODEC[CAPS.video_codecs[codecSelect.value]]);

  if (!CAPS.ffmpeg_available) {
    el("video-warning").textContent =
      "ffmpeg/ffprobe not found on PATH — install ffmpeg to use this tab " +
      "(sudo apt install ffmpeg / brew install ffmpeg / ffmpeg.org).";
    el("video-add-files").disabled = true;
    el("video-start").disabled = true;
  }

  function onCodecChanged() {
    const codec = CAPS.video_codecs[codecSelect.value];
    fillSelect(speedSelect, codec === "libsvtav1" ? SPEEDS_AV1 : SPEEDS_X26X);
    speedSelect.value = codec === "libsvtav1" ? "6" : "medium";
    crfInput.value = { libx264: 23, libx265: 26, libsvtav1: 30 }[codec];
    fillSelect(profileSelect, PROFILES_BY_CODEC[codec]);
    profileSelect.value = NO_PROFILE;
  }
  codecSelect.addEventListener("change", onCodecChanged);

  presetSelect.addEventListener("change", () => {
    if (presetSelect.value === CUSTOM_PRESET) return;
    const preset = CAPS.quality_presets[presetSelect.value];
    const codecLabel = Object.keys(CAPS.video_codecs).find((k) => CAPS.video_codecs[k] === preset.codec);
    codecSelect.value = codecLabel;
    onCodecChanged();
    crfInput.value = preset.crf;
    speedSelect.value = preset.speed;
    profileSelect.value = preset.profile || NO_PROFILE;
  });

  function render() {
    tbody.innerHTML = "";
    for (const path of queue.items) {
      const tr = document.createElement("tr");
      tr.dataset.path = path;
      tr.innerHTML = `<td>${basename(path)}</td><td class="c-status">Queued</td><td class="c-progress"></td><td class="c-saved"></td>`;
      tr.addEventListener("click", () => queue.toggleSelect(path, tr));
      tbody.appendChild(tr);
    }
  }

  el("video-add-files").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_video_files());
    render();
  });
  el("video-add-folder").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_video_folder());
    render();
  });
  el("video-remove").addEventListener("click", () => { queue.removeSelected(); render(); });
  el("video-clear").addEventListener("click", () => { queue.clear(); render(); });
  el("video-browse").addEventListener("click", async () => {
    const dir = await window.pywebview.api.pick_output_folder();
    if (dir) el("video-outdir").value = dir;
  });

  const startBtn = el("video-start");
  const cancelBtn = el("video-cancel");
  const statusEl = el("video-status");
  let polling = null;

  startBtn.addEventListener("click", async () => {
    if (queue.items.length === 0) {
      alert("Add at least one video first.");
      return;
    }
    const options = {
      codec: CAPS.video_codecs[codecSelect.value],
      crf: crfInput.value,
      preset: speedSelect.value,
      profile: profileSelect.value === NO_PROFILE ? null : profileSelect.value,
      target_height: el("video-resolution").value ? Number(el("video-resolution").value) : null,
      audio_mode: el("video-audio").value,
      container: el("video-container").value,
      deinterlace: el("video-deinterlace").checked,
      output_dir: el("video-outdir").value,
    };
    const res = await window.pywebview.api.start_video_job(queue.items, options);
    if (!res.ok) { alert(res.error); return; }
    startBtn.disabled = true;
    cancelBtn.disabled = false;
    polling = setInterval(pollVideoStatus, 300);
  });

  cancelBtn.addEventListener("click", () => window.pywebview.api.cancel_video_job());

  async function pollVideoStatus() {
    const s = await window.pywebview.api.get_video_status();
    for (const row of s.rows) {
      const tr = tbody.querySelector(`tr[data-path="${CSS.escape(row.key)}"]`);
      if (!tr) continue;
      tr.querySelector(".c-status").textContent = row.status;
      tr.querySelector(".c-progress").textContent = row.progress;
      tr.querySelector(".c-saved").textContent = row.saved;
      tr.classList.toggle("row-done", row.status === "Done");
      tr.classList.toggle("row-failed", row.status === "Failed");
      tr.classList.toggle("row-cancelled", row.status === "Cancelled");
    }
    statusEl.textContent = s.overall;
    if (!s.running) {
      clearInterval(polling);
      startBtn.disabled = false;
      cancelBtn.disabled = true;
    }
  }

  render();
}

// ---------------------------------------------------------------------
// Photo tab
// ---------------------------------------------------------------------

function setupPhotoTab() {
  const queue = new Queue();
  const tbody = document.querySelector("#photo-table tbody");
  fillSelect(el("photo-resize"), CAPS.max_dimension_choices);

  function render() {
    tbody.innerHTML = "";
    for (const path of queue.items) {
      const tr = document.createElement("tr");
      tr.dataset.path = path;
      tr.innerHTML = `<td>${basename(path)}</td><td class="c-status">Queued</td><td class="c-saved"></td>`;
      tr.addEventListener("click", () => queue.toggleSelect(path, tr));
      tbody.appendChild(tr);
    }
  }

  el("photo-add-files").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_photo_files());
    render();
  });
  el("photo-add-folder").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_photo_folder());
    render();
  });
  el("photo-remove").addEventListener("click", () => { queue.removeSelected(); render(); });
  el("photo-clear").addEventListener("click", () => { queue.clear(); render(); });
  el("photo-browse").addEventListener("click", async () => {
    const dir = await window.pywebview.api.pick_output_folder();
    if (dir) el("photo-outdir").value = dir;
  });

  const startBtn = el("photo-start");
  const cancelBtn = el("photo-cancel");
  const statusEl = el("photo-status");
  let polling = null;

  startBtn.addEventListener("click", async () => {
    if (queue.items.length === 0) {
      alert("Add at least one photo first.");
      return;
    }
    const options = {
      quality: el("photo-quality").value,
      resize: el("photo-resize").value,
      output_format: el("photo-format").value,
      strip_metadata: el("photo-strip-meta").checked,
      output_dir: el("photo-outdir").value,
    };
    const res = await window.pywebview.api.start_photo_job(queue.items, options);
    if (!res.ok) { alert(res.error); return; }
    startBtn.disabled = true;
    cancelBtn.disabled = false;
    polling = setInterval(pollPhotoStatus, 300);
  });

  cancelBtn.addEventListener("click", () => window.pywebview.api.cancel_photo_job());

  async function pollPhotoStatus() {
    const s = await window.pywebview.api.get_photo_status();
    for (const row of s.rows) {
      const tr = tbody.querySelector(`tr[data-path="${CSS.escape(row.key)}"]`);
      if (!tr) continue;
      tr.querySelector(".c-status").textContent = row.status;
      tr.querySelector(".c-saved").textContent = row.saved;
      tr.classList.toggle("row-done", row.status === "Done");
      tr.classList.toggle("row-failed", row.status === "Failed");
    }
    statusEl.textContent = s.overall;
    if (!s.running) {
      clearInterval(polling);
      startBtn.disabled = false;
      cancelBtn.disabled = true;
    }
  }

  render();
}

// ---------------------------------------------------------------------
// Archive tab
// ---------------------------------------------------------------------

function setupArchiveTab() {
  const queue = new Queue();
  const listEl = el("archive-list");
  fillSelect(el("archive-format"), CAPS.archive_formats);

  let mode = "bundle";
  const bundleBtn = el("archive-mode-bundle");
  const gzipBtn = el("archive-mode-gzip");
  function setMode(m) {
    mode = m;
    bundleBtn.classList.toggle("active", m === "bundle");
    gzipBtn.classList.toggle("active", m === "gzip");
    // Compression level applies in both modes (zip/tar level, or gzip
    // level); only the archive-format choice is bundle-only.
    el("archive-format").disabled = m !== "bundle";
  }
  bundleBtn.addEventListener("click", () => setMode("bundle"));
  gzipBtn.addEventListener("click", () => setMode("gzip"));

  el("archive-level").addEventListener("input", (e) => {
    el("archive-level-value").textContent = e.target.value;
  });

  function render() {
    listEl.innerHTML = "";
    for (const path of queue.items) {
      const li = document.createElement("li");
      li.dataset.path = path;
      li.textContent = path;
      li.addEventListener("click", () => queue.toggleSelect(path, li));
      listEl.appendChild(li);
    }
  }

  el("archive-add-files").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_archive_files());
    render();
  });
  el("archive-add-folder").addEventListener("click", async () => {
    queue.add(await window.pywebview.api.pick_archive_folder());
    render();
  });
  el("archive-remove").addEventListener("click", () => { queue.removeSelected(); render(); });
  el("archive-clear").addEventListener("click", () => { queue.clear(); render(); });
  el("archive-browse").addEventListener("click", async () => {
    const dir = await window.pywebview.api.pick_output_folder();
    if (dir) el("archive-outdir").value = dir;
  });

  const startBtn = el("archive-start");
  const cancelBtn = el("archive-cancel");
  const statusEl = el("archive-status");
  let polling = null;

  startBtn.addEventListener("click", async () => {
    if (queue.items.length === 0) {
      alert("Add at least one file or folder first.");
      return;
    }
    const options = {
      format_label: el("archive-format").value,
      level: el("archive-level").value,
      output_dir: el("archive-outdir").value,
    };
    const api = mode === "bundle" ? window.pywebview.api.start_archive_bundle_job : window.pywebview.api.start_archive_gzip_job;
    const res = await api(queue.items, options);
    if (!res.ok) { alert(res.error); return; }
    startBtn.disabled = true;
    cancelBtn.disabled = false;
    polling = setInterval(pollArchiveStatus, 300);
  });

  cancelBtn.addEventListener("click", () => {
    const api = mode === "bundle" ? window.pywebview.api.cancel_archive_bundle_job : window.pywebview.api.cancel_archive_gzip_job;
    api();
  });

  async function pollArchiveStatus() {
    const api = mode === "bundle" ? window.pywebview.api.get_archive_bundle_status : window.pywebview.api.get_archive_gzip_status;
    const s = await api();
    // gzip mode's Runner also tracks a per-file `rows` breakdown, but the
    // archive tab's file list is a plain <ul> (files/folders can be
    // dropped in ad hoc, unlike the video/photo queues' fixed columns) —
    // the overall "Compressing… 2/5" text is enough here.
    statusEl.textContent = s.overall;
    if (!s.running) {
      clearInterval(polling);
      startBtn.disabled = false;
      cancelBtn.disabled = true;
    }
  }

  render();
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------

if (window.pywebview) {
  init();
} else {
  // Running outside a real pywebview window (e.g. opened directly in a
  // browser for frontend testing). pywebviewready fires once the real
  // bridge is injected; if it never will be (no bridge present at all),
  // this is a no-op and the page just won't be interactive.
  window.addEventListener("pywebviewready", init);
}
