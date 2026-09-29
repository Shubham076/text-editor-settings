from __future__ import annotations

from dataclasses import dataclass
from html import escape

import sublime


@dataclass(frozen=True)
class Option:
	value: str
	label: str
	description: str = ''
	group: str = ''
	badge: str = ''
	badge_color: str = ''


_ACTIVE = {}


def _mix(first, second, amount):
	return '#%02x%02x%02x' % tuple(round(int(first[i:i + 2], 16) * (1 - amount) + int(second[i:i + 2], 16) * amount) for i in (1, 3, 5))


def menu_html(view, options, selected, caption, font_size=None, action=None):
	style = view.style()
	background = style.get('background') or '#ffffff'
	foreground = style.get('foreground') or '#333333'
	# Same fill as the toolbar's picker box and the neutral status pill (foreground at 8% over the
	# background), so the menu reads as part of the toolbar instead of a white sheet on light schemes.
	surface = _mix(background, foreground, 0.08)
	muted = _mix(foreground, background, 0.35)
	border = _mix(background, foreground, 0.25)
	selection = style.get('selection') or style.get('line_highlight') or _mix(background, foreground, 0.12)
	# the check mark and the footer action are the plain text colour, bold, as the console's text
	# is; the scheme's accent is not used so the popup does not introduce a colour the panels lack
	css = '''
body {{ margin: 0; padding: 0; background-color: {surface}; color: {foreground}; }}
#debugger-menu {{ font-size: 1rem; }}
#debugger-menu a {{ color: {foreground}; text-decoration: none; }}
#debugger-menu .menu {{ padding: 0.6rem 0.75rem 0; white-space: nowrap; }}
#debugger-menu .title {{ padding: 0.5rem 0.9rem 0.9rem; font-weight: bold; }}
#debugger-menu .group {{ padding: 0.5rem 0.9rem 0.35rem; font-size: 0.8rem; font-weight: bold; color: {muted}; }}
#debugger-menu .item {{ display: block; padding: 0.55rem 0.9rem; border-radius: 0.5rem; }}
#debugger-menu .item.active {{ background-color: {selection}; }}
#debugger-menu .item.active .description {{ color: {foreground}; }}
#debugger-menu .mark {{ display: inline-block; width: 1.6rem; color: {foreground}; }}
#debugger-menu .label {{ font-weight: bold; }}
#debugger-menu .description, #debugger-menu .hint {{ color: {muted}; }}
#debugger-menu .badge {{ padding: 0.12rem 0.6rem; border-radius: 1rem; font-size: 0.85rem; font-weight: bold; color: {foreground}; background-color: color(var(--foreground) alpha(0.08)); }}
#debugger-menu .footer {{ margin-top: 0.5rem; padding: 0.8rem 0.9rem; border-top: 1px solid {border}; }}
#debugger-menu .action {{ font-weight: bold; color: {foreground}; }}
'''.format(**locals())
	if font_size:
		css = 'html {{ font-size: {:g}px; }}'.format(float(font_size)) + css
	for color in ('yellowish', 'greenish', 'redish', 'bluish'):
		css += '#debugger-menu .badge-{0} {{ color: color(var(--{0}) min-contrast({1} 4)); background-color: color(var(--{0}) alpha(0.15)); }}'.format(color, surface)
	rows = ['<div class="menu"><div class="title">{}</div>'.format(escape(caption))]
	previous_group = None
	widest = len(caption)
	for index, option in enumerate(options):
		if option.group and option.group != previous_group:
			rows.append('<div class="group">{}</div>'.format(escape(option.group.upper())))
		previous_group = option.group
		mark = '<span class="mark">{}</span>'.format('&#10003;' if option.value == selected else '')
		badge = ''
		if option.badge:
			color = option.badge_color if option.badge_color in ('yellowish', 'greenish', 'redish', 'bluish') else ''
			badge = ' <span class="badge badge-{}">&#9679; {}</span>'.format(color, escape(option.badge))
		description = '<br><span class="mark"></span><span class="description">{}</span>{}'.format(escape(option.description), badge) if option.description or badge else ''
		rows.append('<a class="item{}" href="{}">{}<span class="label">{}</span>{}</a>'.format(' active' if option.value == selected else '', 'pick:' + str(index), mark, escape(option.label), description))
		widest = max(widest, len(option.label) + 3, len(option.description) + len(option.badge) + 8)
	left = '<a class="action" href="action">{}</a>'.format(escape(action)) if action else ''
	fill = '&nbsp;' * max(2, min(100, widest) - len(action or '') - 12)
	rows.append('<div class="footer">{}{}<a class="hint" href="close">Esc to close</a></div></div>'.format(left, fill))
	return '<body id="debugger-menu"><style>{}</style>{}</body>'.format(css, ''.join(rows))


class PopupMenu:
	def __init__(self, view, options, on_select, on_hide, action, kind=None):
		self.view = view
		self.options = options
		self.on_select = on_select
		self.on_hide = on_hide
		self.action = action
		self.kind = kind
		self.closed = False

	def close(self, hide=True):
		if self.closed:
			return
		self.closed = True
		if _ACTIVE.get(self.view.id()) is self:
			_ACTIVE.pop(self.view.id())
			if hide and self.view.is_valid() and self.view.is_popup_visible():
				self.view.hide_popup()
		if self.on_hide:
			self.on_hide()

	def _navigate(self, href):
		if self.closed or not self.view.is_valid():
			return
		if href == 'close':
			self.close()
		elif href == 'action' and self.action:
			callback = self.action[1]
			self.close()
			callback()
		else:
			kind, _, index = href.partition(':')
			if kind == 'pick' and index.isdigit() and int(index) < len(self.options):
				value = self.options[int(index)].value
				self.close()
				if self.on_select:
					self.on_select(value)


def show(view, options, selected=None, on_select=None, location=-1, caption='Choose an option',
		on_hide=None, max_width=640, max_height=600, keep_on_selection_modified=False, font_size=None, action=None, kind=None):
	options = tuple(Option(o, o) if isinstance(o, str) else o for o in options)
	if any(not isinstance(o, Option) or not all(isinstance(v, str) for v in (o.value, o.label, o.description, o.group, o.badge, o.badge_color)) for o in options):
		raise ValueError('Options must have string attributes')
	if len({o.value for o in options}) != len(options):
		raise ValueError('Option values must be unique')
	if selected is not None and not any(o.value == selected for o in options):
		raise ValueError('Unknown selected option')
	if action is not None and (len(action) != 2 or not isinstance(action[0], str) or not callable(action[1])):
		raise ValueError('action must be a (label, callback) pair')
	if not view.is_valid():
		return None
	if previous := _ACTIVE.get(view.id()):
		previous.close()
	menu = PopupMenu(view, options, on_select, on_hide, action, kind=kind)
	_ACTIVE[view.id()] = menu
	flags = sublime.KEEP_ON_SELECTION_MODIFIED if keep_on_selection_modified else 0
	view.show_popup(menu_html(view, options, selected, caption, font_size, action[0] if action else None),
		flags=flags, location=location, max_width=max_width, max_height=max_height,
		on_navigate=menu._navigate, on_hide=lambda: menu.close(hide=False))
	return menu


def plugin_unloaded():
	for menu in list(_ACTIVE.values()):
		menu.close()
