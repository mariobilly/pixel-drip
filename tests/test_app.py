"""Server + ffmpeg pipeline tests on a synthetic clip with audio and an accented file name.

Run from the app folder: python -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import cv2
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="pixeldrip-test-")
os.environ["PIXELDRIP_DATA"] = os.path.join(TMP, "data")
os.environ["PIXELDRIP_OUT"] = os.path.join(TMP, "out")
os.environ["PIXELDRIP_STAY"] = "1"
sys.path.insert(0, HERE)

from fastapi.testclient import TestClient  # noqa: E402

import app as A  # noqa: E402
import effect as E  # noqa: E402
import media as M  # noqa: E402

CLIP = os.path.join(TMP, "Clipé ü test.mp4")
PHOTO = os.path.join(TMP, "Fotó 写真.png")  # a combining accent (o + U+0301) and CJK characters


def setUpModule():
    subprocess.run([M.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "1.5", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", CLIP], check=True)
    rng = np.random.default_rng(1)
    M.write_image(PHOTO, rng.integers(0, 255, (300, 200, 3), dtype=np.uint8))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def decode_jpeg(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def wait_job(c, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get("/api/job").json()
        if j["state"] != "running":
            return j
        time.sleep(0.1)
    raise AssertionError("export did not finish")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = TestClient(A.app)

    def test_ping_and_state(self):
        self.assertEqual(self.c.get("/api/ping").json()["app"], "pixel-drip")
        st = self.c.get("/api/state").json()
        self.assertIn("blush", st["palettes"])
        self.assertEqual(st["out_dir"], os.environ["PIXELDRIP_OUT"])
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/static/app.js").status_code, 200)
        self.assertEqual(self.c.get("/static/../app.py").status_code, 404)

    def test_unsupported_file(self):
        bad = os.path.join(TMP, "notes.txt")
        with open(bad, "w") as f:
            f.write("hi")
        r = self.c.post("/api/load", json={"path": bad})
        self.assertEqual(r.status_code, 400)
        self.assertIn("opens photos", r.json()["detail"])

    def test_image_preview_and_export(self):
        m = self.c.post("/api/load", json={"path": PHOTO}).json()["media"]
        self.assertEqual((m["kind"], m["width"], m["height"]), ("image", 200, 300))
        r = self.c.post("/api/preview", json={"params": {}, "side": 150})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(decode_jpeg(r.content).shape, (150, 100, 3))
        r = self.c.post("/api/preview", json={"original": True, "side": 300})
        self.assertEqual(decode_jpeg(r.content).shape, (300, 200, 3))
        self.c.post("/api/export", json={"params": {"window": "cross"}})
        j = wait_job(self.c)
        self.assertEqual(j["state"], "done", j)
        self.assertTrue(j["out"].endswith("Fotó 写真 - Pixel Drip.png"))
        self.assertEqual(M.read_image(j["out"]).shape, (300, 200, 3))
        # a second export never overwrites the first
        self.c.post("/api/export", json={"params": {}})
        j2 = wait_job(self.c)
        self.assertNotEqual(j2["out"], j["out"])
        self.assertTrue(os.path.exists(j["out"]) and os.path.exists(j2["out"]))

    def test_photo_in_motion_exports_a_looping_mp4(self):
        self.c.post("/api/load", json={"path": PHOTO})
        a = self.c.post("/api/preview", json={"params": {"motion": "melt"}, "side": 150, "t": 0.0}).content
        b = self.c.post("/api/preview", json={"params": {"motion": "melt"}, "side": 150, "t": 0.5}).content
        self.assertNotEqual(a, b)
        self.c.post("/api/export", json={"params": {"motion": "pour"}, "loop": 1.5, "fps": 24})
        j = wait_job(self.c)
        self.assertEqual(j["state"], "done", j)
        self.assertEqual((j["kind"], j["total"]), ("animation", 36))
        self.assertTrue(j["out"].endswith(".mp4"))
        self.assertEqual(j["report"]["problems"], [], j["report"])
        self.assertEqual((j["report"]["width"], j["report"]["height"], j["report"]["frames"]), (200, 300, 36))
        self.assertFalse(j["report"]["audio"])

    def test_video_motion_time_follows_the_clip(self):
        info = {"fps_num": 30, "fps_den": 1}
        self.assertEqual(A.video_t(0, info, 3.0), 0.0)
        self.assertAlmostEqual(A.video_t(45, info, 3.0), 0.5)
        self.assertAlmostEqual(A.video_t(100, info, 3.0), 1 / 9)  # 3.33 s: a ninth into the second 3 s cycle

    def test_video_motion_preview_and_export(self):
        self.c.post("/api/load", json={"path": CLIP})
        p = {"motion": "melt", "strength": 1.0, "wash": 0, "fringe": 0}
        a = self.c.post("/api/preview", json={"params": p, "frame": 5, "side": 160, "t": 0.0}).content
        b = self.c.post("/api/preview", json={"params": p, "frame": 5, "side": 160, "t": 0.5}).content
        self.assertNotEqual(a, b)

        self.c.post("/api/export", json={"params": p, "loop": 1.0})
        j = wait_job(self.c)
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(j["kind"], "video")
        self.assertEqual(j["report"]["problems"], [], j["report"])
        self.assertEqual(j["report"]["frames"], 45)
        self.assertTrue(j["report"]["audio"])
        # frame 15 of the export is the melt at 0.5 s into a 1 s cycle (fully melted), not at its start
        info = M.probe(CLIP)
        src = M.read_frame(CLIP, info, 15, 180, 320).astype(int)
        got = M.read_frame(j["out"], M.probe(j["out"]), 15, 180, 320).astype(int)
        at_time = E.render(src.astype(np.uint8), p, A.video_t(15, info, 1.0)).astype(int)
        at_start = E.render(src.astype(np.uint8), p, 0.0).astype(int)
        self.assertLess(np.abs(got - at_time).mean(), np.abs(got - at_start).mean() * 0.5)

    def test_upload(self):
        with open(PHOTO, "rb") as f:
            r = self.c.post("/api/upload", params={"name": "dropped é.png"}, content=f.read())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["media"]["name"], "dropped é.png")

    def test_video_preview_and_export_keeps_audio(self):
        m = self.c.post("/api/load", json={"path": CLIP}).json()["media"]
        self.assertEqual((m["kind"], m["width"], m["height"], m["frames"]), ("video", 180, 320, 45))
        self.assertTrue(m["has_audio"])
        for frame in (0, 20, 44):
            r = self.c.post("/api/preview", json={"params": {"direction": "right"}, "frame": frame, "side": 160})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(decode_jpeg(r.content).shape, (160, 90, 3))
        # different frames really are different frames
        a = decode_jpeg(self.c.post("/api/preview", json={"original": True, "frame": 0, "side": 160}).content)
        b = decode_jpeg(self.c.post("/api/preview", json={"original": True, "frame": 30, "side": 160}).content)
        self.assertGreater(np.abs(a.astype(int) - b.astype(int)).mean(), 2)

        self.c.post("/api/export", json={"params": {}, "shuffle": 10})
        j = wait_job(self.c)
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(j["report"]["problems"], [], j["report"])
        self.assertTrue(j["report"]["audio"])
        self.assertEqual(j["report"]["frames"], 45)
        self.assertEqual((j["report"]["width"], j["report"]["height"]), (180, 320))

    def test_cancel_video_export(self):
        self.c.post("/api/load", json={"path": CLIP})
        A.CANCEL.set()  # cancel lands before the first frame is written
        orig = A.CANCEL.clear
        A.CANCEL.clear = lambda: None
        try:
            self.c.post("/api/export", json={"params": {}})
            j = wait_job(self.c)
        finally:
            A.CANCEL.clear = orig
            A.CANCEL.clear()
        self.assertEqual(j["state"], "cancelled")
        leftovers = [f for f in os.listdir(os.environ["PIXELDRIP_OUT"]) if ".part" in f]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
