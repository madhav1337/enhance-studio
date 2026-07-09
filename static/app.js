"use strict";

const PIPELINES = JSON.parse(document.getElementById("pipelines-data").textContent);

const els = {
  picker: document.getElementById("picker"),
  options: document.getElementById("options"),
  drop: document.getElementById("drop"),
  fileInput: document.getElementById("file-input"),
  folderInput: document.getElementById("folder-input"),
  browse: document.getElementById("browse"),
  browseFolder: document.getElementById("browse-folder"),
  resultsSection: document.getElementById("results-section"),
  results: document.getElementById("results"),
  downloadAll: document.getElementById("download-all"),
  clear: document.getElementById("clear"),
  batchBar: document.getElementById("batch-bar"),
  batchFill: document.getElementById("batch-fill"),
  batchLabel: document.getElementById("batch-label"),
};

let selected = null;          // pipeline id
let optionState = {};         // current option values for the selected pipeline
const outputs = [];           // { output_id, download_name } for successful results
let batchTotal = 0;           // images queued this session
let batchDone = 0;            // images finished (ok or failed)

// --------------------------------------------------------------------- picker
function renderPicker() {
  PIPELINES.forEach((p) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    card.dataset.id = p.id;
    card.innerHTML =
      (p.icon ? `<div class="cicon">${escapeHtml(p.icon)}</div>` : "") +
      `<div class="cname">${escapeHtml(p.name)}</div>` +
      `<div class="ctag">${escapeHtml(p.tagline)}</div>` +
      `<div class="cdesc">${escapeHtml(p.desc)}</div>`;
    card.addEventListener("click", () => selectPipeline(p.id));
    els.picker.appendChild(card);
  });
}

function selectPipeline(id) {
  selected = id;
  const p = PIPELINES.find((x) => x.id === id);
  document.querySelectorAll(".card").forEach((c) =>
    c.classList.toggle("selected", c.dataset.id === id));

  // reset option state to this pipeline's defaults
  optionState = {};
  (p.options || []).forEach((o) => { optionState[o.key] = o.default; });
  renderOptions(p);
  els.drop.classList.remove("disabled");
}

function renderOptions(p) {
  const opts = p.options || [];
  if (!opts.length) { els.options.hidden = true; els.options.innerHTML = ""; return; }
  els.options.hidden = false;
  els.options.innerHTML = "";

  opts.forEach((o) => {
    if (o.type === "checkbox") {
      const label = document.createElement("label");
      label.className = "row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!o.default;
      input.addEventListener("change", () => { optionState[o.key] = input.checked; });
      const text = document.createElement("div");
      text.innerHTML = `<div>${escapeHtml(o.label)}</div>` +
        (o.hint ? `<div class="hint">${escapeHtml(o.hint)}</div>` : "");
      label.append(input, text);
      els.options.appendChild(label);
    } else if (o.type === "radio") {
      const wrap = document.createElement("div");
      wrap.innerHTML = `<div class="opt-label">${escapeHtml(o.label)}</div>`;
      const chips = document.createElement("div");
      chips.className = "chips";
      o.choices.forEach((c) => {
        const chip = document.createElement("label");
        chip.className = "chip";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "opt_" + o.key;
        input.value = c.value;
        input.checked = c.value === o.default;
        input.addEventListener("change", () => { if (input.checked) optionState[o.key] = c.value; });
        const span = document.createElement("span");
        span.textContent = c.label;
        chip.append(input, span);
        chips.appendChild(chip);
      });
      wrap.appendChild(chips);
      els.options.appendChild(wrap);
    }
  });
}

// ------------------------------------------------------------------ dropzone
function wireDropzone() {
  els.browse.addEventListener("click", (e) => { e.stopPropagation(); els.fileInput.click(); });
  els.browseFolder.addEventListener("click", (e) => { e.stopPropagation(); els.folderInput.click(); });
  els.drop.addEventListener("click", () => els.fileInput.click());
  els.drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.fileInput.click(); }
  });
  els.fileInput.addEventListener("change", () => {
    addFiles(els.fileInput.files);
    els.fileInput.value = "";
  });
  els.folderInput.addEventListener("change", () => {
    addFiles(els.folderInput.files);
    els.folderInput.value = "";
  });
  ["dragenter", "dragover"].forEach((ev) =>
    els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.remove("drag"); }));
  els.drop.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
  });
}

function addFiles(fileList) {
  if (!selected) { selectPipeline(PIPELINES[0].id); }
  const files = Array.from(fileList).filter((f) => f.type.startsWith("image/") ||
    /\.(jpe?g|png|webp|tiff?|bmp)$/i.test(f.name));
  if (!files.length) return;
  els.resultsSection.hidden = false;
  batchTotal += files.length;
  updateBatch();
  files.forEach((file) => {
    const card = makeCardShell(file);
    els.results.prepend(card);
    enqueue(() => process(file, card));
  });
}

function updateBatch() {
  if (batchTotal === 0) { els.batchBar.hidden = true; return; }
  els.batchBar.hidden = false;
  const pct = Math.round((batchDone / batchTotal) * 100);
  els.batchFill.style.width = pct + "%";
  const verb = batchDone >= batchTotal ? "done" : "enhancing…";
  els.batchLabel.textContent = `${batchDone} / ${batchTotal} ${verb}`;
}

// -------------------------------------------------------------- process queue
let queue = Promise.resolve();
function enqueue(fn) { queue = queue.then(fn).catch((e) => console.error(e)); return queue; }

async function process(file, card) {
  const fd = new FormData();
  fd.append("pipeline", selected);
  Object.entries(optionState).forEach(([k, v]) =>
    fd.append(k, typeof v === "boolean" ? (v ? "true" : "false") : v));
  fd.append("file", file);
  try {
    const res = await fetch("/api/enhance", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || ("HTTP " + res.status));
    renderSuccess(card, file, data);
    outputs.push({ output_id: data.output_id, download_name: data.download_name });
    updateDownloadAll();
  } catch (err) {
    renderError(card, err.message || String(err));
  } finally {
    batchDone += 1;
    updateBatch();
  }
}

// --------------------------------------------------------------------- render
function makeCardShell(file) {
  const card = document.createElement("div");
  card.className = "result";
  card.innerHTML =
    `<div class="result-top">
       <div class="result-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
       <span class="badge">${escapeHtml(pipelineName(selected))}</span>
     </div>
     <div class="spinner"><div class="ring"></div><div>Enhancing…</div></div>`;
  return card;
}

function renderSuccess(card, file, data) {
  const i = data.info || {};
  const sizeStr = formatSizes(i);
  card.innerHTML =
    `<div class="result-top">
       <div class="result-name" title="${escapeHtml(data.original_name)}">${escapeHtml(data.original_name)}</div>
       <span class="result-meta">${escapeHtml(sizeStr)}</span>
     </div>
     <div class="cmp">
       <img class="before" src="${data.original_url}" alt="before">
       <img class="after" src="${data.enhanced_url}" alt="after">
       <span class="tag l">Before</span>
       <span class="tag r">After</span>
       <div class="handle"></div>
     </div>
     <div class="result-foot">
       <span class="method">${escapeHtml(i.method || "")} &middot; drag the slider to compare</span>
       <a class="btn small" href="/download/${encodeURIComponent(data.output_id)}?as=${encodeURIComponent(data.download_name)}">⬇ Download</a>
     </div>`;
  card.style.setProperty("--split", "50%");
  initCompare(card.querySelector(".cmp"));
}

function renderError(card, msg) {
  const top = card.querySelector(".result-top");
  if (top) top.querySelector(".badge, .result-meta")?.classList.add("err");
  const spin = card.querySelector(".spinner");
  if (spin) spin.replaceWith(Object.assign(document.createElement("div"),
    { className: "result-foot", innerHTML: `<span class="badge err">Failed</span><span class="method">${escapeHtml(msg)}</span>` }));
}

function initCompare(cmp) {
  let dragging = false;
  const set = (clientX) => {
    const r = cmp.getBoundingClientRect();
    let p = ((clientX - r.left) / r.width) * 100;
    p = Math.max(0, Math.min(100, p));
    cmp.style.setProperty("--split", p + "%");
  };
  cmp.addEventListener("pointerdown", (e) => { dragging = true; cmp.setPointerCapture(e.pointerId); set(e.clientX); });
  cmp.addEventListener("pointermove", (e) => { if (dragging) set(e.clientX); });
  cmp.addEventListener("pointerup", () => { dragging = false; });
  cmp.addEventListener("pointercancel", () => { dragging = false; });
}

// ------------------------------------------------------------- download-all
function updateDownloadAll() { els.downloadAll.disabled = outputs.length === 0; }

async function downloadAll() {
  if (!outputs.length) return;
  els.downloadAll.disabled = true;
  const prev = els.downloadAll.textContent;
  els.downloadAll.textContent = "Zipping…";
  try {
    const res = await fetch("/api/zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: outputs }),
    });
    if (!res.ok) throw new Error("zip failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "enhanced.zip";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Could not build ZIP: " + e.message);
  } finally {
    els.downloadAll.textContent = prev;
    els.downloadAll.disabled = false;
  }
}

function clearResults() {
  els.results.innerHTML = "";
  outputs.length = 0;
  batchTotal = 0; batchDone = 0;
  updateBatch();
  els.resultsSection.hidden = true;
  updateDownloadAll();
}

// -------------------------------------------------------------------- helpers
function pipelineName(id) { const p = PIPELINES.find((x) => x.id === id); return p ? p.name : id; }

function formatSizes(info) {
  const o = info.orig_size, u = info.out_size;
  if (o && u) return `${o[0]}×${o[1]} → ${u[0]}×${u[1]}`;
  if (u) return `${u[0]}×${u[1]}`;
  return "";
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ------------------------------------------------------------------------ init
renderPicker();
selectPipeline(PIPELINES[0].id);
wireDropzone();
els.downloadAll.addEventListener("click", downloadAll);
els.clear.addEventListener("click", clearResults);
