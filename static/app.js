"use strict";
// Pixel Drip window: builds the controls, asks the server for previews, runs exports.

const $ = (id) => document.getElementById(id);
const pct = (v) => Math.round(v * 100) + "%";

const PRESETS = [
  { name: "Blush Melt", p: {} },
  { name: "Palm Drip", p: { hi: 0.7, width: 4, length: 0.45, overflow: 0.9, fringe: 4, wash: 0.9, color: 0.2, edge: 0.08 } },
  { name: "Selarón Smear", p: { direction: "right", wash: 0, hi: 0.9, edge: 0.12, width: 5, length: 0.7, fringe: 0 } },
  { name: "Camera Window", p: { direction: "right", mode: "sort", lo: 0.1, hi: 0.9, wash: 0, width: 4, window: "cross", fringe: 0 } },
  { name: "Sorted Rain", p: { mode: "sort", lo: 0.15, hi: 0.85, width: 3, length: 0.35, chaos: 0.8 } },
  { name: "Lilac Haze", p: { palette: "lilac", wash: 0.9, color: 0.25, fringe: 5 } },
  { name: "Rising Ember", p: { direction: "up", palette: "ember", follow: "light", lo: 0.3, hi: 1, wash: 0.7 } },
  { name: "Raw Drip", p: { wash: 0, fringe: 0 } },
];

const GROUPS = [
  { title: "Streaks", items: [
    { k: "direction", type: "seg", options: [["down", "↓ Down"], ["up", "↑ Up"], ["right", "→ Right"], ["left", "← Left"]] },
    { k: "mode", type: "seg", options: [["melt", "Melt"], ["sort", "Sort"]] },
    { k: "width", label: "Streak width", min: 1, max: 32, step: 1, fmt: (v) => v + " px" },
    { k: "length", label: "Max length", min: 0.02, max: 1, step: 0.01, fmt: pct },
    { k: "chaos", label: "Ragged ends", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "overflow", label: "Overflow", min: 0, max: 1, step: 0.01, fmt: pct },
  ] },
  { title: "Which pixels", items: [
    { k: "key", type: "seg", options: [["brightness", "Brightness"], ["hue", "Hue"], ["saturation", "Saturation"]] },
    { k: "lo", label: "Range from", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "hi", label: "Range to", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "invert", type: "toggle", label: "Streak the pixels outside the range" },
  ] },
  { title: "Melt", when: (p) => p.mode === "melt", items: [
    { k: "melt", label: "Hold", min: 0.9, max: 1, step: 0.001, fmt: (v) => v.toFixed(3) },
    { k: "follow", type: "seg", options: [["dark", "Dark drips"], ["light", "Light drips"], ["any", "Any edge"]] },
    { k: "edge", label: "New streak at edges over", min: 0, max: 0.6, step: 0.01, fmt: pct },
  ] },
  { title: "Sort", when: (p) => p.mode === "sort", items: [
    { k: "reverse", type: "toggle", label: "Light first" },
  ] },
  { title: "Colour", items: [
    { k: "palette", type: "palette" },
    { k: "wash", label: "Wash", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "color", label: "Keep original colour", min: 0, max: 1, step: 0.01, fmt: pct },
    { k: "fringe", label: "Fringe", min: 0, max: 20, step: 1, fmt: (v) => v + " px" },
  ] },
  { title: "Window", items: [
    { k: "window", type: "seg", options: [["off", "Off"], ["cross", "Cross"], ["flip", "Flip"], ["clean", "Clean"]] },
    { k: "win_x", label: "Left", min: 0, max: 1, step: 0.01, fmt: pct, when: (p) => p.window !== "off" },
    { k: "win_y", label: "Top", min: 0, max: 1, step: 0.01, fmt: pct, when: (p) => p.window !== "off" },
    { k: "win_w", label: "Width", min: 0.05, max: 1, step: 0.01, fmt: pct, when: (p) => p.window !== "off" },
    { k: "win_h", label: "Height", min: 0.05, max: 1, step: 0.01, fmt: pct, when: (p) => p.window !== "off" },
  ] },
  { title: "Motion", when: () => !!media, items: [
    { k: "motion", type: "seg", options: [["off", "Off"], ["drip", "Drip"], ["melt", "Melt"], ["pour", "Pour"],
      ["breathe", "Breathe"], ["glitch", "Glitch"]] },
    { type: "note", text: (p) => (p.motion === "off" && isVideo() ? MOTION_OFF_VIDEO : MOTION_INFO[p.motion])
      + (p.motion !== "off" && isVideo() ? " It runs along with the clip; ▶ previews it on the current frame." : "") },
    { k: "strength", label: "Strength", min: 0, max: 1, step: 0.01, fmt: pct,
      when: (p) => p.motion !== "off" && p.motion !== "pour" },
    { k: "speed", label: () => (isVideo() ? "Cycles per cycle length" : "Cycles per loop"), min: 1, max: 8, step: 1,
      fmt: (v) => v + "×", when: (p) => p.motion !== "off" },
    { k: "loop", label: () => (isVideo() ? "Cycle length" : "Loop length"), min: 1, max: 30, step: 0.5, extra: true,
      fmt: (v) => v + " s", when: (p) => p.motion !== "off" },
    { k: "fps", type: "seg", extra: true, options: [[24, "24 fps"], [30, "30 fps"], [60, "60 fps"]],
      when: (p) => p.motion !== "off" && !isVideo() },
  ] },
  { title: "Seed", items: [{ k: "seed", type: "seed" }] },
  { title: "Video", when: () => media && media.kind === "video", items: [
    { k: "shuffle", label: "New streak pattern every", min: 0, max: 60, step: 1, extra: true,
      fmt: (v) => (v ? v + " frames" : "never") },
  ] },
];

const MOTION_INFO = {
  off: "A still picture. Pick a motion to export a looping MP4.",
  drip: "Every streak stretches and shrinks at its own pace, like dripping paint.",
  melt: "The whole picture melts down, then rewinds.",
  pour: "Streaks flow down without stopping, like a waterfall.",
  breathe: "The streaked area swells and shrinks.",
  glitch: "Jumps between streak patterns, like a glitching camera.",
};
const MOTION_OFF_VIDEO = "Pick a motion to make the streaks move while the clip plays.";

let DEFAULTS = {};
let PALETTES = {};
let P = {};               // current look
let X = { shuffle: 0, loop: 6, fps: 30 };   // export-only settings
let T = 0;                // position in the motion loop, 0..1
let playing = false;
let media = null;
let frameIdx = 0;
let presetOn = 0;

// ------------------------------------------------------------------ helpers
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r;
}

let toastTimer = 0;
function toast(msg, opts = {}) {
  const t = $("toast");
  t.className = "toast" + (opts.error ? " err" : "");
  t.replaceChildren();
  const m = document.createElement("span");
  m.className = "msg";
  m.textContent = msg;
  t.append(m);
  if (opts.action) {
    const b = document.createElement("button");
    b.textContent = opts.action[0];
    b.onclick = opts.action[1];
    t.append(b);
  }
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, opts.ms || 4000);
}

function save() {
  try { localStorage.setItem("pixeldrip.look", JSON.stringify({ P, X, presetOn })); } catch (e) { /* storage off */ }
}

function restore() {
  try {
    const s = JSON.parse(localStorage.getItem("pixeldrip.look") || "null");
    if (s && s.P) {
      P = { ...DEFAULTS, ...s.P };
      X = { ...X, ...(s.X || {}) };
      presetOn = s.presetOn ?? -1;
      return;
    }
  } catch (e) { /* storage off or bad data */ }
  P = { ...DEFAULTS };
}

// ------------------------------------------------------------------ controls
function buildControls() {
  const root = $("controls");
  root.replaceChildren();
  for (const g of GROUPS) {
    if (g.when && !g.when(P)) continue;
    const sec = document.createElement("section");
    sec.className = "group";
    const h = document.createElement("h2");
    h.textContent = g.title;
    sec.append(h);
    for (const it of g.items) {
      if (it.when && !it.when(P)) continue;
      sec.append(control(it));
    }
    root.append(sec);
  }
}

function setParam(k, v, extra) {
  if (extra) X[k] = v; else P[k] = v;
  if (!extra) { presetOn = -1; markPresets(); }
  save();
  if (k === "loop" && isVideo() && !playing) T = frameT();  // the cycle length moves this frame's motion time
  updatePlaybar();
  if (!extra || (k === "loop" && isVideo())) render();
}

function control(it) {
  const row = document.createElement("div");
  row.className = "row";
  const val = it.extra ? X[it.k] : P[it.k];
  if (it.type === "note") {
    row.className = "note";
    row.textContent = it.text(P);
    return row;
  }
  if (it.type === "seg") {
    const seg = document.createElement("div");
    seg.className = "seg";
    for (const [v, label] of it.options) {
      const b = document.createElement("button");
      b.textContent = label;
      b.className = v === val ? "on" : "";
      b.onclick = () => { setParam(it.k, v, it.extra); buildControls(); };
      seg.append(b);
    }
    row.append(seg);
  } else if (it.type === "toggle") {
    const l = document.createElement("label");
    l.className = "toggle";
    const c = document.createElement("input");
    c.type = "checkbox";
    c.checked = !!val;
    c.onchange = () => setParam(it.k, c.checked);
    l.append(c, document.createTextNode(it.label));
    row.append(l);
  } else if (it.type === "palette") {
    const pal = document.createElement("div");
    pal.className = "pal";
    for (const name of [...Object.keys(PALETTES), "none"]) {
      const b = document.createElement("button");
      b.title = name;
      b.className = (name === val ? "on " : "") + (name === "none" ? "none" : "");
      if (name === "none") b.textContent = "None";
      else for (const c of PALETTES[name]) { const i = document.createElement("i"); i.style.background = c; b.append(i); }
      b.onclick = () => { setParam("palette", name); buildControls(); };
      pal.append(b);
    }
    row.append(pal);
  } else if (it.type === "seed") {
    const wrap = document.createElement("div");
    wrap.className = "seedrow";
    const inp = document.createElement("input");
    inp.type = "number";
    inp.value = val;
    inp.onchange = () => setParam("seed", parseInt(inp.value, 10) || 0);
    const b = document.createElement("button");
    b.textContent = "New seed";
    b.onclick = () => { inp.value = Math.floor(Math.random() * 99999); setParam("seed", parseInt(inp.value, 10)); };
    wrap.append(inp, b);
    row.append(wrap);
  } else {
    const lab = document.createElement("div");
    lab.className = "lab";
    const name = document.createElement("span");
    name.textContent = typeof it.label === "function" ? it.label() : it.label;
    const out = document.createElement("span");
    out.className = "mono";
    out.textContent = it.fmt ? it.fmt(val) : val;
    lab.append(name, out);
    const r = document.createElement("input");
    r.type = "range";
    r.min = it.min; r.max = it.max; r.step = it.step;
    r.value = val;
    r.oninput = () => {
      const v = parseFloat(r.value);
      out.textContent = it.fmt ? it.fmt(v) : v;
      setParam(it.k, v, it.extra);
    };
    r.ondblclick = () => {
      const d = it.extra ? 0 : DEFAULTS[it.k];
      r.value = d;
      r.oninput();
    };
    row.append(lab, r);
  }
  return row;
}

function buildPresets() {
  const root = $("presets");
  root.replaceChildren();
  PRESETS.forEach((pr, i) => {
    const b = document.createElement("button");
    b.className = "preset";
    b.title = pr.name;
    const th = document.createElement("div");
    th.className = "thumb";
    const s = document.createElement("span");
    s.textContent = pr.name;
    b.append(th, s);
    b.onclick = () => {
      const keep = { seed: P.seed, win_x: P.win_x, win_y: P.win_y, win_w: P.win_w, win_h: P.win_h,
                     motion: P.motion, speed: P.speed, strength: P.strength };
      P = { ...DEFAULTS, ...keep, ...pr.p };
      presetOn = i;
      markPresets();
      buildControls();
      save();
      render();
    };
    root.append(b);
  });
  markPresets();
}

function markPresets() {
  [...$("presets").children].forEach((b, i) => b.classList.toggle("on", i === presetOn));
}

let thumbToken = 0;
async function presetThumbs() {
  const token = ++thumbToken;
  const thumbs = [...$("presets").querySelectorAll(".thumb")];
  for (let i = 0; i < PRESETS.length; i++) {
    if (token !== thumbToken || !media) return;
    try {
      const params = { ...DEFAULTS, seed: P.seed, ...PRESETS[i].p };
      const r = await api("/api/preview", { params, frame: frameIdx, side: 240 });
      const url = URL.createObjectURL(await r.blob());
      const old = thumbs[i].dataset.url;
      thumbs[i].style.backgroundImage = `url(${url})`;
      thumbs[i].dataset.url = url;
      if (old) URL.revokeObjectURL(old);
    } catch (e) { return; }
  }
}

function randomize() {
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const rnd = (a, b) => a + Math.random() * (b - a);
  const r2 = (v) => Math.round(v * 100) / 100;
  const dir = pick(["down", "down", "down", "up", "right", "left"]);
  P = {
    ...P,
    direction: dir,
    mode: Math.random() < 0.7 ? "melt" : "sort",
    key: Math.random() < 0.8 ? "brightness" : pick(["hue", "saturation"]),
    lo: r2(rnd(0, 0.3)),
    hi: r2(rnd(0.6, 0.95)),
    invert: false,
    width: Math.round(rnd(2, 12)),
    length: r2(rnd(0.25, 0.9)),
    chaos: r2(rnd(0.3, 0.9)),
    overflow: r2(rnd(0.2, 1)),
    melt: Math.round(rnd(0.985, 1) * 1000) / 1000,
    follow: pick(["dark", "dark", "light", "any"]),
    edge: r2(rnd(0.05, 0.2)),
    reverse: Math.random() < 0.3,
    palette: pick([...Object.keys(PALETTES), "blush", "blush"]),
    wash: r2(rnd(0.5, 0.95)),
    color: r2(rnd(0.15, 0.6)),
    fringe: Math.round(rnd(0, 6)),
    window: Math.random() < 0.2 ? pick(["cross", "flip", "clean"]) : "off",
    seed: Math.floor(Math.random() * 99999),
  };
  presetOn = -1;
  markPresets();
  buildControls();
  save();
  render();
}

// ------------------------------------------------------------------ preview
function previewSide() {
  const v = $("view").getBoundingClientRect();
  if (!media) return 1280;
  const s = Math.min(v.width / media.width, v.height / media.height);
  const long = Math.max(media.width, media.height) * s * (window.devicePixelRatio || 1);
  return Math.max(256, Math.min(1600, Math.round(long)));
}

let inflight = false;
let dirty = false;
let shotUrl = "";
function render() {
  placeWindowBox();
  dirty = true;
  if (!inflight) pump();
}

async function pump() {
  if (!media) return;
  inflight = true;
  dirty = false;
  $("busy").hidden = false;
  try {
    const r = await api("/api/preview", { params: P, frame: frameIdx, side: previewSide(), t: motionOn() ? T : 0 });
    const ms = r.headers.get("X-Render-Ms");
    const url = URL.createObjectURL(await r.blob());
    await swap($("shot"), url);
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = url;
    $("ms").textContent = ms ? `effect ${ms} ms` : "";
    if (playing) {
      const now = performance.now();
      if (lastShown) $("ms").textContent += `  ·  playing ${Math.round(1000 / (now - lastShown))} fps`;
      lastShown = now;
    }
  } catch (e) {
    toast("Preview failed: " + e.message, { error: true });
  }
  inflight = false;
  $("busy").hidden = true;
  if (dirty) pump();
}

// ------------------------------------------------------------------ motion playback
// On a photo T is free: the export is one loop of it. On a video T follows the clip (frame time / cycle length),
// as the export does; playing previews the motion on the current frame.
let lastShown = 0;
function isVideo() { return !!media && media.kind === "video"; }
function motionOn() { return !!media && P.motion !== "off"; }
function frameT() { return isVideo() ? (frameIdx / (media.fps || 30) / X.loop) % 1 : T; }

function updatePlaybar() {
  const on = motionOn();
  $("playbar").hidden = !on;
  $("export").textContent = on && !isVideo() ? "Export MP4" : "Export";
  $("tpos").disabled = isVideo();  // on a video the clip's own time sets it
  if (!on && playing) setPlaying(false);
  if (isVideo() && !playing) T = frameT();
  showT();
}

function showT() {
  $("tpos").value = Math.round(T * 1000);
  $("tlabel").textContent = `${(T * X.loop).toFixed(1)} / ${X.loop} s`;
}

function setPlaying(on) {
  playing = on && motionOn();
  $("play").classList.toggle("on", playing);
  $("play").innerHTML = playing ? "&#10074;&#10074;" : "&#9654;";
  $("play").setAttribute("aria-label", playing ? "Pause" : "Play");
  lastShown = 0;
  if (playing) playLoop();
  else if (isVideo() && T !== frameT()) {  // back to what the export shows at this frame
    T = frameT();
    showT();
    render();
  }
}

async function playLoop() {
  let last = performance.now();
  while (playing) {
    const now = performance.now();
    T = (T + (now - last) / 1000 / X.loop) % 1;
    last = now;
    showT();
    dirty = true;
    if (!inflight) await pump();
    else await new Promise((r) => setTimeout(r, 8));
  }
}

function swap(img, url) {
  return new Promise((res) => {
    img.onload = img.onerror = () => res();
    img.src = url;
  });
}

let origUrl = "";
async function loadOriginal() {
  if (!media) return;
  try {
    const r = await api("/api/preview", { frame: frameIdx, side: previewSide(), original: true });
    const url = URL.createObjectURL(await r.blob());
    await swap($("orig"), url);
    if (origUrl) URL.revokeObjectURL(origUrl);
    origUrl = url;
  } catch (e) { /* the effect preview reports errors */ }
}

function showOriginal(on) {
  if (!media) return;
  $("view").classList.toggle("showorig", on);
  $("badge").hidden = !on;
}

// ------------------------------------------------------------------ window box (drag to move, corner to resize)
function imageRect() {
  const v = $("view").getBoundingClientRect();
  const s = Math.min(v.width / media.width, v.height / media.height);
  const w = media.width * s, h = media.height * s;
  return { x: (v.width - w) / 2, y: (v.height - h) / 2, w, h };
}

function placeWindowBox() {
  const box = $("winbox");
  if (!media || P.window === "off") { box.hidden = true; return; }
  const r = imageRect();
  box.hidden = false;
  box.style.left = r.x + P.win_x * r.w + "px";
  box.style.top = r.y + P.win_y * r.h + "px";
  box.style.width = Math.min(P.win_w, 1 - P.win_x) * r.w + "px";
  box.style.height = Math.min(P.win_h, 1 - P.win_y) * r.h + "px";
}

function initWindowDrag() {
  const box = $("winbox");
  let drag = null;
  box.addEventListener("pointerdown", (e) => {
    const r = imageRect();
    drag = { mode: e.target.id === "grip" ? "size" : "move", x: e.clientX, y: e.clientY, r,
             p: { x: P.win_x, y: P.win_y, w: P.win_w, h: P.win_h } };
    box.setPointerCapture(e.pointerId);
    box.classList.add("active");
    e.preventDefault();
  });
  box.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = (e.clientX - drag.x) / drag.r.w, dy = (e.clientY - drag.y) / drag.r.h;
    const c = (v, a, b) => Math.round(Math.min(b, Math.max(a, v)) * 1000) / 1000;
    if (drag.mode === "move") {
      P.win_x = c(drag.p.x + dx, 0, 1 - Math.min(drag.p.w, 1));
      P.win_y = c(drag.p.y + dy, 0, 1 - Math.min(drag.p.h, 1));
    } else {
      P.win_w = c(drag.p.w + dx, 0.05, 1 - drag.p.x);
      P.win_h = c(drag.p.h + dy, 0.05, 1 - drag.p.y);
    }
    presetOn = -1;
    render();
  });
  const end = () => {
    if (!drag) return;
    drag = null;
    box.classList.remove("active");
    markPresets();
    buildControls();
    save();
  };
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
}

// ------------------------------------------------------------------ media
function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
}

function onMedia(m) {
  media = m;
  frameIdx = 0;
  T = 0;
  setPlaying(false);
  $("empty").hidden = !!m;
  $("export").disabled = !m;
  if (!m) { $("fileinfo").textContent = "No file open"; return; }
  const info = $("fileinfo");
  info.replaceChildren();
  const b = document.createElement("b");
  b.textContent = m.name;
  info.append(b, document.createTextNode(
    m.kind === "video"
      ? `  ·  ${m.width}×${m.height}  ·  ${fmtTime(m.duration)}  ·  ${Math.round(m.fps * 100) / 100} fps${m.has_audio ? "  ·  audio" : ""}`
      : `  ·  ${m.width}×${m.height}`));
  info.title = m.path;
  const vid = m.kind === "video";
  $("scrub").hidden = !vid;
  if (vid) {
    const f = $("frame");
    f.max = Math.max(0, m.frames - 1);
    f.value = 0;
    $("time").textContent = fmtTime(0);
  }
  $("shot").removeAttribute("src");
  $("orig").removeAttribute("src");
  buildControls();
  updatePlaybar();
  placeWindowBox();
  render();
  loadOriginal();
  presetThumbs();
}

async function openDialog() {
  try {
    const j = await (await api("/api/browse", {})).json();
    if (!j.cancelled) onMedia(j.media);
  } catch (e) { toast(e.message, { error: true, ms: 7000 }); }
}

async function uploadFile(file) {
  toast(`Importing ${file.name}…`, { ms: 60000 });
  try {
    const r = await fetch("/api/upload?name=" + encodeURIComponent(file.name), { method: "POST", body: file });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    onMedia((await r.json()).media);
    $("toast").hidden = true;
  } catch (e) { toast(e.message, { error: true, ms: 7000 }); }
}

function initDrop() {
  const v = $("view");
  let depth = 0;
  window.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; v.classList.add("drag"); });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; v.classList.remove("drag"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    depth = 0;
    v.classList.remove("drag");
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
}

let scrubTimer = 0;
function initScrub() {
  $("frame").addEventListener("input", () => {
    frameIdx = parseInt($("frame").value, 10);
    $("time").textContent = fmtTime(frameIdx / (media.fps || 30));
    if (!playing) { T = frameT(); showT(); }
    clearTimeout(scrubTimer);
    scrubTimer = setTimeout(() => { render(); loadOriginal(); }, 90);
  });
  $("frame").addEventListener("change", () => presetThumbs());
}

// ------------------------------------------------------------------ export
async function startExport() {
  if (!media) return;
  try {
    setPlaying(false);
    await api("/api/export", { params: P, max_side: parseInt($("exportSize").value, 10), shuffle: X.shuffle,
                               loop: X.loop, fps: X.fps });
    watchJob();
  } catch (e) { toast(e.message, { error: true, ms: 7000 }); }
}

let jobTimer = 0;
function watchJob() {
  $("progress").hidden = false;
  clearInterval(jobTimer);
  const tick = async () => {
    let j;
    try { j = await (await api("/api/job")).json(); } catch (e) { return; }
    const frac = j.total ? j.done / j.total : 0;
    $("ptitle").textContent = `Exporting ${j.name || ""}`;
    $("pbar").style.width = (j.kind === "image" ? (j.state === "running" ? 50 : 100) : frac * 100) + "%";
    $("pinfo").textContent = j.kind !== "image" && j.state === "running"
      ? `${j.done} / ${j.total} frames` + (j.fps ? `  ·  ${j.fps.toFixed(1)} fps  ·  ${fmtTime(j.eta)} left` : "")
      : j.state === "running" ? "Rendering…" : "";
    if (j.state === "running") return;
    clearInterval(jobTimer);
    $("progress").hidden = true;
    if (j.state === "done") {
      const problems = (j.report && j.report.problems) || [];
      toast((problems.length ? "Saved with warnings (" + problems.join("; ") + "): " : "Saved: ") + j.out, {
        ms: 12000, action: ["Show in folder", () => api("/api/reveal", { path: j.out })],
      });
    } else if (j.state === "error") {
      toast("Export failed: " + j.error, { error: true, ms: 12000 });
    } else if (j.state === "cancelled") {
      toast("Export cancelled");
    }
  };
  jobTimer = setInterval(tick, 400);
  tick();
}

// ------------------------------------------------------------------ boot
async function boot() {
  const st = await (await api("/api/state")).json();
  DEFAULTS = st.defaults;
  PALETTES = st.palettes;
  restore();
  buildPresets();
  buildControls();
  initWindowDrag();
  initDrop();
  initScrub();
  $("open").onclick = openDialog;
  $("open2").onclick = openDialog;
  $("random").onclick = randomize;
  $("play").onclick = () => setPlaying(!playing);
  $("tpos").addEventListener("input", () => {
    T = parseInt($("tpos").value, 10) / 1000;
    showT();
    if (!playing) render();
  });
  $("export").onclick = startExport;
  $("pcancel").onclick = () => api("/api/cancel", {}).catch(() => {});
  window.addEventListener("keydown", (e) => {
    const typing = e.target.tagName === "INPUT" && e.target.type !== "range" && e.target.type !== "checkbox";
    if (e.code === "Space" && !typing) { e.preventDefault(); if (!e.repeat) showOriginal(true); }
    else if (e.ctrlKey && e.key.toLowerCase() === "o") { e.preventDefault(); openDialog(); }
    else if (e.ctrlKey && e.key.toLowerCase() === "e") { e.preventDefault(); startExport(); }
    else if (!typing && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "r") randomize();
    else if (!typing && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "p") setPlaying(!playing);
  });
  window.addEventListener("keyup", (e) => { if (e.code === "Space") showOriginal(false); });
  window.addEventListener("blur", () => showOriginal(false));
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    placeWindowBox();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { render(); loadOriginal(); }, 200);
  });
  const ping = () => fetch("/api/ping", { method: "POST" }).catch(() => {});
  ping();
  setInterval(ping, 4000);
  onMedia(st.media);
  if (st.job && st.job.state === "running") watchJob();
  // a file dropped on the desktop shortcut while the window is open is loaded by the server: follow it
  setInterval(async () => {
    try {
      const s = await (await api("/api/state")).json();
      if (s.media && (!media || s.media.key !== media.key)) onMedia(s.media);
    } catch (e) { /* server busy */ }
  }, 1500);
}

boot().catch((e) => toast("Could not start: " + e.message, { error: true, ms: 60000 }));
