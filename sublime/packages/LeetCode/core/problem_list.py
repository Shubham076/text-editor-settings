"""The problem list: filtering, paging and its minihtml. Pure Python: no Sublime imports.

Look: two segmented filters, a search field and a refresh button, then one bordered table.
Rows are separated by hairlines and every row is a link, so the whole row is clickable and
shows the pointer cursor. Columns are lined up with non-breaking spaces, which works because
the panel uses the editor's monospace font; minihtml has no table or column layout.
"""

from dataclasses import dataclass
from html import escape
from typing import List

from .minihtml import spacer

PAGE_SIZE = 50
SIDE_PADDING = 12
MAX_TITLE_COLUMN = 64  # a longer title just pushes its own difficulty to the right
DIFFICULTIES = ("All", "Easy", "Medium", "Hard")
STATUSES = ("All", "Solved", "Todo")
_LEVELS = {1: "Easy", 2: "Medium", 3: "Hard"}
_NBSP = " "
_PREMIUM = "premium"

_CSS = """
body { margin: 0; padding: 8px 12px 16px; }
a { text-decoration: none; }
.bar { margin-bottom: 16px; white-space: nowrap; }
.muted { color: color(var(--foreground) alpha(0.5)); }
.label { color: color(var(--foreground) alpha(0.7)); }
.seg { padding: 4px 3px; border-radius: 7px;
       border-style: solid; border-width: 1px;
       border-color: color(var(--foreground) alpha(0.2));
       background-color: color(var(--foreground) alpha(0.1)); }
a.chip { padding: 1px 8px; border-radius: 5px; font-size: 0.9rem;
         border-style: solid; border-width: 1px;
         border-color: color(var(--foreground) alpha(0));
         color: color(var(--foreground) alpha(0.9)); }
a.chip.on { color: var(--foreground); background-color: var(--background);
            border-color: color(var(--foreground) alpha(0.3)); }
a.btn { padding: 4px 10px; border-radius: 7px; font-size: 0.9rem; color: var(--foreground);
        border-style: solid; border-width: 1px;
        border-color: color(var(--foreground) alpha(0.24));
        background-color: var(--background); }
a.field { color: color(var(--foreground) alpha(0.65)); }
.table { border-radius: 8px; border-style: solid; border-width: 1px;
         border-color: color(var(--foreground) alpha(0.14)); }
.head, a.row, .empty { padding: 10px 12px; white-space: nowrap;
         border-style: solid; border-width: 0 0 1px 0;
         border-color: color(var(--foreground) alpha(0.04)); }
.head { font-weight: bold; color: color(var(--foreground) alpha(0.5));
        background-color: color(var(--foreground) alpha(0.05));
        border-top-left-radius: 7px; border-top-right-radius: 7px;
        border-color: color(var(--foreground) alpha(0.08)); }
a.row { display: block; color: var(--foreground); }
a.last, .empty { border-width: 0; }
.num { color: color(var(--foreground) alpha(0.5)); }
.easy { color: var(--greenish); }
.medium { color: var(--yellowish); }
.hard { color: var(--redish); }
.solved { color: var(--greenish); }
.pager { margin-top: 12px; }
a.page { color: var(--foreground); }
.off { color: color(var(--foreground) alpha(0.3)); }
"""


@dataclass(frozen=True)
class Problem:
    number: int
    title: str
    slug: str
    difficulty: str
    solved: bool
    premium: bool


@dataclass
class ListState:
    difficulty: str = "All"
    status: str = "All"
    page: int = 0


def problems_from_api(pairs) -> List[Problem]:
    """Problems from the ``stat_status_pairs`` of LeetCode's list API, in site order."""
    problems = [Problem(
        number=int(pair["stat"]["frontend_question_id"]),
        title=pair["stat"]["question__title"],
        slug=pair["stat"]["question__title_slug"],
        difficulty=_LEVELS.get((pair.get("difficulty") or {}).get("level"), ""),
        solved=pair.get("status") == "ac",
        premium=bool(pair.get("paid_only")),
    ) for pair in pairs]
    return sorted(problems, key=lambda problem: problem.number)


def matching(problems, state):
    return [p for p in problems
            if state.difficulty in ("All", p.difficulty)
            and (state.status == "All" or p.solved == (state.status == "Solved"))]


def page_count(total):
    return max(1, -(-total // PAGE_SIZE))


def render(problems, state, width=0):
    """The panel's HTML. ``width`` is the room the panel has, in pixels; the table stretches
    to fill it. Links: ``open:<slug>``, ``difficulty:<name>``, ``status:<name>``,
    ``page:<index>``, ``search`` and ``refresh``."""
    shown = matching(problems, state)
    pages = page_count(len(shown))
    page = min(state.page, pages - 1)
    rows = shown[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    title_column = min(MAX_TITLE_COLUMN, max([len("TITLE")] + [_title_length(p) for p in rows]))

    table = ['<div class="head">{}</div>'.format(
        _columns("", "#", "TITLE", len("TITLE"), title_column) + "DIFFICULTY")]
    for index, problem in enumerate(rows):
        title = escape(problem.title)
        if problem.premium:
            title += '{}<span class="muted">{}</span>'.format(_NBSP * 2, _PREMIUM)
        table.append('<a class="row{}" href="open:{}">{}<span class="{}">{}</span></a>'.format(
            " last" if index == len(rows) - 1 else "", escape(problem.slug),
            _columns('<span class="solved">✓</span>' if problem.solved else "",
                     str(problem.number), title, _title_length(problem), title_column),
            problem.difficulty.lower(), problem.difficulty))
    if not rows:
        table.append('<div class="empty muted">No problems match these filters.</div>')

    body = [
        spacer(width - 2 * SIDE_PADDING),
        '<div class="bar">{}{}{}{}</div>'.format(
            _segments("Difficulty", "difficulty", DIFFICULTIES, state.difficulty),
            _segments("Status", "status", STATUSES, state.status),
            '<a class="btn field" href="search">⌕{}Search…{}</a>{}'.format(
                _NBSP, _NBSP * 18, _NBSP * 2),
            '<a class="btn" href="refresh">↻{}Refresh</a>'.format(_NBSP)),
        '<div class="table">{}</div>'.format("".join(table)),
        '<div class="pager">{}{}{}{}</div>'.format(
            _page_link("‹ Prev", page - 1, page > 0),
            '<span class="label">{0}Page {1} of {2}{0}</span>'.format(_NBSP * 3, page + 1, pages),
            _page_link("Next ›", page + 1, page < pages - 1),
            '<span class="muted">{}{} problems</span>'.format(_NBSP * 4, len(shown))),
    ]
    return '<body id="leetcode-problems"><style>{}</style>{}</body>'.format(_CSS, "".join(body))


def _title_length(problem):
    return len(problem.title) + (2 + len(_PREMIUM) if problem.premium else 0)


def _columns(mark, number, title, title_length, title_column):
    """Solved mark, number and title, each padded to its column with non-breaking spaces.
    ``title`` is HTML, so its visible length is passed separately."""
    return '{}{}<span class="num">{}{}</span>{}{}{}'.format(
        mark or _NBSP, _NBSP * 2, _NBSP * (5 - len(number)), number, _NBSP * 3,
        title, _NBSP * (max(0, title_column - title_length) + 4))


def _segments(label, kind, names, active):
    """A labelled segmented control: one tinted group, the active choice raised inside it."""
    chips = "".join('<a class="chip{}" href="{}:{}">{}</a>'.format(
        " on" if name == active else "", kind, name, name) for name in names)
    return '<span class="label">{}{}</span><span class="seg">{}</span>{}'.format(
        label, _NBSP * 2, chips, _NBSP * 4)


def _page_link(text, page, enabled):
    text = text.replace(" ", _NBSP)
    if not enabled:
        return '<span class="btn off">{}</span>'.format(text)
    return '<a class="btn page" href="page:{}">{}</a>'.format(page, text)
