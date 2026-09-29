from __future__ import annotations

from functools import partial
from html import escape

from .icons import ICON_SIZES, TONES, icon_data_uri
from .style import (
	ACTION, CH, COLORS, CONTROL, CSS, HEADING_LINE, LINE, PAD, PANE_PAD, ROW,
	TAB_PAD, TABS_HEIGHT, TEXT_LINE, TOOL, TOOLBAR_PAD, ZW,
)


class Renderer:
	document_id = 'debugger-live-ui'
	# Typography of the drawn ui; the live panel sets these from the debugger settings.
	font_face = None      # font family in front of the monospace fallbacks
	line_padding = 0      # extra pixels above and below each pane row

	def navigate(self, generation, href):
		if not self.closed and self.view.is_valid() and generation == self.generation:
			callback = self.handlers.get(href)
			if callback:
				callback()

	# -- building blocks -------------------------------------------------------------------

	def px(self, rem):
		return int(round(rem * self.font))

	def register_callback(self, callback):
		key = str(len(self.handlers))
		self.handlers[key] = callback
		return key

	def link(self, content, callback, title, css=''):
		key = self.register_callback(callback)
		return '<a href="{}" class="{}" title="{}">{}</a>'.format(key, css, escape(title, quote=True), content)

	def tint(self, tone):
		"""Hex colour for an icon tone, blended against the scheme background."""
		key, opacity = TONES[tone]
		colour, background = self.palette.get(key, self.palette['foreground']), self.palette['background']
		mixed = [round(int(colour[i:i + 2], 16) * opacity + int(background[i:i + 2], 16) * (1 - opacity)) for i in (1, 3, 5)]
		return '#%02x%02x%02x' % tuple(max(0, min(255, value)) for value in mixed)

	def icon(self, name, tone='default', css=''):
		size = self.px(ICON_SIZES[name])
		uri = icon_data_uri(name, self.tint(tone), size * 2, 0.0 if tone == 'ghost' else 1.0)
		return '<img class="icon {}" src="{}" style="width:{}px;height:{}px;">'.format(css, uri, size, size)

	def slot(self, content, width, css=''):
		return '<span class="slot {}" style="width:{}px;">{}</span>'.format(css, max(0, self.px(width)), content)

	def clip(self, value, width, scale=1.0):
		length = max(1, int(width / (CH * scale)))
		return value if len(value) <= length else value[:max(0, length - 1)] + '…'

	def text(self, value, width, css='', scale=1.0):
		value = str(value)
		clipped = self.clip(value, width, scale)
		return self.slot('<span title="{}">{}</span>'.format(escape(value, quote=True), escape(clipped)), width, css)

	def row(self, content, css=''):
		return '<div class="row {}">{}{}</div>'.format(css, ZW, content)

	def button(self, name, title, callback, enabled=True, css='', width=ACTION, tone='muted'):
		"""An icon action inside a fixed-width slot so columns of actions line up."""
		content = self.icon(name, tone if enabled else 'disabled')
		if not enabled:
			inner = '<span class="icon-button disabled {}" title="{}">{}</span>'.format(css, escape(title + ' · unavailable', quote=True), content)
		else:
			inner = self.link(content, callback, title, 'icon-button ' + css)
		return self.slot(inner, width, 'center')

	def tool(self, name, title, callback, enabled=True, primary=False, css=''):
		tone = 'disabled' if not enabled else 'primary' if primary else 'danger' if css == 'stop' else 'default'
		content = self.icon(name, tone)
		style = 'tool' + (' primary' if primary else '') + (' ' + css if css else '')
		if not enabled:
			inner = '<span class="{} disabled" title="{}">{}</span>'.format(style, escape(title + ' · unavailable', quote=True), content)
		else:
			inner = self.link(content, callback, title, style)
		return self.slot(inner, TOOL, 'center')

	def heading(self, label, key, width, actions='', action_count=0, suffix=''):
		chevron = self.slot(self.icon('down' if key in self.state.expanded else 'chevron', 'muted'), CONTROL, 'center')
		label_width = width - action_count * ACTION - CONTROL
		content = chevron + self.text(label + suffix, label_width, '', 1.15)
		content = self.link(content, partial(self.toggle, key), 'Expand / collapse ' + label)
		return '<div class="section-title">{}{}{}</div>'.format(ZW, self.slot(content, width - action_count * ACTION), actions)

	def toggle(self, key):
		if key in self.state.expanded:
			self.state.expanded.remove(key)
		else:
			self.state.expanded.add(key)
		self.render()

	def expression(self, name, value, kind, width):
		budget = max(4, int(width / CH) - 1)
		name_limit = min(len(name), max(3, budget - 7))
		label = name if len(name) <= name_limit else name[:name_limit - 1] + '…'
		value_limit = max(1, budget - len(label) - 3)
		display = value if len(value) <= value_limit else value[:max(0, value_limit - 1)] + '…'
		content = '{} <span class="muted">=</span> <span class="{}">{}</span>'.format(escape(label), kind, escape(display))
		return self.slot('<span title="{}">{}</span>'.format(escape(name + ' = ' + value, quote=True), content), width)

	def chips(self, items):
		parts = []
		for label, callback, title, active in items:
			parts.append(self.link(escape(label), callback, title, 'chip' + (' active' if active else '')))
		return self.slot('', 0.7).join(parts)

	def toolbar_layout(self, name, status, choose_configuration, controls, gear, split=True, brand=True, extra='', extra_width=0.0, css='', lead='', lead_width=0.0):
		"""Two phantoms: the brand cell and the rest.

		`split=False` joins everything into one phantom. `brand=False` then replaces the brand label
		with `lead` (of `lead_width` rem) in front of the picker, and `extra` (of `extra_width` rem)
		sits between the controls and the gear; the console's fixed bar puts its back arrow in `lead`.
		"""
		brand_width, label_width, state_width = 2.9, 10.3, 7.2
		chars = int(label_width / CH)
		label = escape(self.clip(name, label_width).ljust(chars)).replace(' ', '&nbsp;')
		picker = self.link(label + self.icon('down', 'muted'), choose_configuration, 'Select run configuration', 'picker')
		kind = status.lower() if status in ('Paused', 'Running', 'Stopped') else 'stopped'
		badge = '<span class="state {}">&#9679; {}</span>'.format(kind, escape(status))
		left = picker + self.slot('', 1.05) + self.slot(badge, state_width)
		separator = self.separator()
		# The brand is the debugger's bug icon rather than a name: drawn at the toolbar icon size so
		# both cells get the same line height, left in its slot with air before the picker.
		label = self.slot('<span class="brand" title="Debugger">{}</span>'.format(self.icon('bug', 'muted')), brand_width)
		brand_cell = '<div class="toolbar brand-cell" style="width:{}px;">{}</div>'.format(self.px(brand_width), label)
		rest_width = self.total - 2 * PAD - brand_width - self.space
		left_width = label_width + 1.9 + 0.9 + 1.05 + state_width
		controls_width = 6 * TOOL + 1.5
		gap = rest_width - left_width - 1.5 - controls_width - extra_width - TOOL - 0.6
		if not split:
			cell = 'toolbar joined' + (' ' + css if css else '')
			style = 'style="width:{}px;"'.format(self.px(self.total - 2 * PAD))
			head, head_width = (label, brand_width) if brand else (lead, lead_width)
			gap = self.total - 2 * PAD - head_width - left_width - 1.5 - controls_width - extra_width - TOOL - 0.6
			if gap >= 0:
				toolbar = '<div class="{}" {}>{}{}{}{}{}{}{}</div>'.format(cell, style, head, left, separator, controls, self.slot('', gap), extra, gear)
			else:
				gap = max(0, self.total - 2 * PAD - controls_width - extra_width - TOOL - 0.6)
				toolbar = '<div class="{}" {}>{}{}</div><div class="{} continued" {}>{}{}{}{}</div>'.format(cell, style, head, left, cell, style, controls, self.slot('', gap), extra, gear)
			return toolbar, ''
		style = 'style="width:{}px;"'.format(self.px(rest_width))
		if gap >= 0:
			rest = '<div class="toolbar controls-cell" {}>{}{}{}{}{}{}</div>'.format(
				style, left, separator, controls, self.slot('', gap), extra, gear)
		else:
			gap = max(0, rest_width - controls_width - extra_width - TOOL - 0.6)
			rest = '<div class="toolbar controls-cell" {}>{}</div><div class="toolbar controls-cell continued" {}>{}{}{}{}</div>'.format(
				style, left, style, controls, self.slot('', gap), extra, gear)
		return brand_cell, rest

	def separator(self):
		return self.slot('<span class="separator glyph">│</span>', 1.5, 'center')

	def row_height(self):
		"""Height of a pane row in rem: the mockup row plus the configured padding on each side."""
		return (2.0 if self.state.compact else ROW) + 2 * self.line_padding / self.font

	def font_family(self):
		faces = ([self.font_face] if self.font_face else []) + ['Menlo', 'Consolas', 'DejaVu Sans Mono']
		return ', '.join('"{}"'.format(face.replace('"', '')) for face in faces) + ', monospace'

	def document(self, content):
		css = CSS
		row = self.row_height()
		# Rows are padded around minihtml's natural text line (TEXT_LINE rem for 1rem text) so
		# plain text and fixed-width slots share a baseline; explicit heights would push slot
		# text to the bottom of the row.
		for key, value in {
			'$fontpx': '{}px'.format(self.font), '$fontfamily': self.font_family(),
			'$padrem': '{}rem'.format(PAD), '$panepadrem': '{}rem'.format(PANE_PAD),
			'$rowpadrem': '{:.3f}rem'.format((row - TEXT_LINE) / 2), '$headpadrem': '{:.3f}rem'.format((row - HEADING_LINE) / 2),
			'$linepadrem': '{:.3f}rem'.format((LINE - TEXT_LINE) / 2), '$tabpadrem': '{:.3f}rem'.format((TABS_HEIGHT - 0.07 - TEXT_LINE) / 2),
			'$tabsiderem': '{}rem'.format(TAB_PAD), '$toolpadrem': '{:.3f}rem'.format(TOOLBAR_PAD),
		}.items():
			css = css.replace(key, value)
		for key, value in COLORS.items():
			css = css.replace(key, value)
		css = css.replace('$selection', self.palette['selection'])
		scoped = []
		for rule in css.splitlines():
			selector, separator, declarations = rule.partition('{')
			if not separator:
				continue
			selectors = []
			for item in selector.split(','):
				item = item.strip()
				selectors.append(item if item == 'html' else 'body#' + self.document_id if item == 'body' else '#' + self.document_id + ' ' + item)
			scoped.append(', '.join(selectors) + ' {' + declarations)
		return '<body id="{}"><style>{}</style>{}</body>'.format(self.document_id, '\n'.join(scoped), content)

	def rows_height(self, rows):
		"""Approximate rem height of a column of rows (used to size the panes)."""
		height = 0.0
		for row in rows:
			if 'class="gap-large"' in row:
				height += 0.8
			elif 'class="gap"' in row:
				height += 0.4
			else:
				height += self.row_height()
		return height
