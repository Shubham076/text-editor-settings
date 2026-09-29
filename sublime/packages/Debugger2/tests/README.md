# Tests

Covers `modules/variable_format.py` — the label a variable row shows in the debugger panel
and the hover popup.

```sh
python3 tests/run.py             # run them
python3 tests/run.py --update    # regenerate the expected labels, then run them
```

No sublime, no adapter, no network. 32 tests in about ten milliseconds, so there is no
reason not to run them on every change to the label logic.

## Layout

```
tests/
  run.py                     entry point
  test_variable_format.py    the tests
  fixtures/
    delve.json               values recorded from each adapter over DAP
    debugpy.json
    lldb_c.json
    lldb_rust.json
    synthesized.json         values NOT recorded; see below
    expected.json            the label each fixture value produces
  capture/
    dap_client.py            what the recordings were made with
    programs/                the programs that were debugged
```

## The three kinds of test

**`TestRecordedFixtures`** replays every recorded value and compares the label against
`fixtures/expected.json`. This is the regression net: a behaviour change shows up as a diff
naming the adapter, the value, the old label and the new one.

**`TestBehaviour`** and **`TestFieldLayout`** pin each defect that was fixed, one test each,
so a regression names itself instead of appearing as an anonymous fixture diff.

**`TestInvariants`** asserts properties that have to hold for *every* adapter, including
ones with no fixture here:

- a label never contains an unbalanced quote
- a label never ends on a dangling `=`, `(`, `{`, `,` or `:`
- a label is the value, the reported type, or a prefix of the value
- a label is never longer than the value it summarizes
- a value with no children is always its own label
- wrapping never loses characters

Those are the useful ones for a language nobody here can run: a new adapter may produce a
label we would not have chosen, but it will not produce a fragment cut out of the middle of
a value.

## Changing behaviour on purpose

Run `python3 tests/run.py --update`, **read the diff**, and commit it with the change. Every
line of it is a row that will look different in the panel. If a diff appears in a language
you were not working on, that is the thing to explain before committing.

## Re-recording the fixtures

The recordings are checked in, so the tests need no adapter. Re-record only when you want
to cover a new value shape or a newer adapter.

`capture/dap_client.py` is a DAP client with just enough in it to launch a program, stop on
a line, and walk `variables` from the top frame. `capture/programs/` holds what was
debugged: structs, nested structs, pointers, arrays, maps, slices, interfaces, unions,
`Vec`, `HashMap`, `Option`, tuple structs, dicts, lists, objects, and containers that are
short but hold elided contents.

What the current fixtures were recorded against:

| fixture | adapter | language |
| --- | --- | --- |
| `delve.json` | delve 1.27.1 | go 1.25.5 darwin/arm64 |
| `debugpy.json` | debugpy 1.8.20 | CPython 3.12.0 |
| `lldb_c.json` | lldb-dap 17.0.0 | Apple clang 17.0.0 |
| `lldb_rust.json` | lldb-dap 17.0.0 | rustc 1.95.0 |

`lldb-dap` ships with the Xcode command line tools, at
`/Library/Developer/CommandLineTools/usr/bin/lldb-dap`, which is why C and rust are
recorded and js, java, c#, ruby, php and lua are not.

Set `supportsVariableType` in `initialize` when recording. Without it an adapter is entitled
to leave `type` out, and a container that reports no type falls back to its whole value —
you would record the fallback rather than the behaviour.

## `synthesized.json`

Not recorded. Representative values taken from each adapter's documented output format, so
the label logic is at least pinned for shapes that cannot be captured here. Treat it as
reasoning, not evidence, and replace an entry with a real recording whenever one of those
adapters is available.

## Mutation checks

The suite was checked by reverting each fix in turn and confirming it fails:

| reverted | tests that fail |
| --- | --- |
| a leading `[` not treated as a container | 4 |
| `(` always opening the contents | 3 |
| the positional-group guard in `_fields_of` | 7 |
| the flatness check | 5 |
| string literals not stepped over | 1 |

The last one found a gap: the first version of the suite passed with that revert, because
no fixture held a bracket inside a string in front of the contents. lldb writes a char
pointer as `0x0001 "[a]"`, which is exactly that, and
`test_bracket_inside_a_string_is_not_the_start_of_contents` now covers it. Worth repeating
after adding tests.
