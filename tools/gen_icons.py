# -*- coding: utf-8 -*-
"""Generate new launcher icons (deep blue glass bg + cyan spectrum bars) as RGBA PNGs."""
import struct
import zlib
import math

GRAD = [(0.00, (0x16, 0x23, 0x3A)), (0.50, (0x0C, 0x14, 0x24)), (1.00, (0x07, 0x0B, 0x14))]
BARS = [(0.40, 0.42), (0.62, 0.55), (0.92, 0.70), (0.66, 0.55), (0.44, 0.42)]  # (height_frac, width_frac)
BAR_COLOR = (0x35, 0xE0, 0xFF)
SS = 4  # supersampling


def lerp(a, b, t):
    return a + (b - a) * t


def make_png_rgba(w, h, px):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend(px(x, y))
    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        return c + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def round_rect(x, y, w, h, r):
    """distance < 0 inside rounded rect, 0 on edge, >0 outside (with aa at 0)"""
    cx = max(r, min(x, w - r))
    cy = max(r, min(y, h - r))
    dx = x - cx
    dy = y - cy
    d = math.hypot(dx, dy) - r
    return d


def rounded_bar(x, y, w, h, r):
    """coverage 0..1 of a rounded vertical bar"""
    return min(1.0, max(0.0, 0.5 - round_rect(x, y, w, h, r)))


def gen_icon(size):
    def pixel(x, y):
        # supersampled coordinate -> base coordinate
        bx = (x + 0.5) / SS
        by = (y + 0.5) / SS
        # background gradient
        t = by / size
        for i in range(len(GRAD) - 1):
            p0, c0 = GRAD[i]
            p1, c1 = GRAD[i + 1]
            if p0 <= t <= p1:
                tt = (t - p0) / (p1 - p0)
                bg = tuple(int(lerp(c0[j], c1[j], tt)) for j in range(3))
                break
        else:
            bg = GRAD[-1][1]
        # rounded rect mask (radius ~ 22% of size)
        r = size * 0.22
        edge = round_rect(bx, by, size, size, r)
        cov_bg = min(1.0, max(0.0, 0.5 - edge))
        # glyph: 5 spectrum bars
        gcov = 0.0
        bar_w = size * 0.075
        gap = (size - 5 * bar_w) / 6
        base_y = size * 0.78
        for i, (hf, wf) in enumerate(BARS):
            bx0 = gap + i * (bar_w + gap)
            bw = bar_w * wf
            bh = size * hf
            gcov = max(gcov, rounded_bar(bx0 + (bar_w - bw) / 2, base_y - bh, bw, bh, bw / 2))
        # composite
        glyph = tuple(int(lerp(bg[j], BAR_COLOR[j], gcov)) for j in range(3))
        alpha = int(cov_bg * 255)
        # subtle bottom darkening on the glyph
        return (glyph[0], glyph[1], glyph[2], alpha)
    # supersample
    data = bytearray()
    for y in range(size * SS):
        for x in range(size * SS):
            r, g, b, a = pixel(x, y)
            data += bytes((r, g, b, a))
    # downsample with alpha premultiplied-ish averaging
    out = bytearray()
    for y in range(size):
        for x in range(size):
            rs = gs = bs = as_ = 0
            for sy in range(SS):
                for sx in range(SS):
                    i = ((y * SS + sy) * size * SS + (x * SS + sx)) * 4
                    r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
                    as_ += a
                    rs += r * a
                    gs += g * a
                    bs += b * a
            n = SS * SS
            a = as_ // n
            if a > 0:
                r = rs // max(1, as_)
                g = gs // max(1, as_)
                b = bs // max(1, as_)
            else:
                r = g = b = 0
            out += bytes((r, g, b, a))
    return make_png_rgba(size, size, lambda x, y: bytes(out[(y * size + x) * 4:(y * size + x) * 4 + 4]))


if __name__ == '__main__':
    targets = [
        ('mod/res/u3.png', 48),
        ('mod/res/SD.png', 72),
        ('mod/res/jy.png', 96),
        ('mod/res/D2.png', 144),
        ('mod/res/CG.png', 192),
    ]
    import os
    os.makedirs('mod/res', exist_ok=True)
    for path, size in targets:
        png = gen_icon(size)
        open(path, 'wb').write(png)
        print('wrote', path, len(png), 'bytes')
