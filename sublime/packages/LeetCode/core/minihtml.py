"""Helpers shared by the panels' minihtml. Pure Python: no Sublime imports."""

_PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
          "AAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII=")  # 1x1, transparent


def spacer(width):
    """An invisible line ``width`` pixels wide, or nothing when there is no room to fill.

    A phantom is only as wide as its widest line, so blocks inside it stop short of the
    view's edge. An image is the one element minihtml gives an exact size, so one of these
    at the top holds the phantom open and every block below stretches to match.
    """
    width = int(width)
    return '<img src="{}" width="{}" height="1">'.format(_PIXEL, width) if width > 0 else ""
