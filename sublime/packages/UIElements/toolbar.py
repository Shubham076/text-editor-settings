"""One toolbar combining dropdown fields, icon buttons, and text buttons."""

import sublime

from . import buttons, dropdown, dropdown_html


class Toolbar(dropdown.DropdownRow):
    def __init__(self, view, items, region, phantom_key, on_change, values, menu_mode, heading):
        items = tuple(items)
        if any(not isinstance(item, (dropdown.Field, buttons.Button)) for item in items):
            raise ValueError("Toolbar items must be Field or Button instances")
        fields = [item for item in items if isinstance(item, dropdown.Field)]
        self.buttons = buttons._validate(item for item in items if isinstance(item, buttons.Button))
        super().__init__(view, fields, region, phantom_key, on_change, values, menu_mode, heading)
        keys = [item.key for item in items]
        if len(keys) != len(set(keys)):
            raise ValueError("All toolbar item keys must be unique")
        normalized = {field.key: field for field in self.fields}
        self.items = tuple(normalized.get(item.key, item) for item in items)

    def _html(self):
        return dropdown_html.controls(
            self.view, self.items, self._values, self.open_field, self.menu_mode, self.heading, framed=True)

    def _navigate(self, href):
        if href.startswith("click:"):
            buttons._click(self.view, self.buttons, href)
        else:
            super()._navigate(href)


def attach(view, items, region=None, phantom_key="ui_elements_toolbar", on_change=None, values=None,
           menu_mode="inline", heading=None):
    return dropdown._mount(Toolbar(
        view, items, region if region is not None else sublime.Region(0),
        phantom_key, on_change, values, menu_mode, heading))


def plugin_unloaded():
    for row in list(dropdown._rows.values()):
        if isinstance(row, Toolbar):
            row.detach()
