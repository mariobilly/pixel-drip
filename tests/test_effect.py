"""Engine tests. Run from the app folder: python -m unittest discover -s tests"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import effect as E  # noqa: E402

RAW = {"wash": 0, "fringe": 0, "width": 1, "window": "off"}  # streak pass only, at 1-px streaks


def column(values):
    """A 1-px-wide H x 1 grey image from 0..255 values."""
    v = np.array(values, np.uint8)[:, None, None]
    return np.repeat(v, 3, axis=2)


def photo(h=120, w=90, seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.stack([(x * 255 / w), (y * 255 / h), ((x + y) * 128 / (w + h))], -1)
    return np.clip(base + rng.normal(0, 18, (h, w, 3)), 0, 255).astype(np.uint8)


class Params(unittest.TestCase):
    def test_defaults_and_clamping(self):
        p = E.params({"lo": -3, "hi": 9, "width": 500, "fringe": -2, "direction": "sideways", "bogus": 1,
                      "palette": "nope", "seed": -1})
        self.assertEqual((p["lo"], p["hi"]), (0.0, 1.0))
        self.assertEqual(p["width"], 32)
        self.assertEqual(p["fringe"], 0)
        self.assertEqual(p["direction"], E.DEFAULTS["direction"])
        self.assertEqual(p["palette"], E.DEFAULTS["palette"])
        self.assertNotIn("bogus", p)
        self.assertGreaterEqual(p["seed"], 0)

    def test_none_palette_allowed(self):
        self.assertEqual(E.params({"palette": "none"})["palette"], "none")


class Orientation(unittest.TestCase):
    def test_round_trip_every_direction(self):
        img = photo(37, 23)
        for d in E.DIRECTIONS:
            np.testing.assert_array_equal(E.from_lines(E.to_lines(img, d), d), img)

    def test_lines_start_where_streaks_start(self):
        img = photo(10, 6)
        np.testing.assert_array_equal(E.to_lines(img, "down")[2], img[:, 2])
        np.testing.assert_array_equal(E.to_lines(img, "up")[2], img[::-1, 2])
        np.testing.assert_array_equal(E.to_lines(img, "right")[3], img[3])
        np.testing.assert_array_equal(E.to_lines(img, "left")[3], img[3, ::-1])


class Streaks(unittest.TestCase):
    def test_melt_drags_dark_down_over_light(self):
        # dark pixel on top of a mid-grey run: with follow=dark it should be dragged down the run
        img = column([30] + [150] * 20)
        out = E.render(img, {**RAW, "lo": 0, "hi": 1, "melt": 1.0, "length": 1, "chaos": 0, "follow": "dark",
                             "edge": 0.1})
        self.assertTrue((out[:, 0, 0] == 30).all(), out[:, 0, 0])

    def test_melt_restarts_on_darker_edge(self):
        img = column([120] * 5 + [20] * 5 + [200] * 5)
        out = E.render(img, {**RAW, "lo": 0, "hi": 1, "melt": 1.0, "length": 1, "chaos": 0, "follow": "dark",
                             "edge": 0.1})
        self.assertEqual(list(out[:5, 0, 0]), [120] * 5)
        self.assertEqual(list(out[5:, 0, 0]), [20] * 10)  # the dark band drips over the light one

    def test_pixels_outside_the_range_stay(self):
        img = photo()
        p = {**RAW, "lo": 0.0, "hi": 0.5, "overflow": 0}
        out = E.render(img, p)
        bright = E.luma(img) > 0.5
        np.testing.assert_array_equal(out[bright], img[bright])

    def test_sort_orders_each_run_dark_first(self):
        vals = [200, 50, 120, 90, 10, 160]
        out = E.render(column(vals), {**RAW, "mode": "sort", "lo": 0, "hi": 1, "length": 1, "chaos": 0})
        self.assertEqual(list(out[:, 0, 0]), sorted(vals))
        out = E.render(column(vals), {**RAW, "mode": "sort", "lo": 0, "hi": 1, "length": 1, "chaos": 0,
                                      "reverse": True})
        self.assertEqual(list(out[:, 0, 0]), sorted(vals, reverse=True))

    def test_sort_keeps_the_pixels(self):
        img = photo()
        out = E.render(img, {**RAW, "mode": "sort", "direction": "right"})
        for y in range(img.shape[0]):
            a = sorted(map(tuple, img[y]))
            b = sorted(map(tuple, out[y]))
            self.assertEqual(a, b)

    def test_length_cap_limits_streaks(self):
        img = column([10] + [200] * 99)
        out = E.render(img, {**RAW, "lo": 0, "hi": 1, "melt": 1.0, "length": 0.2, "chaos": 0, "overflow": 0,
                             "follow": "any", "edge": 1.0})
        self.assertTrue((out[:20, 0, 0] == 10).all())
        self.assertEqual(out[20, 0, 0], 200)  # a new run starts on the original pixel

    def test_same_settings_same_result(self):
        img = photo(seed=3)
        p = {"seed": 11, "chaos": 0.9}
        np.testing.assert_array_equal(E.render(img, p), E.render(img, p))
        self.assertFalse(np.array_equal(E.render(img, p), E.render(img, {**p, "seed": 12})))


class Look(unittest.TestCase):
    def test_every_option_runs_on_odd_sizes(self):
        for shape in ((1, 1), (3, 7), (31, 17), (64, 129)):
            img = photo(*shape)
            for d in E.DIRECTIONS:
                for mode in E.MODES:
                    for win in E.WINDOW_MODES:
                        for key in E.KEYS:
                            out = E.render(img, {"direction": d, "mode": mode, "window": win, "key": key,
                                                 "width": 9, "fringe": 30})
                            self.assertEqual(out.shape, img.shape)
                            self.assertEqual(out.dtype, np.uint8)

    def test_rgba_input_is_accepted(self):
        img = np.dstack([photo(), np.full((120, 90), 255, np.uint8)])
        self.assertEqual(E.render(img).shape, (120, 90, 3))

    def test_clean_window_shows_the_original(self):
        img = photo(200, 100)
        p = E.params({**RAW, "window": "clean", "win_x": 0.2, "win_y": 0.3, "win_w": 0.5, "win_h": 0.4})
        out = E.render(img, p)
        x0, y0, x1, y1 = E.window_rect(p, 100, 200)
        np.testing.assert_array_equal(out[y0:y1, x0:x1], img[y0:y1, x0:x1])

    def test_wash_pulls_toward_palette(self):
        white = np.full((4, 4, 3), 255, np.uint8)
        out = E.wash(white, "blush", 1.0, 0.0)
        self.assertEqual(tuple(out[0, 0]), E.PALETTES["blush"][2])
        np.testing.assert_array_equal(E.wash(white, "blush", 0.0), white)
        np.testing.assert_array_equal(E.wash(white, "none", 1.0), white)

    def test_wash_keeps_colour_when_asked(self):
        red = np.zeros((2, 2, 3), np.uint8)
        red[..., 0] = 220
        flat = E.wash(red, "mono", 1.0, 0.0)
        kept = E.wash(red, "mono", 1.0, 1.0)
        self.assertEqual(flat[0, 0, 0], flat[0, 0, 1])  # mono map: grey
        self.assertGreater(int(kept[0, 0, 0]) - int(kept[0, 0, 1]), 100)  # still clearly red

    def test_width_scales_with_picture_size(self):
        small, big = photo(96, 54, 1), photo(1920, 1080, 1)
        # same settings should give the same look: compare the big render downscaled to the small one's size
        import cv2
        p = {"seed": 5}
        a = E.render(small, p).astype(np.int16)
        b = cv2.resize(E.render(big, p), (54, 96), interpolation=cv2.INTER_AREA).astype(np.int16)
        self.assertLess(np.abs(a - b).mean(), 40)


class Motion(unittest.TestCase):
    def test_off_ignores_time(self):
        img = photo(seed=4)
        np.testing.assert_array_equal(E.render(img, {}, 0.37), E.render(img, {}, 0.0))

    def test_every_motion_loops_and_moves(self):
        img = photo(160, 120, seed=5)
        for m in E.MOTIONS[1:]:
            for mode in E.MODES:
                p = {"motion": m, "mode": mode, "strength": 0.9}
                a, b = E.render(img, p, 0.0), E.render(img, p, 1.0)
                np.testing.assert_array_equal(a, b, err_msg=f"{m}/{mode} does not loop")
                moved = any(not np.array_equal(a, E.render(img, p, t)) for t in (0.25, 0.5, 0.75))
                self.assertTrue(moved, f"{m}/{mode} does not move")

    def test_zero_strength_is_the_still_look(self):
        img = photo(seed=6)
        for m in ("drip", "melt", "breathe"):
            for mode in E.MODES:
                still = E.render(img, {"mode": mode})
                np.testing.assert_array_equal(E.render(img, {"motion": m, "mode": mode, "strength": 0}, 0.3), still,
                                              err_msg=f"{m}/{mode}")

    def test_melt_starts_almost_clean_and_peaks_halfway(self):
        img = photo(200, 120, seed=7)
        p = {**RAW, "motion": "melt", "strength": 1.0}
        changed = [np.count_nonzero(np.any(E.render(img, p, t) != img, axis=2)) for t in (0.0, 0.25, 0.5)]
        self.assertLess(changed[0], changed[1])
        self.assertLess(changed[1], changed[2])

    def test_pour_flows_along_the_streak(self):
        p = E.params({"motion": "pour"})
        caps, _, off0, _ = E.line_plan(p, 50, 400, 0.10)
        _, _, off1, _ = E.line_plan(p, 50, 400, 0.12)
        first0 = (-off0) % caps  # where the first grid break sits on each line
        first1 = (-off1) % caps
        step = (first1 - first0) % caps
        self.assertTrue(((step > 0) & (step < caps // 4)).all())  # every break moved a little further along

    def test_glitch_changes_pattern_in_steps(self):
        img = photo(seed=8)
        p = {"motion": "glitch", "strength": 0.0}  # 2 patterns per cycle
        np.testing.assert_array_equal(E.render(img, p, 0.1), E.render(img, p, 0.4))
        self.assertFalse(np.array_equal(E.render(img, p, 0.1), E.render(img, p, 0.6)))


if __name__ == "__main__":
    unittest.main()
