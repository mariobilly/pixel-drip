"""Draws the Pixel Drip icon (icon.png + multi-size icon.ico): a blush tile melting into streaks."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
S = 512


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((16, 16, S - 16, S - 16), radius=104, fill=(26, 20, 23, 255))
    # pale sky band, then streak columns of uneven length in the reel's colours
    top, cols = 96, 12
    x0, x1 = 88, S - 88
    w = (x1 - x0) / cols
    colours = [(252, 222, 214), (238, 176, 160), (214, 140, 126), (185, 163, 214), (122, 86, 88)]
    lengths = [0.62, 0.86, 0.7, 0.95, 0.78, 0.66, 0.9, 0.74, 0.98, 0.7, 0.82, 0.6]
    span = S - 96 - top
    d.rectangle((x0, top, x1, top + 70), fill=colours[0])
    for i in range(cols):
        L = lengths[i] * span
        bands = [(0.0, colours[1]), (0.34, colours[2]), (0.62, colours[3] if i % 3 == 1 else colours[4])]
        xa, xb = x0 + i * w, x0 + (i + 1) * w
        for j, (f, c) in enumerate(bands):
            ya = top + 70 + f * (L - 70)
            yb = top + 70 + (bands[j + 1][0] if j + 1 < len(bands) else 1.0) * (L - 70)
            d.rectangle((xa, ya, xb, yb), fill=c)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((16, 16, S - 16, S - 16), radius=104, fill=255)
    img.paste(tile, (0, 0), mask)
    return img


if __name__ == "__main__":
    im = draw()
    im.save(os.path.join(HERE, "icon.png"))
    im.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                     (256, 256)])
    print("icon.png and icon.ico written")
