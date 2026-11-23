"""The test panel's minihtml. Pure Python: no Sublime imports.

Order, top to bottom: actions, the banner (run in progress, error, or summary), then one card
per test. The banner sits above the cards so the outcome of a run is always in view. The
problem's title is the panel's one line of text, above all of this.

Layout rules: surfaces are told apart by background only; the one border is a card's left
edge, green for a passed test and red for a failed one. Everything shares one left edge (the
card padding), and spacing comes in steps of 4px.

Links: ``add``, ``run``, ``submit``, ``run:<index>``, ``edit:<index>``, ``delete:<index>``.
"""

from html import escape

from . import testcases

MAX_VALUE_LENGTH = 400  # longer values are cut so one huge array cannot bury the panel
_NBSP = " "
_BADGE = {"running": "Running", "pass": "Passed", "fail": "Failed", "error": "Error"}

_CSS = """
body { margin: 0; padding: 8px 0 12px; }
a { text-decoration: none; }
.muted { color: color(var(--foreground) alpha(0.55)); }
.bar { margin-bottom: 12px; white-space: nowrap; }
a.btn { padding: 1px 6px; border-radius: 4px; font-size: 0.9rem; color: var(--foreground);
        background-color: color(var(--foreground) alpha(0.12)); }
a.primary { background-color: color(var(--greenish) alpha(0.28)); }
a.submit { background-color: color(var(--yellowish) alpha(0.28)); }
a.danger { background-color: color(var(--redish) alpha(0.24)); }
.banner { margin-bottom: 12px; padding: 8px 12px; border-radius: 6px; }
.headline { font-weight: bold; }
.detail { margin-top: 4px; }
.running { background-color: color(var(--bluish) alpha(0.22)); }
.ok { background-color: color(var(--greenish) alpha(0.2)); }
.bad { background-color: color(var(--redish) alpha(0.2)); }
.card { margin-bottom: 8px; padding: 8px 12px 12px 9px; border-radius: 6px;
        background-color: color(var(--foreground) alpha(0.06));
        border-style: solid; border-width: 0 0 0 3px;
        border-color: color(var(--foreground) alpha(0.06)); }
.card.pass { border-color: var(--greenish); }
.card.fail, .card.error { border-color: var(--redish); }
.head { white-space: nowrap; }
.name { font-weight: bold; }
.badge { padding: 0 6px; border-radius: 8px; font-size: 0.85rem; font-weight: bold; }
.badge.pass { background-color: color(var(--greenish) alpha(0.3)); }
.badge.fail, .badge.error { background-color: color(var(--redish) alpha(0.3)); }
.badge.running { background-color: color(var(--bluish) alpha(0.3)); }
.key { margin-top: 8px; font-size: 0.85rem; color: color(var(--foreground) alpha(0.55)); }
.wrong { color: var(--redish); }
.right { color: var(--greenish); }
"""


def title(question, language):
    """The panel's line of text, shown above the phantom."""
    return "{}. {}  ({})".format(question.frontend_id, question.title, language)


def render(question, cases, message, running):
    """``message`` is the error of the last run (compile error, expired session, ...)."""
    parts = [
        '<div class="bar">{}</div>'.format((_NBSP * 2).join((
            _button("add", "+ Add"), _button("run", "▶ Run all", "primary"),
            _button("submit", "Submit", "submit")))),
        _banner(cases, message, running),
    ]
    parts += [_card(index, case, question.param_names) for index, case in enumerate(cases)]
    if not cases:
        parts.append('<div class="muted">No test cases yet. Add one to run your code.</div>')
    return '<body id="leetcode-tests"><style>{}</style>{}</body>'.format(_CSS, "".join(parts))


def _button(href, label, kind=""):
    # Non-breaking spaces keep a label on one line; a plain space would let it wrap mid-button.
    return '<a class="btn {}" href="{}">{}</a>'.format(kind, href, label.replace(" ", _NBSP))


def _banner(cases, message, running):
    if running:
        count = sum(1 for case in cases if case.status == "running")
        return '<div class="banner running"><div class="headline">Running {} test{} on LeetCode…</div></div>'.format(
            count, "" if count == 1 else "s")
    if message:
        headline, _, detail = message.partition("\n")
        detail = detail.strip("\n")
        return '<div class="banner bad"><div class="headline">{}</div>{}</div>'.format(
            escape(headline), '<div class="detail">{}</div>'.format(_lines(detail)) if detail else "")
    summary = testcases.summary(cases)
    if not summary:
        return ""
    passed = all(case.status == "pass" for case in cases if case.status)
    return '<div class="banner {}"><div class="headline">{}</div></div>'.format(
        "ok" if passed else "bad", escape(summary))


def _card(index, case, param_names):
    head = ['<span class="name">Test{}{}</span>'.format(_NBSP, index + 1)]
    if case.status in _BADGE:
        head.append('<span class="badge {}">{}</span>'.format(case.status, _BADGE[case.status]))
    if case.custom:
        head.append('<span class="muted">custom</span>')
    head.append(_button("run:{}".format(index), "Run"))
    if case.custom:
        head += [_button("edit:{}".format(index), "Edit"),
                 _button("delete:{}".format(index), "Delete", "danger")]

    named = len(param_names) == len(case.values)
    inputs = "".join("<div>{}</div>".format(
        _text("{} = {}".format(name, value) if named else value))
        for name, value in zip(param_names if named else case.values, case.values))
    body = ['<div class="head">{}</div>'.format((_NBSP * 2).join(head)), _field("Input", inputs)]
    if case.expected:
        body.append(_field("Expected", "<div>{}</div>".format(_text(case.expected))))
    if case.status in ("pass", "fail") or case.actual:
        body.append(_field("Output", '<div class="{}">{}</div>'.format(
            "right" if case.status == "pass" else "wrong", _text(case.actual or "(empty)"))))
    if case.stdout:
        body.append(_field("Stdout", _lines(case.stdout)))
    edge = case.status if case.status in ("pass", "fail", "error") else ""
    return '<div class="card {}">{}</div>'.format(edge, "".join(body))


def _field(label, content):
    return '<div class="key">{}</div>{}'.format(label, content)


def _text(value):
    value = str(value)
    if len(value) > MAX_VALUE_LENGTH:
        value = value[:MAX_VALUE_LENGTH] + "…"
    return escape(value)


def _lines(text):
    """Multi-line text, one div per line, keeping each line's indentation."""
    rendered = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = _NBSP * (len(line) - len(stripped))
        rendered.append("<div>{}{}</div>".format(indent, _text(stripped) or _NBSP))
    return "".join(rendered)
