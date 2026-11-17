"""Pixel Drip - local desktop app (FastAPI backend + Chrome/Edge app window).

The backend holds the open picture or clip, renders previews on request and runs exports. The window is the
plain HTML page in static/.
"""
import collections
import os
import subprocess
import sys
import threading
import time
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("PIXELDRIP_DATA") or os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), "PixelDrip")
os.makedirs(DATA_DIR, exist_ok=True)

# pythonw has no console (stdout is None): route all output to a log file before anything prints
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(DATA_DIR, "app.log"), "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = _log
else:  # a console that cannot show a file name's accents must not crash the server
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

sys.path.insert(0, APP_DIR)

from concurrent.futures import ThreadPoolExecutor  # noqa: E402

import cv2  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Body, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402

import effect as E  # noqa: E402
import media as M  # noqa: E402

PORT = int(os.environ.get("PIXELDRIP_PORT") or 47861)
APP_ID = "pixel-drip"
STATIC = os.path.join(APP_DIR, "static")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
NO_STORE = {"Cache-Control": "no-store"}
EXPORT_SIDES = {0: None, 1920: 1920, 1280: 1280}
RENDER_WORKERS = 3  # frames rendered at once during a video export (about 1.8x faster than one at a time)

app = FastAPI()
S = {"media": None, "job": {"state": "idle"}, "last_ping": time.time(), "pinged": False}
LOCK = threading.Lock()
CACHE = {}  # (media key, frame, long side) -> RGB frame
CANCEL = threading.Event()

# native file dialogs run in their own process so Tk never shares threads with the server
PICK_CODE = """
import sys, tkinter as tk
from tkinter import filedialog
r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)
p = filedialog.askopenfilename(parent=r, title='Open a photo or video', filetypes=[
    ('Photos and videos', %r), ('Photos', %r), ('Videos', %r), ('All files', '*.*')])
sys.stdout.write(p or '')
"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def out_dir():
    """Where exports go: the PIXELDRIP_OUT environment variable, else Videos\\Pixel Drip in the user's folder."""
    if os.environ.get("PIXELDRIP_OUT"):
        return os.environ["PIXELDRIP_OUT"]
    return os.path.join(os.path.expanduser("~"), "Videos", "Pixel Drip")


def unique_path(folder, stem, ext):
    os.makedirs(folder, exist_ok=True)
    p, i = os.path.join(folder, stem + ext), 2
    while os.path.exists(p) or os.path.exists(p + ".part" + ext) or os.path.exists(p + ".part.mp4"):
        p, i = os.path.join(folder, f"{stem} ({i}){ext}"), i + 1
    return p


# --------------------------------------------------------------------------- media

def public(m):
    if not m:
        return None
    return {k: m[k] for k in ("key", "path", "name", "kind", "width", "height", "frames", "fps", "duration",
                              "has_audio")}


def load_media(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise RuntimeError("File not found: " + path)
    kind = M.kind(path)
    if kind is None:
        raise RuntimeError("Pixel Drip opens photos (PNG, JPG, WebP, TIFF, BMP) and videos (MP4, MOV, WebM, MKV, "
                           "AVI, GIF).")
    m = {"key": str(time.time_ns()), "path": path, "name": os.path.basename(path), "kind": kind}
    if kind == "image":
        img = M.read_image(path)
        m.update(img=img, width=img.shape[1], height=img.shape[0], frames=1, fps=0, duration=0, has_audio=False)
    else:
        info = M.probe(path)
        m.update(info=info, width=info["width"], height=info["height"], frames=info["frames"], fps=info["fps"],
                 duration=info["duration"], has_audio=info["has_audio"])
    with LOCK:
        S["media"] = m
        CACHE.clear()
    log("loaded", kind, path)
    return public(m)


def source(frame, side):
    """The open picture, or one frame of the open clip, scaled to fit `side` (cached)."""
    m = S["media"]
    if not m:
        raise HTTPException(404, "Nothing is open")
    side = int(min(max(side, 64), 4096))
    frame = 0 if m["kind"] == "image" else int(min(max(frame, 0), m["frames"] - 1))
    key = (m["key"], frame, side)
    with LOCK:
        hit = CACHE.get(key)
    if hit is not None:
        return hit
    W, H = M.fit(m["width"], m["height"], side)
    if m["kind"] == "image":
        img = m["img"] if (W, H) == (m["width"], m["height"]) else cv2.resize(m["img"], (W, H),
                                                                                interpolation=cv2.INTER_AREA)
    else:
        img = M.read_frame(m["path"], m["info"], frame, W, H)
    with LOCK:
        if S["media"] is m:
            while len(CACHE) >= 8:
                CACHE.pop(next(iter(CACHE)))
            CACHE[key] = img
    return img


# --------------------------------------------------------------------------- export

def video_t(i, info, loop):
    """Motion time of video frame i: the motion runs one cycle every `loop` seconds of the clip."""
    return (i * info["fps_den"] / info["fps_num"] / loop) % 1.0


def run_export(m, p, max_side, shuffle, anim, loop=6.0):
    """Write the export: a PNG for a still picture, else an MP4 (a video, or a still picture in motion)."""
    job = S["job"]
    stem = os.path.splitext(m["name"])[0] + " - Pixel Drip"
    writer = jobs = None
    try:
        if m["kind"] == "image" and not anim:
            img = m["img"]
            if max_side and max(img.shape[:2]) > max_side:
                img = cv2.resize(img, M.fit(m["width"], m["height"], max_side), interpolation=cv2.INTER_AREA)
            path = unique_path(out_dir(), stem, ".png")
            M.write_image(path, E.render(img, p))
            job.update(done=1, out=path)
            job["state"] = "done"
            log("exported", path, f"{time.time() - job['started']:.1f}s")
            return
        W, H = M.even_size(m["width"], m["height"], max_side or 4096)
        if m["kind"] == "image":
            # one loop of the motion: frame i is loop time i / n, so the clip repeats without a seam
            img = m["img"]
            if (W, H) != (m["width"], m["height"]):
                img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
            n = anim["frames"]
            info = {"frames": n, "fps_num": anim["fps"], "fps_den": 1, "has_audio": False, "aoff": 0.0}
            jobs = ((img, p, i / n) for i in range(n))
        else:
            info, n = m["info"], m["info"]["frames"]

            def frames():
                for i, f in M.decode_frames(m["path"], info, W, H):
                    if i >= n:
                        return
                    q = dict(p)
                    if shuffle:
                        q["seed"] = p["seed"] + i // shuffle
                    yield f, q, video_t(i, info, loop)

            jobs = frames()
        path = unique_path(out_dir(), stem, ".mp4")
        writer = M.VideoWriter(path, W, H, info, m["path"])
        pending = collections.deque()  # rendering frames, oldest first: written in order

        def drain(keep):
            while len(pending) > keep:
                writer.write(pending.popleft().result())
                job["done"] += 1

        with ThreadPoolExecutor(RENDER_WORKERS, thread_name_prefix="render") as pool:
            for f, q, t in jobs:
                if CANCEL.is_set():
                    break
                pending.append(pool.submit(E.render, f, q, t))
                drain(RENDER_WORKERS)
            if not CANCEL.is_set():
                drain(0)
        if CANCEL.is_set():
            writer.cancel()
            job.update(state="cancelled")
            log("export cancelled")
            return
        rep = writer.finish(job["done"])
        writer = None
        job.update(out=path, report=rep, state="done")
        if rep["problems"]:
            log("export check:", rep["problems"])
        log("exported", path, f"{time.time() - job['started']:.1f}s")
    except Exception as e:
        traceback.print_exc()
        if writer:
            writer.cancel()
        job.update(state="error", error=str(e))
    finally:
        if hasattr(jobs, "close"):
            jobs.close()  # stops the decoder if the export ended early


# --------------------------------------------------------------------------- routes: app shell

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers=NO_STORE)


@app.get("/static/{path:path}")
def static(path: str):
    full = os.path.normpath(os.path.join(STATIC, path))
    if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
        raise HTTPException(404)
    return FileResponse(full, headers=NO_STORE)


@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(APP_DIR, "icon.ico"))


@app.get("/api/ping")
def ping_get():
    return {"app": APP_ID}


@app.post("/api/ping")
def ping():
    S["last_ping"], S["pinged"] = time.time(), True
    return {"ok": True}


@app.get("/api/state")
def state():
    pal = {k: ["#%02x%02x%02x" % c for c in v] for k, v in E.PALETTES.items()}
    return {"media": public(S["media"]), "job": job_public(), "out_dir": out_dir(), "defaults": E.DEFAULTS,
            "palettes": pal}


# --------------------------------------------------------------------------- routes: media

@app.post("/api/browse")
def browse():
    imgs = " ".join("*" + e for e in sorted(M.IMAGE_EXT))
    vids = " ".join("*" + e for e in sorted(M.VIDEO_EXT))
    r = subprocess.run([sys.executable, "-c", PICK_CODE % (imgs + " " + vids, imgs, vids)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", creationflags=M.NO_WINDOW)
    path = (r.stdout or "").strip()
    if not path:
        return {"media": public(S["media"]), "cancelled": True}
    return _load(path)


@app.post("/api/load")
def load(body: dict = Body(...)):
    return _load(body.get("path", ""))


def _load(path):
    try:
        return {"media": load_media(path)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(400, str(e))


@app.post("/api/upload")
async def upload(req: Request, name: str):
    """Files dropped into the window arrive as bytes (the browser does not reveal their path)."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe = "".join(c for c in os.path.basename(name) if c not in '<>:"/\\|?*').strip() or "dropped"
    path = os.path.join(UPLOAD_DIR, safe)
    with open(path, "wb") as f:
        async for chunk in req.stream():
            f.write(chunk)
    return _load(path)


@app.post("/api/preview")
def preview(body: dict = Body(...)):
    try:
        img = source(int(body.get("frame", 0)), int(body.get("side", 1280)))
        p = dict(body.get("params") or {})
        t = time.time()
        out = img if body.get("original") else E.render(img, p, float(body.get("t") or 0.0))
        ms = int((time.time() - t) * 1000)
        return Response(M.jpeg(out), media_type="image/jpeg", headers={**NO_STORE, "X-Render-Ms": str(ms)})
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


# --------------------------------------------------------------------------- routes: export

def job_public():
    j = dict(S["job"])
    j.pop("thread", None)
    if j.get("state") == "running" and j.get("done"):
        el = time.time() - j["started"]
        j["fps"] = j["done"] / max(el, 1e-6)
        j["eta"] = (j["total"] - j["done"]) / max(j["fps"], 1e-6)
    return j


@app.post("/api/export")
def export(body: dict = Body(...)):
    m = S["media"]
    if not m:
        raise HTTPException(400, "Open a photo or video first")
    if S["job"].get("state") == "running":
        raise HTTPException(409, "An export is already running")
    p = E.params(body.get("params") or {})
    max_side = EXPORT_SIDES.get(int(body.get("max_side") or 0))
    shuffle = max(0, int(body.get("shuffle") or 0))
    loop = min(30.0, max(1.0, float(body.get("loop") or 6)))
    anim = None
    if m["kind"] == "image" and p["motion"] != "off":
        fps = int(body.get("fps") or 30)
        fps = fps if fps in (24, 25, 30, 60) else 30
        anim = {"fps": fps, "frames": max(2, int(round(loop * fps)))}
    CANCEL.clear()
    S["job"] = {"state": "running", "kind": "animation" if anim else m["kind"], "done": 0,
                "total": anim["frames"] if anim else m["frames"], "started": time.time(), "out": None,
                "error": None, "name": m["name"]}
    threading.Thread(target=run_export, args=(m, p, max_side, shuffle, anim, loop), daemon=True).start()
    return job_public()


@app.get("/api/job")
def job():
    return job_public()


@app.post("/api/cancel")
def cancel():
    CANCEL.set()
    return job_public()


@app.post("/api/reveal")
def reveal(body: dict = Body(...)):
    path = body.get("path") or ""
    if path and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        folder = out_dir()
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)
    return {"ok": True}


# --------------------------------------------------------------------------- lifecycle

def watchdog():
    """Quit once the window has been closed for a while (and no export is running)."""
    while True:
        time.sleep(2)
        idle = time.time() - S["last_ping"]
        if S["job"].get("state") == "running":
            continue
        if idle > (20 if S["pinged"] else 180):
            log("no window for %ds, exiting" % idle)
            os._exit(0)


def serve():
    threading.Thread(target=E.warm_up, daemon=True).start()
    if not os.environ.get("PIXELDRIP_STAY"):
        threading.Thread(target=watchdog, daemon=True).start()
    log("serving on", PORT)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        load_media(sys.argv[1])
    serve()
