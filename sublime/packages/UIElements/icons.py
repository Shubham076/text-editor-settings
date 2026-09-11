"""Small antialiased PNG icons, tinted to the editor color scheme."""

import base64
from functools import lru_cache
import math
import struct
import zlib


NAMES = ("settings", "play", "restart", "stop")


def _inside(name, x, y):
    if name == "play":
        return 4 <= x <= 13 and abs(y - 8) <= (13 - x) * 0.6
    if name == "stop":
        return 4 <= x <= 12 and 4 <= y <= 12
    radius = math.hypot(x - 8, y - 8)
    if name == "settings":
        tooth = math.cos(8 * math.atan2(y - 8, x - 8)) > 0.4
        return 3 <= radius <= 5.25 or (4.75 <= radius <= 7 and tooth)
    return (4.5 <= radius <= 6.2 and not (x < 8 and y < 6)) or (1 <= x <= 6 and x + 1 <= y <= 7)


def _chunk(kind, data):
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xffffffff)


@lru_cache(maxsize=64)
def data_uri(name, color):
    if name not in NAMES:
        raise ValueError("Unknown icon: {!r}".format(name))
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    pixels = bytearray()
    for y in range(16):
        pixels.append(0)
        for x in range(16):
            coverage = sum(_inside(name, x + (sx + 0.5) / 4, y + (sy + 0.5) / 4)
                           for sy in range(4) for sx in range(4))
            pixels.extend((*rgb, round(coverage * 255 / 16)))
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(pixels)))
           + _chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
