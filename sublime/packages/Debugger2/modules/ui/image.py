from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from . layout import View

from ..import core
from ..settings import Settings

from . import png

import sublime
import base64

def _path_for_image(name: str) -> str:
	return core.package_path_relative(f'contributes/Images/{name}')

def _data_image_png_b64_png_from_resource(path: str) -> str:
	png_data = sublime.load_binary_resource(path)
	return f'data:image/png;base64,{base64.b64encode(png_data).decode("ascii")}'


def _rgb_from_color(color: str) -> tuple[int, int, int]:
	value = color.lstrip('#')

	if len(value) == 3:
		value = ''.join(c * 2 for c in value)

	return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _data_image_recoloured(path: str, color: str) -> str:
	'''The same artwork drawn in `color`

	minihtml cannot tint an image, there is no filter, no mask and no svg, so the tint has to happen
	before the image reaches it. The shape of an icon is its alpha and nothing else, so the alpha is
	taken from the file and a new png is built from it in the colour asked for. Everything else about
	the icon, its size, its weight, where it sits, is untouched.
	'''
	width, height, alpha = png.alpha_channel(sublime.load_binary_resource(path))
	data = png.rgba_png(width, height, _rgb_from_color(color), alpha)

	return f'data:image/png;base64,{base64.b64encode(data).decode("ascii")}'


def reload_images():
	Image.cached = {}
	Images.shared = Images()

class Image:
	cached: dict[str, str] = {}

	@staticmethod
	def named(name: str) -> Image:
		file = _path_for_image(f'universal/unoptimized-{name}')
		file_optimized = _path_for_image(f'universal/{name}')

		# never recoloured: a breakpoint is red because red is what it means
		return Image(file, file_optimized, file_optimized, tinted=False)

	@staticmethod
	def named_light_dark(name: str) -> Image:
		light = _path_for_image(f'light/{name}')
		dark = _path_for_image(f'dark/{name}')
		return Image(light, dark, light)

	def __init__(self, file: str, file_dark: str, file_light: str, tinted: bool = True) -> None:
		self.file = file
		self.file_light = file_light
		self.file_dark = file_dark

		# whether this icon is a shape to be drawn in the foreground colour, or artwork whose own colours
		# carry meaning
		self.tinted = tinted


	def data(self, layout: View|None = None) -> str:
		if layout and layout.luminocity < 0.5:
			file = self.file_light
		else:
			file = self.file_dark

		# the light and the dark copy differ only in colour, and colour is what is about to be replaced,
		# so either one gives the same shape
		colour = layout.foreground if layout and self.tinted and Settings.icon_foreground_color else None

		key = f'{file}{colour}'
		if key in Image.cached:
			return Image.cached[key]

		data = _data_image_recoloured(file, colour) if colour else _data_image_png_b64_png_from_resource(file)
		Image.cached[key] = data
		return data


class Images:
	shared: Images

	def __init__(self) -> None:
		self.dot = Image.named('breakpoint.png')
		self.dot_emtpy = Image.named('breakpoint-broken.png')
		self.dot_expr = Image.named('breakpoint-expr.png')
		self.dot_log = Image.named('breakpoint-log.png')
		self.dot_disabled = Image.named('breakpoint-disabled.png')
		self.resume = Image.named_light_dark('continue.png')
		self.play = Image.named_light_dark('play.png')
		self.restart = Image.named_light_dark('restart.png')
		self.edit = Image.named_light_dark('edit.png')
		self.run_any = Image.named_light_dark('run_any.png')
		self.stop = Image.named_light_dark('stop.png')
		self.settings = Image.named_light_dark('settings.png')
		self.pause = Image.named_light_dark('pause.png')

		self.clear = Image.named_light_dark('clear_disabled.png')

		self.stop_disable = Image.named_light_dark('stop_disabled.png')
		self.pause_disable = Image.named_light_dark('pause_disabled.png')

		self.up = Image.named_light_dark('up.png')
		self.down = Image.named_light_dark('step_over.png')
		self.left = Image.named_light_dark('step_out.png')
		self.right = Image.named_light_dark('step_into.png')

		self.down_disable = Image.named_light_dark('step_over_disabled.png')
		self.left_disable = Image.named_light_dark('step_out_disabled.png')
		self.right_disable = Image.named_light_dark('step_into_disabled.png')

		self.thread = Image.named_light_dark('thread_stopped.png')
		self.loading = Image.named_light_dark('loading_disabled.png')
		self.check_mark = Image.named_light_dark('check_mark_disabled.png')

		self.thread_running = Image.named_light_dark('thread_running.png')

		# the full strength artwork, not the `_disabled` variant. `convert.py` builds those by multiplying
		# the alpha by 0.15, which on a light background leaves a disclosure triangle that is barely there
		self.open = Image.named_light_dark('open.png')
		self.close = Image.named_light_dark('close.png')
