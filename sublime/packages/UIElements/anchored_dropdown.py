"""Dropdowns aligned below their buttons, expanding the phantom layout."""

from . import dropdown


def attach(view, fields, region=None, phantom_key="ui_elements_anchored_dropdown", on_change=None,
           values=None, heading=None):
    return dropdown.attach(view, fields, region=region, phantom_key=phantom_key,
                           on_change=on_change, values=values, menu_mode="inline", heading=heading)
