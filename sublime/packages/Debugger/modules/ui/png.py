from __future__ import annotations

import struct
import zlib

_SIGNATURE = b'\x89PNG\r\n\x1a\n'

# channels per pixel for each png colour type
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunks(data: bytes):
	pos = len(_SIGNATURE)
	while pos + 8 <= len(data):
		length = struct.unpack('>I', data[pos : pos + 4])[0]
		yield data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
		pos += 12 + length


def _unfilter(raw: bytes, width: int, height: int, bits: int, channels: int) -> list[bytearray]:
	stride = (width * channels * bits + 7) // 8
	step = max(1, channels * bits // 8)

	rows: list[bytearray] = []
	previous = bytearray(stride)
	pos = 0

	for _ in range(height):
		kind = raw[pos]
		pos += 1
		line = bytearray(raw[pos : pos + stride])
		pos += stride

		for i in range(stride):
			left = line[i - step] if i >= step else 0
			up = previous[i]
			upleft = previous[i - step] if i >= step else 0

			if kind == 1:
				line[i] = (line[i] + left) & 0xFF
			elif kind == 2:
				line[i] = (line[i] + up) & 0xFF
			elif kind == 3:
				line[i] = (line[i] + (left + up) // 2) & 0xFF
			elif kind == 4:
				estimate = left + up - upleft
				dl, du, dul = abs(estimate - left), abs(estimate - up), abs(estimate - upleft)
				nearest = left if (dl <= du and dl <= dul) else (up if du <= dul else upleft)
				line[i] = (line[i] + nearest) & 0xFF

		rows.append(line)
		previous = line

	return rows


def _samples(line: bytearray, width: int, bits: int, channels: int) -> list[int]:
	'''One value per channel per pixel, unpacked from whatever bit depth the file uses'''
	if bits == 8:
		return list(line[: width * channels])

	if bits == 16:
		return [line[i] for i in range(0, width * channels * 2, 2)]

	out: list[int] = []
	per_byte = 8 // bits
	mask = (1 << bits) - 1

	for index in range(width * channels):
		byte = line[index // per_byte]
		shift = 8 - bits * (index % per_byte + 1)
		out.append((byte >> shift) & mask)

	return out


def alpha_channel(data: bytes) -> tuple[int, int, bytearray]:
	'''The size and the alpha of every pixel, whatever the colour type and bit depth'''
	width = height = bits = colour = 0
	palette_alpha = b''
	compressed = b''

	for kind, payload in _chunks(data):
		if kind == b'IHDR':
			width, height, bits, colour = struct.unpack('>IIBB', payload[:10])
		elif kind == b'tRNS':
			palette_alpha = payload
		elif kind == b'IDAT':
			compressed += payload

	channels = _CHANNELS[colour]
	rows = _unfilter(zlib.decompress(compressed), width, height, bits, channels)

	alpha = bytearray(width * height)
	full = (1 << bits) - 1

	for y, line in enumerate(rows):
		values = _samples(line, width, bits, channels)

		for x in range(width):
			if colour == 3:
				index = values[x]
				alpha[y * width + x] = palette_alpha[index] if index < len(palette_alpha) else 255
			elif colour == 4:
				alpha[y * width + x] = values[x * 2 + 1] * 255 // full
			elif colour == 6:
				alpha[y * width + x] = values[x * 4 + 3] * 255 // full
			else:
				alpha[y * width + x] = 255

	return width, height, alpha


def rgba_png(width: int, height: int, rgb: tuple[int, int, int], alpha: bytearray) -> bytes:
	'''A png of one colour, shaped by `alpha`'''
	r, g, b = rgb
	raw = bytearray()

	for y in range(height):
		raw.append(0)
		for x in range(width):
			raw += bytes((r, g, b, alpha[y * width + x]))

	def chunk(kind: bytes, payload: bytes) -> bytes:
		return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)

	return (
		_SIGNATURE
		+ chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
		+ chunk(b'IDAT', zlib.compress(bytes(raw), 9))
		+ chunk(b'IEND', b'')
	)
