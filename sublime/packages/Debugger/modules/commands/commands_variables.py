from functools import partial

import sublime

from .. import core, dap, ui
from ..settings import Settings
from ..views.session_scope import SessionScope
from ..views.variable import VariableView
from ..command import Action, ActionElement


class VariableCopyValue(ActionElement):
	name = 'Copy Value'
	key = 'variable_copy_value'
	element = VariableView

	def action(self, debugger, element: VariableView):
		element.copy_value()


class VariableCopyAsExpression(ActionElement):
	name = 'Copy as Expression'
	key = 'variable_copy_expression'
	element = VariableView

	def action(self, debugger, element: VariableView):
		element.copy_expr()


class VariableAddToWatch(ActionElement):
	name = 'Add To Watch'
	key = 'variable_add_to_watch'
	element = VariableView

	def action(self, debugger, element: VariableView):
		element.add_watch()


class WatchRemoveExpression(Action):
	name = 'Remove Expression'
	key = 'watch_remove_expression'

	def action(self, debugger):
		ui.InputList('Remove watched expression')[[
			ui.InputListItem(partial(debugger.watch.remove, expression), expression.value)
			for expression in debugger.watch.expressions
		]].run()


class WatchRemoveAllExpression(Action):
	name = 'Remove All Expressions'
	key = 'watch_remove_all_expressions'

	def action(self, debugger):
		debugger.watch.remove_all()


class CopyCallstack(Action):
	name = 'Copy Callstack'
	key = 'copy_callstack'

	@core.run
	async def action(self, debugger):
		lines = []
		async def collect(session):
			lines.append(session.name)
			for thread in session.threads:
				lines.append(thread.name)
				if thread.stopped:
					lines.extend('\t' + frame.name for frame in await thread.children())
			for child in session.children:
				await collect(child)
		try:
			for session in SessionScope(debugger, active_only=Settings.session_panels).sessions:
				await collect(session)
			sublime.set_clipboard('\n'.join(lines))
		except dap.Error as error:
			debugger.console.error(str(error))
