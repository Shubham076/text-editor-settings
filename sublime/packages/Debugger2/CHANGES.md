# Variable rendering changes

Changes on `feat/lsp-hover-integration` to how a variable is labelled in the debugger
panel and the hover popup. They all sit in two functions and their helpers:

- `value_summary()` in `modules/views/variable.py` — the short label for a row that has
  children. Shared by the panel (`variable.py:render_header`) and the hover popup
  (`hover.py:_lines_for`), so one behaviour covers both.
- `_fields_of()` in `modules/hover.py` — lays a value out down the page at the last level
  the popup goes to, instead of across one line.

Neither function exists upstream; both arrived in `b59b206` along with `modules/hover.py`
itself. They were written against delve's output and, applied to every adapter, mislabelled
values from adapters that format them differently.

## What a row shows

An adapter puts the whole recursive serialization of a value in the DAP `value` field.
Using it as the row label repeats every child listed underneath and pushes the rest of the
row off the end, so the label is cut back to the part in front of the contents:

| adapter writes | row shows |
| --- | --- |
| `main.Config {Name: "x", Port: 8080}` | `main.Config` |
| `[]main.item len: 5, cap: 8, [{…}]` | `[]main.item len: 5, cap: 8` |
| `AgenticPluginConfig(api_key='x', timeout=30)` | `AgenticPluginConfig` |
| `{'a': {'x': 1, 'y': {...}}}` | `dict` |
| `{'a': 1, 'b': 2}` | `{'a': 1, 'b': 2}` |

## The changes

### `3d4353e` — an object summarizes to its type

`_contents_index` returned the first `{` anywhere in the value. A python repr nests one
deep inside, so `AgenticPluginInstallerSettings(policy=…(…, overrides={}), …)` was cut at
`overrides=`: an unbalanced 120 character prefix that wrapped over a dozen lines, longer
than the value it summarized. Objects written as `Name(...)` with no dict inside were not
summarized at all.

A `(` now opens the contents, but only when its group runs to the end of the value. That
is what a python repr looks like. Delve puts the dynamic type of an interface in front of
the contents, `error(*errors.errorString) *{s: "boom"}`, where the group does not reach the
end and belongs in the label. String literals are stepped over, so a brace inside
`path='/a/{b}/c'` is not mistaken for the start of the contents.

### `cf39b2a` — the reported type is carried on the variable

An adapter that renders a container as only its contents, as debugpy does for a dict,
leaves nothing in front to cut at. `supportsVariableType` is already sent at initialize
(`session.py:189`) and adapters answer it, but `dap.Variable` dropped `type` in
`from_variable` and `from_evaluate`. It is now carried and used as the label for those.

### `b16b7c3` — lists, dicts and objects read one item per line

Three things kept a python container printing across the row:

- `_contents_index` skipped a `[` at the start of a value. `previous` is empty there and an
  empty string is a substring of `'_.'`, so the test for an identifier running into the
  bracket passed and **every list** fell through to returning its whole value. Go reached
  the right answer one branch later, by way of the "holds nothing" rule, which masked it.
- A width gate let anything that happened to fit stay inline, so a dict holding one object
  printed the object twice, once in the label and again below it.
- `_fields_of` only recognised `T {A: 1}`, so at the last level of the popup a python
  object printed on one line while a go struct was laid out per field. Its key test
  rejected both `a=1` and a dict's `'k': v` and folded every field into the first.

A field name is now read up to the first `:` or `=` outside a string literal, and a quoted
key counts as one.

### `d2e8de9` — flat contents that fit preview inline

`{'a': 1, 'b': 2}` says more than `dict` and the row has space for it. **Width alone is the
wrong test.** An adapter renders only so many levels and elides the rest, debugpy writing
`{...}`, so:

```
{'a': {'x': 1, 'y': {...}}, 'b': {'p': 2, 'q': {...}}}     54 characters, unbounded content
[[1, 2], [3, 4]]        16 characters, nested
{'a': 1, 'b': 2}        16 characters, flat
```

The last two are the same length and only one is worth previewing. So contents preview
inline only when `_is_flat_contents()` holds — nothing in them opens a container of its own
and nothing was elided — and when they fit in front of a name on an indented row
(`MAX_INLINE_CONTENTS`). Anything else takes its type and is read one item per line.

### `a22e30d` — a positional group is not a struct

`_fields_of` took any `Name(...)` reaching the end of a value as a field list. Rust reports
an option as `Some(5)` and a tuple variant as `Tagged("t")`, a js function its parameters
as `function foo(a, b)`, a c++ vector its length as `std::vector<int>(3)`. A group must now
name at least one field to be laid out as one; positional groups are left as written.

## Compatibility

The DAP messages were always well formed and complete — every field was present in the
child rows. These are label heuristics over the `value` string, and each adapter formats
that string its own way, so the changes were checked against values captured over DAP
rather than against assumptions.

### Measured

Captured by driving each adapter over DAP and walking the variable tree.

| language | adapter | nodes | `value_summary` vs. before | `_fields_of` vs. before |
| --- | --- | --- | --- | --- |
| Go | delve 1.27.1 | 50 | unchanged | 46 distinct, unchanged |
| C | lldb-dap 17.0.0, clang 17 | 101 | unchanged | 37 distinct, unchanged |
| Rust | lldb-dap 17.0.0, rustc 1.95 | 25 | unchanged | 23 distinct, unchanged |
| Python | debugpy 1.8.20 | — | fixed, see above | fixed, see above |

Covered: structs, nested structs, pointers, `[]*T`, `[][]T`, arrays, maps, slices with
`len:`/`cap:` headers and a `memoryReference`, interfaces with a dynamic type, channels,
functions, C `char[N]` strings and unions, Rust `Vec`, `HashMap`, `Option`, tuple structs,
`&[T]`, and `(i32, &str)` — a value that *starts* with `(` and must not be read as
contents.

Only python behaviour changed. Delve, lldb C and lldb Rust all write a type, an address or
a `len:`/`cap:` header in front of their contents, so they never reach the branch that
falls back to the reported type.

### Not measured

No adapter for these is installed here, so representative values were taken from each
one's documented format and checked for sanity rather than against a recording. Treat the
table as reasoning, not evidence:

| adapter | value | row shows |
| --- | --- | --- |
| vscode-js-debug | `Object {a: 1, b: 2}` | `Object` |
| vscode-js-debug | `Map(2) {'a' => 1}` | `Map(2)` |
| vscode-js-debug | `function foo(a, b)` | `function foo` |
| java-debug | `Item@1234  {name: "x"}` | `Item@1234` |
| java-debug | `ArrayList<Item>  size=2` | unchanged |
| netcoredbg | `Item {Name="x", Qty=1}` | `Item` |
| netcoredbg | `{System.String[3]}` | reported type |
| rdbg | `{"a"=>1, "b"=>2}` | unchanged, flat and short |
| rdbg | `#<Item name="x", qty=1>` | unchanged |
| xdebug | `array(3) [0 => 1]` | `array(3)` |
| lua | `table: 0x7f8 {a = 1}` | `table: 0x7f8` |

214 values in total, measured and synthesized, were checked against the invariant that a
label is either the whole value, the reported type, or a clean prefix of the value — never
an unbalanced fragment and never ending on a dangling `=`, `(`, `{`, `,` or `:`. No
failures.

### Known trade-offs

- A single value wrapper loses its payload from the label: `Some(5)` shows `Some`,
  `Symbol(x)` shows `Symbol`. The payload is the row underneath.
- A rust slice shows `&` for `&[i32] @ 0x…`, because the `[` follows a `&` that is not part
  of an identifier. Pre-existing, unchanged by any of this, and worth fixing separately.
- A small dict now shows its contents inline only while they are flat. A dict of two dicts
  shows `dict` even though it is short.
- An adapter that reports no `type` for a bare container falls back to the whole value, the
  behaviour before any of this.

## Re-running the checks

```sh
python3 tests/run.py
```

The pure label logic now lives in `modules/variable_format.py`, which imports no sublime,
so it can be exercised from a terminal: 32 tests in about ten milliseconds. The values
recorded from each adapter are checked in under `tests/fixtures/`, so no adapter is needed
to run them, and `tests/capture/` holds the DAP client and the programs they were recorded
from. See `tests/README.md`.

`python3 tests/run.py --update` regenerates the expected labels. Read that diff before
committing it — every line is a row that will look different in the panel.
