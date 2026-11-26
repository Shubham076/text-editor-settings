from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, Mock

import test_live_ui as fixtures


class StripChipsTests(unittest.TestCase):
	"""The fixed strip: a chip for each running configuration, and only the controls that can be pressed"""

	setUp = fixtures.LiveTests.setUp
	make_ui = fixtures.LiveTests.make_ui
	make_strip = fixtures.LiveTests.make_strip
	session = fixtures.LiveTests.session

	def configure(self, names, selected, running=(), paused=()):
		items = [types.SimpleNamespace(name=name, id_ish=name) for name in names]
		self.backend.project.configurations = items
		self.backend.project.name = selected
		self.backend.project.configuration_or_compound = next(item for item in items if item.name == selected)
		self.backend.sessions = [self.session(name, paused=name in paused) for name in (*running, *paused)]
		self.backend.session = next((session for session in self.backend.sessions if session.configuration.name == selected), None)
		return items

	def strip_html(self, width=1000):
		strip = self.make_strip()
		strip.viewport_extent.return_value = (width, 22)
		self.sublime.PhantomSet = Mock(side_effect=[Mock(), Mock()])
		self.ui = self.make_ui(header_view=strip)
		self.ui.render()
		return self.ui.phantoms.update.call_args.args[0][0][1]

	def chips(self, html):
		"""(css class, title) of every chip, in the order drawn"""
		chips = []
		for part in html.split('<a href="')[1:]:
			head = part.split('>', 1)[0]
			css = head.split('class="', 1)[1].split('"', 1)[0]
			if css.startswith('cfg') and css != 'cfg-cross':
				css = css.replace('cfg-name', 'cfg')
				chips.append((css, head.split('title="', 1)[1].split('"', 1)[0]))
		return chips

	def test_nothing_running_shows_the_selection_and_only_the_start_button(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-api-gateway')
		html = self.strip_html()
		self.assertEqual(self.chips(html), [('cfg active', 'ps-api-gateway · Stopped'), ('cfg more', 'Select run configuration')])
		# nothing running: one button runs it, one debugs it, in that order
		self.assertLess(html.index('title="Run without the debugger"'), html.index('title="Debug"'))
		for title in ('Step over', 'Step into', 'Step out', 'Restart', 'Stop'):
			self.assertNotIn('title="{}'.format(title), html)
		# the status badge is gone: the chip carries the status
		self.assertNotIn('class="state', html)
		self.assertNotIn('class="picker"', html)

	def test_every_running_configuration_is_a_chip_in_project_order_and_stopped_ones_are_not(self):
		self.configure(['ps-api-gateway', 'ps-backend', 'ps-agentic', 'ps-scheduler'], 'ps-agentic',
			running=('ps-agentic', 'ps-api-gateway'), paused=('ps-backend',))
		html = self.strip_html()
		self.assertEqual(self.chips(html), [
			('cfg', 'ps-api-gateway · Running'), ('cfg', 'ps-backend · Paused'), ('cfg active', 'ps-agentic · Running'),
			('cfg more', 'Select run configuration')])
		# the selected chip keeps its whole name, the others lose the words they share
		for text in ('>ps-agentic</a>', '>api-gateway</a>', '>backend</a>'):
			self.assertIn(text, html)
		self.assertNotIn('ps-scheduler', html)
		# running: pause, restart and stop, no stepping
		for title in ('Pause', 'Restart', 'Stop'):
			self.assertIn('title="{}"'.format(title), html)
		self.assertNotIn('title="Step over', html)
		self.assertNotIn('strip continued', html)

	def test_the_button_it_was_started_with_is_green_while_it_runs(self):
		self.configure(['ps-api-gateway'], 'ps-api-gateway')
		html = self.strip_html()
		# nothing running: neither is lit, and play has no background of its own
		self.assertIn('class="tool" title="Run without the debugger"', html)
		self.assertIn('class="tool" title="Debug"', html)

		self.configure(['ps-api-gateway'], 'ps-api-gateway', running=('ps-api-gateway',))
		html = self.strip_html()
		self.assertIn('class="tool" title="Run without the debugger"', html)
		self.assertIn('class="tool active" title="Debug"', html)
		self.assertIn('title="Pause"', html)

		# run without the debugger: play is the lit one, and there is nothing to pause
		self.backend.session.no_debug = True
		html = self.strip_html()
		self.assertIn('class="tool active" title="Run without the debugger"', html)
		self.assertIn('class="tool" title="Debug"', html)
		self.assertNotIn('title="Pause"', html)

	def test_step_buttons_appear_while_the_selection_is_paused(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-backend', running=('ps-api-gateway',), paused=('ps-backend',))
		html = self.strip_html()
		titles = ['Continue', 'Step over', 'Step into', 'Step out', 'Restart', 'Stop']
		positions = [html.index('title="{}"'.format(title)) for title in titles]
		self.assertEqual(positions, sorted(positions))

	def test_a_chip_selects_its_configuration_and_the_selected_chip_opens_the_list(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-backend', running=('ps-api-gateway', 'ps-backend'))
		html = self.strip_html()
		picker = self.ui.toolbar.picker
		picker.select, picker.show = Mock(), Mock()
		html = self.ui.toolbar.strip()
		keys = {}
		for part in html.split('<a href="')[1:]:
			key, rest = part.split('"', 1)
			keys[rest.split('title="', 1)[1].split('"', 1)[0]] = key
		self.ui.handlers[keys['ps-api-gateway · Running']]()
		picker.select.assert_called_once_with('ps-api-gateway')
		picker.show.assert_not_called()
		self.ui.handlers[keys['ps-backend · Running']]()
		self.ui.handlers[keys['Select run configuration']]()
		self.assertEqual(picker.show.call_count, 2)

	def test_chips_that_do_not_fit_are_counted_on_the_list_button_and_the_selection_stays(self):
		names = ['ps-service-number-{}'.format(index) for index in range(8)]
		self.configure(names, names[7], running=names)
		html = self.strip_html(width=700)
		chips = self.chips(html)
		self.assertIn(('cfg active', names[7] + ' · Running'), chips)
		self.assertLess(len(chips), 9)
		hidden = 9 - len(chips)
		self.assertIn('>+{}<'.format(hidden), html)
		self.assertNotIn('strip continued', html)
		# the first chips are the ones kept, in order
		self.assertEqual([title for _, title in chips[:-2]], [name + ' · Running' for name in names[:len(chips) - 2]])

	def test_a_selected_compound_is_a_chip_and_other_compounds_are_not(self):
		items = self.configure(['api', 'web'], 'api', running=('api', 'web'))
		compound = self.dap.ConfigurationCompound()
		compound.name, compound.id_ish, compound.configurations = 'everything', 'everything', ['api', 'web']
		self.backend.project.compounds = [compound]
		self.assertEqual([title for _, title in self.chips(self.strip_html())],
			['api · Running', 'web · Running', 'Select run configuration'])
		self.backend.project.configuration_or_compound = compound
		self.backend.project.name = 'everything'
		self.assertEqual([title for _, title in self.chips(self.strip_html())][0], 'everything · Running')

	def test_status_dots_take_their_colour_from_the_stylesheet(self):
		self.configure(['a', 'b', 'c'], 'c', running=('a',), paused=('b',))
		html = self.strip_html()
		# green while running and yellow while paused, the classes the rest of the ui uses; a ring when stopped
		self.assertIn('<span class="infoish">&#9679;</span>', html)
		self.assertIn('<span class="warnish">&#9679;</span>', html)
		self.assertIn('<span class="faint">&#9675;</span>', html)
		document = self.ui.document('')
		self.assertIn('.string, #debugger-live-ui .infoish { color: color(var(--greenish) min-contrast(var(--background) 4)); }', document)

	def test_short_names_only_drop_whole_shared_words(self):
		short_names = self.loaded['_live_test.modules.ui.toolbar'].short_names
		self.assertEqual(short_names(['ps-backend', 'ps-agentic']), ['backend', 'agentic'])
		self.assertEqual(short_names(['backend', 'backup']), ['backend', 'backup'])
		self.assertEqual(short_names(['api', 'api-worker']), ['api', 'api-worker'])
		self.assertEqual(short_names(['only-one']), ['only-one'])
		self.assertEqual(short_names([]), [])

	def press(self, html, title):
		"""Presses the link titled `title` and runs what it starts"""
		key = html.split('title="{}"'.format(title))[0].rsplit('<a href="', 1)[1].split('"', 1)[0]
		result = self.ui.handlers[key]()
		if result is not None:
			self.asyncio.run(result)

	def stoppable(self):
		async def stop(session):
			self.backend.sessions.remove(session)
		self.backend.stop = AsyncMock(side_effect=stop)

	def test_every_chip_has_its_cross_inside_it_the_selected_one_too(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-backend', running=('ps-api-gateway',))
		html = self.strip_html()
		self.assertEqual(html.count('from the bar'), 2)
		# the name and its cross are two links inside the one box of the chip
		for name, css in (('ps-api-gateway', 'cfg'), ('ps-backend', 'cfg active')):
			chip = html.split('<span class="{}">'.format(css.replace('cfg', 'cfg boxed')), 1)[1].split('"></span></span>', 1)[0]
			self.assertIn('title="{} · '.format(name), chip)
			self.assertIn('title="Remove {} from the bar"'.format(name), chip)

	def test_one_that_stops_keeps_its_chip_until_its_cross_is_pressed(self):
		names = ['ps-api-gateway', 'ps-backend', 'ps-agentic']
		self.configure(names, 'ps-agentic', running=('ps-api-gateway', 'ps-backend'))
		self.strip_html()

		# ps-backend is stopped: still a chip
		self.configure(names, 'ps-agentic', running=('ps-api-gateway',))
		html = self.strip_html()
		self.assertEqual(self.chips(html), [
			('cfg', 'ps-api-gateway · Running'), ('cfg', 'ps-backend · Stopped'), ('cfg active', 'ps-agentic · Stopped'),
			('cfg more', 'Select run configuration')])

		# its cross takes it off without asking: nothing of it is running
		self.sublime.ok_cancel_dialog = Mock(return_value=False)
		self.press(html, 'Remove ps-backend from the bar')
		self.sublime.ok_cancel_dialog.assert_not_called()
		html = self.strip_html()
		self.assertEqual(self.chips(html), [
			('cfg', 'ps-api-gateway · Running'), ('cfg active', 'ps-agentic · Stopped'), ('cfg more', 'Select run configuration')])

		# and running it again puts it back
		self.configure(names, 'ps-agentic', running=('ps-api-gateway', 'ps-backend'))
		self.assertIn(('cfg', 'ps-backend · Running'), self.chips(self.strip_html()))

	def test_the_cross_of_a_running_chip_asks_and_cancel_leaves_it_running(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-backend', running=('ps-api-gateway', 'ps-backend'))
		self.stoppable()
		html = self.strip_html()
		self.sublime.ok_cancel_dialog = Mock(return_value=False)
		self.press(html, 'Remove ps-api-gateway from the bar')
		self.sublime.ok_cancel_dialog.assert_called_once()
		self.assertIn('ps-api-gateway is running', self.sublime.ok_cancel_dialog.call_args.args[0])
		self.backend.stop.assert_not_awaited()
		self.assertIn(('cfg', 'ps-api-gateway · Running'), self.chips(self.strip_html()))

	def test_the_cross_of_a_running_chip_stops_it_and_takes_it_off_once_confirmed(self):
		self.configure(['ps-api-gateway', 'ps-backend'], 'ps-backend', running=('ps-api-gateway', 'ps-backend'))
		self.stoppable()
		html = self.strip_html()
		self.sublime.ok_cancel_dialog = Mock(return_value=True)
		self.press(html, 'Remove ps-api-gateway from the bar')
		self.assertEqual(self.backend.stop.await_count, 1)
		self.assertEqual([session.configuration.name for session in self.backend.sessions], ['ps-backend'])
		self.assertEqual(self.chips(self.strip_html()), [('cfg active', 'ps-backend · Running'), ('cfg more', 'Select run configuration')])

	def test_removing_the_selected_chip_selects_the_next_one_or_nothing(self):
		names = ['ps-api-gateway', 'ps-backend', 'ps-agentic']
		items = self.configure(names, 'ps-backend', running=('ps-api-gateway', 'ps-backend', 'ps-agentic'))
		self.stoppable()
		self.sublime.ok_cancel_dialog = Mock(return_value=True)
		self.backend.open_session_output = Mock()
		self.panel.enable_input_mode = self.panel.scroll_to_end = Mock()
		loaded = []

		def load_configuration(name, id_ish=''):
			loaded.append(name)
			self.backend.project.configuration_or_compound = next((item for item in items if item.name == name), None)
			self.backend.project.name = name
		self.backend.project.load_configuration = load_configuration

		# the one after it
		self.press(self.strip_html(), 'Remove ps-backend from the bar')
		self.assertEqual(loaded, ['ps-agentic'])
		# at the end of the row, the one before it
		self.press(self.strip_html(), 'Remove ps-agentic from the bar')
		self.assertEqual(loaded, ['ps-agentic', 'ps-api-gateway'])
		# the last one: nothing selected, and the bar offers the list
		self.press(self.strip_html(), 'Remove ps-api-gateway from the bar')
		self.assertEqual(loaded, ['ps-agentic', 'ps-api-gateway', ''])
		self.assertEqual(self.backend.sessions, [])
		self.assertEqual(self.chips(self.strip_html()), [('cfg more', 'Select run configuration')])

	def test_picking_a_configuration_shows_it_on_the_tab_it_was_last_looked_at_on(self):
		items = self.configure(['ps-api-gateway', 'ps-backend'], 'ps-api-gateway')

		def load_configuration(name, id_ish=''):
			self.backend.project.configuration_or_compound = next(item for item in items if item.name == name)
			self.backend.project.name = name
		self.backend.project.load_configuration = load_configuration
		self.strip_html()
		self.ui.toolbar.select_tab = Mock()

		# never looked at: the tab that is open stays
		self.ui.state.tab = 'watch'
		self.ui.toolbar.picker.select('ps-backend')
		self.ui.toolbar.select_tab.assert_called_once_with('watch')
		# backend is left on its console, and gateway comes back on the watch
		self.ui.state.tab = 'console'
		self.ui.toolbar.picker.select('ps-api-gateway')
		self.assertEqual(self.ui.toolbar.select_tab.call_args.args, ('watch',))
		self.ui.state.tab = 'debugger'
		self.ui.toolbar.picker.select('ps-backend')
		self.assertEqual(self.ui.toolbar.select_tab.call_args.args, ('console',))

	def test_the_red_of_stop_is_the_theme_s_on_a_terminal_too(self):
		# a terminal's view has the Terminus scheme, whose red is the terminal's pure red
		self.view.style.return_value = dict(self.view.style.return_value, redish='#cd0000', bluish='#0000ee')
		reference = Mock()
		reference.is_valid.return_value = True
		reference.style.return_value = {'background': '#2d353b', 'foreground': '#d3c6aa', 'redish': '#e67e80', 'bluish': '#7fbbb3'}
		self.backend.callstack.view = reference
		self.configure(['ps-api-gateway'], 'ps-api-gateway', running=('ps-api-gateway',))
		self.strip_html()
		self.assertEqual(self.ui.palette['redish'], '#e67e80')
		self.assertEqual(self.ui.palette['bluish'], '#7fbbb3')
		# what the icons are blended against stays the view's own
		self.assertEqual(self.ui.palette['background'], '#fafafa')


if __name__ == '__main__':
	unittest.main()
