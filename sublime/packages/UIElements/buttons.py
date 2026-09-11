"""Clickable, color-scheme-aware buttons with Python callbacks."""

from dataclasses import dataclass
from typing import Callable

import sublime

from . import dropdown, dropdown_html, icons


VARIANTS = ("btn", "btn-red", "btn-green", "btn-yellow")


@dataclass(frozen=True)
class Button:
    key: str
    label: str
    on_click: Callable[[], None]
    variant: str = "btn"
    icon: str = ""


def btn(key, label, on_click):
    return Button(key, label, on_click)


def btn_red(key, label, on_click):
    return Button(key, label, on_click, "btn-red")


def btn_green(key, label, on_click):
    return Button(key, label, on_click, "btn-green")


def btn_yellow(key, label, on_click):
    return Button(key, label, on_click, "btn-yellow")


def icon(key, name, on_click, title=None):
    return Button(key, title if title is not None else name.title(), on_click, icon=name)


def _validate(items):
    items = tuple(items)
    keys = set()
    for button in items:
        if not isinstance(button, Button):
            raise ValueError("Each button must be a Button instance")
        if not isinstance(button.key, str) or not button.key or button.key in keys:
            raise ValueError("Button keys must be unique, non-empty strings")
        if not isinstance(button.label, str) or not callable(button.on_click):
            raise ValueError("Buttons require a string label and an on_click callback")
        if button.variant not in VARIANTS:
            raise ValueError("Unknown button variant: {!r}".format(button.variant))
        if not isinstance(button.icon, str) or (button.icon and button.icon not in icons.NAMES):
            raise ValueError("Unknown icon: {!r}".format(button.icon))
        keys.add(button.key)
    return items


def _click(view, items, href):
    kind, _, index = href.partition(":")
    if kind != "click" or not index.isdigit() or int(index) >= len(items):
        return
    active = dropdown._active.get(view.id())
    if active:
        active.close()
    items[int(index)].on_click()


class ButtonRow(dropdown._PhantomRow):
    def __init__(self, view, items, region, phantom_key, heading):
        super().__init__(view, region, phantom_key, heading)
        self.buttons = _validate(items)

    def _html(self):
        return dropdown_html.controls(self.view, self.buttons, {}, None, heading=self.heading)

    def _navigate(self, href):
        _click(self.view, self.buttons, href)


def attach(view, items, region=None, phantom_key="ui_elements_buttons", heading=None):
    return dropdown._mount(ButtonRow(
        view, items, region if region is not None else sublime.Region(0), phantom_key, heading))


def plugin_unloaded():
    for row in list(dropdown._rows.values()):
        if isinstance(row, ButtonRow):
            row.detach()
