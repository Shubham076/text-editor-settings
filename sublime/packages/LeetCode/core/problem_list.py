"""The problem list: filtering, paging and its minihtml. Pure Python: no Sublime imports.

Every row is a link, so the whole row is clickable and shows the pointer cursor.
"""

from dataclasses import dataclass
from html import escape
from typing import List

PAGE_SIZE = 50
DIFFICULTIES = ("All", "Easy", "Medium", "Hard")
STATUSES = ("All", "Solved", "Todo")
_LEVELS = {1: "Easy", 2: "Medium", 3: "Hard"}
_NBSP = " "

_CSS = """
body { margin: 0; padding: 8px 0 12px; }
a { text-decoration: none; }
.bar { margin-bottom: 12px; white-space: nowrap; }
.label, .muted { color: color(var(--foreground) alpha(0.55)); }
.chip { padding: 1px 6px; border-radius: 4px; font-size: 0.9rem; color: var(--foreground);
        background-color: color(var(--foreground) alpha(0.12)); }
.chip.on { font-weight: bold; background-color: color(var(--bluish) alpha(0.28)); }
.action { color: var(--bluish); font-weight: bold; }
.head { padding: 4px 8px; font-weight: bold; color: color(var(--foreground) alpha(0.55)); }
a.row { display: block; padding: 4px 8px; border-radius: 4px; color: var(--foreground); }
a.alt { background-color: color(var(--foreground) alpha(0.045)); }
.easy { color: var(--greenish); }
.medium { color: var(--yellowish); }
.hard { color: var(--redish); }
.solved { color: var(--greenish); }
.pager { margin-top: 8px; }
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


def render(problems, state):
    """The panel's HTML. Links: ``open:<slug>``, ``difficulty:<name>``, ``status:<name>``,
    ``page:<index>``, ``search`` and ``refresh``."""
    shown = matching(problems, state)
    pages = page_count(len(shown))
    page = min(state.page, pages - 1)
    rows = shown[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    body = [
        '<div class="bar">{}{}{}{}</div>'.format(
            _chips("Difficulty", "difficulty", DIFFICULTIES, state.difficulty),
            _chips("Status", "status", STATUSES, state.status),
            '<a class="action" href="search">Search…</a>' + _NBSP * 3,
            '<a class="action" href="refresh">Refresh</a>'),
        '<div class="head">{}</div>'.format(_cells("", "#", "Difficulty") + "Title"),
    ]
    for index, problem in enumerate(rows):
        body.append('<a class="row{}" href="open:{}">{}{}{}</a>'.format(
            " alt" if index % 2 else "", escape(problem.slug),
            _cells('<span class="solved">✓</span>' if problem.solved else "", str(problem.number),
                   problem.difficulty, problem.difficulty.lower()),
            escape(problem.title),
            '{}<span class="muted">premium</span>'.format(_NBSP * 2) if problem.premium else ""))
    if not rows:
        body.append('<div class="row muted">No problems match these filters.</div>')
    body.append('<div class="pager">{}{}{}{}</div>'.format(
        _page_link("‹ Prev", page - 1, page > 0),
        '<span class="label">{0}Page {1} of {2}{0}</span>'.format(_NBSP * 3, page + 1, pages),
        _page_link("Next ›", page + 1, page < pages - 1),
        '<span class="muted">{}{} problems</span>'.format(_NBSP * 4, len(shown))))
    return '<body id="leetcode-problems"><style>{}</style>{}</body>'.format(_CSS, "".join(body))


def _cells(mark, number, difficulty, difficulty_class=""):
    """The fixed-width columns before the title, padded with non-breaking spaces."""
    return "{}{}{}{}<span class=\"{}\">{}</span>{}".format(
        mark or _NBSP, _NBSP, _NBSP * (5 - len(number)), number + _NBSP * 3,
        difficulty_class, difficulty, _NBSP * (12 - len(difficulty)))


def _chips(label, kind, names, active):
    chips = (_NBSP).join('<a class="chip{}" href="{}:{}">{}</a>'.format(
        " on" if name == active else "", kind, name, name) for name in names)
    return '<span class="label">{}{}</span>{}{}'.format(label, _NBSP, chips, _NBSP * 4)


def _page_link(text, page, enabled):
    if not enabled:
        return '<span class="off">{}</span>'.format(text)
    return '<a class="action" href="page:{}">{}</a>'.format(page, text)
