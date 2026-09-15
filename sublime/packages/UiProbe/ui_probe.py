"""UI probe: a fixed header view stacked above a scrollable body view, no input strip.

Sublime shows one output panel at a time and minihtml has no flexbox, overflow or fixed
positioning, so the only way to stack a non-scrolling region above a scrolling one is two
*views* in two *groups* of a row layout. This package opens exactly that from sample content
so the behaviour can be seen before anything is built on it:

- Group 0 (top): a scratch view holding one empty line and a red header phantom. The group is
  sized to the header, so there is nothing to scroll.
- Group 1 (bottom): a scratch view with a few hundred lines and blue marker phantoms, which
  scrolls on its own.

Group heights are fractions of the window, not pixels, so a poll scales the top row until its
text area matches the wanted header height (the same trick Debugger2 uses with font size on
an io panel's input strip). Everything is restored by `ui_probe_close`.
"""
import sublime
import sublime_plugin

SETTINGS = 'UiProbe.sublime-settings'
KEY = 'ui_probe'

# window id -> saved state
_probes = {}


def _settings():
	return sublime.load_settings(SETTINGS)


def _esc(text):
	return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class UiProbeOpenCommand(sublime_plugin.WindowCommand):
	def run(self):
		window = self.window
		_close(window)

		settings = _settings()
		hide_tabs = bool(settings.get('hide_tabs', True))
		lines = int(settings.get('body_lines', 300))

		own_window = False
		if settings.get('separate_window', False):
			sublime.run_command('new_window')
			window = sublime.active_window()
			own_window = True

		state = {
			'layout': window.layout(),
			'active': window.active_view(),
			'tabs_hidden': False,
			'own_window': own_window,
			'fraction': 0.15,
		}
		_probes[window.id()] = state

		if hide_tabs and window.get_tabs_visible():
			window.run_command('toggle_tabs')
			state['tabs_hidden'] = True

		window.set_layout(_layout(state['fraction']))

		window.focus_group(0)
		header = window.new_file()
		_configure(header, 'UI Probe: header (fixed)')
		header.settings().set('scroll_past_end', False)
		header.settings().set('word_wrap', False)
		header.run_command('append', {'characters': ''})

		window.focus_group(1)
		body = window.new_file()
		_configure(body, 'UI Probe: body (scrollable)')
		body.run_command('append', {'characters': '\n' + '\n'.join('body line %d' % i for i in range(1, lines + 1))})

		state['header'] = header
		state['body'] = body
		state['header_set'] = sublime.PhantomSet(header, KEY)
		state['body_set'] = sublime.PhantomSet(body, KEY)
		state['width'] = 0

		_draw_body(state)
		_poll(window.id())


class UiProbeCloseCommand(sublime_plugin.WindowCommand):
	def run(self):
		# a probe opened with `separate_window` lives in another window: close it from anywhere
		for window_id in list(_probes):
			for window in sublime.windows():
				if window.id() == window_id:
					_close(window)
		_close(self.window)


class UiProbeDumpCommand(sublime_plugin.WindowCommand):
	"""Writes view geometry to `path` (a file) to see where gaps come from."""

	def run(self, path):
		state = _probes.get(self.window.id())
		if not state:
			return
		out = []
		for key in ('header', 'body'):
			v = state[key]
			out.append('%s: viewport_extent=%s viewport_position=%s layout_extent=%s line_height=%s '
				'text_to_layout(0)=%s line0_region=%s padding=(%s,%s) size=%s' % (
					key, v.viewport_extent(), v.viewport_position(), v.layout_extent(), v.line_height(),
					v.text_to_layout(0), v.line(0), v.settings().get('line_padding_top'),
					v.settings().get('line_padding_bottom'), v.size()))
		out.append('fraction=%s layout=%s' % (state['fraction'], self.window.layout()))
		with open(path, 'w') as f:
			f.write('\n'.join(out) + '\n')


def _close(window):
	# popped first, so the on_pre_close of the views closed below finds no state and cannot
	# tear down a probe that `ui_probe_open` is about to create in the same window
	state = _probes.pop(window.id(), None)
	# sweep every probe view, not just the remembered pair: editing this plugin reloads the
	# module and empties `_probes`, which would otherwise leave orphans behind
	for view in window.views():
		if view.settings().get(KEY) and view.is_valid():
			view.set_scratch(True)
			view.close()
	if not state:
		return
	if state.get('own_window'):
		if window.is_valid():
			window.run_command('close_window')
		return
	window.set_layout(state['layout'])
	if state['tabs_hidden'] and not window.get_tabs_visible():
		window.run_command('toggle_tabs')
	active = state.get('active')
	if active and active.is_valid():
		window.focus_view(active)


class UiProbeListener(sublime_plugin.EventListener):
	def on_pre_close(self, view):
		if not view.settings().get(KEY):
			return
		window = view.window()
		state = _probes.get(window.id()) if window else None
		if not state or view.id() not in (state['header'].id(), state['body'].id()):
			return
		# the user closed one of the two views: tear the probe down once the close has landed
		sublime.set_timeout(lambda: _close(window))


def _layout(fraction):
	fraction = max(0.02, min(0.9, fraction))
	return {
		'cols': [0.0, 1.0],
		'rows': [0.0, fraction, 1.0],
		'cells': [[0, 0, 1, 1], [0, 1, 1, 2]],
	}


def _configure(view, name):
	view.set_name(name)
	view.set_scratch(True)
	s = view.settings()
	s.set(KEY, True)
	s.set('gutter', False)
	s.set('line_numbers', False)
	s.set('fold_buttons', False)
	s.set('draw_indent_guides', False)
	s.set('highlight_line', False)
	s.set('draw_white_space', 'none')
	s.set('rulers', [])
	s.set('margin', 0)
	s.set('caret_style', 'solid')
	s.set('is_widget', True)
	# the user's 7px line padding would frame every band with blank space
	s.set('line_padding_top', 0)
	s.set('line_padding_bottom', 0)
	# an inline phantom wider than the viewport wraps onto a second row, leaving a blank
	# text row above it (seen as text_to_layout(0).y == line_height + padding)
	s.set('word_wrap', False)


PAD_X = 10
PAD_Y = 6


def _band_width(view):
	# content width so that content + horizontal padding stays inside the viewport and the
	# inline phantom never wraps; minihtml has no box-sizing
	return max(40, int(view.viewport_extent()[0]) - 2 * PAD_X - 4)


def _draw_header(state):
	header = state['header']
	width = _band_width(header)
	state['width'] = width
	current = int(header.viewport_extent()[1])
	html = (
		'<body id="ui-probe">'
		'<div style="background-color: #c0392b; color: #ffffff; padding: %dpx %dpx; width: %dpx;">'
		'<b>FIXED HEADER</b> &nbsp; group 0, never scrolls &nbsp; '
		'<span style="color: #f5c6c0;">content %dpx, text area %dpx, row fraction %.3f</span>'
		'</div></body>'
	) % (PAD_Y, PAD_X, width, int(header.layout_extent()[1]), current, state['fraction'])
	# inline on the buffer's only (empty) line, so the line *is* the header and nothing blank
	# shows above it; LAYOUT_BLOCK would draw below the line and leave a gap
	state['header_set'].update([sublime.Phantom(sublime.Region(0), html, sublime.LAYOUT_INLINE)])


def _draw_body(state):
	body = state['body']
	width = _band_width(body)
	phantoms = []
	top = (
		'<body id="ui-probe"><div style="background-color: #2d6cdf; color: #ffffff; padding: %dpx %dpx; width: %dpx;">'
		'<b>SCROLLABLE BODY</b> &nbsp; group 1, scroll me: this banner leaves with the text</div></body>'
	) % (PAD_Y, PAD_X, width)
	phantoms.append(sublime.Phantom(sublime.Region(0), top, sublime.LAYOUT_INLINE))  # line 0 is empty
	for line in range(25, body.rowcol(body.size())[0], 25):
		pt = body.text_point(line, 0)
		html = (
			'<body id="ui-probe"><div style="background-color: #1f4fa8; color: #dbe6ff; padding: 2px %dpx; width: %dpx;">'
			'marker at %s</div></body>'
		) % (PAD_X, width, _esc(body.substr(body.line(pt))))
		phantoms.append(sublime.Phantom(sublime.Region(pt), html, sublime.LAYOUT_BLOCK))
	state['body_set'].update(phantoms)


def _poll(window_id):
	state = _probes.get(window_id)
	if not state:
		return
	header, body = state['header'], state['body']
	if not header.is_valid() or not body.is_valid():
		return
	window = header.window()
	if not window:
		return

	_draw_header(state)
	# fit the top row to the header phantom: viewport height is text area only, the tab bar
	# (if shown) sits above it inside the same group, so scale and iterate
	current = header.viewport_extent()[1]
	# fit the row to the header's own height (the phantom line is the whole buffer), so no
	# blank strip is left under the band
	wanted = header.layout_extent()[1]
	if current > 0 and abs(current - wanted) > 2:
		state['fraction'] = max(0.02, min(0.9, state['fraction'] * wanted / current))
		window.set_layout(_layout(state['fraction']))
		header.set_viewport_position((0, 0), False)

	if _band_width(body) != state.get('body_width'):
		state['body_width'] = _band_width(body)
		_draw_body(state)

	sublime.set_timeout(lambda: _poll(window_id), 400)
