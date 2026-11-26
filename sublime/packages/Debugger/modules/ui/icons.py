from __future__ import annotations

import base64
from functools import lru_cache
import math
import re
import struct
import zlib


# Icon sizes in rem, measured from the mockups (toolbar icons 24px, tree chevrons 16px, ...).
ICON_SIZES = {
	'play': 1.2, 'run': 1.2, 'pause': 1.2, 'stop': 1.2, 'restart': 1.2, 'over': 1.2, 'into': 1.2, 'out': 1.2, 'settings': 1.2, 'back': 1.2, 'bug': 1.2,
	'chevron': 0.8, 'down': 0.8, 'up': 0.8, 'plus': 1.0, 'close': 0.8, 'edit': 0.9, 'breakpoint': 1.0, 'unchecked': 1.0,
	'breakpoints': 1.2, 'tasks': 1.2, 'trash': 1.2,
}
# The buttons of the bar are drawn larger inside their box, about the centre: the shapes keep a
# margin of three units on the 24-unit grid, which at this zoom is under one. The box itself stays
# as it is, the height of the bar and of the fixed strip is worked out from it
TOOL_ZOOM = 1.15
TOOL_ICONS = frozenset(name for name, size in ICON_SIZES.items() if size == 1.2)
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
#
# An icon with curves is given as the path data of its svg (`path`), which is flattened to
# polylines when the module loads (`_flatten`). Those are Tabler's outline icons (MIT licence,
# https://tabler.io/icons), drawn on the same 24-unit grid with the same stroke.
ICONS = {
	'play': (('poly', ((5, 4), (15, 12), (5, 20)), True), ('line', (19, 5), (19, 19))),
	# start, as opposed to go on from where it stopped: the triangle alone, without the bar of `play`
	'run': (('poly', ((7, 4), (19, 12), (7, 20)), True),),
	# The same two shapes filled in, for the icons at the head of a line in a file. On the bar an
	# outline sits among other outlines, at the size of a button. In the margin of a file it is a
	# third of that size next to text, where an outline is a few thin strokes that read as a bracket
	'run-filled': (('solid', ((7, 4), (19, 12), (7, 20))),),
	'stop-filled': (('srect', 4.5, 4.5, 19.5, 19.5, 2),),
	'pause': (('rrect', 6, 4, 10, 20, 1), ('rrect', 14, 4, 18, 20, 1)),
	'stop': (('rrect', 4.5, 4.5, 19.5, 19.5, 2),),
	'restart': (('path', 'M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4 M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4'),),
	# clears the console: a bin
	'trash': (('path', 'M4 7h16 M10 11v6 M14 11v6 M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12 M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3'),),
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
	# the toolbar's way to the breakpoints view: a breakpoint dot inside a ring
	'breakpoints': (('arc', (12, 12), 9, 0, 360), ('disc', (12, 12), 4)),
	'settings': (
		('path', 'M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37'
			'a1.724 1.724 0 0 0 1.065 2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573c.94 1.543 -.826 3.31 -2.37 2.37'
			'a1.724 1.724 0 0 0 -2.572 1.065c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066c-1.543 .94 -3.31 -.826 -2.37 -2.37'
			'a1.724 1.724 0 0 0 -1.065 -2.572c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573c-.94 -1.543 .826 -3.31 2.37 -2.37'
			'c1 .608 2.296 .07 2.572 -1.065z'),
		('arc', (12, 12), 3, 0, 360),
	),
	# the tasks of the project: a list with its items ticked off
	'tasks': (('path', 'M3.5 5.5l1.5 1.5l2.5 -2.5 M3.5 11.5l1.5 1.5l2.5 -2.5 M3.5 17.5l1.5 1.5l2.5 -2.5 M11 6h9 M11 12h9 M11 18h9'),),
	'back': (('line', (19, 12), (5, 12)), ('poly', ((12, 19), (5, 12), (12, 5)), False)),  # arrow left: back to the debugger view
	# the brand mark, and the debug button: a head on a rounded body with a seam, three legs a side
	'bug': (('path', 'M9 9v-1a3 3 0 0 1 6 0v1 M8 9h8a6 6 0 0 1 1 3v3a5 5 0 0 1 -10 0v-3a6 6 0 0 1 1 -3 M3 13h4 M17 13h4 M12 20v-6'
		' M4 19l3.35 -2 M20 19l-3.35 -2 M4 7l3.75 2.4 M20 7l-3.75 2.4'),),
}
STROKE = 2.0


def _arc_points(x1, y1, rx, ry, large, sweep, x2, y2):
	"""The points of an svg elliptical arc (no rotation) from (x1, y1) to (x2, y2), the start left out"""
	dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
	scale = dx * dx / (rx * rx) + dy * dy / (ry * ry)
	if scale > 1:
		rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
	numerator = rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx
	k = math.sqrt(max(0.0, numerator / (rx * rx * dy * dy + ry * ry * dx * dx))) * (-1 if large == sweep else 1)
	cxp, cyp = k * rx * dy / ry, -k * ry * dx / rx
	cx, cy = cxp + (x1 + x2) / 2, cyp + (y1 + y2) / 2
	start = math.atan2((dy - cyp) / ry, (dx - cxp) / rx)
	delta = math.atan2((-dy - cyp) / ry, (-dx - cxp) / rx) - start
	if sweep and delta < 0:
		delta += 2 * math.pi
	elif not sweep and delta > 0:
		delta -= 2 * math.pi
	steps = max(2, math.ceil(abs(delta) / (math.pi / 8)))
	return [(cx + rx * math.cos(start + delta * i / steps), cy + ry * math.sin(start + delta * i / steps)) for i in range(1, steps)] + [(x2, y2)]


def _flatten(data):
	"""Svg path data as `poly` shapes: the commands M L H V C A Z, absolute or relative"""
	tokens = re.findall(r'[MmLlHhVvCcAaZz]|-?\d*\.?\d+', data)
	shapes, points, x, y, index, command = [], [], 0.0, 0.0, 0, ''

	def take(count):
		nonlocal index
		values = [float(token) for token in tokens[index:index + count]]
		index += count
		return values

	def end(closed):
		if len(points) > 1:
			shapes.append(('poly', tuple(points), closed))

	while index < len(tokens):
		if tokens[index].isalpha():
			command = tokens[index]
			index += 1
		relative = command.islower()
		ox, oy = (x, y) if relative else (0.0, 0.0)
		kind = command.upper()
		if kind == 'Z':
			end(True)
			x, y = points[0]
			points = [(x, y)]
			continue
		if kind == 'M':
			end(False)
			x, y = take(2)
			x, y = x + ox, y + oy
			points = [(x, y)]
			# the pairs after the first of a move are lines
			command = 'l' if relative else 'L'
			continue
		if kind == 'L':
			x, y = take(2)
			x, y = x + ox, y + oy
		elif kind == 'H':
			x = take(1)[0] + ox
		elif kind == 'V':
			y = take(1)[0] + oy
		elif kind == 'C':
			x1, y1, x2, y2, x3, y3 = take(6)
			for step in range(1, 6):
				t = step / 6
				u = 1 - t
				points.append((
					u * u * u * x + 3 * u * u * t * (x1 + ox) + 3 * u * t * t * (x2 + ox) + t * t * t * (x3 + ox),
					u * u * u * y + 3 * u * u * t * (y1 + oy) + 3 * u * t * t * (y2 + oy) + t * t * t * (y3 + oy)))
			x, y = x3 + ox, y3 + oy
		elif kind == 'A':
			rx, ry, _, large, sweep, x2, y2 = take(7)
			points.extend(_arc_points(x, y, rx, ry, bool(large), bool(sweep), x2 + ox, y2 + oy)[:-1])
			x, y = x2 + ox, y2 + oy
		points.append((x, y))
	end(False)
	return shapes


ICONS = {name: tuple(part for shape in shapes for part in (_flatten(shape[1]) if shape[0] == 'path' else (shape,)))
	for name, shapes in ICONS.items()}


def _segment_distance(px, py, ax, ay, bx, by):
	dx, dy = bx - ax, by - ay
	length = dx * dx + dy * dy
	t = 0.0 if not length else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
	return math.hypot(px - ax - t * dx, py - ay - t * dy)


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
		elif kind == 'solid':
			# a polygon and everything inside it: the distance to its edge, negative on the inside
			(_, points) = shape
			pairs = list(zip(points, points[1:] + points[:1]))
			d = min(_segment_distance(x, y, a[0], a[1], b[0], b[1]) for a, b in pairs)
			# inside when a ray to the right crosses the edge an odd number of times
			crossings = sum(1 for a, b in pairs if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
			d = (-d if crossings % 2 else d) - half
		elif kind == 'srect':
			# a rounded rectangle and everything inside it
			(_, x0, y0, x1, y1, rr) = shape
			cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
			hx, hy = (x1 - x0) / 2 - rr, (y1 - y0) / 2 - rr
			qx, qy = abs(x - cx) - hx, abs(y - cy) - hy
			d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - rr - half
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
	zoom = TOOL_ZOOM if name in TOOL_ICONS else 1.0
	pixel = 24 / size / zoom
	origin = 12 - 12 / zoom
	rows = bytearray()
	for row in range(size):
		rows.append(0)
		y = origin + (row + 0.5) * pixel
		for column in range(size):
			coverage = _icon_coverage(shapes, origin + (column + 0.5) * pixel, y, pixel)
			rows.extend((*rgb, int(round(coverage * alpha * 255))))
	return 'data:image/png;base64,' + base64.b64encode(_png(size, size, rows)).decode('ascii')
