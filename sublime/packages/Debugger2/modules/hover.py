from __future__ import annotations

from typing import Any, Callable
import html
import sublime
import sublime_plugin

from . import core
from . import dap
from . import ui
from .debugger import Debugger
from .settings import Settings
from .views.variable import VariableView
from .variable_format import (
	CHILD_INDENT,
	CONTINUATION_INDENT,
	WRAP_WIDTH,
	_fields_of,
	_is_flat_contents,
	_leaf_lines,
	_line_for_variable,
	_wrapped,
	PYTHON_GROUPS,
	value_summary,
)

# The name this package registers itself under in LSP
LSP_PROVIDER_NAME = 'Debugger'

# How many children of a value are included in the popup before it gets too noisy
MAX_CHILDREN = 20

# how far into a value the popup goes at most. The hovered value is 0, so 3 is it, its children, theirs,
# and theirs. Deep enough that the fields of a struct inside a slice each get a line rather than being
# printed inline and running off the edge. Below the hovered value itself a level is only asked for when
# the adapter's rendering of the value says nothing about what is inside it, see `_is_opaque`
MAX_DEPTH = 3

# how tall the popup is allowed to get. The popup scrolls, so this is not about what fits on screen, it
# is about how long the hover takes: every level is another request, and the budget is checked before
# each one, so the popup only asks what is inside something it still has room to show
MAX_LINES = 120

# js-debug exposes the inherited prototype chain as a synthetic child. It is useful as a collapsed
# row in Variables, but recursively expanding it in a textual hover fills the popup with Object
# methods instead of the hovered value's own properties.
JAVASCRIPT_PROTOTYPE = '[[Prototype]]'
NON_RECURSIVE_CHILDREN = {JAVASCRIPT_PROTOTYPE}

# debugpy adds a `len()` row to every container and sorts the members of an object that are not its
# data (`__dunder__`, `_protected`, methods, nested classes) into group rows. In the Variables panel
# they are collapsed and cost one row each; a textual hover that expanded them would be about what the
# value is made of rather than what it holds, so it leaves them out
SYNTHETIC_CHILDREN = {'len()', *PYTHON_GROUPS}

# what each level in is indented by

# The class name and size limits LSP uses for its hover popup, see Packages/LSP/popups.css and the
# popup_max_characters_width/popup_max_characters_height settings of LSP
POPUP_CLASSNAME = 'debugger_popup'
POPUP_MAX_CHARACTERS_WIDTH = 120

# where a value is broken across lines. Less than the width above: that one is the popup, and what is
# inside it is narrower by the padding of the wrapper and of mdpopups own container

# what a value that had to be broken across lines is indented by, so a continuation reads as one
POPUP_MAX_CHARACTERS_HEIGHT = 1000

_registered_with_lsp = False


async def evaluate_hover(view: sublime.View, point: int) -> tuple[Debugger, dap.Variable, sublime.Region] | None:
	debugger = Debugger.get(view)
	if not debugger:
		return None

	session = debugger.session
	if not session or not debugger.project.is_source_file(view):
		return None

	r = session.adapter.on_hover_provider(view, point)
	if not r:
		return None

	word_string, region = r
	response = await session.evaluate_expression(word_string, 'hover')
	return debugger, dap.Variable.from_evaluate(session, '', response), region


@core.run
async def show_popup(view: sublime.View, point: int):
	'''The hover popup used when the information is not contributed to the LSP popup

	Renders the same content as the LSP integration with the same stylesheet, so that the hover looks the
	same whether or not LSP is installed. Expanding a value is done by following the link into
	`show_variable_popup`, exactly like from the LSP popup.
	'''
	try:
		r = await evaluate_hover(view, point)
		if not r:
			return

		_, variable, region = r
		lines = await _lines_for(variable, 0, '', MAX_LINES)
		_show_styled_popup(view, region.a, _html_for_variable(variable, lines, view, point))

	# errors trying to evaluate a hover expression should be ignored
	except dap.Error as e:
		core.error('adapter failed hover evaluation', e)

	# anything else is a bug in the popup itself, and swallowing it silently means a hover that does
	# nothing with no way to find out why. `_resolve_lsp_hover_content` already does this
	except Exception:
		core.exception()


@core.run
async def show_variable_popup(view: sublime.View, point: int):
	'''The debuggers own variable popup, with the value expanded and expandable children'''
	try:
		r = await evaluate_hover(view, point)
		if not r:
			return

		debugger, variable, region = r
		component = VariableView(debugger, variable)
		component.toggle_expand()

		popup = ui.Popup(view, region.a)
		with popup:
			with ui.div(width=500):
				component.append_stack()

	# errors trying to evaluate a hover expression should be ignored
	except dap.Error as e:
		core.error('adapter failed hover evaluation', e)


def _show_styled_popup(view: sublime.View, location: int, content: str):
	'''Shows `content` the way LSP shows the content of its hover popup

	Goes through mdpopups with LSPs stylesheet and its wrapper element, so a hover looks identical with
	and without the LSP integration. `subl:` links are handled by minihtml itself, so no on_navigate
	callback is needed for the link into the variable popup.
	'''
	try:
		import mdpopups  # type: ignore

	# mdpopups is a declared dependency of this package so this only covers a broken install, an
	# unstyled popup is still better than no hover at all
	except ImportError:
		view.show_popup(content, location=location, max_width=1024, flags=sublime.PopupFlags.HIDE_ON_MOUSE_MOVE_AWAY)
		return

	css, classname = _popup_css()

	# no <body> of our own: mdpopups wraps what it is given in `<style>...</style><div class="mdpopups">`
	# and minihtml treats <body> as the root element, so one nested inside those divs renders nothing at
	# all. LSP gets away with it because there the body is the root
	mdpopups.show_popup(
		view,
		_html_wrapper(content),
		css=css,
		md=False,
		wrapper_class=classname,
		location=location,
		max_width=int(view.em_width() * POPUP_MAX_CHARACTERS_WIDTH),
		max_height=int(view.line_height() * POPUP_MAX_CHARACTERS_HEIGHT),
		flags=sublime.PopupFlags.HIDE_ON_MOUSE_MOVE_AWAY,
	)


def _popup_css() -> tuple[str, str]:
	'''The stylesheet and wrapper class name for the popup

	Prefers LSPs own stylesheet when LSP is installed, which keeps the popup identical to the LSP hover
	popup including any customization of it, and falls back to our copy of the relevant rules otherwise.
	'''
	try:
		return sublime.load_resource('Packages/LSP/popups.css'), 'lsp_popup'
	except Exception:
		...

	try:
		return sublime.load_resource(core.package_path_relative('contributes/popups.css')), POPUP_CLASSNAME
	except Exception:
		core.exception()
		return '', POPUP_CLASSNAME


def _html_wrapper(content: str) -> str:
	'''The same container LSP wraps each hover section in, see html_wrapper() in LSPs plugin/core/views.py

	The spacer acts as the bottom padding, working around minihtmls margin collapsing bug.
	'''
	return f'<div class="wrapper">{content}<div class="wrapper--spacer"></div></div>'


class DebuggerShowHoverPopupCommand(sublime_plugin.TextCommand):
	'''Opens the debuggers own variable popup, this is linked to from the hover popup'''

	def run(self, edit: sublime.Edit, point: int):
		self.view.hide_popup()
		show_variable_popup(self.view, point)

	def is_enabled(self, point: int = 0):  # type: ignore
		return bool(Debugger.get(self.view))


# --- LSP integration ------------------------------------------------------------------------------


def is_active() -> bool:
	'''Whether the hover information is contributed to the LSP popup instead of shown in our own popup'''
	return _registered_with_lsp


def is_lsp_ignored() -> bool:
	'''Whether LSP is installed but turned off

	A package in `ignored_packages` has its plugins unloaded, but it is still a directory on the import
	path, so `from LSP.plugin import ...` keeps working and hands back a module of a package that is not
	running. Registering with that leaves the hover contributed to a popup nothing will ever show, and
	the debuggers own popup suppressed because it believes LSP has it covered.
	'''
	ignored = sublime.load_settings('Preferences.sublime-settings').get('ignored_packages') or []

	return 'LSP' in ignored


def startup():
	global _registered_with_lsp

	if not Settings.hover_in_lsp_popup:
		return

	if is_lsp_ignored():
		core.info('LSP is ignored, using the built in hover popup')
		return

	try:
		from LSP.plugin import register_hover_content_provider  # type: ignore
	except ImportError:
		core.info('LSP is not installed, using the built in hover popup')
		return
	except Exception:
		core.exception()
		return

	register_hover_content_provider(LSP_PROVIDER_NAME, _lsp_hover_content_provider, priority=-10)
	_registered_with_lsp = True
	core.info('contributing hover information to the LSP popup')


def shutdown():
	global _registered_with_lsp

	if not _registered_with_lsp:
		return

	_registered_with_lsp = False

	try:
		from LSP.plugin import unregister_hover_content_provider  # type: ignore
		unregister_hover_content_provider(LSP_PROVIDER_NAME)
	except Exception:
		core.exception()


def _lsp_hover_content_provider(view: sublime.View, point: int) -> Any:
	from LSP.plugin import Promise  # type: ignore

	promise, resolve = Promise.packaged_task()

	# LSP requests the content from its async worker thread but core.run() can only schedule onto the
	# event loop from the main thread, so hop back onto it before starting the evaluation
	sublime.set_timeout(lambda: _resolve_lsp_hover_content(view, point, resolve))
	return promise


@core.run
async def _resolve_lsp_hover_content(view: sublime.View, point: int, resolve: Callable[[str | None], None]):
	try:
		r = await evaluate_hover(view, point)
		if not r:
			resolve(None)
			return

		_, variable, _ = r
		resolve(_html_for_variable(variable, await _lines_for(variable, 0, '', MAX_LINES), view, point))

	# errors trying to evaluate a hover expression should be ignored
	except dap.Error as e:
		core.error('adapter failed hover evaluation', e)
		resolve(None)

	except Exception:
		core.exception()
		resolve(None)


async def _children_of(variable: dap.Variable) -> list[dap.Variable]:
	if not variable.variablesReference:
		return []

	try:
		children = await variable.fetch()
	except dap.Error:
		return []

	return [child for child in children if child.name not in SYNTHETIC_CHILDREN][:MAX_CHILDREN]


def _is_opaque(variable: dap.Variable) -> bool:
	'''Whether the adapter's rendering of the value leaves out what is inside it, so the popup has to ask

	The Variables panel shows a value one level at a time and the reader opens what they want; a hover
	cannot, so it decides for them. What it decides by is the `value` the adapter wrote. debugpy writes
	the repr of an object, `Config(a=1, sub=Sub(x=2))`, which names every field and is laid out one per
	line by `_leaf_lines` without a request. Asking for its children instead brings back everything
	`dir()` finds on it: for a pydantic model that is `model_fields`, `model_config` and the rest of the
	class, and a hover on the object that owns it fills with those instead of the object's own fields.

	Delve writes `(*"types.X")(0x1400009e160)` for a value it stopped short of, js-debug writes `Object`,
	lldb `Item @ 0x16fdfe260`, and any of them elides deeper contents as `...`: none of those say anything
	a reader wants, and only the adapter's `variables` request does.
	'''
	value = ' '.join((variable.value or '').split())

	# debugpy and delve elide with three dots, js-debug with the one character ellipsis
	if '...' in value or '…' in value:
		return True

	# `Config(a=1)`, `types.T {A: 1}`, `{'k': 1}`: every field is named
	if _fields_of(value):
		return False

	# `[1, 2, 3]`, `{}`: a literal of nothing but scalars is all there is. Only a literal: delve's
	# `(*T)(0x...)` is just as flat and says nothing
	return not (value[:1] in ('[', '{') and value[-1:] in (']', '}') and _is_flat_contents(value))


async def _lines_for(variable: dap.Variable, depth: int, indent: str, limit: int) -> list[str]:
	'''The value and, as far down as `MAX_DEPTH`, what is inside it

	One level is not enough. An adapter renders the value of a variable to a depth of its own choosing
	and marks what it did not load: delve writes `(*"types.PluginSelection")(0x1400009e160)` for an
	element it stopped short of, which is an address and nothing a reader wants. Its own `variables`
	request answers properly, so ask again for anything that has more inside it.
	'''
	# the hovered value is always opened, that is what the hover is for; what is inside it only where
	# the adapter's own rendering of it would leave the reader with an address or a type name
	expand = depth < MAX_DEPTH and variable.name not in NON_RECURSIVE_CHILDREN and (depth == 0 or _is_opaque(variable))

	if not expand:
		return _leaf_lines(variable.name, variable.value, indent)[:limit]

	# a value that is about to have its contents listed underneath does not need them inline as well
	value = value_summary(variable)

	children = await _children_of(variable)

	# js-debug sometimes puts a complete object literal in `value` as well as returning each property
	# as a child. Once the children are rendered that preview repeats every property. The synthetic
	# prototype child gives us an adapter-independent way to recognize that representation and a useful
	# short label for it.
	prototype = next((child for child in children if child.name == JAVASCRIPT_PROTOTYPE), None)
	if prototype and (variable.value or '').lstrip().startswith(('{', '[')):
		value = value_summary(prototype) or variable.type or value

	lines = _wrapped(_line_for_variable(variable.name, value, indent), indent + CONTINUATION_INDENT)

	for child in children:
		# the budget bounds the requests as well as the height: going deeper only happens while there is
		# room to show what comes back
		if len(lines) >= limit:
			lines.append(indent + CHILD_INDENT + '…')
			break

		lines += await _lines_for(child, depth + 1, indent + CHILD_INDENT, limit - len(lines))

	return lines


def _html_for_variable(variable: dap.Variable, lines: list[str], view: sublime.View, point: int) -> str:
	content = _syntax_highlight(view, '\n'.join(lines))

	if variable.variablesReference:
		url = sublime.command_url('debugger_show_hover_popup', {'point': point})
		content += f'<p><a href="{url}">Open in Debugger</a></p>'

	return content


def _syntax_highlight(view: sublime.View, text: str) -> str:
	'''Renders text as a code block highlighted with the syntax of the hovered view

	This is what gives the content the same look as the content of a language server, which goes through
	mdpopups as well. mdpopups is a declared dependency of this package, so the plain text fallback only
	covers a broken install.
	'''
	try:
		import mdpopups  # type: ignore
		return mdpopups.syntax_highlight(view, text, language=mdpopups.get_language_from_view(view))
	except Exception:
		escaped = html.escape(text, quote=False).replace('\n', '<br>').replace('  ', '&nbsp;&nbsp;')
		return f'<p>{escaped}</p>'
