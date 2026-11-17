"""Pixel Drip engine: threshold pixel sorting and melting streaks, colour wash, channel fringe, inset window.

Every public function takes and returns an HxWx3 uint8 RGB array. The frame is re-oriented so the streak
direction always runs along a line from its start (index 0) to its end, the numba kernel works line by line,
and the result is turned back. All randomness comes from a hash of (seed, line), so the same settings give the
same streaks on every frame of a video: nothing flickers unless the picture itself changes.

Motion (for still pictures) makes the streaks move over a loop: render(img, p, t) with t in [0, 1) is one moment
of it, and t = 1 is t = 0 again, so a clip of frames t = i / n loops without a seam.
"""
import math

import cv2
import numpy as np
from numba import config as _numba_config
from numba import njit, prange

# Previews and an export can run kernels at the same time: never fall back to the non-thread-safe workqueue.
_numba_config.THREADING_LAYER = "threadsafe"

DIRECTIONS = ("down", "up", "right", "left")
MODES = ("melt", "sort")
FOLLOWS = ("dark", "light", "any")
KEYS = ("brightness", "hue", "saturation")
WINDOW_MODES = ("off", "cross", "flip", "clean")
MOTIONS = ("off", "drip", "melt", "pour", "breathe", "glitch")

# Gradient-map colour washes: shadow, mid, highlight (RGB). "blush" matches the reference reel.
PALETTES = {
    "blush": ((78, 50, 46), (226, 146, 126), (252, 222, 214)),
    "lilac": ((44, 36, 66), (150, 128, 196), (240, 228, 250)),
    "ember": ((52, 22, 18), (204, 96, 64), (255, 226, 188)),
    "sea": ((18, 40, 52), (88, 152, 160), (226, 246, 238)),
    "mono": ((30, 30, 30), (128, 128, 128), (238, 238, 238)),
}

DEFAULTS = {
    "direction": "down",
    "mode": "melt",        # melt: colours are dragged along the streak; sort: each run is sorted by key
    "key": "brightness",
    "lo": 0.0,             # runs are the pixels whose key is inside [lo, hi] ...
    "hi": 0.82,
    "invert": False,       # ... or outside it
    "length": 0.55,        # longest streak, as a fraction of the line
    "chaos": 0.6,          # how much streak length varies from line to line
    "overflow": 0.5,       # how far a streak keeps going past the end of its run (drips into the light)
    "melt": 0.996,         # melt: how firmly a streak holds its colour (1 = solid, lower fades it out)
    "follow": "dark",      # melt: a new streak starts where the picture gets darker / lighter / either
    "edge": 0.1,           # melt: how big that change must be (0..1 of the key)
    "reverse": False,      # sort: light first instead of dark first
    "seed": 7,
    "wash": 0.85,          # colour wash strength
    "palette": "blush",
    "color": 0.4,         # how much of the picture's own colour survives the wash
    "width": 6,            # streak width in px (the reel was shot on a low-res camera, so its streaks are chunky)
    "fringe": 2,           # px offset of red/blue along the streaks
    "window": "off",
    "win_x": 0.07, "win_y": 0.31, "win_w": 0.86, "win_h": 0.36,
    "motion": "off",       # drip: each streak stretches and shrinks on its own; melt: the picture melts and
                           # rewinds; pour: streaks flow like a waterfall; breathe: the streaked area swells;
                           # glitch: jumps between streak patterns
    "speed": 1,            # motion cycles per loop (whole numbers keep the loop seamless)
    "strength": 0.7,       # how far the motion goes
}

_PERP = {"down": "right", "up": "left", "right": "down", "left": "up"}
_FLIP = {"down": "up", "up": "down", "right": "left", "left": "right"}


def params(p=None):
    """Defaults merged with p; unknown keys dropped, values clamped to their ranges."""
    q = dict(DEFAULTS)
    for k, v in (p or {}).items():
        if k in q and v is not None:
            q[k] = v
    for k in ("lo", "hi", "length", "chaos", "overflow", "edge", "wash", "color", "win_x", "win_y", "win_w",
              "win_h", "strength"):
        q[k] = min(1.0, max(0.0, float(q[k])))
    q["melt"] = min(1.0, max(0.0, float(q["melt"])))
    q["fringe"] = int(min(40, max(0, round(float(q["fringe"])))))
    q["width"] = int(min(32, max(1, round(float(q["width"])))))
    q["seed"] = int(q["seed"]) & 0x7FFFFFFF
    q["speed"] = int(min(8, max(1, round(float(q["speed"])))))
    q["invert"], q["reverse"] = bool(q["invert"]), bool(q["reverse"])
    for k, allowed in (("direction", DIRECTIONS), ("mode", MODES), ("key", KEYS), ("follow", FOLLOWS),
                       ("window", WINDOW_MODES), ("motion", MOTIONS)):
        if q[k] not in allowed:
            q[k] = DEFAULTS[k]
    if q["palette"] not in PALETTES and q["palette"] != "none":
        q["palette"] = DEFAULTS["palette"]
    return q


# --------------------------------------------------------------------------- orientation

def to_lines(img, direction):
    """Re-orient so axis 1 runs along the streak, starting where the streak starts."""
    if direction == "down":
        a = img.transpose(1, 0, 2)
    elif direction == "up":
        a = img[::-1].transpose(1, 0, 2)
    elif direction == "right":
        a = img
    else:
        a = img[:, ::-1]
    return np.ascontiguousarray(a)


def from_lines(lines, direction):
    if direction == "down":
        a = lines.transpose(1, 0, 2)
    elif direction == "up":
        a = lines.transpose(1, 0, 2)[::-1]
    elif direction == "right":
        a = lines
    else:
        a = lines[:, ::-1]
    return np.ascontiguousarray(a)


# --------------------------------------------------------------------------- kernel

_M32 = np.uint64(0xFFFFFFFF)


def _rand(seed, lines, salt):
    """Deterministic hash of (seed, line, salt) -> [0, 1) for an array of line numbers."""
    a = np.asarray(lines, np.uint64)
    h = (np.uint64(seed) * np.uint64(0x9E3779B1) + a * np.uint64(0x85EBCA77)
         + np.uint64(salt * 0xC2B2AE3D + 0x27D4EB2F)) & _M32
    h ^= h >> np.uint64(15)
    h = (h * np.uint64(0x2C1B3C6D)) & _M32
    h ^= h >> np.uint64(12)
    h = (h * np.uint64(0x297A2D39)) & _M32
    h ^= h >> np.uint64(15)
    return h.astype(np.float64) / 4294967296.0


def _wave(x):
    """0 -> 1 -> 0 over each whole unit of x, smooth at both ends."""
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * x)


def line_plan(p, L, N, t=0.0):
    """Per-line streak cap, overflow, grid offset and reach at loop time t.

    The cap is the longest a run may get on that line; a run that ends on its own (not on the cap) spills
    `overflow` further. A grid offset >= 0 makes runs break on a fixed grid (pour slides that grid along the
    line); -1 counts each cap from the start of its run. Reach is how far a melted streak has dripped from the
    edge it started at; past it the picture shows through (drip and melt grow and shrink it).
    """
    lines = np.arange(L)
    cap = max(2.0, p["length"] * N) * (1.0 - p["chaos"] * _rand(p["seed"], lines, 1))
    spill_f = p["overflow"] * _rand(p["seed"], lines, 2)
    off = np.full(L, -1, np.int64)
    reach = np.full(L, N + 1, np.int64)
    m, a, ph = p["motion"], p["strength"], (t % 1.0) * p["speed"]
    f = None
    if m in ("drip", "melt"):
        r = _rand(p["seed"], lines, 3)
        g = _wave(ph + r) if m == "drip" else _wave(ph - 0.15 * r)
        f = (1.0 - a * (1.0 - g)) ** 2  # 1 = fully dripped, (1 - strength)^2 = barely
        if p["mode"] == "sort":
            cap = cap * f
    caps = np.maximum(2, cap.astype(np.int64))
    spills = (spill_f * caps).astype(np.int64)
    if f is not None and p["mode"] == "melt":
        # no streak is longer than its cap plus spill, so a full reach changes nothing
        reach = np.maximum(1, ((caps + spills) * f).astype(np.int64))
    if m == "pour":
        off = np.mod(np.floor(_rand(p["seed"], lines, 4) * caps - ph * caps), caps).astype(np.int64)
    return caps, spills, off, reach


@njit(parallel=True, cache=True, nogil=True)
def _streaks(px, key, mask, mode, caps, spills, offs, reach, persist, follow, edge, reverse):
    """px (L,N,3) uint8, key (L,N) float32, mask (L,N) bool, per-line plan from line_plan -> new (L,N,3) uint8.

    A run starts at a masked pixel and goes on while pixels stay masked, up to the line's cap (or the next grid
    line); a run that ends on the mask then spills further.
    mode 0 melts: the run holds the colour it started with (fading by `persist`) and drags it along, until it
    meets a pixel that is darker (follow 0), lighter (1) or different (2) by more than `edge`, which starts a
    fresh streak; past `reach` px from a streak's start the picture shows through until the next one.
    mode 1 sorts the run by key.
    """
    L, N = key.shape
    out = px.copy()
    for l in prange(L):
        cap = caps[l]
        spill = spills[l]
        off = offs[l]
        far = reach[l]
        i = 0
        while i < N:
            if not mask[l, i]:
                i += 1
                continue
            j = i + 1
            if off < 0:
                while j < N and mask[l, j] and j - i < cap:
                    j += 1
            else:
                while j < N and mask[l, j] and (j + off) % cap != 0:
                    j += 1
            end = j
            if j >= N or not mask[l, j]:
                end = min(N, j + spill)
            if end - i > 1:
                if mode == 0:
                    r = float(px[l, i, 0])
                    g = float(px[l, i, 1])
                    b = float(px[l, i, 2])
                    held = key[l, i]
                    start = i
                    w = 1.0 - persist
                    for k in range(i + 1, end):
                        d = key[l, k] - held
                        is_edge = (follow == 0 and -d > edge) or (follow == 1 and d > edge) or (
                            follow == 2 and abs(d) > edge)
                        if is_edge or k - start > far:  # a new streak, or past its reach: the picture shows
                            r = float(px[l, k, 0])
                            g = float(px[l, k, 1])
                            b = float(px[l, k, 2])
                            held = key[l, k]
                            if is_edge:
                                start = k
                            continue
                        r = r * persist + px[l, k, 0] * w
                        g = g * persist + px[l, k, 1] * w
                        b = b * persist + px[l, k, 2] * w
                        held = held * persist + key[l, k] * w
                        out[l, k, 0] = np.uint8(r + 0.5)
                        out[l, k, 1] = np.uint8(g + 0.5)
                        out[l, k, 2] = np.uint8(b + 0.5)
                else:
                    seg = key[l, i:end].copy()
                    if reverse:
                        seg = -seg
                    order = np.argsort(seg, kind="mergesort")
                    for k in range(end - i):
                        src = i + order[k]
                        out[l, i + k, 0] = px[l, src, 0]
                        out[l, i + k, 1] = px[l, src, 1]
                        out[l, i + k, 2] = px[l, src, 2]
            i = max(end, i + 1)
    return out


# --------------------------------------------------------------------------- stages

def sort_key(img, kind):
    if kind == "hue":
        return cv2.cvtColor(img, cv2.COLOR_RGB2HSV_FULL)[..., 0].astype(np.float32) / 255.0
    if kind == "saturation":
        return cv2.cvtColor(img, cv2.COLOR_RGB2HSV_FULL)[..., 1].astype(np.float32) / 255.0
    return luma(img)


def luma(img):
    return cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_RGB2GRAY).astype(np.float32) * (1.0 / 255.0)


def drip(img, p, direction=None, t=0.0):
    """The streak pass on its own (no wash, no window), at loop time t.

    With width > 1 the streaks are worked out on lines `width` px wide and stretched back with nearest
    sampling, so they come out chunky; pixels the pass leaves alone keep the full-resolution original.
    """
    d = direction or p["direction"]
    lines = to_lines(img, d)
    L, N = lines.shape[:2]
    s = p["width"]
    small = lines
    if s > 1 and L > s:
        small = cv2.resize(lines, (N, max(1, int(round(L / s)))), interpolation=cv2.INTER_AREA)
    key = sort_key(small, p["key"])
    lo, hi = min(p["lo"], p["hi"]), max(p["lo"], p["hi"])
    if p["motion"] == "breathe":
        hi = max(lo, hi - p["strength"] * 0.45 * float(_wave((t % 1.0) * p["speed"])))
    mask = (key >= lo) & (key <= hi)
    if p["invert"]:
        mask = ~mask
    caps, spills, offs, reach = line_plan(p, small.shape[0], N, t)
    out = _streaks(small, key, mask, 0 if p["mode"] == "melt" else 1, caps, spills, offs, reach, p["melt"],
                   FOLLOWS.index(p["follow"]), p["edge"], p["reverse"])
    if small is not lines:
        changed = np.any(out != small, axis=2).astype(np.uint8)
        changed = cv2.resize(changed, (N, L), interpolation=cv2.INTER_NEAREST).astype(bool)
        out = np.where(changed[..., None], cv2.resize(out, (N, L), interpolation=cv2.INTER_NEAREST), lines)
    return from_lines(out, d)


def wash(img, palette, amount, keep=0.0):
    """Three-stop gradient map on luminance, with `keep` of the picture's own colour laid back on top."""
    if amount <= 0 or palette not in PALETTES:
        return img
    return _wash(np.ascontiguousarray(img), _palette_lut(palette).astype(np.float32), float(amount), float(keep))


@njit(parallel=True, cache=True, nogil=True)
def _wash(img, lut, amount, keep):
    H, W, _ = img.shape
    out = np.empty_like(img)
    rest = 1.0 - amount
    for y in prange(H):
        for x in range(W):
            r = float(img[y, x, 0])
            g = float(img[y, x, 1])
            b = float(img[y, x, 2])
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            li = min(255, int(lum + 0.5))
            o = r * rest + (lut[li, 0] + (r - lum) * keep) * amount
            out[y, x, 0] = np.uint8(min(255.0, max(0.0, o + 0.5)))
            o = g * rest + (lut[li, 1] + (g - lum) * keep) * amount
            out[y, x, 1] = np.uint8(min(255.0, max(0.0, o + 0.5)))
            o = b * rest + (lut[li, 2] + (b - lum) * keep) * amount
            out[y, x, 2] = np.uint8(min(255.0, max(0.0, o + 0.5)))
    return out


_LUTS = {}


def _palette_lut(name):
    if name not in _LUTS:
        s, m, h = (np.array(c, np.float32) for c in PALETTES[name])
        t = np.linspace(0.0, 1.0, 256, dtype=np.float32)[:, None]
        lower = s + (m - s) * np.clip(t * 2.0, 0, 1)
        upper = m + (h - m) * np.clip(t * 2.0 - 1.0, 0, 1)
        _LUTS[name] = np.clip(np.where(t < 0.5, lower, upper) + 0.5, 0, 255).astype(np.uint8)
    return _LUTS[name]


def fringe(img, px, direction):
    """Red and blue slide apart along the streaks, leaving lavender/teal edges."""
    if px <= 0:
        return img
    axis = 0 if direction in ("down", "up") else 1
    sign = 1 if direction in ("down", "right") else -1
    out = img.copy()
    out[..., 0] = _shift(img[..., 0], -sign * px, axis)
    out[..., 2] = _shift(img[..., 2], sign * px, axis)
    return out


def _shift(ch, d, axis):
    """Shift one channel by d px along axis, repeating the edge pixels (no wrap-around)."""
    n = ch.shape[axis]
    idx = np.clip(np.arange(n) - d, 0, n - 1)
    return np.take(ch, idx, axis=axis)


def window_rect(p, w, h):
    x0 = int(round(p["win_x"] * w))
    y0 = int(round(p["win_y"] * h))
    x1 = min(w, x0 + max(2, int(round(p["win_w"] * w))))
    y1 = min(h, y0 + max(2, int(round(p["win_h"] * h))))
    x0, y0 = min(x0, w - 2), min(y0, h - 2)
    return x0, y0, max(x0 + 2, x1), max(y0 + 2, y1)


def render(img, p=None, t=0.0):
    """Full look at loop time t: streaks, then the inset window, then the colour wash and fringe over everything.

    `width` and `fringe` are px on a 1920-px frame and scale with the picture, so a small preview and the
    full-size export look the same.
    """
    p = params(p)
    t = float(t) % 1.0
    if p["motion"] == "glitch":  # a new streak pattern 2..16 times per cycle
        p["seed"] = (p["seed"] + int(math.floor(t * p["speed"] * (2 + round(p["strength"] * 14))))) & 0x7FFFFFFF
    img = np.ascontiguousarray(img[..., :3], dtype=np.uint8)
    h, w = img.shape[:2]
    s = max(h, w) / 1920.0
    p["width"] = max(1, int(round(p["width"] * s)))
    p["fringe"] = max(1, int(round(p["fringe"] * s))) if p["fringe"] else 0
    out = drip(img, p, t=t)
    if p["window"] != "off":
        x0, y0, x1, y1 = window_rect(p, w, h)
        crop = np.ascontiguousarray(img[y0:y1, x0:x1])
        if p["window"] == "clean":
            inner = crop
        else:
            inner = drip(crop, p, (_PERP if p["window"] == "cross" else _FLIP)[p["direction"]], t)
        out[y0:y1, x0:x1] = inner
    out = wash(out, p["palette"], p["wash"], p["color"])
    return fringe(out, p["fringe"], p["direction"])


def warm_up():
    """Compile the kernel (or load it from the numba cache) so the first preview is quick."""
    render(np.zeros((8, 8, 3), np.uint8), {"mode": "melt"})
    render(np.zeros((8, 8, 3), np.uint8), {"mode": "sort", "motion": "pour"})
