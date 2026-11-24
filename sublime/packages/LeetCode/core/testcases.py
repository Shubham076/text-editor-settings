"""Test case inputs and judge results. Pure Python: no Sublime imports, so it is unit-testable.

A test case input is a list of values, one per parameter of the solution method, each kept as
the text LeetCode's judge reads (``[2,7,11,15]``, ``9``, ``"abc"``). The judge takes them one
per line, with the cases of a batch simply concatenated.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .html_text import html_to_text

_OPENERS = "[{("
_CLOSERS = "]})"
_NAME_PREFIX = re.compile(r"^[A-Za-z_]\w*\s*=(?!=)\s*")
_LINE_BREAK = re.compile(r"\s*\n\s*")
LONG_INPUT = 80  # characters; past this an input is written over several lines
ROW_INDENT = "  "  # in front of each row of a grid
_EXAMPLE_OUTPUT = re.compile(r"^Output(?::[ \t]*\n?|[ \t]*\n)[ \t]*(\S.*)$", re.MULTILINE)


@dataclass
class TestCase:
    values: List[str]
    expected: str = ""
    custom: bool = False
    status: str = ""  # "", "running", "pass", "fail", "error"
    actual: str = ""
    stdout: str = ""

    def reset(self):
        self.status = self.actual = self.stdout = ""


@dataclass
class RunResult:
    """Outcome of one judge run over a batch of cases."""
    error: str = ""  # compile/runtime/limit error text; empty when every case ran
    runtime: str = ""
    cases: List[dict] = field(default_factory=list)  # status, actual, expected, stdout per case


def split_top_level(text, separator=","):
    """Split on separators that are outside brackets and string literals."""
    parts, current, depth, quote, escaped = [], [], 0, "", False
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
        elif char == separator and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def parse_input(text, param_names):
    """Turn what the user typed into one value per parameter.

    Accepts ``nums = [3,2,4], target = 6``, the bare ``[3,2,4], 6``, or one value per line.
    A value may itself run over several lines, as ``format_input`` writes a big array: a
    line break inside brackets does not end the value.
    Raises ValueError with a message fit to show the user.
    """
    text = text.strip()
    if not text:
        raise ValueError("The test input is empty.")
    if len(param_names) == 1:
        values = [text]  # a single parameter takes the whole text, commas and all
    elif "\n" in text:
        values = split_top_level(text, "\n")
    else:
        values = split_top_level(text)
    values = [_NAME_PREFIX.sub("", _LINE_BREAK.sub("", value)) for value in values]
    if param_names and len(values) != len(param_names):
        raise ValueError("Expected {} value{} ({}), got {}.".format(
            len(param_names), "" if len(param_names) == 1 else "s",
            ", ".join(param_names), len(values)))
    return values


def format_input(values, param_names):
    """Show values the way LeetCode's examples do: ``nums = [2,7,11,15], target = 9``.

    A long input goes one parameter per line instead, with a grid spread over one row per
    line, so it can be read and edited. ``parse_input`` reads both forms back.
    """
    named = len(param_names) == len(values)
    parts = ["{} = {}".format(name, value) for name, value in zip(param_names, values)] if named else values
    if len(", ".join(parts)) <= LONG_INPUT:
        return ", ".join(parts)
    lines = []
    for index, value in enumerate(values):
        prefix = "{} = ".format(param_names[index]) if named else ""
        laid_out = layout(value)
        lines += [prefix + laid_out[0]] + laid_out[1:]
    return "\n".join(lines)


def layout(value):
    """A value as the lines to show it on.

    A grid, an array of arrays, gets its brackets on their own lines with one row per line
    between them, indented. Everything else is one line however long it is, as is each row;
    whatever shows the value grows or scrolls to fit.
    """
    items = split_top_level(value[1:-1]) if value.startswith("[") and value.endswith("]") else []
    if not any(item.startswith("[") for item in items):
        return [value]
    rows = [ROW_INDENT + item + "," for item in items]
    return ["["] + rows[:-1] + [rows[-1][:-1], "]"]


def example_cases(example_inputs, example_outputs, param_count):
    """Build the default cases from the question's example inputs and outputs."""
    cases = []
    for index, raw in enumerate(example_inputs):
        values = [line.strip() for line in raw.splitlines() if line.strip()]
        if param_count and len(values) != param_count:
            continue  # not shaped like this method's input; skip rather than break the batch
        expected = example_outputs[index] if index < len(example_outputs) else ""
        cases.append(TestCase(values, expected))
    return cases


def example_outputs(content_html):
    """The ``Output:`` of each example in the description, in order. Display only: the judge
    returns the authoritative expected answer when the case is run."""
    return [match.strip() for match in _EXAMPLE_OUTPUT.findall(html_to_text(content_html or ""))]


def data_input(cases):
    """The ``data_input`` the judge expects for a batch of cases."""
    return "\n".join(value for case in cases for value in case.values)


def parse_run_result(response, case_count):
    """Read LeetCode's ``check`` response for an ``interpret_solution`` run."""
    answers = _list(response, "code_answer")
    expected = _list(response, "expected_code_answer")
    stdout = _list(response, "std_output_list")
    verdicts = response.get("compare_result") or ""
    error = ""
    if not response.get("run_success", False):
        detail = (response.get("full_compile_error") or response.get("compile_error")
                  or response.get("full_runtime_error") or response.get("runtime_error") or "")
        error = "\n".join(part for part in (response.get("status_msg", "Run failed"), detail) if part)

    cases = []
    for index in range(case_count):
        actual = _at(answers, index)
        if error and not actual:
            status = "error"
        elif index < len(verdicts):
            status = "pass" if verdicts[index] == "1" else "fail"
        else:
            status = "pass" if actual and actual == _at(expected, index) else "fail"
        cases.append({"status": status, "actual": actual,
                      "expected": _at(expected, index), "stdout": _at(stdout, index).rstrip()})
    return RunResult(error, response.get("status_runtime", ""), cases)


def apply_run_result(cases, result):
    for case, outcome in zip(cases, result.cases):
        case.status = outcome["status"]
        case.actual = outcome["actual"]
        case.stdout = outcome["stdout"]
        if outcome["expected"]:
            case.expected = outcome["expected"]


def summary(cases):
    ran = [case for case in cases if case.status in ("pass", "fail", "error")]
    if not ran:
        return ""
    passed = sum(1 for case in ran if case.status == "pass")
    if passed == len(ran):
        return "All {} passed".format(len(ran))
    return "{} of {} passed".format(passed, len(ran))


def format_submission(response):
    """Plain-text report of a ``check`` response for a submission."""
    verdict = response.get("status_msg", "Unknown")
    lines = [verdict, "=" * len(verdict), ""]
    total = response.get("total_testcases")
    if total:
        lines.append("Test cases: {}/{} passed".format(response.get("total_correct", 0), total))
    if verdict == "Accepted":
        lines.append("Runtime: {}{}".format(
            response.get("status_runtime", "N/A"), _percentile(response.get("runtime_percentile"))))
        lines.append("Memory:  {}{}".format(
            response.get("status_memory", "N/A"), _percentile(response.get("memory_percentile"))))
    else:
        for label, key in (("Last input", "last_testcase"), ("Expected", "expected_output"),
                           ("Output", "code_output"), ("Stdout", "std_output")):
            value = response.get(key)
            if value:
                lines.append("{}: {}".format(label, str(value).strip().replace("\n", ", ")))
        detail = (response.get("full_compile_error") or response.get("full_runtime_error")
                  or response.get("compile_error") or response.get("runtime_error"))
        if detail:
            lines += ["", detail]
    return "\n".join(lines) + "\n"


def _percentile(value):
    return "" if value is None else "  (beats {:.1f}%)".format(value)


def _list(response, key) -> List[str]:
    value = response.get(key) or []
    return value if isinstance(value, list) else [str(value)]


def _at(items, index) -> str:
    return str(items[index]) if index < len(items) else ""
