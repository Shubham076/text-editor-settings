"""Delimited-text parsing, type inference, and sorting for CsvGridOverlay."""

import csv
import io
import os
import re

# Sublime ships a generous field limit already, but very wide quoted cells in
# exported data can still trip the default. Raise it once, defensively.
try:
    csv.field_size_limit(1024 * 1024 * 8)
except (OverflowError, ValueError):
    pass


EXTENSION_DELIMITERS = {
    ".csv": ",",
    ".tsv": "\t",
    ".tab": "\t",
    ".psv": "|",
}

SNIFF_CANDIDATES = (",", "\t", ";", "|")

_NUMERIC_RE = re.compile(
    r"""^[+-]?               # sign
        (?:\d{1,3}(?:,\d{3})+|\d+)   # 1,234,567 or 1234567
        (?:\.\d+)?           # fraction
        (?:[eE][+-]?\d+)?    # exponent
        %?$                  # trailing percent
    """,
    re.VERBOSE,
)


def normalize_delimiter(value):
    """Translate a settings value such as "tab" or "\\t" into a single character."""

    if not isinstance(value, str) or not value:
        return None
    aliases = {
        "tab": "\t",
        "\\t": "\t",
        "comma": ",",
        "semicolon": ";",
        "pipe": "|",
        "space": " ",
    }
    resolved = aliases.get(value.lower(), value)
    return resolved[0] if resolved else None


def sniff_delimiter(text, file_name=None, override=None):
    """Pick the field delimiter from an explicit override, the extension, or the text."""

    explicit = normalize_delimiter(override)
    if explicit:
        return explicit

    if file_name:
        by_extension = EXTENSION_DELIMITERS.get(
            os.path.splitext(file_name)[1].lower()
        )
        if by_extension:
            return by_extension

    sample = "\n".join(text.splitlines()[:20])
    if not sample.strip():
        return ","

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(SNIFF_CANDIDATES))
        if dialect.delimiter in SNIFF_CANDIDATES:
            return dialect.delimiter
    except csv.Error:
        pass

    # Fall back to whichever candidate yields the most consistent column count.
    best = (",", -1.0)
    for candidate in SNIFF_CANDIDATES:
        counts = [line.count(candidate) for line in sample.splitlines() if line.strip()]
        if not counts or max(counts) == 0:
            continue
        consistency = counts.count(counts[0]) / len(counts)
        score = consistency * min(max(counts), 12)
        if score > best[1]:
            best = (candidate, score)
    return best[0]


class _LineTracker(object):
    """Feed lines to csv.reader while remembering how many it consumed.

    A quoted field may span several lines, so the only reliable way to map a
    record back to its buffer text is to watch which lines the reader pulled.
    """

    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.lines):
            raise StopIteration
        line = self.lines[self.index]
        self.index += 1
        return line


def parse(text, delimiter, max_rows=0):
    """Parse delimited text into a rectangular list of rows.

    Returns ``(rows, spans, truncated, total_rows)``. ``rows`` is padded so every
    row has the same number of fields, and ``spans[i]`` is the inclusive
    ``(first_line, last_line)`` range the record occupies in ``text``.
    """

    tracker = _LineTracker(text)
    reader = csv.reader(tracker, delimiter=delimiter)
    rows = []
    spans = []
    truncated = False
    total = 0

    while True:
        start_line = tracker.index
        try:
            record = next(reader)
        except StopIteration:
            break
        except csv.Error:
            # A malformed record should still leave everything before it usable.
            truncated = truncated or bool(rows)
            break

        total += 1
        if max_rows and len(rows) >= max_rows:
            truncated = True
            continue
        rows.append(record)
        spans.append((start_line, max(start_line, tracker.index - 1)))

    # Trailing newlines produce a final empty record; drop it.
    while rows and not any(field.strip() for field in rows[-1]):
        rows.pop()
        spans.pop()
        total -= 1

    column_count = max((len(row) for row in rows), default=0)
    for row in rows:
        if len(row) < column_count:
            row.extend([""] * (column_count - len(row)))

    return rows, spans, truncated, total


def serialize_record(record, delimiter):
    """Render one record back to delimited text, quoting only where needed.

    The line terminator is kept as "\r\n" so the writer still quotes fields
    containing newlines, then stripped: the caller replaces an existing record
    in place and supplies no terminator of its own.
    """

    buffer = io.StringIO()
    csv.writer(
        buffer, delimiter=delimiter, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL
    ).writerow(record)
    return buffer.getvalue()[:-2]


def is_numeric(value):
    return bool(_NUMERIC_RE.match(value.strip())) if value.strip() else False


def numeric_columns(rows, sample_size=200, threshold=0.6):
    """Return the set of column indexes whose sampled values are mostly numeric."""

    if not rows:
        return set()

    column_count = len(rows[0])
    numeric_hits = [0] * column_count
    value_counts = [0] * column_count

    for row in rows[:sample_size]:
        for index, value in enumerate(row[:column_count]):
            if not value.strip():
                continue
            value_counts[index] += 1
            if is_numeric(value):
                numeric_hits[index] += 1

    return {
        index
        for index in range(column_count)
        if value_counts[index] and numeric_hits[index] / value_counts[index] >= threshold
    }


def _numeric_value(value):
    cleaned = value.strip().rstrip("%").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def sort_key(value, numeric):
    """Build a sort key that keeps blanks last and orders numbers numerically."""

    text = value.strip()
    if not text:
        return (1, 0.0, "")
    if numeric:
        number = _numeric_value(text)
        if number is not None:
            return (0, number, "")
    return (0, 0.0, text.lower())


def sort_rows(rows, column, descending, numeric):
    """Return rows ordered by one column, preserving each row's original index."""

    if column is None:
        return rows
    return sorted(
        rows,
        key=lambda entry: sort_key(
            entry[1][column] if column < len(entry[1]) else "", numeric
        ),
        reverse=bool(descending),
    )
