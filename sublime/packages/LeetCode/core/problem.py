"""The question model and the solution file written for it. Pure Python: no Sublime imports.

A solution file starts with a comment header that identifies the problem, followed by the
description and the code between two marker lines. Only the code between the markers is sent
to LeetCode:

    /*
     * @leetcode id=1 slug=two-sum lang=java
     *
     * 1. Two Sum (Easy)
     * ...
     */

    // Do not remove code start
    class Solution { ... }
    // Do not remove code end
"""

import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .html_text import html_to_text
from .testcases import layout


@dataclass(frozen=True)
class BlockComment:
    """How a language writes a multi-line comment, and what the text must not contain."""
    opening: str
    line_prefix: str
    closing: str
    forbidden: str  # the text that would end the comment early
    replacement: str


C_BLOCK = BlockComment("/*", " * ", " */", "*/", "* /")
PYTHON_BLOCK = BlockComment('"""', "", '"""', '"""', "'''")
RUBY_BLOCK = BlockComment("=begin", "", "=end", "\n=end", "\n =end")


@dataclass(frozen=True)
class Language:
    extension: str
    comment: str  # line comment, used for the code markers
    block: BlockComment = C_BLOCK


LANGUAGES = {
    "python3": Language(".py", "#", PYTHON_BLOCK),
    "python": Language(".py", "#", PYTHON_BLOCK),
    "java": Language(".java", "//"),
    "cpp": Language(".cpp", "//"),
    "c": Language(".c", "//"),
    "csharp": Language(".cs", "//"),
    "javascript": Language(".js", "//"),
    "typescript": Language(".ts", "//"),
    "golang": Language(".go", "//"),
    "rust": Language(".rs", "//"),
    "kotlin": Language(".kt", "//"),
    "swift": Language(".swift", "//"),
    "scala": Language(".scala", "//"),
    "php": Language(".php", "//"),
    "ruby": Language(".rb", "#", RUBY_BLOCK),
}
DEFAULT_LANGUAGE = "python3"

CODE_START = "Do not remove code start"
CODE_END = "Do not remove code end"
HEADER_WIDTH = 80  # description lines are wrapped to this many columns

_HEADER_SCAN = 4000  # the header is at the top; no need to read a whole file to find it
_TAG_LINE = re.compile(r"@leetcode\s+(.+)")
_TAG_FIELD = re.compile(r"(\w+)=(\S+)")
_LEGACY_TITLE = re.compile(r"^\s*(?:#|//)\s*LeetCode Problem:\s*(.+?)\s*$", re.MULTILINE)
_MARKER = r"^[ \t]*(?:#|//)[ \t]*{}[ \t]*$"
_START = re.compile(_MARKER.format(CODE_START), re.MULTILINE)
_END = re.compile(_MARKER.format(CODE_END), re.MULTILINE)


@dataclass
class Question:
    id: str  # internal id, the one the judge wants
    frontend_id: str  # the number shown on the site
    title: str
    slug: str
    difficulty: str = ""
    content: str = ""  # description HTML; empty for premium questions without access
    topics: List[str] = field(default_factory=list)
    hints: List[str] = field(default_factory=list)
    snippets: Dict[str, str] = field(default_factory=dict)  # language slug -> starter code
    example_inputs: List[str] = field(default_factory=list)  # one newline-joined input per example
    param_names: List[str] = field(default_factory=list)

    @classmethod
    def from_graphql(cls, data):
        return cls(
            id=str(data.get("questionId") or ""),
            frontend_id=str(data.get("questionFrontendId") or ""),
            title=data.get("title") or "",
            slug=data.get("titleSlug") or "",
            difficulty=data.get("difficulty") or "",
            content=data.get("content") or "",
            topics=[tag["name"] for tag in data.get("topicTags") or []],
            hints=data.get("hints") or [],
            snippets={s["langSlug"]: s["code"] for s in data.get("codeSnippets") or []},
            example_inputs=data.get("exampleTestcaseList") or [],
            param_names=_param_names(data.get("metaData"), data.get("exampleTestcaseList")),
        )


def _param_names(meta_json, example_inputs):
    """Parameter names of the solution method, which also fixes how many lines a case has."""
    try:
        meta = json.loads(meta_json or "{}")
    except ValueError:
        meta = {}
    if "classname" in meta:  # design problems take the method names, then their arguments
        return ["operations", "arguments"]
    names = [param.get("name", "arg{}".format(i)) for i, param in enumerate(meta.get("params") or [])]
    if not names and example_inputs:
        names = ["arg{}".format(i) for i in range(len(example_inputs[0].splitlines()))]
    return names


@dataclass(frozen=True)
class SolutionInfo:
    slug: str
    language: str


def parse_header(text, slug_for_title=None):
    """Identify the problem a solution file is for, or None if it is not one.

    ``slug_for_title`` resolves the title of files written before the ``@leetcode`` line
    existed; without it (or without a match) the slug is derived from the title.
    """
    head = text[:_HEADER_SCAN]
    tag = _TAG_LINE.search(head)
    if tag:
        fields = dict(_TAG_FIELD.findall(tag.group(1)))
        if fields.get("slug"):
            return SolutionInfo(fields["slug"], fields.get("lang", ""))
    legacy = _LEGACY_TITLE.search(head)
    if legacy:
        title = legacy.group(1)
        slug = (slug_for_title(title) if slug_for_title else None) or slugify(title)
        return SolutionInfo(slug, "")
    return None


def slugify(title):
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def language_for_extension(extension) -> Optional[str]:
    for slug, language in LANGUAGES.items():
        if language.extension == extension:
            return slug
    return None


def extract_code(text):
    """The code between the markers; the whole text when there are no markers."""
    start = _START.search(text)
    if not start:
        return text.strip()
    end = _END.search(text, start.end())
    return text[start.end():end.start() if end else len(text)].strip()


def file_name(question, language):
    title = re.sub(r"[-\s]+", "_", re.sub(r"[^\w\s-]", "", question.title)).lower()
    stem = "_".join(part for part in ("leetcode", question.frontend_id, title) if part)
    return stem + LANGUAGES.get(language, Language(".txt", "//")).extension


def render_template(question, language):
    """The text of a new solution file: a block comment with the problem, then the code
    between the two marker lines."""
    spec = LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])
    header = [
        "@leetcode id={} slug={} lang={}".format(question.frontend_id, question.slug, language),
        "",
        "{}. {} ({})".format(question.frontend_id, question.title, question.difficulty),
    ]
    if question.topics:
        header.append("Topics: " + ", ".join(question.topics))
    header += ["", html_to_text(question.content) or "(No description available.)"]
    for number, hint in enumerate(question.hints, 1):
        header += ["", "Hint {}: {}".format(number, html_to_text(hint))]

    code = question.snippets.get(language)
    if code is None:
        code = "{} No {} starter code is available for this problem.".format(spec.comment, language)
    return "\n".join(_block_comment(header, spec.block) + [
        "", spec.comment + " " + CODE_START, code.rstrip(), "", spec.comment + " " + CODE_END, ""])


def refreshed_header(text, question, language):
    """The header a solution file would get today, when the one in ``text`` is different.

    Returns ``(header, length)``: the new header and how many characters at the start of
    ``text`` it replaces, everything above the code-start marker. Returns None when the
    header is already current or ``text`` has no marker, so the code is never touched.
    """
    fresh = render_template(question, language)
    old_marker, new_marker = _START.search(text), _START.search(fresh)
    if not old_marker or not new_marker:
        return None
    header = fresh[:new_marker.start()]
    if text[:old_marker.start()] == header:
        return None
    return header, old_marker.start()


def _block_comment(paragraphs, block):
    text = "\n".join(paragraphs).replace(block.forbidden, block.replacement)
    lines = [block.opening]
    for line in text.splitlines():
        wrapped = textwrap.wrap(line, HEADER_WIDTH, break_long_words=False, break_on_hyphens=False)
        # A big grid has no spaces to wrap at; give it one row per line.
        wrapped = [piece for part in wrapped
                   for piece in (layout(part) if len(part) > HEADER_WIDTH else [part])]
        lines += [(block.line_prefix + part).rstrip() for part in wrapped or [""]]
    return lines + [block.closing]
