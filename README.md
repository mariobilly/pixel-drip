# Pixel Drip

A melting pixel-sort look for your photos and videos: dark shapes drip down over light ones in chunky streaks, under
a soft colour wash. Photos can also move, as a seamless MP4 loop.

**Everything runs on your computer. No account, no API key, nothing is uploaded.**

Inspired by the melting pixel-sort look in a DIY-camera reel by
[André Oliveira Cebola](https://www.instagram.com/reel/DdyzoCDh_lK/). Pixel Drip is an independent project and
shares no code with it.

## Install

You need:
- Windows 10 or 11 (it is built and tested on Windows 11)
- [Python](https://www.python.org/downloads/) 3.11 or newer
- [ffmpeg](https://ffmpeg.org/download.html) on your PATH (ffmpeg and ffprobe), for videos and MP4 export
- Google Chrome or Microsoft Edge: the app opens in its own window

```
python -m pip install -r requirements.txt
python launch.pyw
```

The first start takes a little longer: numba compiles the effect once.

Optional: `powershell -ExecutionPolicy Bypass -File make_shortcut.ps1` puts a **Pixel Drip** shortcut on your
Desktop. You can drop a photo or video onto it, or into the window.

## How it works
1. **Open** a photo (PNG, JPG, WebP, TIFF, BMP) or a video (MP4, MOV, WebM, MKV, AVI, GIF).
2. Pick a **preset**. The thumbnails show each one on your own picture:
   - **Blush Melt**: dark shapes drip down over light ones under a blush-pink wash.
   - **Palm Drip**: finer, longer drips with a lavender fringe.
   - **Selarón Smear**: horizontal smears in the original colours.
   - **Camera Window**: a horizontal sort with a vertically sorted inset, like looking through a camera's screen.
   - **Sorted Rain**, **Lilac Haze**, **Rising Ember**, **Raw Drip**.
3. Fine-tune in the right panel. Double-click a slider to reset it.
   - **Streaks**:
     - **direction**;
     - **Melt** (each streak holds a colour and drags it along) or **Sort** (each run is sorted by brightness);
     - **width** (chunky like a low-res camera, or fine);
     - **max length**, **ragged ends**, and **overflow** (how far streaks run past where they would stop).
   - **Which pixels**: only pixels whose brightness, hue or saturation is inside the range are streaked. Bright skies
     stay clean by default.
   - **Melt**:
     - **Hold**: 1 keeps one solid colour, lower values fade the streak out.
     - **Drips**: a new streak starts where the picture gets darker, lighter, or at any edge.
   - **Colour**: wash palette (blush, lilac, ember, sea, mono, none), wash strength, how much original colour is
     kept, and the red/blue **fringe**.
   - **Window**: an inset rectangle shown streaked **cross**-wise, **flip**ped, or **clean**. Drag it on the preview;
     drag its corner to resize.
   - **Seed**: a different streak pattern. The same seed always gives the same streaks, so videos don't flicker.
   - **Video → New streak pattern every N frames**: re-rolls the pattern for a stuttering, animated look.
   - **Motion** makes the effect move, on photos and videos:
     - **Drip**: every streak stretches and shrinks at its own pace, like dripping paint.
     - **Melt**: the picture melts down, then rewinds.
     - **Pour**: streaks flow down without stopping, like a waterfall.
     - **Breathe**: the streaked area swells and shrinks.
     - **Glitch**: jumps between streak patterns, like a glitching camera.

     Each motion has **Strength** and a speed setting.
     - **Photo**: set the **Loop length** and frame rate. Press **▶** (or **P**) to play it in the preview, or
       drag the loop bar.
     - **Video**: the motion runs along with the clip, one cycle every **Cycle length** seconds. Each frame's
       preview shows exactly what the export will have at that point. **▶** previews the motion on the current
       frame, and pausing returns to the clip's own time.
4. Hold **Space** to see the original. Press **R** to randomize, **Ctrl+O** to open a file, **Ctrl+E** to export.
5. **Export**:
   - Photos are saved as PNG. With **Motion** on, a photo is saved as an MP4 that is exactly one loop long, so it
     repeats without a seam.
   - Videos are saved as H.264 MP4 with the original audio. It uses NVIDIA's NVENC encoder when your GPU has one.
   - Optional size cap: 1920 or 1280 px.
   - On a fast PC, a 20 s 1080×1920 video takes about a minute.
   - Files go to `Videos\Pixel Drip` in your user folder. Set the `PIXELDRIP_OUT` environment variable to use another
     folder. Existing files are never overwritten.

## What's where
- `effect.py`: the engine. It uses numba kernels for the streaks and the colour wash. `width` and `fringe` scale
  with the picture, so the preview matches the full-size export.
- `media.py`: ffmpeg and ffprobe plumbing:
  - probe;
  - image read and write that works with accented file names;
  - grab a single frame, or pipe every frame;
  - write the MP4 with the source audio, then check it with ffprobe.
- `app.py`: a FastAPI server on `127.0.0.1:47861` for previews and exports. It quits about 20 s after the window
  closes, unless an export is still running.
- `launch.pyw`: the launcher. It opens a Chrome or Edge app window.
- `static/`: the window (HTML, CSS, JS).
- `make_icon.py`, `make_shortcut.ps1`: rebuild the icon and the Desktop shortcut.
- Your data: `%LOCALAPPDATA%\PixelDrip\`: dropped files (`uploads\`), the app window's browser profile (`window\`)
  and `app.log`.

## Tests
```
python -m unittest discover -s tests
```
The server tests use FastAPI's TestClient, which needs httpx (`python -m pip install httpx`). There are 32 tests:
- **Engine:** the streak rules, sort order, determinism, window, wash, and size scaling. For motion, it checks
  that every style loops and moves, that Strength 0 is the still look, that Melt grows, that Pour flows the right
  way, and that Glitch steps.
- **Server:** image and video previews, export on a synthetic clip with audio and an accented file name (frames,
  size and audio are checked), upload, and cancel. For motion, it checks a photo exported as a looping MP4, and
  that a video's motion follows the clip's time (an exported frame matches the render at that frame's moment
  in the cycle).

## Credits
- Inspiration: the melting pixel-sort look in a DIY-camera reel by
  [André Oliveira Cebola](https://www.instagram.com/reel/DdyzoCDh_lK/).

## Licence

MIT, see [LICENSE](LICENSE).
