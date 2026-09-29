from __future__ import annotations

import base64
from functools import lru_cache
import math
import struct
import zlib


# Icon sizes in rem, measured from the mockups (toolbar icons 24px, tree chevrons 16px, ...).
ICON_SIZES = {
	'play': 1.2, 'pause': 1.2, 'stop': 1.2, 'restart': 1.2, 'over': 1.2, 'into': 1.2, 'out': 1.2, 'settings': 1.2, 'back': 1.2, 'bug': 1.2,
	'chevron': 0.8, 'down': 0.8, 'up': 0.8, 'plus': 1.0, 'close': 0.8, 'edit': 0.9, 'breakpoint': 1.0, 'unchecked': 1.0,
}
# Icon tints as (colour scheme key, opacity against the background).
TONES = {
	'default': ('foreground', 0.9), 'muted': ('foreground', 0.75), 'faint': ('foreground', 0.5),
	# the primary action's icon is the plain text colour, as the console's text is; only its tinted
	# background marks it as the main one
	'disabled': ('foreground', 0.35), 'primary': ('foreground', 1.0), 'danger': ('redish', 1.0), 'ghost': ('foreground', 0.0),
}
# -- stroke icons ---------------------------------------------------------------------------
# The mockups use 24-unit line icons (Lucide geometry, 2-unit strokes, round joins). Unicode
# glyphs cannot reproduce that consistently, so the icons are rasterised here into small PNGs,
# tinted from the colour scheme, with signed-distance antialiasing. Everything is pure Python
# so it runs inside the plugin host.
ICONS = {
	'play': (('poly', ((5, 4), (15, 12), (5, 20)), True), ('line', (19, 5), (19, 19))),
	'pause': (('rrect', 6, 4, 10, 20, 1), ('rrect', 14, 4, 18, 20, 1)),
	'stop': (('rrect', 4.5, 4.5, 19.5, 19.5, 2),),
	'restart': (('arc', (12, 12), 9, 0, 317), ('poly', ((21, 3), (21, 8), (16, 8)), False)),
	'over': (('poly', ((9, 18), (15, 12), (9, 6)), False),),
	'into': (('poly', ((6, 9), (12, 15), (18, 9)), False),),
	'out': (('poly', ((6, 15), (12, 9), (18, 15)), False),),  # step out leaves the frame: upward chevron
	'chevron': (('poly', ((9, 18), (15, 12), (9, 6)), False),),
	'down': (('poly', ((6, 9), (12, 15), (18, 9)), False),),
	'up': (('poly', ((18, 15), (12, 9), (6, 15)), False),),
	'plus': (('line', (12, 5), (12, 19)), ('line', (5, 12), (19, 12))),
	'close': (('line', (18, 6), (6, 18)), ('line', (6, 6), (18, 18))),
	'edit': (('poly', ((2, 22), (3.5, 16.5), (17, 3), (21, 7), (7.5, 20.5)), True), ('line', (15, 5), (19, 9))),
	'breakpoint': (('disc', (12, 12), 6),),
	'unchecked': (('arc', (12, 12), 6, 0, 360),),
	'settings': (('gear', (12, 12), 7.2, 9.8), ('arc', (12, 12), 3, 0, 360)),
	'back': (('line', (19, 12), (5, 12)), ('poly', ((12, 19), (5, 12), (12, 5)), False)),  # arrow left: back to the debugger view
	# the brand mark: Lucide's bug, its curves flattened to the primitives above. A rounded body
	# with a seam down the middle, a half-disc head on two short necks, two antennae and three
	# legs a side.
	'bug': (
		('rrect', 6, 9, 18, 21, 3), ('line', (12, 11), (12, 20.5)),
		('arc', (12, 6.5), 3, 180, 360), ('line', (9, 6.5), (9, 9)), ('line', (15, 6.5), (15, 9)),
		('line', (8, 2), (9.9, 3.9)), ('line', (16, 2), (14.1, 3.9)),
		('poly', ((6.5, 9.5), (4, 8.2), (3, 5)), False), ('line', (6, 13), (2, 13)), ('poly', ((3, 21), (4, 18.2), (6.8, 17)), False),
		('poly', ((17.5, 9.5), (20, 8.2), (21, 5)), False), ('line', (18, 13), (22, 13)), ('poly', ((21, 21), (20, 18.2), (17.2, 17)), False),
	),
}
STROKE = 2.0


def _segment_distance(px, py, ax, ay, bx, by):
	dx, dy = bx - ax, by - ay
	length = dx * dx + dy * dy
	t = 0.0 if not length else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
	return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _gear_points(cx, cy, inner, outer, teeth=8):
	points = []
	for index in range(teeth):
		angle = math.radians(index * 360 / teeth)
		for radius, offset in ((inner, -13), (outer, -8), (outer, 8), (inner, 13)):
			a = angle + math.radians(offset)
			points.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
	return points


def _icon_coverage(shapes, x, y, pixel):
	"""Coverage in 0..1 of the icon at point (x, y) in 24-unit space; `pixel` is one device pixel."""
	half = STROKE / 2
	coverage = 0.0
	for shape in shapes:
		kind = shape[0]
		if kind == 'line':
			(_, a, b) = shape
			d = _segment_distance(x, y, a[0], a[1], b[0], b[1]) - half
		elif kind == 'poly':
			(_, points, closed) = shape
			pairs = list(zip(points, points[1:] + (points[:1] if closed else ())))
			d = min(_segment_distance(x, y, a[0], a[1], b[0], b[1]) for a, b in pairs) - half
		elif kind == 'gear':
			(_, (cx, cy), inner, outer) = shape
			points = _gear_points(cx, cy, inner, outer)
			pairs = list(zip(points, points[1:] + points[:1]))
			d = min(_segment_distance(x, y, a[0], a[1], b[0], b[1]) for a, b in pairs) - half
		elif kind == 'arc':
			(_, (cx, cy), radius, start, end) = shape
			angle = math.degrees(math.atan2(y - cy, x - cx)) % 360
			if end - start >= 360 or start <= angle <= end:
				d = abs(math.hypot(x - cx, y - cy) - radius) - half
			else:
				ends = [(cx + radius * math.cos(math.radians(a)), cy + radius * math.sin(math.radians(a))) for a in (start, end)]
				d = min(math.hypot(x - ex, y - ey) for ex, ey in ends) - half
		elif kind == 'rrect':
			(_, x0, y0, x1, y1, rr) = shape
			cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
			hx, hy = (x1 - x0) / 2 - rr, (y1 - y0) / 2 - rr
			qx, qy = abs(x - cx) - hx, abs(y - cy) - hy
			outside = math.hypot(max(qx, 0), max(qy, 0))
			d = abs(outside + min(max(qx, qy), 0) - rr) - half
		else:  # disc
			(_, (cx, cy), radius) = shape
			d = math.hypot(x - cx, y - cy) - radius
		coverage = max(coverage, max(0.0, min(1.0, 0.5 - d / pixel)))
	return coverage


def _png(width, height, rows):
	def chunk(kind, data):
		payload = kind + data
		return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload) & 0xffffffff)
	return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
		+ chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b''))


@lru_cache(maxsize=256)
def icon_data_uri(name, color, size, alpha=1.0):
	"""PNG data URI of `name` drawn in `color` (#rrggbb) at `size` device pixels square."""
	shapes = ICONS[name]
	rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
	pixel = 24 / size
	rows = bytearray()
	for row in range(size):
		rows.append(0)
		y = (row + 0.5) * pixel
		for column in range(size):
			coverage = _icon_coverage(shapes, (column + 0.5) * pixel, y, pixel)
			rows.extend((*rgb, int(round(coverage * alpha * 255))))
	return 'data:image/png;base64,' + base64.b64encode(_png(size, size, rows)).decode('ascii')
