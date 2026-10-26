"""xV logo: a hand-drawn cartoon TV with "xV" on its screen (ink on paper, the V in red).

    python tools/make_logo.py   -> docs/assets/xv-mark.png (transparent), xv-avatar.png (on paper), favicon.png
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "docs" / "assets"
S = 2048
INK, RED, PAPER, SCREEN = (21, 20, 18), (192, 57, 43), (242, 238, 229), (226, 233, 228)
rnd = random.Random(2610)


def wobble(pts, amp, step=12):
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(2, int(math.dist((x0, y0), (x1, y1)) / step))
        out += [[x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n] for i in range(n)]
    out.append(list(pts[-1]))
    p1, p2 = rnd.random() * 6, rnd.random() * 6
    for i, p in enumerate(out):
        p[0] += amp * math.sin(i * .05 + p1)
        p[1] += amp * math.sin(i * .041 + p2)
    return out


def stroke(d, pts, w):
    for i, (x, y) in enumerate(pts):
        k = i / max(1, len(pts) - 1)
        ww = w * (.88 + .12 * math.sin(k * math.pi)) * (.95 + .05 * math.sin(i * .23))
        d.ellipse([x - ww / 2, y - ww / 2, x + ww / 2, y + ww / 2], fill=255)


def rounded(x0, y0, x1, y1, r, n=10):
    """points around a rounded rectangle (closed)"""
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts + [pts[0]]


def ink(mask, colour):
    noise = Image.effect_noise((S, S), 46).filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 255 if v > 70 else int(v * 2.6))
    layer = Image.new("RGBA", (S, S), colour + (0,))
    layer.putalpha(ImageChops.multiply(mask, noise))
    return layer


def fill(points, colour):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in points], fill=255)
    layer = Image.new("RGBA", (S, S), colour + (0,))
    layer.putalpha(m)
    return layer


def mark():
    layers = []
    body = rounded(330, 640, 1720, 1600, 150)
    screen = rounded(450, 760, 1380, 1480, 110)
    layers.append(fill(wobble(body, 4), PAPER))
    layers.append(fill(wobble(screen, 3), SCREEN))
    L = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(L)
    stroke(d, wobble(body, 6), 74)                                       # TV body
    stroke(d, wobble(screen, 5), 52)                                     # screen
    stroke(d, wobble([(860, 640), (640, 330)], 4), 44)                   # antennae
    stroke(d, wobble([(1060, 640), (1300, 300)], 4), 44)
    for cx, cy, r in ((1550, 880, 70), (1550, 1100, 70)):                # knobs
        stroke(d, wobble([(cx + r * math.cos(a / 20 * math.pi), cy + r * math.sin(a / 20 * math.pi)) for a in range(41)], 2, 8), 34)
    stroke(d, wobble([(1490, 1300), (1610, 1300)], 2), 26)               # speaker lines
    stroke(d, wobble([(1490, 1370), (1610, 1370)], 2), 26)
    stroke(d, wobble([(560, 1600), (480, 1760)], 3), 56)                 # feet
    stroke(d, wobble([(1490, 1600), (1570, 1760)], 3), 56)
    stroke(d, wobble([(640, 1000), (850, 1250)], 4), 70)                 # the x (ink)
    stroke(d, wobble([(850, 1000), (640, 1250)], 4), 70)
    layers.append(ink(L, INK))
    D = Image.new("L", (S, S), 0)
    dots = ImageDraw.Draw(D)
    for cx, cy, r in ((640, 320, 58), (1310, 290, 58)):                  # antenna tips
        dots.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    layers.append(ink(D, INK))
    V = Image.new("L", (S, S), 0)
    stroke(ImageDraw.Draw(V), wobble([(930, 860), (1080, 1330), (1270, 840)], 5), 104)   # the V (red)
    layers.append(ink(V, RED))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for l in layers:
        out = Image.alpha_composite(out, l)
    return out


def paper():
    im = Image.new("RGB", (S, S), PAPER)
    n = Image.effect_noise((S, S), 18).convert("L")
    im = Image.blend(im, Image.merge("RGB", [n, n, n]), .06)
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(2400):
        x, y, l, a = rnd.random() * S, rnd.random() * S, 10 + rnd.random() * 40, rnd.random() * math.pi
        d.line([x, y, x + math.cos(a) * l, y + math.sin(a) * l], fill=(120, 105, 80, 22) if rnd.random() < .5 else (255, 255, 255, 60), width=2)
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    m = mark()
    m.resize((256, 256), Image.LANCZOS).save(OUT / "xv-mark.png", optimize=True)
    avatar = Image.alpha_composite(paper().convert("RGBA"), m).convert("RGB")
    avatar.resize((1024, 1024), Image.LANCZOS).save(OUT / "xv-avatar.png", optimize=True)
    avatar.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png", optimize=True)
    print("saved", [p.name for p in OUT.glob("*.png")])
