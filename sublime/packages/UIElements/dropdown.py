"""Shared dropdown models and phantom lifecycle for UIElements.

    from UIElements import anchored_dropdown, dropdown

    row = anchored_dropdown.attach(view, [
        dropdown.Field("severity", "Severity", ["Critical", "High", "Low"]),
    ], on_change=lambda key, value: print(key, value))

    row.values
    row.set("severity", "High")
    row.detach()
"""

from collections import namedtuple
from dataclasses import dataclass
from uuid import uuid4

import sublime
import sublime_plugin

from . import dropdown_html


Field = namedtuple("Field", "key caption options")


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    description: str = ""
    group: str = ""
    badge: str = ""        # short status shown as a pill after the description, e.g. "Paused"
    badge_color: str = ""  # colour scheme variable for the pill ("yellowish", "greenish", ...) or "" for neutral


def _normalize_options(options):
    options = tuple(Option(o, o) if isinstance(o, str) else o for o in options)
    if any(not isinstance(o, Option) or not all(isinstance(v, str) for v in
           (o.value, o.label, o.description, o.group, o.badge, o.badge_color)) for o in options):
        raise ValueError("Options must be strings or Option instances with string attributes")
    if len({o.value for o in options}) != len(options):
        raise ValueError("Option values must be unique within a field")
    return options


_rows = {}
_active = {}


class _PhantomRow:
    def __init__(self, view, region, phantom_key, heading):
        self.view = view
        self.region = region
        self.phantom_key = phantom_key
        self.heading = heading
        self._pid = None
        self._render_token = None
        self._detached = False
        self._id = uuid4().hex

    def _position(self):
        if self._pid is not None:
            regions = self.view.query_phantom(self._pid)
            if regions and regions[0].begin() >= 0:
                self.region = regions[0]
        return self.region

    def render(self):
        if self._detached or not self.view.is_valid():
            return
        point = self._position().begin()
        siblings = [row for row in _rows.values()
                    if not row._detached and row.view.id() == self.view.id()
                    and row._position().begin() == point]
        if self not in siblings:
            siblings.append(self)
        for row in siblings:
            row._render()

    def _render(self):
        previous = self._pid
        token = self._render_token = object()
        self._pid = self.view.add_phantom(
            self.phantom_key, self.region, self._html(), sublime.LAYOUT_BLOCK,
            lambda href: self._dispatch(token, href))
        if previous is not None:
            self.view.erase_phantom_by_id(previous)

    def _dispatch(self, token, href):
        if not self._detached and token is self._render_token and self.view.is_valid():
            self._navigate(href)

    def _html(self):
        raise NotImplementedError

    def _navigate(self, href):
        raise NotImplementedError

    def close(self):
        pass

    def detach(self):
        self._detached = True
        self._render_token = None
        self.close()
        if self._pid is not None and self.view.is_valid():
            self.view.erase_phantom_by_id(self._pid)
        self._pid = None
        _rows.pop(self._id, None)


def _mount(row):
    row.render()
    _rows[row._id] = row
    return row


class DropdownRow(_PhantomRow):
    def __init__(self, view, fields, region, phantom_key, on_change, values, menu_mode, heading):
        super().__init__(view, region, phantom_key, heading)
        if menu_mode not in ("popup", "inline"):
            raise ValueError("menu_mode must be 'popup' or 'inline'")
        self.menu_mode = menu_mode
        self.on_change = on_change
        self.fields = []
        self._values = {}
        for field in fields:
            if not isinstance(field.key, str) or not field.key or field.key in self._values:
                raise ValueError("Field keys must be unique, non-empty strings")
            if not isinstance(field.caption, str):
                raise ValueError("Field captions must be strings")
            options = _normalize_options(field.options)
            self.fields.append(Field(field.key, field.caption, options))
            self._values[field.key] = options[0].value if options else None
        for key, value in (values or {}).items():
            self._validate(key, value)
            self._values[key] = value
        self.open_field = None
        self._session = None

    @property
    def values(self):
        return dict(self._values)

    def _field(self, key):
        for field in self.fields:
            if field.key == key:
                return field
        raise KeyError(key)

    def _validate(self, key, value):
        field = self._field(key)
        if not field.options and value is None:
            return
        if not any(o.value == value for o in field.options):
            raise ValueError("Unknown option for field {!r}: {!r}".format(key, value))

    def _html(self):
        return dropdown_html.controls(
            self.view, self.fields, self._values, self.open_field, self.menu_mode, self.heading)

    def set(self, key, value):
        self._validate(key, value)
        if self._detached:
            return
        changed = self._values[key] != value
        self._values[key] = value
        if self.open_field is not None:
            self.close()
        elif changed:
            self.render()
        if changed and self.on_change:
            self.on_change(key, value)

    def open(self, key):
        field = self._field(key)
        if self._detached or not self.view.is_valid() or not field.options:
            return
        if self.open_field == key:
            self.close()
            return
        previous = _active.get(self.view.id())
        if previous:
            previous.close()
        self.open_field = key
        session = self._session = object()
        _active[self.view.id()] = self
        self.render()
        if self.menu_mode == "inline":
            return
        anchor = min(self.view.line(self._position().begin()).end() + 1, self.view.size())
        self.view.show_popup(
            self._menu(), location=anchor, max_width=520, max_height=520,
            on_navigate=lambda href: self._pick(session, href),
            on_hide=lambda: self._hidden(session))

    def _menu(self):
        field = self._field(self.open_field)
        return dropdown_html.menu(self.view, field, self._values[field.key])

    def close(self, hide=True):
        if self.open_field is None:
            return
        self.open_field = None
        self._session = None
        if _active.get(self.view.id()) is self:
            _active.pop(self.view.id())
            if hide and self.menu_mode == "popup" and self.view.is_valid() and self.view.is_popup_visible():
                self.view.hide_popup()
        self.render()

    def _hidden(self, session):
        if self._session is session:
            self.close(hide=False)

    def _navigate(self, href):
        kind, _, index = href.partition(":")
        if kind == "open" and index.isdigit() and int(index) < len(self.fields):
            self.open(self.fields[int(index)].key)
        elif kind in ("pick", "close"):
            self._pick(self._session, href)

    def _pick(self, session, href):
        if self._session is not session or self.open_field is None:
            return
        if href == "close":
            self.close()
            return
        kind, _, index = href.partition(":")
        field = self._field(self.open_field)
        if kind == "pick" and index.isdigit() and int(index) < len(field.options):
            self.set(field.key, field.options[int(index)].value)


def attach(view, fields, region=None, phantom_key="ui_elements_dropdown", on_change=None, values=None,
           menu_mode="popup", heading=None):
    """Attach independent buttons without modifying the buffer or selections."""
    return _mount(DropdownRow(
        view, fields, region if region is not None else sublime.Region(0),
        phantom_key, on_change, values, menu_mode, heading))


class UiElementsListener(sublime_plugin.EventListener):
    def on_deactivated(self, view):
        row = _active.get(view.id())
        if row:
            row.close()

    def on_selection_modified(self, view):
        row = _active.get(view.id())
        if row and not getattr(row, "keep_on_selection_modified", False):
            row.close()

    def on_close(self, view):
        active = _active.get(view.id())
        if active:
            active.close()
        for row in list(_rows.values()):
            if row.view.id() == view.id():
                row.detach()


def plugin_unloaded():
    for active in list(_active.values()):
        active.close()
    for row in list(_rows.values()):
        row.detach()
