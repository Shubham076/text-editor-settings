"""The tab strip under a terminal panel: one tab per terminal, pinned below the output

Sublime shows one panel at a time and gives a panel no tabs, so with a few terminals open
there was nothing on screen to say which one was showing or what else was open. A row of
tabs drawn into the terminal itself scrolls away with the output. What does stay put is the
one-line input strip of an io panel (`Window.create_io_panel`): it sits under the output and
never scrolls. So a terminal that lives in a panel is opened as an io panel (`create_panel`)
and its strip, which never takes input, is the canvas for a row of tabs drawn as a phantom.

Every terminal is still a panel of its own, so every one has a strip of its own. They all
draw the same row and each marks its own terminal as the one showing: a strip is only ever
on screen while its panel is.

    [>_ Terminal 1] [>_ Terminal 2] [>_ Terminal 3 x] [+]                 [search] [clear]

A click on a tab shows that terminal, a click on the name of the one showing renames it, the
cross closes it. A tab is called "Terminal 1", "Terminal 2" and so on unless it was given a name.
"""

import base64
import html
import sys
import time

import sublime
import sublime_plugin

from .const import EXEC_PANEL
from .terminal import Terminal


# on the terminal view: the id of its strip, when it was opened, the name it was given, its number
STRIP_KEY = "terminus_view.strip_id"
ORDER_KEY = "terminus_view.tab_order"
NAME_KEY = "terminus_view.tab_name"
NUMBER_KEY = "terminus_view.tab_number"
# on the strip: that it is one, and the panel it belongs to
STRIP_FLAG = "terminus_strip"
STRIP_PANEL = "terminus_strip.panel"

# the longest a name is drawn before it is cut, and the shortest it is cut to when the row is full
NAME_MAX = 28
NAME_MIN = 6
# Sublime draws a history arrow at the right end of an io panel's input strip
STRIP_ARROW = 40

_phantoms = {}      # strip view id -> PhantomSet (kept: a set dropped takes its phantoms with it)
_signatures = {}    # strip view id -> what the row was last drawn from
_images = {}
_polling = False
# this module as it was loaded: a reload leaves the old one running its timers, and it has to stop
_module = sys.modules.get(__name__)


# -- panels ------------------------------------------------------------------------------------

def create_panel(window, panel_name, like=None):
    """A new panel for a terminal, with a strip for the tabs under it

    The build panel stays a plain one: it is not a terminal to switch to. `like` is the view
    this one replaces (a reset destroys the panel and makes it again), whose place in the row
    and name carry over.
    """
    if panel_name == EXEC_PANEL or not hasattr(window, "create_io_panel"):
        return window.get_output_panel(panel_name)

    view, strip = window.create_io_panel(panel_name, lambda text: None)
    strip_settings = strip.settings()
    for key, value in {
        "gutter": False, "line_numbers": False, "margin": 0, "line_padding_top": 0,
        "line_padding_bottom": 0, "draw_indent_guides": False, "draw_white_space": "none",
        "scroll_past_end": False, "word_wrap": False, "highlight_line": False, "is_widget": True,
        "rulers": [], "auto_complete": False, STRIP_FLAG: True, STRIP_PANEL: panel_name,
    }.items():
        strip_settings.set(key, value)
    strip.set_read_only(True)

    # the lowest number no other terminal of the window has: closing "Terminal 2" frees the 2
    taken = {v.settings().get(NUMBER_KEY) for _, v in panels(window)}
    number = next(n for n in range(1, len(taken) + 2) if n not in taken)

    settings = view.settings()
    settings.set(STRIP_KEY, strip.id())
    settings.set(ORDER_KEY, time.time())
    settings.set(NUMBER_KEY, number)
    if like:
        old = like.settings()
        for key in (ORDER_KEY, NAME_KEY, NUMBER_KEY):
            if old.get(key) is not None:
                settings.set(key, old.get(key))
    return view


def strip_of(view):
    strip_id = view.settings().get(STRIP_KEY)
    if not strip_id:
        return None
    strip = sublime.View(strip_id)
    return strip if strip.is_valid() else None


def panel_name_of(view):
    strip = strip_of(view)
    return strip.settings().get(STRIP_PANEL) if strip else None


def order_of(window, panel_name):
    """Where a panel comes in the row; a terminal without a tab comes after those with one"""
    view = window.find_output_panel(panel_name)
    order = view.settings().get(ORDER_KEY) if view else None
    return order if order is not None else float("inf")


def panels(window):
    """The terminals of `window` that have a tab, as (panel name, view), in the order opened"""
    found = []
    for panel in window.panels():
        if not panel.startswith("output."):
            continue
        name = panel[len("output."):]
        view = window.find_output_panel(name)
        if not view or not view.settings().get("terminus_view") or not strip_of(view):
            continue
        found.append((view.settings().get(ORDER_KEY) or 0, name, view))
    found.sort(key=lambda entry: entry[0])
    return [(name, view) for _, name, view in found]


def window_of(panel_name, view_id):
    for window in sublime.windows():
        view = window.find_output_panel(panel_name)
        if view and view.id() == view_id:
            return window
    return None


def label(view, panel_name):
    """What a tab says: the name it was given, or else "Terminal" and its number"""
    settings = view.settings()
    name = settings.get(NAME_KEY)
    if name:
        return name
    number = settings.get(NUMBER_KEY)
    return "Terminal {}".format(number) if number else panel_name


# -- drawing -----------------------------------------------------------------------------------

def image(variant, name):
    key = (variant, name)
    if key not in _images:
        package = __package__.split(".")[0]
        try:
            data = sublime.load_binary_resource("Packages/{}/images/tabs/{}/{}.png".format(package, variant, name))
            _images[key] = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        except Exception:
            _images[key] = ""
    return _images[key]


def is_dark(view):
    background = (view.style() or {}).get("background") or "#000000"
    try:
        red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return True
    return 0.299 * red + 0.587 * green + 0.114 * blue < 128


def cut(text, width):
    return text if len(text) <= width else text[:max(1, width - 1)] + "…"


class Metrics:
    """The sizes the row is drawn at, all in pixels, worked out from the font of the editor

    minihtml has no way to push something to the right edge, so the gap before the buttons
    on the right is a spacer of a width worked out here. That needs the width of the text, and
    so a monospaced font: the strip is given the font of the terminal above it.
    """

    def __init__(self, view, strip):
        preferences = sublime.load_settings("Preferences.sublime-settings")
        settings = view.settings()
        editor_font = preferences.get("font_size", 12) or 12
        self.font = max(10, round(editor_font * 0.875))
        view_font = settings.get("font_size") or editor_font
        ratio = (view.em_width() or 0) / view_font if view_font else 0
        # a font that has not been laid out yet has no width: most monospaced fonts are about this
        self.char = self.font * (ratio if 0.3 < ratio < 1 else 0.6)
        self.font_face = settings.get("font_face") or preferences.get("font_face") or None
        self.height = round(self.font * 2.5)
        self.icon = round(self.font * 1.15)
        self.gap = self.char                    # every gap along the row is one space
        width = strip.viewport_extent()[0] or view.viewport_extent()[0]
        self.width = int(width - STRIP_ARROW) if width else 0

    def tab(self, name, active):
        # a space, the icon, a space, the name and two spaces; or one and the cross and one
        width = self.icon + (len(name) + 4) * self.char
        if active:
            width += self.icon
        return width

    def button(self):
        return self.icon + 2 * self.gap + 1


def row(window, view, strip, panel_name, items, metrics):
    """The html of the row drawn in the strip of `panel_name`"""
    m = metrics
    dark = is_dark(strip)
    variant = "dark" if dark else "light"
    names = [label(v, name) for name, v in items]

    # the names give way before the buttons do: they are cut, longest first, until the row fits
    fixed = 3 * m.button() + 6
    limit = NAME_MAX
    shown = [cut(name, limit) for name in names]
    while limit > NAME_MIN and fixed + sum(m.tab(n, p == panel_name) for n, (p, _) in zip(shown, items)) > m.width:
        limit -= 1
        shown = [cut(name, limit) for name in names]
    used = fixed + sum(m.tab(n, p == panel_name) for n, (p, _) in zip(shown, items))
    spacer = max(0, int(m.width - used))

    def img(name, cls="icon"):
        return '<img class="{}" src="{}">'.format(cls, image(variant, name))

    # Every gap along the row is a space of the font, and no box has padding at its sides:
    # minihtml paints a box that has some wider than it lays it out. The tab that is showing
    # is two boxes side by side, its name and its cross, and their fills would overlap.
    gap = "&nbsp;"
    parts = []
    for text, (name, _) in zip(shown, items):
        href = html.escape(name, quote=True)
        text = html.escape(text)
        if name == panel_name:
            parts.append(
                '<a class="on name" href="rename:{href}">{gap}{icon}{gap}{text}{gap}</a>'
                '<a class="on cross" href="close:{href}">{cross}{gap}</a>'.format(
                    href=href, text=text, icon=img("prompt-active"), cross=img("close"), gap=gap))
        else:
            parts.append(
                '<a class="tab" href="switch:{href}">{gap}{icon}{gap}{text}{gap}</a>'.format(
                    href=href, text=text, icon=img("prompt"), gap=gap))
    # a space between one tab and the next, outside the fill of the one showing
    parts = [part + gap for part in parts]
    parts.append('<a class="button" href="new">{gap}{}{gap}</a>'.format(img("plus"), gap=gap))
    parts.append('<img style="width:{}px;height:1px">'.format(spacer))
    parts.append('<a class="button first" href="search:{}">{gap}{}{gap}</a>'.format(
        html.escape(panel_name, quote=True), img("search"), gap=gap))
    parts.append('<a class="button" href="clear:{}">{gap}{}{gap}</a>'.format(
        html.escape(panel_name, quote=True), img("trash"), gap=gap))

    line = "color(var(--foreground) alpha(0.14))"
    top = max(0, round((m.height - m.font * 1.35) / 2) - 1)
    css = """
        html, body {{ margin: 0; padding: 0; }}
        body {{ font-size: {font}px; {face} }}
        .row {{ height: {height}px; }}
        a {{ text-decoration: none; color: color(var(--foreground) alpha(0.55)); }}
        .tab {{ display: inline-block; padding: {top}px 0 {top}px 0; }}
        .on {{ display: inline-block; background-color: color(var(--foreground) alpha({on})); color: var(--foreground); }}
        .name {{ padding: {top}px 0 {top}px 0; border-radius: 5px 0 0 5px; }}
        .cross {{ padding: {top}px 0 {top}px 0; border-radius: 0 5px 5px 0; }}
        .button {{ display: inline-block; padding: {top}px 0 {top}px 0; }}
        .first {{ border-left: 1px solid {line}; }}
        .icon {{ width: {icon}px; height: {icon}px; }}
    """.format(
        font=m.font, face='font-family: "{}";'.format(m.font_face) if m.font_face else "",
        height=m.height, top=top, icon=m.icon,
        line=line, on=0.22 if dark else 0.17)
    return '<body id="terminus-tabs"><style>{}</style><div class="row">{}</div></body>'.format(css, "".join(parts))


def draw(window, view, panel_name, items):
    strip = strip_of(view)
    if not strip:
        return
    metrics = Metrics(view, strip)
    if not metrics.width:
        # not laid out yet: the poll draws it once it has a width
        return
    if metrics.font_face and strip.settings().get("font_face") != metrics.font_face:
        strip.settings().set("font_face", metrics.font_face)
    content = row(window, view, strip, panel_name, items, metrics)
    phantoms = _phantoms.get(strip.id())
    if not phantoms:
        # whatever a copy of this module from before a reload drew is still there
        strip.erase_phantoms("terminus_tabs")
        phantoms = _phantoms[strip.id()] = sublime.PhantomSet(strip, "terminus_tabs")
    phantoms.update([sublime.Phantom(
        sublime.Region(0), content, sublime.LAYOUT_INLINE,
        lambda href: navigate(window, href))])
    _signatures[strip.id()] = signature(view, strip)
    fit(strip, metrics.height)


def fit(strip, height):
    """Sizes the strip to the row

    The input strip of an io panel is one line of text tall and nothing but its font size
    changes that, so the font size is scaled by how far off the height is. One pass gets
    close; the poll keeps at it until it is within two pixels.
    """
    current = strip.viewport_extent()[1]
    if current <= 0 or abs(current - (height + 2)) <= 2:
        return
    settings = strip.settings()
    size = settings.get("font_size") or 12
    settings.set("font_size", max(6, min(200, round(size * (height + 2) / current, 1))))


def signature(view, strip):
    preferences = sublime.load_settings("Preferences.sublime-settings")
    return (strip.viewport_extent()[0], view.viewport_extent()[0], str(strip.style()),
            preferences.get("font_size"), preferences.get("font_face"), view.settings().get("font_face"))


def refresh(window):
    """Draws the row again in every strip of `window`, and the count in the status bar"""
    if not window or not window.is_valid():
        return
    items = panels(window)
    for name, view in items:
        draw(window, view, name, items)
    live = {strip.id() for strip in (strip_of(view) for _, view in items) if strip}
    if not any(panels(other) for other in sublime.windows() if other.id() != window.id()):
        for strip_id in [strip_id for strip_id in _phantoms if strip_id not in live]:
            _phantoms.pop(strip_id, None)
            _signatures.pop(strip_id, None)

    from .render import refresh_terminus_status
    refresh_terminus_status(window)
    start_polling()


def refresh_later(window, delay=100):
    sublime.set_timeout(lambda: refresh(window), delay)


def start_polling():
    global _polling
    if not _polling:
        _polling = True
        sublime.set_timeout(poll, 500)


def poll():
    """Redraws the strip that is showing when its width, colours or font change

    Nothing tells a plugin that a panel was resized or a colour scheme switched.
    """
    global _polling
    if sys.modules.get(__name__) is not _module:
        return
    any_panel = False
    for window in sublime.windows():
        items = panels(window)
        if not items:
            continue
        any_panel = True
        active = window.active_panel()
        for name, view in items:
            if active != "output." + name:
                continue
            strip = strip_of(view)
            if not strip:
                continue
            if _signatures.get(strip.id()) != signature(view, strip):
                refresh(window)
            else:
                fit(strip, Metrics(view, strip).height)
    if any_panel:
        sublime.set_timeout(poll, 500)
    else:
        _polling = False


# -- clicks ------------------------------------------------------------------------------------

def navigate(window, href):
    action, _, panel_name = href.partition(":")
    panel_name = html.unescape(panel_name)
    view = window.find_output_panel(panel_name) if panel_name else None

    if action == "new":
        window.run_command("terminus_open", {"show_in_panel": True})
    elif action == "switch" and view:
        window.run_command("show_panel", {"panel": "output." + panel_name})
        window.focus_view(view)
        refresh(window)
    elif action == "rename" and view:
        # the palette has to be opened once with nothing typed, or it does not find the command
        window.run_command("show_overlay", {"overlay": "command_palette", "text": ""})
        window.run_command("hide_overlay")
        window.run_command("show_overlay", {
            "overlay": "command_palette", "command": "terminus_rename_tab", "args": {"panel_name": panel_name}})
    elif action == "close" and view:
        view.run_command("terminus_close")
    elif action == "search" and view:
        from . import search
        window.focus_view(view)
        search.ask(window, panel_name)
    elif action == "clear" and view:
        # what is on the screen and above it goes, then the shell is asked to draw its prompt again
        from . import search
        search.clear(view)
        view.run_command("terminus_reset", {"soft": True})
        terminal = Terminal.from_id(view.id())
        if terminal:
            terminal.send_key("l", ctrl=True)
        window.focus_view(view)


class TerminusRenameTabCommand(sublime_plugin.WindowCommand):
    """Gives the tab of a terminal a name; an empty one puts it back to "Terminal" and its number"""

    def run(self, name, panel_name=None):
        view = self.target(panel_name)
        if not view:
            return
        name = (name or "").strip()
        if name:
            view.settings().set(NAME_KEY, name)
        else:
            view.settings().erase(NAME_KEY)
        refresh(self.window)
        self.window.focus_view(view)

    def target(self, panel_name=None):
        window = self.window
        if not panel_name:
            active = window.active_panel() or ""
            panel_name = active[len("output."):] if active.startswith("output.") else None
        names = [name for name, _ in panels(window)]
        if panel_name not in names:
            return None
        return window.find_output_panel(panel_name)

    def is_enabled(self, **kwargs):
        return bool(self.target(kwargs.get("panel_name")))

    def input(self, args):
        if "name" in args:
            return None
        panel_name = args.get("panel_name")
        view = self.target(panel_name)
        if not view:
            return None
        return TerminusTabNameInputHandler(label(view, panel_name or ""))

    def input_description(self):
        return "Terminus"


class TerminusTabNameInputHandler(sublime_plugin.TextInputHandler):
    def __init__(self, initial):
        super().__init__()
        self.initial = initial

    def name(self):
        return "name"

    def initial_text(self):
        return self.initial

    def placeholder(self):
        return "name of the terminal (empty for its number)"


class TerminusTabsListener(sublime_plugin.EventListener):
    def on_activated(self, view):
        settings = view.settings()
        if settings.get(STRIP_FLAG):
            # the strip is only there to be drawn on: a click on it gives the terminal the keys back
            panel_name = settings.get(STRIP_PANEL)
            for window in sublime.windows():
                output = window.find_output_panel(panel_name) if panel_name else None
                if output and output.settings().get(STRIP_KEY) == view.id():
                    sublime.set_timeout(lambda: window.focus_view(output))
                    break
        elif settings.get("terminus_view") and settings.get(STRIP_KEY):
            panel_name = panel_name_of(view)
            window = window_of(panel_name, view.id()) if panel_name else None
            if window:
                refresh(window)
