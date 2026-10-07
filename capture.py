#!/usr/bin/env python3
"""capture.py — watch the game's Trend screen and record the results for you.

The game shows a 5x10 board of the last 50 results, newest at the bottom right.
That is the whole trick: because the board is *cumulative*, a screenshot every
few seconds captures everything. You do not need to video anything, and you do
not need to time the rounds.

    python capture.py --demo                  no game needed - proves the reader works
    python capture.py --file shot.png --report   read a screenshot and show me
    python capture.py --adb --once            one pass, tell me what you see
    python capture.py --adb                   watch and record, unattended

Requires nothing beyond the standard library. Needs an Android emulator with
ADB reachable (BlueStacks, LDPlayer, MuMu, Android Studio AVD all expose it) or
a screenshot file.

WHAT IT DOES NOT DO
  It records results; it does not place bets. Every turn it feeds the app is a
  pass - zero stake - so the bankroll never moves. That is deliberate: this tool
  exists to gather the evidence, and evidence is free.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib

from engine import safe_console

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "capture_config.json")
LOG_PATH = os.path.join(HERE, "capture_log.txt")

SYMBOLS = ("r", "b", "g")          # the app's order; the game's own order does not matter
DEFAULT_BASE = "http://127.0.0.1:8077"


# ====================================================================== images
class Img:
    """A tiny RGB image. Only what is needed: width, height, pixel lookup."""

    __slots__ = ("w", "h", "bpp", "px")

    def __init__(self, w: int, h: int, bpp: int, px: bytes) -> None:
        self.w, self.h, self.bpp, self.px = w, h, bpp, px

    def at(self, x: int, y: int):
        o = (y * self.w + x) * self.bpp
        return (self.px[o], self.px[o + 1], self.px[o + 2])

    def __repr__(self) -> str:
        return "Img(%dx%d, %dbpp)" % (self.w, self.h, self.bpp * 8)


def _png_decode(data: bytes) -> Img:
    """PNG in, pixels out. 8-bit grey / RGB / palette / RGBA only.

    Written out longhand because the project is deliberately dependency-free,
    and a decoder for the four formats a screenshot tool actually produces is
    about sixty lines.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    idat = bytearray()
    palette = b""
    w = h = depth = ctype = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8:
                raise ValueError("only 8-bit PNGs are supported (this is %d-bit)" % depth)
            if interlace:
                raise ValueError("interlaced PNGs are not supported")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if ctype not in (0, 2, 3, 4, 6):
        raise ValueError("unsupported PNG colour type %s" % ctype)

    raw = zlib.decompress(bytes(idat))
    chan = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * chan
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(chan, stride):
                line[i] = (line[i] + line[i - chan]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - chan] if i >= chan else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - chan] if i >= chan else 0
                b = prev[i]
                c = prev[i - chan] if i >= chan else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line

    if ctype == 2:
        return Img(w, h, 3, bytes(out))
    if ctype == 6:
        return Img(w, h, 4, bytes(out))
    if ctype == 0:
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            v = out[i]
            rgb[3 * i:3 * i + 3] = bytes((v, v, v))
        return Img(w, h, 3, bytes(rgb))
    if ctype == 4:
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            v = out[2 * i]
            rgb[3 * i:3 * i + 3] = bytes((v, v, v))
        return Img(w, h, 3, bytes(rgb))
    # palette
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        idx = out[i] * 3
        rgb[3 * i:3 * i + 3] = palette[idx:idx + 3]
    return Img(w, h, 3, bytes(rgb))


def _bmp_decode(data: bytes) -> Img:
    """Uncompressed BMP, as written by the PowerShell fallback."""
    if data[:2] != b"BM":
        raise ValueError("not a BMP")
    off = struct.unpack("<I", data[10:14])[0]
    w, h, _planes, bpp = struct.unpack("<iiHH", data[18:28])
    compression = struct.unpack("<I", data[30:34])[0]
    if compression != 0:
        raise ValueError("only uncompressed BMP is supported")
    if bpp not in (24, 32):
        raise ValueError("only 24- or 32-bit BMP is supported (this is %d)" % bpp)
    top_down = h < 0
    h = abs(h)
    step = bpp // 8
    row_bytes = ((w * step + 3) // 4) * 4
    rgb = bytearray(w * h * 3)
    for y in range(h):
        src_y = y if top_down else (h - 1 - y)
        base = off + src_y * row_bytes
        for x in range(w):
            b, g, r = data[base + x * step], data[base + x * step + 1], data[base + x * step + 2]
            o = (y * w + x) * 3
            rgb[o], rgb[o + 1], rgb[o + 2] = r, g, b
    return Img(w, h, 3, bytes(rgb))


def _adb_decode(data: bytes) -> Img:
    """`adb exec-out screencap` with no -p: a 12-byte header then raw pixels.

    Far better than pulling a PNG off the device - no compression to undo, so a
    whole screenshot costs milliseconds instead of seconds, which matters when
    polling for hours.
    """
    # Some adb builds hand back a finished PNG instead of the raw frame, and
    # BlueStacks' own HD-Adb.exe is one of them depending on the version. Check
    # for that first: without it the PNG's first header field is read as a frame
    # width and the answer is "unsupported screen format 218103808", which
    # explains nothing to anybody. Same for BMP.
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_decode(data)
    if data[:2] == b"BM":
        return _bmp_decode(data)
    if len(data) < 16:
        raise ValueError("screencap returned %d bytes - the device probably refused" % len(data))
    w, h, fmt = struct.unpack("<III", data[:12])
    if fmt == 1:        # RGBA_8888
        bpp, px = 4, data[12:]
        if len(px) < w * h * 4:
            raise ValueError("short screencap frame")
        return Img(w, h, 4, px)
    if fmt in (2, 3):   # RGBX_8888 / RGB_888
        bpp, px = 4, data[12:]
        if len(px) < w * h * 4:
            raise ValueError("short screencap frame")
        return Img(w, h, 4, px)
    if fmt == 4:        # RGB_565
        px = data[12:12 + w * h * 2]
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            v = px[2 * i] | (px[2 * i + 1] << 8)
            r = ((v >> 11) & 0x1F) * 255 // 31
            g = ((v >> 5) & 0x3F) * 255 // 63
            b = (v & 0x1F) * 255 // 31
            rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2] = r, g, b
        return Img(w, h, 3, bytes(rgb))
    raise ValueError("unsupported screen format %d from the device" % fmt)


def load_image(path: str) -> Img:
    data = open(path, "rb").read()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_decode(data)
    if data[:2] == b"BM":
        return _bmp_decode(data)
    if data[:2] == b"\xff\xd8":
        raise ValueError("that is a JPEG - take the screenshot as PNG instead "
                         "(a phone photo cannot be read reliably)")
    raise ValueError("unrecognised image format")


def save_png(img: Img, path: str) -> None:
    """Only used to write the --demo board so it can be looked at."""
    rows = bytearray()
    for y in range(img.h):
        rows.append(0)
        for x in range(img.w):
            r, g, b = img.at(x, y)
            rows += bytes((r, g, b))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


# ====================================================================== colour
def classify(rgb) -> "str | None":
    """rr -> red, b -> blue, g -> green, None if the pixel is not one of them.

    Thresholds are set from the real game: measured on a photo of the actual
    board the three symbols sit at roughly rgb(165,62,51) red, rgb(17,114,78)
    green and rgb(12,54,184) blue. The rules below separate those three cleanly
    and reject everything else on the screen - the orange panel (hue 24), the
    gold crowns (hue 47), the skin tones (saturation about 0.36) and the white
    tiles all fall outside.
    """
    r, g, b = rgb
    mx = r if r >= g and r >= b else (g if g >= b else b)
    mn = r if r <= g and r <= b else (g if g <= b else b)
    if mx == 0 or (mx - mn) / mx < 0.42 or mx < 80:
        return None
    h = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0] * 360.0
    if h < 18 or h >= 335:
        return "r"
    if 70 <= h < 170:
        return "g"
    if 185 <= h < 265:
        return "b"
    return None


def read_cell(img: Img, cx: int, cy: int, r: int):
    """Vote across a disc: returns (symbol or None, confidence 0..1)."""
    votes = {"r": 0, "b": 0, "g": 0}
    total = 0
    step = max(1, r // 4)
    r2 = r * r
    for dy in range(-r, r + 1, step):
        for dx in range(-r, r + 1, step):
            if dx * dx + dy * dy > r2:
                continue
            x, y = cx + dx, cy + dy
            if 0 <= x < img.w and 0 <= y < img.h:
                total += 1
                c = classify(img.at(x, y))
                if c:
                    votes[c] += 1
    if not total:
        return None, 0.0
    hit = max(votes.values())
    if hit == 0:
        return None, 0.0
    best = max(votes, key=lambda k: votes[k])
    return best, hit / float(total)


# ======================================================================== grid
def _bands(hist, thresh: float, gap: int):
    out, i, n = [], 0, len(hist)
    while i < n:
        if hist[i] >= thresh:
            j = i
            while j < n and hist[j] >= thresh:
                j += 1
            out.append([i, j - 1])
            i = j
        else:
            i += 1
    merged = []
    for b in out:
        if merged and b[0] - merged[-1][1] <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))
    return merged


def _bands(hist, thresh: float, gap: int):
    """Contiguous runs above a threshold, then merge runs separated by <= gap."""
    out, i, n = [], 0, len(hist)
    while i < n:
        if hist[i] >= thresh:
            j = i
            while j < n and hist[j] >= thresh:
                j += 1
            out.append([i, j - 1])
            i = j
        else:
            i += 1
    merged = []
    for b in out:
        if merged and b[0] - merged[-1][1] <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))
    return merged


def is_bright(rgb) -> bool:
    """The board is drawn on light rounded strips; this finds those.

    Anchoring on the strips rather than on colour is what makes the reader work
    on a real screen. A first attempt asked whether ANY symbol-coloured pixel
    appeared in a row, which is true of the whole image as soon as the crop
    includes a sliver of the game behind the popup - the reader then saw one
    enormous band and no board at all. The strips are the one thing that is
    reliably bright, wide and quiet.
    """
    r, g, b = rgb
    mx = r if r >= g and r >= b else (g if g >= b else b)
    mn = r if r <= g and r <= b else (g if g <= b else b)
    if mx < 150:
        return False
    return mx == 0 or (mx - mn) / mx <= 0.35


def _runs(flags, gap: int):
    """Contiguous runs of truthy values, merging runs separated by <= gap."""
    out, i, n = [], 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            out.append([i, j - 1])
            i = j
        else:
            i += 1
    merged = []
    for b in out:
        if merged and b[0] - merged[-1][1] <= gap:
            merged[-1][1] = b[1]
        else:
            merged.append(list(b))
    return merged


def _profile(img: Img, predicate, axis: str, lo: int = 0, hi=None, stride: int = 3) -> list:
    """How many pixels along each line satisfy the predicate."""
    if axis == "y":
        hi = img.h if hi is None else hi
        return [sum(1 for x in range(lo, img.w, stride)
                    if predicate(img.at(x, y))) for y in range(hi)]
    hi = img.w if hi is None else hi
    return [sum(1 for y in range(lo, hi, stride)
                if predicate(img.at(x, y))) for x in range(img.w)]


def find_board(img: Img):
    """Locate the five light strips. Returns (rows, x0, x1) or None.

    The strips are found by where the board is NOT, which sounds backwards and
    is not. Brightness alone does not mark a strip: a strip's top and bottom
    edges are pure white all the way across, while its middle is mostly icon,
    so the profile inside one strip can dip lower than the gap between two -
    thresholding on brightness found four bands and cut one strip in half.

    The gaps between strips really do have no white at all, so the reliable
    rule is: find the rows with almost no white, and whatever sits between them
    is a strip.
    """
    prof = _profile(img, is_bright, "y")
    peak = max(prof) if prof else 0
    if peak < img.w * 0.15:
        return None                       # no wide light strip anywhere
    # The cutoff cannot be a fixed number: how much white shows in a gap
    # depends on the art behind it, and on a photo of a screen the gap is not
    # black. So try progressively more generous cutoffs and take the first that
    # yields a plausible set of strips. On the photographed board the gaps hold
    # about 30 white pixels and the dimmest row *inside* a strip holds 86, so
    # anything between those two values works and the loop finds it.
    min_h, max_h = max(6, img.h // 60), img.h // 3
    bands = []
    # The ladder reaches quite high on purpose. A tilted board smears white
    # into the gaps, so they stop being near-empty and only read as "lower than
    # the strips" - about a third of the peak on a modest tilt. On an aligned
    # screenshot the low cutoffs succeed first and nothing changes.
    for frac in (0.05, 0.08, 0.12, 0.18, 0.25, 0.32, 0.40, 0.45):
        empty = [v < peak * frac for v in prof]
        cand = [b for b in _runs([not e for e in empty], 0)
                if min_h <= b[1] - b[0] <= max_h]
        if len(cand) >= 3:
            bands = cand
            break
    if len(bands) > 5:                    # anything shorter is not a strip
        bands = sorted(bands, key=lambda b: -(b[1] - b[0]))[:5]
    bands = sorted(bands, key=lambda b: b[0])
    if len(bands) < 3:
        return None

    # horizontal extent of the strips, trimmed so a bright patch of game art
    # outside the popup cannot widen it
    y0, y1 = bands[0][0], bands[-1][1]
    cprof = _profile(img, is_bright, "x", lo=y0, hi=y1 + 1)
    span = (y1 - y0)
    hits = [i for i, v in enumerate(cprof) if v > span * 0.03]
    if not hits:
        return None
    lo = hits[int(len(hits) * 0.02)]
    hi = hits[int(len(hits) * 0.98) - 1] if len(hits) > 5 else hits[-1]
    return bands, lo, hi


def icon_band(img: Img, strip, x0: int, x1: int):
    """The vertical extent of the symbols inside one strip.

    A strip is mostly white padding - the icons occupy about two thirds of its
    height. Profiling columns across the whole strip therefore spends most of
    its samples on padding, and with a sampling stride of three it stepped
    straight over the thin parts of a symbol and lost the last column of a row.
    Finding where the symbols actually are removes the padding from the
    question, and doubles as the tilt fix: each strip gets its own centre, so a
    photo taken at an angle is read row by row instead of on a grid drawn over
    the whole board.
    """
    y0, y1 = strip
    prof = []
    for y in range(y0, y1 + 1):
        prof.append(sum(1 for x in range(x0, x1 + 1, 2) if classify(img.at(x, y))))
    peak = max(prof) if prof else 0
    if peak < 3:
        return strip
    runs = _runs([v >= peak * 0.25 for v in prof], max(2, (y1 - y0) // 20))
    if not runs:
        return strip
    # the widest span of symbol pixels; a stray arc elsewhere in the strip
    # cannot win this
    best = max(runs, key=lambda b: sum(prof[b[0]:b[1] + 1]))
    return [y0 + best[0], y0 + best[1]]


def column_spans(img: Img, band, x0: int, x1: int, want: int = 10) -> list:
    """Where the symbols sit across one strip, as a list of (centre, width).

    Widths are not a reliable way to tell a symbol from junk: on a photo of a
    screen the icons angle away from the camera and their apparent widths range
    from 29 to 79 pixels in the same row, while a plain median-based filter
    assumed one width and discarded the narrow ones - which is how a row of ten
    icons became a row of nine.

    So widths are used only to find *roughly* where the symbols are. The
    positions are then re-fitted onto an even spacing, because that is the one
    thing genuinely known about this board: it holds exactly ten symbols, evenly
    spaced. Everything after this snaps each cell onto the real centre.
    """
    y0, y1 = band
    step = 1 if (y1 - y0) < 90 else 2
    prof = [sum(1 for y in range(y0, y1 + 1, step) if classify(img.at(x, y)))
            for x in range(x0, x1 + 1)]
    peak = max(prof) if prof else 0
    if peak < 2:
        return []
    gap = max(3, (x1 - x0) // 60)
    runs = _runs([v >= max(1, peak * 0.15) for v in prof], gap)
    runs = [[b[0] + x0, b[1] + x0] for b in runs]
    if not runs:
        return []
    widest = max(b[1] - b[0] for b in runs)
    solid = [b for b in runs if (b[1] - b[0]) >= widest * 0.25]
    if len(solid) < 3:
        return []

    if len(solid) >= want:
        # enough real spans: take the widest ten, left to right
        pick = sorted(sorted(solid, key=lambda b: -(b[1] - b[0]))[:want],
                      key=lambda b: b[0])
        centres = [(b[0] + b[1]) / 2.0 for b in pick]
        widths = [float(b[1] - b[0]) for b in pick]
    else:
        # too few spans to trust the positions: keep the first and the last and
        # spread the rest evenly between them
        cs = [b[0] for b in sorted(solid, key=lambda b: b[0])]
        lo, hi = cs[0], cs[-1]
        span_w = widest
        step_c = (hi - lo) / float(want - 1)
        centres = [lo + i * step_c for i in range(want)]
        widths = [span_w] * want
    return list(zip(centres, widths))


def snap(img: Img, cx: float, cy: float, dx: int, dy: int):
    """Nudge a nominal cell centre onto the symbol it was aiming at.

    The centroid of the symbol-coloured pixels in the neighbourhood. A ring of
    colour has its centroid at the ring's centre, so this lands on the icon even
    when the board is photographed at an angle, and moves hardly at all when the
    screenshot is clean.
    """
    sx = sy = n = 0
    x_lo, x_hi = int(cx - dx), int(cx + dx)
    y_lo, y_hi = int(cy - dy), int(cy + dy)
    for y in range(max(0, y_lo), min(img.h, y_hi + 1), 2):
        for x in range(max(0, x_lo), min(img.w, x_hi + 1), 2):
            if classify(img.at(x, y)):
                sx += x
                sy += y
                n += 1
    if n < 25:
        return cx, cy
    return sx / float(n), sy / float(n)


def detect_grid(img: Img) -> "dict | None":
    """Work out where the board is. Returns geometry, or None if not found."""
    board = find_board(img)
    if not board:
        return None
    strips, x0, x1 = board
    rows = [icon_band(img, st, x0, x1) for st in strips]
    spans = column_spans(img, rows[0], x0, x1)
    if len(spans) < 3:
        return None
    return {"w": img.w, "h": img.h, "rows": rows,
            "cols": [c for c, _w in spans],
            "col_w": [w for _c, w in spans],
            "cells": len(rows) * len(spans), "x0": x0, "x1": x1,
            "per_row": [len(column_spans(img, b, x0, x1)) for b in rows]}


def read_grid(img: Img, geom: dict) -> list:
    """Read every cell, row-major: oldest at [0], newest last.

    The board fills left to right and top to bottom and the game marks the
    newest cell "NEW", which is where the bottom-right position comes from.
    """
    out = []
    rows = geom["rows"]
    x0, x1 = geom.get("x0", 0), geom.get("x1", img.w - 1)
    rh = sum(b[1] - b[0] for b in rows) / max(len(rows), 1)
    cw = sum(geom["col_w"]) / max(len(geom["col_w"]), 1) if geom.get("col_w") else \
        (x1 - x0) / max(len(geom["cols"]), 1)
    r = max(6, int(min(rh, cw) * 0.32))
    for band in rows:
        cy0 = (band[0] + band[1]) / 2.0
        for cx0 in geom["cols"]:
            cx, cy = snap(img, cx0, cy0, int(cw * 0.45), int(rh * 0.45))
            sym, _conf = read_cell(img, int(round(cx)), int(round(cy)), r)
            out.append(sym)
    # A game with fewer than fifty results leaves the newest slots empty, and
    # the empty slots are always at the end, so trailing blanks are padding
    # rather than unreadable symbols. Dropping them keeps the sequence equal to
    # the game's actual history, which is what the alignment depends on.
    while out and out[-1] is None:
        out.pop()
    return out


# ==================================================================== tracking
def advance(prev: list, new: list):
    """Which results are new since the last look?

    Returns (results, note). An empty list means nothing changed. ``note`` is
    None on success or a short explanation of why the pair could not be
    aligned - which is a real case, not a hypothetical: if the popup is closed
    and reopened, or the game restarts, the board is unrelated and recording
    anything from it would write fiction into the ledger.
    """
    if len(prev) == len(new) and prev == new:
        return [], None

    # a young game fills up from the start: the old board is a prefix of the new
    if len(new) > len(prev) and new[:len(prev)] == prev:
        return [x for x in new[len(prev):] if x], None

    # otherwise the board slid: prev[m:] must equal new[:-m]
    if len(prev) == len(new):
        fits = [m for m in range(1, min(len(new), 7))
                if prev[m:] == new[:len(new) - m]]
        if fits:
            m = fits[0]
            fresh = [x for x in new[len(new) - m:] if x]
            if len(fits) > 1:
                return fresh, "several alignments fit (%s) - used the smallest, " \
                              "so this may under-record" % fits
            return fresh, None

    return [], ("the board does not line up with the last look - if you closed and "
                "reopened it, or the game restarted, that is expected; sitting this "
                "one out rather than guessing")


# =================================================================== buzzcast
def api(base: str, path: str, body=None, timeout: float = 10.0):
    url = base.rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


def drain(base: str, pending: list, dry_run: bool = False) -> list:
    """Feed as much of the waiting queue as the app will take.

    Returns what is still waiting, in order. This is the whole of the
    data-safety rule: results are only ever removed from the queue once the app
    has actually accepted them, so an app that is down, restarted or refusing
    cannot cause a result to be skipped. Before this, results were marked as
    seen the moment they were spotted, and an app that was down for a minute
    lost them permanently - the board had slid on by the time it came back.
    """
    if not pending:
        return []
    fed = feed(base, pending, dry_run)
    if dry_run:
        return list(pending)          # a rehearsal consumes nothing
    return list(pending[fed:])


def app_alive(base: str) -> bool:
    try:
        api(base, "/api/health", timeout=4)
        return True
    except Exception:                                              # noqa: BLE001
        return False


def feed(base: str, results: list, dry_run: bool = False) -> int:
    """Push results into the app as recorded-only turns (no stake, ever)."""
    done = 0
    for sym in results:
        if sym not in SYMBOLS:
            continue
        if dry_run:
            print("    would record %s" % sym.upper())
            done += 1
            continue
        try:
            st = api(base, "/api/state")
            if st.get("phase") != "await_result":
                # nothing is on the table, so sit the turn out first - the app
                # refuses to resolve twice, which is what stops a double-tap
                # from logging one result as two turns
                api(base, "/api/pass", {})
            turn = api(base, "/api/resolve", {"result": sym})
            pnl = (turn.get("turn") or {}).get("pnl")
            print("    recorded %-5s turn %s  pnl %s" %
                  (sym.upper(), (turn.get("turn") or {}).get("n"), pnl))
            done += 1
        except urllib.error.URLError as exc:
            print("    buzzcast is not answering at %s (%s) - stopping here"
                  % (base, exc))
            break
        except Exception as exc:                                   # noqa: BLE001
            print("    could not record %s: %s" % (sym.upper(), exc))
            break
    return done


# ================================================================== capturing
# Where the popular emulators keep the adb they ship with. Kept as path
# COMPONENTS, not as ready-made strings: glob treats a backslash as an escape
# character on anything that is not Windows, so a hard-coded "C:\\...\\adb.exe"
# pattern silently matches nothing when it is tested anywhere else. Joined with
# os.path.join it is correct on every platform, and can be tested everywhere.
ADB_PATTERNS = [
    ("Program Files", "BlueStacks*", "HD-Adb.exe"),
    ("Program Files (x86)", "BlueStacks*", "HD-Adb.exe"),
    ("BlueStacks*", "HD-Adb.exe"),
    ("LDPlayer*", "adb.exe"),
    ("LDPlayer*", "LDPlayer*", "adb.exe"),
    ("Program Files", "Netease", "MuMu*", "shell", "adb.exe"),
    ("Program Files*", "MuMu*", "shell", "adb.exe"),
    ("Program Files*", "Nox", "bin", "adb.exe"),
    ("Nox", "bin", "adb.exe"),
    ("Program Files*", "Microvirt", "MEmu", "adb.exe"),
    ("Program Files*", "Tencent", "GameLoop*", "adb.exe"),
    ("AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
]


def adb_in(homes) -> list:
    """Every adb executable living under these folders. Never raises.

    Split out from find_adbs() so a test can point it at a made-up emulator
    installation and see whether it would have been found. That test is the
    only reason to trust the search on a machine that has no emulator on it.
    """
    import glob as _glob
    found = []
    for home in homes:
        for parts in ADB_PATTERNS:
            try:
                for hit in _glob.glob(os.path.join(home, *parts)):
                    if os.path.isfile(hit) and hit not in found:
                        found.append(hit)
            except Exception:                                      # noqa: BLE001
                continue
    return found


def find_adbs(explicit=None) -> list:
    """Every adb on this machine, best first. Never raises."""
    if explicit:
        return [explicit]
    found = []
    for name in ("adb", "adb.exe"):
        try:
            subprocess.run([name, "version"], capture_output=True, timeout=10)
            found.append(name)
            break
        except Exception:                                          # noqa: BLE001
            pass
    # Search every drive root, not just C:. People install emulators on D:.
    homes = []
    for drive in ("C", "D", "E", "F", "G"):
        root = drive + ":\\"
        if os.path.isdir(root):
            homes.append(root)
    homes.append(os.path.expanduser("~") + os.sep)
    found += adb_in(homes)

    # Newest emulator install first: with two versions installed, the one most
    # recently touched is the one actually being used.
    def rank(path):
        try:
            return -os.path.getmtime(path)
        except OSError:
            return 0
    tail = sorted((f for f in found if os.path.isabs(f)), key=rank)
    head = [f for f in found if not os.path.isabs(f)]
    return head + tail


def adb_executable(explicit=None) -> "str | None":
    hits = find_adbs(explicit)
    return hits[0] if hits else None


def adb_devices(adb: str) -> list:
    """The serials of the emulators adb can actually talk to."""
    try:
        out = subprocess.run([adb, "devices"], capture_output=True,
                             timeout=30).stdout.decode("utf-8", "replace")
    except Exception:                                              # noqa: BLE001
        return []
    devs = []
    for line in out.splitlines()[1:]:
        bits = line.split()
        if len(bits) >= 2 and bits[1] == "device":
            devs.append(bits[0])
    return devs


def grab_adb(adb: str, serial: "str | None" = None) -> Img:
    cmd = [adb] + (["-s", serial] if serial else []) + ["exec-out", "screencap"]
    out = subprocess.run(cmd, capture_output=True, timeout=45).stdout
    return _adb_decode(out)


def grab_screen(rect, out_path: str = None) -> Img:
    """Windows-only fallback: capture a rectangle of the desktop.

    Writes a BMP rather than a PNG so the reader can stay dependency-free, and
    because System.Drawing saves it natively.
    """
    x, y, w, h = rect
    out_path = out_path or os.path.join(HERE, "capture_shot.bmp")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b = New-Object System.Drawing.Bitmap(%d, %d);"
        "$g = [System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen(%d, %d, 0, 0, $b.Size);"
        "$b.Save('%s', [System.Drawing.Imaging.ImageFormat]::Bmp)"
    ) % (w, h, x, y, out_path.replace("\\", "\\\\"))
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, timeout=60)
    if not os.path.exists(out_path):
        raise RuntimeError("the screen capture failed - run capture.py --screens "
                           "to list the monitor size, then pass --screen X,Y,W,H. "
                           "(%s)" % (proc.stderr.decode("utf-8", "replace")[:200]))
    return load_image(out_path)


# ================================================================= demo board
def make_demo_board(sequence=None) -> Img:
    """Draw a pretend board, so the reader can be proved without a game."""
    if sequence is None:
        import random
        rng = random.Random(7)
        sequence = [rng.choice(["r", "b", "g"]) for _ in range(50)]
    w, h = 720, 900
    px = bytearray()
    panel = (232, 148, 84)
    px += bytes(panel) * (w * h)                    # orange panel everywhere

    def put(x, y, rgb):
        if 0 <= x < w and 0 <= y < h:
            o = (y * w + x) * 3
            px[o], px[o + 1], px[o + 2] = rgb

    def rounded(x0, y0, x1, y1, rgb, rad=10):
        for y in range(y0, y1):
            for x in range(x0, x1):
                if (x < x0 + rad and y < y0 + rad and
                        (x - x0 - rad) ** 2 + (y - y0 - rad) ** 2 > rad * rad):
                    continue
                if (x > x1 - rad and y < y0 + rad and
                        (x - x1 + rad) ** 2 + (y - y0 - rad) ** 2 > rad * rad):
                    continue
                if (x < x0 + rad and y > y1 - rad and
                        (x - x0 - rad) ** 2 + (y - y1 + rad) ** 2 > rad * rad):
                    continue
                if (x > x1 - rad and y > y1 - rad and
                        (x - x1 + rad) ** 2 + (y - y1 + rad) ** 2 > rad * rad):
                    continue
                put(x, y, rgb)

    def disc(cx, cy, r, rgb):
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    put(x, y, rgb)

    fill = {"r": (222, 48, 42), "g": (26, 172, 108), "b": (32, 78, 220)}
    face = (238, 206, 176)      # skin patch in the middle, like the real art
    hat = {"r": (250, 214, 70), "g": (250, 214, 70), "b": (250, 214, 70)}

    left, top, cw, ch = 40, 40, 64, 74
    for row in range(5):
        y0 = top + row * (ch + 22)
        rounded(left, y0, left + 10 * cw + 10, y0 + ch, (247, 244, 238), 12)
        for col in range(10):
            sym = sequence[row * 10 + col]
            cx = left + 12 + col * cw + cw // 2 - 12
            cy = y0 + ch // 2
            disc(cx, cy, 24, fill[sym])
            disc(cx, cy + 3, 12, face)
            disc(cx, cy - 10, 11, hat[sym])
    return Img(w, h, 3, bytes(px))


# ======================================================================== main
def log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (stamp, line))
    except OSError:
        pass


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            return json.loads(open(CONFIG_PATH, encoding="utf-8").read())
        except Exception:                                          # noqa: BLE001
            return {}
    return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)


def describe(img: Img, seq: list, geom: dict) -> str:
    cols = len(geom["cols"])
    lines = []
    for i in range(0, len(seq), cols):
        chunk = seq[i:i + cols]
        lines.append("   " + " ".join((c or "?").upper() if c else "." for c in chunk))
    counts = {}
    for c in seq:
        if c:
            counts[c] = counts.get(c, 0) + 1
    known = sum(counts.values())
    bits = " ".join("%s %.0f%%" % (k.upper(), 100.0 * counts.get(k, 0) / known)
                    for k in SYMBOLS) if known else "nothing recognised"
    lines.append("   %d cells, %d unknown" % (len(seq), len(seq) - known))
    lines.append("   counts: " + bits)
    return "\n".join(lines)


def run_check(args) -> int:
    """One command that says whether recording can work, and names what is missing.

    The alternative is four separate failures discovered one at a time - no adb,
    no emulator, no board on screen, no app - and from the outside they all look
    identical: "it does not work". This walks the same chain the watcher walks,
    in order, and stops at the first link that is broken.
    """
    print("buzzcast capture check")
    print()
    ready = True

    # ---- where the picture comes from ------------------------------------
    if args.file:
        print("  picture ............. from %s" % args.file)
        img, why = None, None
        try:
            img = load_image(args.file)
        except Exception as exc:                                   # noqa: BLE001
            why = str(exc)
        if img is None:
            print("                        CANNOT READ IT - %s" % why)
            return 1
        print("                        %s" % img)
    else:
        adbs = find_adbs(args.adb_path)
        if not adbs:
            print("  adb ................. NOT FOUND")
            print()
            print("  There is no emulator's adb on this machine, and none on PATH.")
            print("  Looked on drives C: D: E: F: G: and in your home folder, in")
            print("  the places BlueStacks, LDPlayer, MuMu, Nox, MEmu and GameLoop")
            print("  install it.")
            print()
            print("  To fix it: install BlueStacks, then in it turn on")
            print("      Settings > Advanced > Android Debug Bridge")
            print("  and run this again.")
            return 1
        adb = adbs[0]
        print("  adb ................. %s" % adb)
        for extra in adbs[1:]:
            print("                        also found: %s" % extra)

        devs = adb_devices(adb)
        if not devs and not args.serial:
            # BlueStacks and friends sometimes need to be told where to listen.
            # Trying the usual ports costs a second and saves a support round.
            for port in (5555, 5565, 7555, 62001, 21503):
                try:
                    subprocess.run([adb, "connect", "127.0.0.1:%d" % port],
                                   capture_output=True, timeout=15)
                except Exception:                                  # noqa: BLE001
                    pass
            devs = adb_devices(adb)
        if not devs:
            print("  emulator ............ NOT RUNNING")
            print()
            print("  adb is here, but nothing is connected to it. Start the")
            print("  emulator and let it finish booting - the game does not have")
            print("  to be open yet - then run this again.")
            return 1
        serial = args.serial or devs[0]
        print("  emulator ............ %s" % serial)
        for extra in devs[1:]:
            if extra != serial:
                print("                        also running: %s" % extra)
        try:
            img = grab_adb(adb, serial)
            print("  screenshot .......... %s" % img)
        except Exception as exc:                                   # noqa: BLE001
            print("  screenshot .......... FAILED - %s" % exc)
            return 1

    # ---- can the board be read out of it ---------------------------------
    geom = detect_grid(img)
    if not geom:
        print("  board ............... NOT VISIBLE")
        print()
        print("  The picture arrived, but there is no Trend board in it.")
        print("  Open the game's Trend popup and leave it open - that board is")
        print("  the only thing this reads. Then run this again.")
        return 1
    seq = read_grid(img, geom)
    known = [c for c in seq if c]
    print("  board ............... %d cells, %d rows x %d columns, %d unread"
          % (geom["cells"], len(geom["rows"]), len(geom["cols"]),
             len(seq) - len(known)))
    for i in range(0, len(seq), len(geom["cols"])):
        print("                        %s" % " ".join(
            (c or "?").upper() for c in seq[i:i + len(geom["cols"])]))
    if not known:
        print("  letters ............. none recognised - is the popup really open?")
        return 1
    if any(not c for c in seq):
        ready = False
        print("  letters ............. %d could not be read" % (len(seq) - len(known)))
        print("                        the watcher waits for a clearer look rather")
        print("                        than guessing, so this is safe - but the")
        print("                        window may be covered or very small")

    # ---- is there anywhere for the results to go -------------------------
    if app_alive(args.base):
        print("  buzzcast app ........ running at %s" % args.base)
    else:
        ready = False
        print("  buzzcast app ........ NOT RUNNING at %s" % args.base)
        print("                        results would be held safely, in order,")
        print("                        until you start it (START.bat or WATCH.bat)")

    # ---- verdict ---------------------------------------------------------
    print()
    if ready:
        print("  READY. Open the Trend popup, then double-click WATCH.bat.")
        print("  Compare the letters above with the board on your screen first -")
        print("  if they differ, stop and say so rather than recording them.")
        return 0
    print("  NOT READY YET - fix what is marked above, then run this again.")
    return 1


def main() -> int:
    safe_console()
    ap = argparse.ArgumentParser(
        description="read the game's Trend board and record the results in buzzcast",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--adb", action="store_true", help="grab from an Android emulator")
    src.add_argument("--file", help="read a screenshot you already have")
    src.add_argument("--screen", help="capture the desktop, X,Y,W,H (Windows)")
    src.add_argument("--demo", action="store_true",
                     help="draw a pretend board and read it back - no game needed")
    ap.add_argument("--serial", help="which adb device, if you have several")
    ap.add_argument("--adb-path", help="path to adb if it is not on PATH")
    ap.add_argument("--report", action="store_true",
                    help="just show me what you see, do not record")
    ap.add_argument("--watch", action="store_true", help="keep checking")
    ap.add_argument("--interval", type=float, default=15.0,
                    help="seconds between checks when watching (default 15)")
    ap.add_argument("--once", action="store_true", help="one pass, then stop")
    ap.add_argument("--no-initial", action="store_true",
                    help="do NOT record the results already on the board when you "
                         "start (use if you recorded them by hand already)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be recorded, but change nothing")
    ap.add_argument("--base", default=DEFAULT_BASE, help="buzzcast address")
    ap.add_argument("--screens", action="store_true", help="list the screen size and exit")
    ap.add_argument("--check", action="store_true",
                    help="check the whole recording chain and say what is missing")
    args = ap.parse_args()

    if args.check:
        return run_check(args)

    if args.screens:
        try:
            script = ("Add-Type -AssemblyName System.Windows.Forms;"
                      "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, timeout=30).stdout.decode()
            print("primary screen:", out.strip())
            print("use it as --screen X,Y,W,H  (X,Y is the window's top-left corner)")
        except Exception as exc:                                   # noqa: BLE001
            print("could not ask Windows:", exc)
        return 0

    if args.demo:
        seq_true = ["r", "b", "g", "b", "r", "g", "g", "b", "r", "r",
                    "b", "b", "g", "r", "b", "g", "r", "g", "b", "g",
                    "g", "r", "b", "b", "g", "r", "r", "b", "g", "b",
                    "r", "g", "b", "r", "g", "b", "b", "r", "g", "r",
                    "b", "r", "g", "g", "b", "r", "b", "g", "r", "b"]
        img = make_demo_board(seq_true)
        path = os.path.join(HERE, "demo_board.png")
        save_png(img, path)
        print("wrote %s (%s) - open it if you want to see what it read" % (path, img))
        geom = detect_grid(img)
        if not geom:
            print("FAILED to find the board in the image I just drew")
            return 1
        seq = read_grid(img, geom)
        print("found %d cells in %d rows x %d columns"
              % (geom["cells"], len(geom["rows"]), len(geom["cols"])))
        print(describe(img, seq, geom))
        right = sum(1 for a, b in zip(seq, seq_true) if a == b)
        print("   read %d of %d correctly" % (right, len(seq_true)))
        return 0 if right == len(seq_true) else 1

    rect = None
    if args.screen:
        try:
            rect = [int(v) for v in args.screen.split(",")]
            assert len(rect) == 4
        except Exception:                                          # noqa: BLE001
            print("--screen wants X,Y,W,H - four numbers separated by commas")
            return 2

    def grab():
        """One screenshot from whichever source was asked for."""
        if args.file:
            return load_image(args.file)
        if args.screen:
            return grab_screen(rect)
        if args.adb:
            adb = adb_executable(args.adb_path)
            if not adb:
                raise RuntimeError(
                    "cannot find adb. Start your emulator and enable ADB in its "
                    "settings, or pass --adb-path 'C:\\path\\to\\adb.exe'")
            return grab_adb(adb, args.serial)
        raise RuntimeError("pick a source: --demo, --file, --screen or --adb")

    try:
        img = grab()
    except Exception as exc:                                       # noqa: BLE001
        # A first look that fails is ordinary, not exceptional: the emulator may
        # still be booting, the popup may not be open yet, or the file may not
        # be written. It used to end in a raw traceback. When watching, the loop
        # retries anyway, so carry on and let it.
        if not args.watch:
            print("cannot read the screen: %s" % exc)
            print("nothing has been changed. Fix that and run it again with --report "
                  "to check what it sees.")
            return 2
        print("cannot read the screen yet (%s) - watching, and will keep trying" % exc)
        img = None

    if img is None:
        geom = None
    else:
        geom = detect_grid(img)

    geom = detect_grid(img)
    if not geom:
        if not args.watch:
            print("could not find the Trend board in that image.")
            print("Are the popup open and the whole board visible? If it is visible and")
            print("this still fails, send me a PNG screenshot and I will tune the reader.")
            return 1
        print("no board visible yet - watching, and will keep trying")
        seq = []
    else:
        seq = read_grid(img, geom)
    known = [c for c in seq if c]
    if geom and img is not None:
        print("%s -> %d cells, %d rows x %d columns" %
              (img, geom["cells"], len(geom["rows"]), len(geom["cols"])))
        print(describe(img, seq, geom))
    if not known and not args.watch:
        print("nothing recognised - wrong window, or the popup is not open")
        return 1

    if args.report or args.once and not args.watch:
        if args.report:
            print("\nCompare the letters above with the board on your screen.")
            print("They should match exactly, left to right, top to bottom.")
            print("If they do, you are ready:  python capture.py --adb --watch")
        # Say this out loud. "--once" reads like "record one round" and someone
        # will leave it running for an hour and wonder where the data is.
        print("\nlook-only pass: NOTHING was recorded and nothing was changed.")
        print("to record, run without --once/--report:  python capture.py --adb --watch")
        return 0

    cfg = load_config()
    prev = cfg.get("last_seen") or []
    pending0 = list(cfg.get("pending") or [])
    initial = not prev and bool(known)
    if initial and not args.no_initial:
        # On the very first look the whole board is history you did not watch
        # happen, but it is still fifty REAL results, in order, on the screen.
        # Recording them gives you a fifty-turn head start on the evidence and
        # costs nothing. (Use --no-initial if you have already recorded those
        # turns by hand, or the same results would land in the ledger twice.)
        results, note = [c for c in seq if c], (
            "first look: recording the whole board - up to 50 real results you had "
            "not recorded yet. Use --no-initial next time if you already had them.")
    else:
        results, note = advance(prev, seq) if prev else ([], None)
    if note:
        print("  note: " + note)
    if prev and not results and not note:
        print("  nothing new since the last look")
    if results:
        print("  %d new result(s): %s" % (len(results), " ".join(r.upper() for r in results)))

    if not args.watch:
        queue = pending0 + list(results)
        if queue:
            cfg["pending"] = drain(args.base, queue, args.dry_run)
        cfg["last_seen"] = [c for c in seq]
        save_config(cfg)
        return 0

    print("\nwatching every %.0f seconds. Ctrl+C to stop." % args.interval)
    if not app_alive(args.base):
        print()
        print("  *** the buzzcast app is NOT running at %s" % args.base)
        print("  *** start it first (double-click START.bat, or run: python run.py)")
        print("  *** without it there is nowhere to put the results. I will keep")
        print("  *** watching and hold onto them - the board shows the last 50, so")
        print("  *** anything within that window is still recorded once it appears.")
    if not prev:
        queue = list(pending0)
        if progress := [c for c in seq if c]:
            if args.no_initial:
                print("first look taken as the starting point: %d results on the board, "
                      "none recorded (--no-initial)" % len(progress))
            else:
                print("the board already holds %d results - recording all of them now, "
                      "because they are real results you had not recorded" % len(progress))
                queue += progress
        n = feed(args.base, queue, args.dry_run) if queue else 0
        cfg["pending"] = list(queue) if args.dry_run else queue[n:]
        cfg["last_seen"] = [c for c in seq]
        save_config(cfg)
        if queue and n < len(queue):
            print("  %d are waiting for the app - they are kept safe, in order, and"
                  % (len(queue) - n))
            print("  will be recorded as soon as it is running.")
    total = 0
    misses = 0
    quiet = 0
    n = 0
    while True:
        try:
            time.sleep(args.interval)
            img = grab_adb(adb_executable(args.adb_path), args.serial) if args.adb \
                else (grab_screen([int(v) for v in args.screen.split(",")]) if args.screen
                      else load_image(args.file))
            geom = detect_grid(img)
            if not geom:
                misses += 1
                print("  board not visible (%d in a row)" % misses)
                if misses == 3:
                    log("board not visible three times in a row")
                continue
            misses = 0
            seq = read_grid(img, geom)
            cfg = load_config()
            prev = cfg.get("last_seen") or []
            # Two separate things, and conflating them loses data:
            #   last_seen - where the BOARD was, which is how new results are
            #               spotted. It has to keep up with the board.
            #   pending   - results spotted but not yet in the ledger, in order.
            #               It has to survive the app being down.
            # Marking results as seen the moment they were spotted lost them for
            # good: by the time the app came back the board had slid, and the
            # missed results could no longer be lined up with anything.
            pending = list(cfg.get("pending") or [])

            if not prev:
                fresh, note = [c for c in seq if c], None
            else:
                fresh, note = advance(prev, seq)
            if note:
                print("  " + note)
                log("alignment: " + note)
            if fresh:
                pending += fresh
                log("spotted %d: %s" % (len(fresh), " ".join(fresh)))

            cfg["last_seen"] = [c for c in seq]
            if pending:
                before = len(pending)
                pending = drain(args.base, pending, args.dry_run)
                n = before - len(pending)
                total += n
                if n:
                    log("recorded %d" % n)
                    print("  recorded %d (this run: %d, %d still waiting)"
                          % (n, total, len(pending)))
                if len(pending) > 200:
                    print("  %d results are waiting for the app - is it running?"
                          % len(pending))
            else:
                # quiet by default: a poll every few seconds for hours would
                # otherwise fill the window with dots and bury anything real
                quiet += 1
                if quiet >= 20:
                    quiet = 0
                    print("  ... still watching (this run: %d recorded)" % total)
            cfg["pending"] = pending
            save_config(cfg)
        except KeyboardInterrupt:
            print("\nstopped. %d result(s) recorded this run. Log: %s" % (total, LOG_PATH))
            return 0
        except Exception as exc:                                   # noqa: BLE001
            print("  hiccup: %s (carrying on)" % exc)
            log("error: %s" % exc)
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
