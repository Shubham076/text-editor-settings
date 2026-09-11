"""Floating dropdowns using Sublime's text-anchored popup API."""

import sublime

from . import dropdown, dropdown_html


def attach(view, fields, region=None, phantom_key="ui_elements_floating_dropdown", on_change=None,
           values=None, heading=None):
    return dropdown.attach(view, fields, region=region, phantom_key=phantom_key,
                           on_change=on_change, values=values, menu_mode="popup", heading=heading)


class PopupMenu:
    def __init__(self, view, options, selected, on_select, on_hide, on_search, caption, keep_on_selection_modified,
                 action=None):
        self.view = view
        self.field = dropdown.Field("selection", caption, options)
        self.selected = selected
        self.on_select = on_select
        self.on_hide = on_hide
        self.on_search = on_search
        self.action = action
        self.keep_on_selection_modified = keep_on_selection_modified
        self.closed = False

    def _navigate(self, href):
        if self.closed:
            return
        if href == "close":
            self.close()
        elif href == "search" and self.on_search:
            callback = self.on_search
            self.close()
            callback()
        elif href == "action" and self.action:
            callback = self.action[1]
            self.close()
            callback()
        else:
            kind, _, index = href.partition(":")
            if kind != "pick" or not index.isdigit() or int(index) >= len(self.field.options):
                return
            value = self.field.options[int(index)].value
            callback = self.on_select
            self.selected = value
            self.close()
            if callback:
                callback(value)

    def close(self, hide=True):
        if self.closed:
            return
        self.closed = True
        if dropdown._active.get(self.view.id()) is self:
            dropdown._active.pop(self.view.id())
            if hide and self.view.is_valid() and self.view.is_popup_visible():
                self.view.hide_popup()
        if self.on_hide:
            self.on_hide()


def show(view, options, selected=None, on_select=None, location=-1, caption="Choose an option",
         on_hide=None, on_search=None, max_width=520, max_height=520, keep_on_selection_modified=False,
         font_size=None, action=None):
    """Open a menu for an existing trigger, without creating a button or phantom.

    `font_size` (px) fixes the menu's text size; by default it follows the view's font.
    `action` is an optional `(label, callback)` shown as a link in the menu footer; the menu
    closes before the callback runs.
    """
    options = dropdown._normalize_options(options)
    if not options or not view.is_valid():
        return None
    if selected is not None and not any(option.value == selected for option in options):
        raise ValueError("Unknown selected option: {!r}".format(selected))
    if action is not None and (len(action) != 2 or not isinstance(action[0], str) or not callable(action[1])):
        raise ValueError("action must be a (label, callback) pair")
    menu = PopupMenu(view, options, selected, on_select, on_hide, on_search, caption, keep_on_selection_modified, action)
    content = dropdown_html.menu(view, menu.field, selected, search=on_search is not None, font_size=font_size,
                                 action=action[0] if action else None)
    previous = dropdown._active.get(view.id())
    if previous:
        previous.close()
    dropdown._active[view.id()] = menu
    flags = sublime.KEEP_ON_SELECTION_MODIFIED if keep_on_selection_modified else 0
    view.show_popup(content, flags=flags, location=location, max_width=max_width, max_height=max_height,
                    on_navigate=menu._navigate, on_hide=lambda: menu.close(hide=False))
    return menu


def plugin_unloaded():
    for active in list(dropdown._active.values()):
        if isinstance(active, PopupMenu):
            active.close()
