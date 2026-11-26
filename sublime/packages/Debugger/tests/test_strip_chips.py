from __future__ import annotations

import types
import unittest
from unittest.mock import Mock

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
			if css.startswith('cfg'):
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


if __name__ == '__main__':
	unittest.main()
