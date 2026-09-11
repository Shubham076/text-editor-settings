"""Minihtml rendering for the dropdown component."""

from html import escape

from . import icons


_TOOLBAR_PADDING = 10


_CSS = """
body {{ margin: 0; padding: 6px 4px; background-color: {background};
        color: {foreground}; font-size: 1rem; line-height: 1.6; }}
a {{ text-decoration: none; color: {foreground}; }}
.heading {{ margin-bottom: 4px; font-size: 0.85rem; }}
.toolbar {{ padding: 8px {toolbar_padding}px; border: 1px solid {toolbar_border};
            border-radius: 6px; background-color: {toolbar_background}; }}
.toolbar .button {{ border-color: transparent; }}
.toolbar .btn {{ background-color: transparent; }}
.toolbar-divider {{ color: {foreground}; padding: 0 4px; }}
.toolbar-menu {{ padding-left: {toolbar_inset}px; }}
.buttons, .expanded {{ white-space: nowrap; }}
.expanded {{ margin-top: 6px; padding-bottom: 2rem; }}
.caret {{ color: {muted}; }}
.icon-button {{ padding: 3px 4px; }}
.button {{ padding: 3px 8px; border-radius: 4px; border: 1px solid {border};
           color: {foreground}; background-color: {button}; }}
.btn-red {{ background-color: color(var(--redish) alpha(0.18)); border-color: var(--redish); }}
.btn-green {{ background-color: color(var(--greenish) alpha(0.18)); border-color: var(--greenish); }}
.btn-yellow {{ background-color: color(var(--yellowish) alpha(0.18)); border-color: var(--yellowish); }}
.spacer {{ color: {background}; background-color: {background}; border-color: {background}; }}
.spacer .caret {{ color: {background}; }}
.menu {{ padding: 0.6rem 0.75rem 0; background-color: {surface}; border: 1px solid {border};
         border-radius: 0.6rem; white-space: nowrap; }}
.inline-menu {{ display: inline-block; width: 24rem; }}
.title {{ padding: 0.5rem 0.9rem 0.9rem; font-weight: bold; }}
.menu-search {{ font-weight: normal; font-size: 0.85rem; text-decoration: underline; }}
.group {{ padding: 0.5rem 0.9rem 0.35rem; font-size: 0.8rem; font-weight: bold; color: {muted}; }}
.item {{ display: block; padding: 0.55rem 0.9rem; border-radius: 0.5rem; color: {foreground}; }}
.item.active {{ background-color: {selection}; }}
.item.active .label, .item.active .description {{ color: {foreground}; }}
.mark {{ display: inline-block; width: 1.6rem; color: {accent}; }}
.label {{ font-weight: bold; }}
.description {{ color: {muted}; }}
.badge {{ padding: 0.12rem 0.6rem; border-radius: 1rem; font-size: 0.85rem; font-weight: bold;
          color: {foreground}; background-color: color(var(--foreground) alpha(0.08)); }}
.badge-yellowish {{ color: color(var(--yellowish) min-contrast(var(--background) 4)); background-color: color(var(--yellowish) alpha(0.15)); }}
.badge-greenish {{ color: color(var(--greenish) min-contrast(var(--background) 4)); background-color: color(var(--greenish) alpha(0.15)); }}
.badge-redish {{ color: color(var(--redish) min-contrast(var(--background) 4)); background-color: color(var(--redish) alpha(0.15)); }}
.badge-bluish {{ color: color(var(--bluish) min-contrast(var(--background) 4)); background-color: color(var(--bluish) alpha(0.15)); }}
.footer {{ margin-top: 0.5rem; padding: 0.8rem 0.9rem; border-top: 1px solid {border}; white-space: nowrap; }}
.footer .action {{ font-weight: bold; color: {accent}; }}
.footer .hint {{ color: {muted}; }}
.footer .fill {{ display: inline-block; }}
"""


def _mix(first, second, amount):
    return "#%02x%02x%02x" % tuple(
        round(int(first[i:i + 2], 16) * (1 - amount) + int(second[i:i + 2], 16) * amount)
        for i in (1, 3, 5))


def _palette(view):
    style = view.style()
    background = style.get("background", "#ffffff")
    foreground = style.get("foreground", "#333333")
    button = _mix(background, "#000000", 0.08)
    # Menus sit on a surface slightly lighter than the editor: nearly white on light schemes, a
    # touch lighter on dark ones. Taken from the scheme's real background, not the popup CSS
    # override some schemes apply to var(--background).
    light = sum(int(background[i:i + 2], 16) for i in (1, 3, 5)) > 3 * 128
    return {
        "background": background,
        "foreground": foreground,
        "button": button,
        "surface": _mix(background, "#ffffff", 0.6 if light else 0.06),
        # Highlights follow the scheme's own selection and accent colours.
        "selection": style.get("selection") or style.get("line_highlight") or _mix(button, "#000000", 0.08),
        "accent": style.get("accent") or style.get("bluish") or foreground,
        "toolbar_background": _mix(background, foreground, 0.06),
        "toolbar_border": _mix(background, foreground, 0.18),
        "selected": _mix(button, "#000000", 0.08),
        "border": _mix(button, foreground, 0.2),
        "muted": _mix(foreground, button, 0.35),
    }


def _body(view, content, popup=False, font_size=None):
    palette = _palette(view)
    css = _CSS.format(toolbar_padding=_TOOLBAR_PADDING, toolbar_inset=_TOOLBAR_PADDING + 1, **palette)
    if popup:
        # The popup window already frames the menu; fill it with the menu surface and drop the
        # inner border so no second band shows around the card.
        css += "body {{ padding: 0; background-color: {surface}; }}\n.menu {{ border: 0; border-radius: 0; }}\n".format(**palette)
    if font_size:
        # Hosts whose view uses a tiny font (for example a phantom-only panel) pass the size the
        # menu should be read at; rem units in the stylesheet then follow it.
        css = "html {{ font-size: {}px; }}\n".format(font_size) + css
    return '<body id="ui-elements"><style>{}</style>{}</body>'.format(css, content)


def _action(button, index, palette):
    icon = getattr(button, "icon", "")
    if icon:
        style = "icon-button"
        content = '<img src="{}" style="width: 1rem; height: 1rem;">'.format(
            icons.data_uri(icon, palette["foreground"]))
        spacer = '<span class="icon-button spacer"><img src="{}" style="width: 1rem; height: 1rem;"></span>'.format(
            icons.data_uri(icon, palette["background"]))
    else:
        style = "button " + button.variant
        content = escape(button.label)
        spacer = '<span class="button spacer">{}</span>'.format(content)
    link = '<a class="{}" href="click:{}" title="{}">{}</a>'.format(
        style, index, escape(button.label), content)
    return link, spacer + "&nbsp;"


def controls(view, items, values, open_field, menu_mode="popup", heading=None, framed=False):
    parts, spacers = [], []
    expanded = ""
    field_index = button_index = 0
    palette = _palette(view)
    previous_kind = None
    for item in items:
        kind = "dropdown" if hasattr(item, "options") else "icon" if getattr(item, "icon", "") else "button"
        if framed and previous_kind is not None and kind != previous_kind:
            parts.append('<span class="toolbar-divider">|</span>')
            spacers.append('<span class="toolbar-divider spacer">|</span>&nbsp;')
        previous_kind = kind
        if kind != "dropdown":
            link, spacer = _action(item, button_index, palette)
            parts.append(link)
            spacers.append(spacer)
            button_index += 1
            continue
        selected = next((o for o in item.options if o.value == values[item.key]), None)
        label = escape(selected.label) if selected else "No options"
        caption = '{}: '.format(escape(item.caption)) if item.caption else ""
        content = '{}{} &nbsp;<span class="caret">&#9662;</span>'.format(caption, label)
        if item.options:
            parts.append('<a class="button{}" href="open:{}">{}</a>'.format(
                " open" if open_field == item.key else "", field_index, content))
        else:
            parts.append('<span class="button">{}</span>'.format(content))
        if menu_mode == "inline" and open_field == item.key:
            expanded = '<div class="expanded">{}{}</div>'.format(
                "".join(spacers), _menu_content(item, values[item.key], inline=True))
        spacers.append('<span class="button spacer">{}</span>&nbsp;'.format(content))
        field_index += 1
    title = '<div class="heading">{}</div>'.format(escape(heading)) if heading else ""
    row = '<div class="buttons">{}</div>'.format("&nbsp;".join(parts))
    if framed:
        row = '<div class="toolbar">{}</div>'.format(row)
        if expanded:
            expanded = '<div class="toolbar-menu">{}</div>'.format(expanded)
    return _body(view, title + row + expanded)


def _menu_content(field, selected, inline=False, search=False, action=None):
    title = escape(field.caption or "Choose an option")
    if search:
        title += ' &nbsp;<a class="menu-search" href="search">Search...</a>'
    parts = ['<div class="menu{}"><div class="title">{}</div>'.format(
        " inline-menu" if inline else "", title)]
    previous_group = None
    widest = len(field.caption or "Choose an option")
    for index, option in enumerate(field.options):
        if option.group and option.group != previous_group:
            parts.append('<div class="group">{}</div>'.format(escape(option.group.upper())))
        previous_group = option.group
        mark = '<span class="mark">{}</span>'.format("&#10003;" if option.value == selected else "")
        badge = ""
        if option.badge:
            kind = " badge-" + option.badge_color if option.badge_color else ""
            badge = ' <span class="badge{}">&#9679; {}</span>'.format(escape(kind), escape(option.badge))
        description = '<br><span class="mark"></span><span class="description">{}</span>{}'.format(
            escape(option.description), badge) if option.description else ""
        widest = max(widest, len(option.label) + 3, len(option.description) + 3 + (len(option.badge) + 5 if option.badge else 0))
        parts.append('<a class="item{}" href="pick:{}">{}<span class="label">{}</span>{}</a>'.format(
            " active" if option.value == selected else "", index, mark, escape(option.label), description))
    hint = "Esc to close"
    left = '<a class="action" href="action">{}</a>'.format(escape(action)) if action else ""
    # Monospace hosts: pad the footer so the hint sits at the right edge of the widest row.
    filler = max(1, widest - (len(action) if action else 0) - len(hint))
    parts.append('<div class="footer">{}<span class="fill">{}</span><a class="hint" href="close">{}</a></div></div>'.format(
        left, "&nbsp;" * filler, hint))
    return "".join(parts)


def menu(view, field, selected, search=False, font_size=None, action=None):
    return _body(view, _menu_content(field, selected, search=search, action=action), popup=True, font_size=font_size)
