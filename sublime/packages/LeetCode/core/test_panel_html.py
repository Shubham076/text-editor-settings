"""The test panel's minihtml. Pure Python: no Sublime imports.

Order, top to bottom: actions, the banner (run in progress, error, or summary), then one card
per test. The banner sits above the cards so the outcome of a run is always in view. The
problem's title is the panel's one line of text, above all of this.

Look: a card has the editor's own background and a hairline border that turns red when
its test failed. Each value sits in an inset box tinted with the foreground colour, which
makes it a little darker than the editor in a light scheme and a little lighter in a dark
one; the output box is green or red. minihtml has no right alignment or hover, so every row
flows from the left.

Width: a phantom is only as wide as its widest line, so the cards would stop at the width
of the button row. ``render`` takes the width to fill and holds it open with a spacer.

Links: ``add``, ``run``, ``submit``, ``run:<index>``, ``edit:<index>``, ``delete:<index>``,
and ``copy-input:<index>``, ``copy-expected:<index>``, ``copy-output:<index>``,
``copy-stdout:<index>``.
"""

import textwrap
from html import escape

from . import testcases
from .minihtml import spacer

MAX_VALUE_LENGTH = 4000  # longer values are cut so one huge array cannot bury the panel
_NBSP = " "
SIDE_PADDING = 12
BANNER_PADDING = 14
_BADGE = {"running": "Running", "pass": "Passed", "fail": "Failed", "error": "Error"}
_MARK = {"running": "…", "pass": "✓", "fail": "✕", "error": "✕"}

_CSS = """
body { margin: 0; padding: 8px 12px 16px; }
a { text-decoration: none; }
.muted { color: color(var(--foreground) alpha(0.5)); }
.bar { margin-bottom: 16px; white-space: nowrap; }
a.btn { padding: 3px 10px; border-radius: 6px; font-size: 0.9rem; color: var(--foreground);
        border-style: solid; border-width: 1px;
        border-color: color(var(--foreground) alpha(0.14));
        background-color: color(var(--foreground) alpha(0.07)); }
a.outline { background-color: var(--background); }
a.submit { font-weight: bold; color: var(--background);
           background-color: var(--greenish); border-color: var(--greenish); }
a.ghost { padding: 1px 6px; border-color: color(var(--foreground) alpha(0));
          background-color: color(var(--foreground) alpha(0));
          color: color(var(--foreground) alpha(0.7)); }
a.danger { color: var(--redish); }
.banner { margin-bottom: 12px; padding: 10px 14px;  /* BANNER_PADDING */ border-radius: 8px;
          border-style: solid; border-width: 1px; }
.headline { font-weight: bold; }
.detail { margin-top: 4px; }
.banner.running { background-color: color(var(--bluish) alpha(0.12));
                  border-color: color(var(--bluish) alpha(0.35)); }
.banner.ok { background-color: color(var(--greenish) alpha(0.12));
             border-color: color(var(--greenish) alpha(0.35)); }
.banner.bad { background-color: color(var(--redish) alpha(0.1));
              border-color: color(var(--redish) alpha(0.35)); }
.card { margin-bottom: 12px; border-radius: 8px;
        border-style: solid; border-width: 1px;
        border-color: color(var(--foreground) alpha(0.12));
        background-color: var(--background); }
.card.fail, .card.error { border-color: color(var(--redish) alpha(0.45)); }
.head { padding: 10px 14px; white-space: nowrap;
        border-style: solid; border-width: 0 0 1px 0;
        border-color: color(var(--foreground) alpha(0.08)); }
.card.fail .head, .card.error .head { border-color: color(var(--redish) alpha(0.25)); }
.fields { padding: 4px 14px 16px; }
.mark { font-weight: bold; color: color(var(--foreground) alpha(0.35)); }
.mark.pass { color: var(--greenish); }
.mark.fail, .mark.error { color: var(--redish); }
.mark.running { color: var(--bluish); }
.name { font-weight: bold; }
.badge { padding: 0 7px; border-radius: 8px; font-size: 0.8rem; font-weight: bold;
         border-style: solid; border-width: 1px; }
.badge.pass { color: var(--greenish); background-color: color(var(--greenish) alpha(0.12));
              border-color: color(var(--greenish) alpha(0.4)); }
.badge.fail, .badge.error { color: var(--redish);
              background-color: color(var(--redish) alpha(0.1));
              border-color: color(var(--redish) alpha(0.4)); }
.badge.running { color: var(--bluish); background-color: color(var(--bluish) alpha(0.12));
                 border-color: color(var(--bluish) alpha(0.4)); }
.key { margin-top: 12px; margin-bottom: 6px; font-size: 0.75rem; font-weight: bold;
       color: color(var(--foreground) alpha(0.5)); }
a.copy { font-weight: normal; color: var(--bluish); }
.box { padding: 8px 12px; border-radius: 6px; white-space: nowrap;
       border-style: solid; border-width: 1px;
       border-color: color(var(--foreground) alpha(0.18));
       background-color: color(var(--foreground) alpha(0.09)); }
.box div { padding: 3px 0; }
.box.right { color: var(--greenish); background-color: color(var(--greenish) alpha(0.1));
             border-color: color(var(--greenish) alpha(0.35)); }
.box.wrong { color: var(--redish); background-color: color(var(--redish) alpha(0.08));
             border-color: color(var(--redish) alpha(0.35)); }
"""


def title(question, language):
    """The panel's line of text, shown above the phantom."""
    return "{}. {}  ({})".format(question.frontend_id, question.title, language)


def render(question, cases, message, running, width=0, em_width=0):
    """``message`` is the error of the last run (compile error, expired session, ...).
    ``width`` is the room the panel has, in pixels; the cards stretch to fill it.
    ``em_width`` is the width of one character; with both, the banner's text is wrapped to
    fit, because a phantom in a view without word wrap never wraps its own lines."""
    columns = 0
    if width > 0 and em_width > 0:
        columns = max(20, int((width - 2 * SIDE_PADDING - 2 * BANNER_PADDING - 2) / em_width))
    parts = [
        spacer(width - 2 * SIDE_PADDING),
        '<div class="bar">{}</div>'.format((_NBSP * 2).join((
            _button("add", "+ Add", "outline"), _button("run", "▶ Run all"),
            _button("submit", "Submit", "submit")))),
        _banner(cases, message, running, columns),
    ]
    parts += [_card(index, case, question.param_names) for index, case in enumerate(cases)]
    if not cases:
        parts.append('<div class="muted">No test cases yet. Add one to run your code.</div>')
    return '<body id="leetcode-tests"><style>{}</style>{}</body>'.format(_CSS, "".join(parts))


def _button(href, label, kind=""):
    # Non-breaking spaces keep a label on one line; a plain space would let it wrap mid-button.
    return '<a class="btn {}" href="{}">{}</a>'.format(kind, href, label.replace(" ", _NBSP))


def _banner(cases, message, running, columns=0):
    if running:
        count = sum(1 for case in cases if case.status == "running")
        return '<div class="banner running"><div class="headline">Running {} test{} on LeetCode…</div></div>'.format(
            count, "" if count == 1 else "s")
    if message:
        headline, _, detail = message.partition("\n")
        detail = detail.strip("\n")
        return '<div class="banner bad"><div class="headline">{}</div>{}</div>'.format(
            _lines(headline, columns),
            '<div class="detail">{}</div>'.format(_lines(detail, columns)) if detail else "")
    summary = testcases.summary(cases)
    if not summary:
        return ""
    passed = all(case.status == "pass" for case in cases if case.status)
    return '<div class="banner {}"><div class="headline">{}</div></div>'.format(
        "ok" if passed else "bad", escape(summary))


def _card(index, case, param_names):
    head = ['<span class="mark {}">{}</span>{}<span class="name">Test{}{}</span>'.format(
        case.status or "", _MARK.get(case.status, "○"), _NBSP, _NBSP, index + 1)]
    if case.status in _BADGE:
        head.append('<span class="badge {}">{}</span>'.format(case.status, _BADGE[case.status]))
    if case.custom:
        head.append('<span class="muted">custom</span>')
    head.append(_button("run:{}".format(index), "▶ Run", "ghost"))
    if case.custom:
        head += [_button("edit:{}".format(index), "Edit", "ghost"),
                 _button("delete:{}".format(index), "Delete", "ghost danger")]

    named = len(param_names) == len(case.values)
    inputs = "".join(_value(value, name if named else "")
                     for name, value in zip(param_names if named else case.values, case.values))
    copy = "copy-{}:" + str(index)
    fields = [_field("INPUT", inputs, copy=copy.format("input"))]
    if case.expected:
        fields.append(_field("EXPECTED", _value(case.expected), copy=copy.format("expected")))
    if case.status in ("pass", "fail") or case.actual:
        fields.append(_field("OUTPUT", _value(case.actual or "(empty)"),
                             "right" if case.status == "pass" else "wrong", copy.format("output")))
    if case.stdout:
        fields.append(_field("STDOUT", _lines(case.stdout), copy=copy.format("stdout")))
    edge = case.status if case.status in ("pass", "fail", "error") else ""
    return '<div class="card {}"><div class="head">{}</div><div class="fields">{}</div></div>'.format(
        edge, (_NBSP * 2).join(head), "".join(fields))


def _field(label, content, kind="", copy=""):
    """A labelled value box. ``copy`` is the link that copies the value to the clipboard."""
    link = '{}<a class="copy" href="{}">⧉{}Copy</a>'.format(_NBSP * 2, copy, _NBSP) if copy else ""
    return '<div class="key">{}{}</div><div class="box {}">{}</div>'.format(label, link, kind, content)


def _value(value, name=""):
    """A test value, with its parameter name when it has one (see ``testcases.layout``)."""
    value = str(value)
    if len(value) > MAX_VALUE_LENGTH:
        value = value[:MAX_VALUE_LENGTH] + "…"
    lines = testcases.layout(value)
    if name:  # a grid goes under its name; anything else stays beside it
        lines = ["{} =".format(name)] + lines if len(lines) > 1 else ["{} = {}".format(name, value)]
    return _lines("\n".join(lines))


def _text(value):
    return escape(str(value))


def _lines(text, columns=0):
    """Multi-line text, one div per line, keeping each line's indentation. With ``columns``,
    a line longer than that many characters continues on the next, at the same indentation."""
    rendered = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = _NBSP * (len(line) - len(stripped))
        pieces = [stripped]
        if columns and len(line) > columns:
            pieces = textwrap.wrap(stripped, max(20, columns - len(indent))) or [stripped]
        rendered += ["<div>{}{}</div>".format(indent, _text(piece) or _NBSP) for piece in pieces]
    return "".join(rendered)
