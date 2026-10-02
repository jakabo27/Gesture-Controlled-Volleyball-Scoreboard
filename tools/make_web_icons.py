"""Draws the phone page's icons (web/icon.svg, icon-192.png, icon-512.png): a rainbow "2" and a blue "1"
in the same LED-dot style and FastLED colors as the page. Usage: python tools/make_web_icons.py"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')

SEGMENTS = [(8, 162, 8, 98), (8, 82, 8, 18), (18, 8, 82, 8), (92, 18, 92, 82),
            (82, 90, 18, 90), (92, 98, 92, 162), (82, 172, 18, 172)]
GLYPHS = {2: [1, 0, 1, 1, 1, 0, 1], 1: [0, 0, 0, 1, 0, 1, 0]}


def scale8(i, s):
    return (i * (1 + s)) >> 8


def rainbow(hue):  # FastLED hsv2rgb_rainbow, full saturation and value (same as web/protocol.js)
    hue &= 0xFF
    o8 = (hue & 0x1F) << 3
    t, tt = scale8(o8, 85), scale8(o8, 170)
    if not hue & 0x80:
        if not hue & 0x40:
            return (255 - t, t, 0) if not hue & 0x20 else (171, 85 + t, 0)
        return (171 - tt, 170 + t, 0) if not hue & 0x20 else (0, 255 - t, t)
    if not hue & 0x40:
        return (0, 171 - tt, 85 + tt) if not hue & 0x20 else (t, 0, 255 - t)
    return (85 + t, 0, 171 - t) if not hue & 0x20 else (170 + t, 0, 85 - t)


def leds():
    """(x, y, (r, g, b), lit) for both digits in a 218 x 180 box."""
    out = []
    for d, (glyph, color) in enumerate([(2, 'rainbow'), (1, 160)]):
        for s, (x1, y1, x2, y2) in enumerate(SEGMENTS):
            for p in range(9):
                t = p / 8
                lit = GLYPHS[glyph][s]
                c = rainbow((s * 9 + p) * 255 // 63) if color == 'rainbow' else rainbow(color)
                out.append((d * 118 + x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, c, lit))
    return out


def png(size):
    ss = 4
    img = Image.new('RGB', (size * ss, size * ss), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size * ss * 0.62 / 218          # keep inside the maskable safe zone
    ox = (size * ss - 218 * scale) / 2
    oy = (size * ss - 180 * scale) / 2
    r = 4.4 * scale
    for x, y, c, lit in leds():
        cx, cy = ox + x * scale, oy + y * scale
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c if lit else (34, 34, 34))
    img.resize((size, size), Image.LANCZOS).save(os.path.join(WEB, 'icon-%d.png' % size), optimize=True)


def svg():
    dots = ''.join('<circle cx="%.1f" cy="%.1f" r="4.4" fill="%s"/>' % (
        x, y, 'rgb(%d,%d,%d)' % c if lit else '#222') for x, y, c, lit in leds())
    with open(os.path.join(WEB, 'icon.svg'), 'w', newline='\n') as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-41 -60 300 300">'
                '<rect x="-41" y="-60" width="300" height="300" rx="60" fill="#000"/>%s</svg>\n' % dots)


if __name__ == '__main__':
    svg()
    png(192)
    png(512)
    print('icons written to', WEB)
