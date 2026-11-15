"""Generate the SWManager logo (PNG + ICO). Reproducible: `python make_logo.py`."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = 512
RADIUS = 116
TOP = (58, 128, 246)      # blu
BOTTOM = (124, 72, 232)    # viola


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def vertical_gradient(size, top, bottom):
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return grad.resize((size, size))


def main():
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = vertical_gradient(SIZE, TOP, BOTTOM).convert("RGBA")
    base.paste(grad, (0, 0), rounded_mask(SIZE, RADIUS))

    d = ImageDraw.Draw(base)
    # Three horizontal "sliders" with knobs: evoke a control panel.
    rows = [(150, 0.66), (256, 0.38), (362, 0.58)]
    bar_x0, bar_x1 = 120, 392
    track = (255, 255, 255, 90)
    knob = (255, 255, 255, 255)
    bar_h = 26
    knob_r = 34
    for cy, pos in rows:
        d.rounded_rectangle([bar_x0, cy - bar_h // 2, bar_x1, cy + bar_h // 2],
                            radius=bar_h // 2, fill=track)
        kx = int(bar_x0 + (bar_x1 - bar_x0) * pos)
        d.ellipse([kx - knob_r, cy - knob_r, kx + knob_r, cy + knob_r],
                  fill=knob)
        d.ellipse([kx - knob_r + 10, cy - knob_r + 10,
                   kx + knob_r - 10, cy + knob_r - 10],
                  fill=(90, 90, 210, 255))

    out_png = os.path.join(HERE, "logo.png")
    base.save(out_png)

    # Smaller versions for the header + window icon.
    base.resize((128, 128), Image.LANCZOS).save(
        os.path.join(HERE, "logo_128.png"))
    base.save(os.path.join(HERE, "logo.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128),
                     (256, 256)])
    print("Logo generato:", out_png)


if __name__ == "__main__":
    main()
