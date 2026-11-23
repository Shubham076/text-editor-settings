"""Turn a LeetCode problem description (HTML) into plain text."""

import html
import re

_SUPERSCRIPT = re.compile(r"<sup>(.*?)</sup>", re.DOTALL)
_SUBSCRIPT = re.compile(r"<sub>(.*?)</sub>", re.DOTALL)
_LIST_ITEM = re.compile(r"<li[^>]*>")
_LINE_BREAK = re.compile(r"<br\s*/?>|</(p|div|pre|li|ul|ol|h\d)>|<(p|div|pre|ul|ol)[^>]*>")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_SPACES = re.compile(r"[ \t ]+")
_SECTION = re.compile(r"^(Example \d+|Constraints|Follow[- ]up|Note)\b", re.IGNORECASE)


def html_to_text(content):
    """Tags are removed while entities are still escaped, so a literal ``<=`` in the text
    (``&lt;=`` in the source) can never be mistaken for a tag."""
    if not content:
        return ""
    text = _SUPERSCRIPT.sub(r"^\1", content)
    text = _SUBSCRIPT.sub(r"_\1", text)
    text = _LIST_ITEM.sub("- ", text)
    text = _LINE_BREAK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    compact = []
    for line in text.splitlines():
        line = _SPACES.sub(" ", line).strip()
        if not line:
            continue  # the source's own blank lines are noise; sections get one back below
        if _SECTION.match(line) and compact:
            compact.append("")
        compact.append(line)
    return "\n".join(compact)
