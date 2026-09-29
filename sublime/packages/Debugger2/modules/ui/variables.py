from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ..variable_format import PYTHON_GROUPS, value_summary
from ..views.variable import VariableView, VariableViewState
from .style import ACTION, CONTROL

if TYPE_CHECKING:
	from .panel import PanelUI


class VariablesPane:
	def __init__(self, ui: PanelUI):
		self.ui = ui
		self.actions = {}
		self.limits = {}

	def reset(self):
		self.actions.clear()
		self.limits.clear()

	def watch(self, width):
		ui = self.ui
		expressions = ui.backend.watch.expressions
		# no add button: the prompt strip below the Watch panel adds an expression on enter
		rows = [ui.heading('Watch', 'watch', width, suffix=' ({})'.format(len(expressions)))]
		if 'watch' not in ui.state.expanded:
			return rows
		for expression in expressions:
			result = expression.results.get(ui.active_session)
			variable = result if result is not None and not isinstance(result, Exception) else None
			if variable and variable.session is ui.active_session and variable.session.is_paused:
				rows.extend(self.variable_rows(variable, width, on_edit=partial(self.edit_watch, expression), on_remove=partial(self.remove_watch, expression),
					key='watch:' + expression.value))
			else:
				content = ui.expression(expression.value, str(result) if isinstance(result, Exception) else 'Not available', 'muted', width - 2 * ACTION)
				content += ui.button('edit', 'Edit expression', partial(self.edit_watch, expression)) + ui.button('close', 'Remove expression', partial(self.remove_watch, expression))
				rows.append(ui.row(content))
		if not expressions:
			rows.append(ui.row('<span class="muted">Type an expression below and press enter</span>'))
		return rows

	def edit_watch(self, expression):
		self.ui.prompt('Edit expression', expression.value, lambda value: self.ui.backend.watch.edit(expression, value))

	def remove_watch(self, expression):
		if expression in self.ui.backend.watch.expressions:
			self.ui.backend.watch.remove(expression)

	def render(self, width):
		ui = self.ui
		rows = [ui.heading('Variables', 'variables', width)]
		if 'variables' not in ui.state.expanded:
			return rows
		session = ui.active_session
		if not session or not session.is_paused:
			return rows + [ui.row('<span class="muted">Available when paused</span>')]
		for index, variable in enumerate(session.variables):
			rows.extend(self.variable_rows(variable, width, key=self.scope_key(index, variable)))
		return rows

	def scope_key(self, index, scope):
		"""The expansion key of a top-level scope (Locals, Globals, ...): its name, not its object

		Every step delivers new variable objects, so nothing keyed by object survives a step. Rows
		are keyed by their name path instead (`variable_rows`): a scope by its name, a variable by
		the scope and the names down to it, a watch by its expression. What the user opened stays
		open through stepping until they fold it; the paths under a scope are forgotten when the
		last session ends (`PanelUI.forget_expanded_variables`), the scopes' own state is kept. The
		first scope, the frame's locals, opens by itself the first time it is seen.
		"""
		key = 'scope:' + scope.name
		if key not in self.ui.state.scopes_seen:
			self.ui.state.scopes_seen.add(key)
			if index == 0:
				self.ui.state.expanded.add(key)
		return key

	def variable_rows(self, variable, width, depth=0, on_edit=None, on_remove=None, key=None):
		ui = self.ui
		key = key if key is not None else 'var:' + variable.name
		if key not in self.actions:
			actions = VariableView(ui.backend, variable, state=VariableViewState())
			actions.dirty = partial(self.variable_changed, variable)
			self.actions[key] = actions
		actions = self.actions[key]
		expanded = key in ui.state.expanded
		indent = min(depth * CONTROL, max(0, width - 8))
		buttons = int(on_edit is not None) + int(on_remove is not None) + int(bool(variable.memoryReference))
		content = ui.slot('', indent)
		content += ui.button('down' if expanded else 'chevron', 'Expand / collapse ' + variable.name,
			partial(ui.toggle, key), variable.has_children, width=CONTROL)
		label_width = max(1, width - indent - CONTROL - buttons * ACTION)
		if variable.name in PYTHON_GROUPS:
			# one of debugpy's group rows: a name that opens, nothing to inspect or copy
			content += ui.text(variable.name, label_width, 'muted')
		else:
			value = value_summary(variable) or ''
			kind = 'string' if value.startswith(('"', "'")) else 'number' if value.replace('.', '', 1).lstrip('-').isdigit() else 'muted'
			label = ui.expression(variable.name, value, kind, label_width)
			content += ui.link(label, actions.edit_variable if variable.containerVariablesReference else actions.copy_value, 'Inspect / copy ' + variable.name)
		if variable.memoryReference:
			content += ui.button('over', 'Open memory', actions.clicked_memory)
		if on_edit:
			content += ui.button('edit', 'Edit expression', on_edit)
		if on_remove:
			content += ui.button('close', 'Remove expression', on_remove)
		rows = [ui.row(content)]
		if not variable.has_children or not expanded:
			return rows
		children = ui.tree.get(variable)
		if children is None or isinstance(children, str):
			return rows + [ui.row(ui.text(children or 'Loading…', width, 'muted'))]
		# debugpy sends its group rows first; what the object holds reads better in front of what it is made of
		children = [child for child in children if child.name not in PYTHON_GROUPS] + [child for child in children if child.name in PYTHON_GROUPS]
		# the first page of children; None once the reader has asked for the rest (`show_more`)
		count = self.limits.get(key, 20)
		for child in children[:count]:
			rows.extend(self.variable_rows(child, width, depth + 1, key='{}/{}'.format(key, child.name)))
		if count is not None and len(children) > count:
			rows.append(ui.row(ui.link('{} more items…'.format(len(children) - count), partial(self.show_more, key), 'Show all variables', 'muted')))
		return rows

	def variable_changed(self, variable):
		self.ui.tree.cache.pop(id(variable), None)
		self.ui.invalidate()

	def show_more(self, key):
		"""The `N more items…` row was clicked: show every child of that row

		Keyed by the row's name path like everything else here, so the limit is found again on the
		next render and survives until the next step clears `limits`. One click shows all of them
		rather than the next page: a reader who asks for more wants the item they are looking for,
		not another round of scrolling and clicking.
		"""
		self.limits[key] = None
		self.ui.invalidate()
