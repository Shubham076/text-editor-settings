# Merging the debugger hover popup into the LSP hover popup

Tracking file for the work on [sublimelsp/LSP#2646](https://github.com/sublimelsp/LSP/issues/2646)
("Combining lsp popup with debugger"). Two repositories are involved: LSP gets a generic
extension point, the debugger becomes a consumer of it.

Last updated: 2026-09-07

## The problem

During a debug session, hovering over an expression produced two popups: the debugger opened its
own (`start.py` `on_hover` -> `ui.Popup`) and LSP opened its own (`documents.py` `on_hover` ->
`lsp_hover` -> `show_lsp_popup`). Two independent `view.show_popup()` calls on the same hover point.

LSP's `LspHoverCommand` is already a merger of several async content sources (server hovers,
diagnostics, quickfix actions, document links) collected with `Promise.all` and joined with
`<hr class="m-0">`. So the fix is to make that source list extensible rather than to special case
the debugger.

## Repositories / branches

| What | Path | Base | Branch | Commit |
|---|---|---|---|---|
| LSP | `~/Library/Application Support/Sublime Text/Packages/LSP` | `sublimelsp/LSP` `main` @ `b5019f25` (v2.13.0) | `feat/hover-content-providers` | `eb198753` |
| Debugger | `~/Library/Application Support/Sublime Text/Packages/Debugger` | `daveleroy/SublimeDebugger` `master` @ `91d91a6` | `feat/lsp-hover-integration` | `38b59ca`, `0a0d195` |

`0a0d195` on the debugger branch is the value summary change described below. It is a separate
concern from the hover work and wants its own PR, it just shares the branch for now.

The debugger branch is a cherry-pick (`-x`) of `8ee84e6`, which was first written against the old
`shubham-dogra-s1/SublimeDebugger` checkout in
`~/Library/Application Support/Sublime Text/Packages/Debugger`. It applied cleanly onto upstream;
the amends on top drop the `VariableView` import from `start.py`, which became unused once the hover
code moved out, and fold in the styling fix (`contributes/popups.css`, the `mdpopups` dependency and
the `modules/hover.py` rewrite of the non LSP popup).

## LSP side - `feat/hover-content-providers`

New public API, exported from `LSP.plugin`:

```python
HoverContentProvider = Callable[[sublime.View, int], 'Promise[str | None]']

register_hover_content_provider(name: str, provider: HoverContentProvider, priority: int = 0)
unregister_hover_content_provider(name: str)
```

| File | Change |
|---|---|
| `plugin/core/hover_providers.py` | New. Registry plus `hover_content_providers()`, which returns `(name, priority, provider)` ordered by ascending priority, then name. |
| `plugin/__init__.py` | Exports `HoverContentProvider`, `register_hover_content_provider`, `unregister_hover_content_provider`. |
| `plugin/hover.py` | `request_external_content_async()` requests all providers with `Promise.all`, in parallel with the `textDocument/hover` requests. `_show_hover()` assembles the sections: negative priority above the server content, the rest below, joined with `<hr class="m-0">`. |
| `plugin/core/types.py`, `LSP.sublime-settings`, `sublime-package.json` | New `show_external_content_in_hover` setting, default `true`. |
| `tests/test_hover_providers.py` | New. Registration, overwrite-on-duplicate-name, ordering. |

Design decisions worth defending in review:

- **`Promise` return type**, so a slow provider (a DAP `evaluate` round trip) does not block the
  popup. Whichever source settles first calls `show_lsp_popup`; later ones hit the existing
  `is_popup_visible()` branch and `update_lsp_popup`. No second popup, no new lifecycle code.
- **`priority`** gives deterministic section order regardless of package load order. Debug values
  want to sit above the server hover, hence the debugger registers at `-10`.
- **No `on_navigate` callback in the API.** `make_command_link` builds a `subl:` URL and
  `_on_navigate` deliberately passes on that scheme, because minihtml runs those itself. A provider
  therefore gets fully interactive content via its own commands without LSP routing callbacks.
- **Exceptions from a provider** are caught per provider and go through `exception_log`, so a broken
  third party package cannot take out the hover popup.

Checks run: `uvx ruff@0.15.17 check .` clean; `uvx pyright@1.1.408 plugin stubs` reports only the
pre-existing `orjson could not be resolved` (a tox dependency that was not installed).

Not done: no docs page. The comparable `register_file_watcher_implementation` API is not documented
either, so where this belongs is a question for the maintainers.

## Debugger side - `feat/lsp-hover-integration`

| File | Change |
|---|---|
| `modules/hover.py` | New. Holds all the hover logic. |
| `modules/views/variable.py` | `value_summary()` - the short label for an expandable value, see below. In `0a0d195`. |
| `contributes/popups.css` | New. The rules from LSP's `popups.css` that apply to our content, under `.debugger_popup`, so the popup looks the same when LSP is not installed. |
| `dependencies.json` | Added `mdpopups`. It was only ever present because LSP pulls it in; without it `_show_styled_popup` falls back to a bare `view.show_popup()` with no stylesheet. |
| `start.py` | `on_hover` is now a 8 line delegation; `hover.startup()` in `plugin_loaded`, `hover.shutdown()` in `plugin_unloaded`; dropped the unused `VariableView` import. |
| `modules/settings.py`, `Debugger.sublime-settings` | New `hover_in_lsp_popup` setting, default `true`, requires a restart. |

`modules/hover.py` contains:

- `evaluate_hover(view, point)` - the logic that used to be inline in `start.py`: find the
  `Debugger`, check for an active session and a source file, ask the adapter for the expression via
  `adapter.on_hover_provider`, then `session.evaluate_expression(word, 'hover')`.
- `show_popup(view, point)` - the hover popup used when the LSP integration is not active. Renders
  exactly the same content as the LSP integration through `mdpopups.show_popup()`, so the hover is
  identical with and without LSP. `_popup_css()` prefers `Packages/LSP/popups.css` (so a customized
  LSP stylesheet applies here too) and falls back to the bundled `contributes/popups.css`;
  `_html_wrapper()` reproduces LSP's `html_wrapper()` container so the padding matches.
- `show_variable_popup(view, point)` - the debugger's own `VariableView` popup with expandable
  children, unchanged behaviour. No longer the hover handler, it is now only reached through the
  "Open in Debugger" link, from both the LSP popup and the popup above.
- `DebuggerShowHoverPopupCommand` - a plain `TextCommand` that opens the variable popup. This is the
  target of the `subl:` link in either popup, so nested values stay reachable.
- `startup()` / `shutdown()` - registers `'Debugger'` with LSP at `priority=-10`. The
  `from LSP.plugin import ...` sits inside the function and is wrapped in `try/except ImportError`,
  so LSP stays an optional dependency.
- `_lsp_hover_content_provider` - bridges LSP's `Promise.packaged_task()` to the debugger's
  `@core.run` coroutines: it returns the promise immediately and resolves it when the DAP evaluate
  and the child `variables` request come back.
- `_html_for_variable` / `_line_for_variable` / `_syntax_highlight` - renders the value plus up to
  `LSP_MAX_CHILDREN` (20) children as one line per value, highlighted with
  `mdpopups.syntax_highlight()` using the syntax of the hovered view, and appends an
  "Open in Debugger" link when the value has children. Newlines inside a value are collapsed so the
  rows stay aligned. `mdpopups` is imported lazily and falls back to escaped preformatted text: it is
  an LSP dependency, so it is present whenever this code path is active, but it is not declared as a
  dependency of the debugger.

`on_hover` bails out when `hover.is_active()`, which is what actually removes the second popup.
When LSP is missing or `hover_in_lsp_popup` is `false`, nothing changes for existing users.

## Variable value summaries - `0a0d195`

Found 2026-09-07 while hovering `items` in the test bed: the popup showed `item-1` twice, once in the
row for `items` itself and again in the row for child `[0]`. Not a bug in the hover work - the DAP
`value` of an expandable variable is often the entire recursive serialization of its contents. Delve
renders the slice as `[]main.item len: 5, cap: 8, [{Name: "item-1", ...}, ...]`, so the label repeats
every child that is listed right below it, and clips at the row width because there is no wrapping and
no horizontal scrolling in the panel (`ui/align.py:aligned_html_inner`, `ui/html.py:255`).

Other debuggers do not hide the summary when a value is expanded, they keep the summary short:
Chrome DevTools synthesizes a preview of the first few properties, IntelliJ shows only the type plus a
size and an object id, delve's own CLI caps it with `max-string-len` / `max-array-values`. Only this
package prints the adapter string verbatim. Following IntelliJ:

| File | Change |
|---|---|
| `modules/views/variable.py` | New `value_summary()` / `_contents_index()`. `render()` uses it for the row label. |
| `modules/hover.py` | `_html_for_variable()` uses it for the hovered value. Children keep the full value the adapter rendered. |
| `modules/dap/variable.py` | `from_evaluate()` carries `memoryReference` through, so a hovered value can show its address. |

`value_summary()` leaves the value alone when it has no children. When it does, it cuts the value where
the contents start and appends `memoryReference` when the adapter reports one. When nothing is left in
front of the contents, or nothing looks like contents, the original value is kept.

`_contents_index()` finds that point by scanning forwards for the first `{`, or the first `[` that is
not part of a type - a `[` belongs to a type when an identifier runs into it, as in `map[string]int`,
or when it holds nothing or a number, as in `[]main.item` and `[5]int`. Scanning forwards rather than
stripping the group the value ends with is not a detail: the first attempt did strip the trailing
group, and it silently did nothing for exactly the values that need it, because delve caps the length
of a value and the contents are left unterminated. Both forms are in the table below.

| Adapter value | Row label |
|---|---|
| `[]main.item len: 5, cap: 8, [{Name: "item-1", ...}, ...]` | `[]main.item len: 5, cap: 8 0xc000112000` |
| the same, cut off by delve mid contents | `[]main.item len: 5, cap: 8 0xc000112000` |
| `[][]string len: 2, cap: 2, [["a"],["b"]]` | `[][]string len: 2, cap: 2` |
| `[5]int [1,2,3,4,5]` | `[5]int` |
| `main.item {Name: "item-1", Value: 1, Tags: ...}` | `main.item 0xc000010030` |
| `map[string]int len: 2, ["a": 1, "b": 2]` | `map[string]int len: 2` |
| `55`, `"hello [world]"` (no children) | unchanged |
| `[1, 2, 3]`, `{'a': 1}` (debugpy) | unchanged, there is no prefix to keep |

Notes:

- The label is type level whether the row is collapsed or expanded, like IntelliJ. It is not a summary
  that disappears on expand.
- Panel rows are summarized at every depth, because every row is a `VariableView` and each one can be
  expanded. The **popup is deliberately different**: only the hovered value is summarized, each child
  keeps the value the adapter rendered for it. Summarizing the children there too was tried and
  reverted - the popup has no expansion, so it left five `[n]: main.item` rows carrying nothing, which
  is strictly worse than the dump it replaced. The rule is that a summary is only worth it where the
  detail is one click away.
- The two renderers share `value_summary()` and nothing else. They are separate on purpose:

  | | Variable viewer (`VariableView`) | Hover popup (`_html_for_variable`) |
  |---|---|---|
  | Renderer | `ui.div` tree through the phantom layout engine | one `mdpopups.syntax_highlight()` block |
  | Structure | recursive, one `VariableView` per node, children fetched lazily on expand | flat, the value plus up to `MAX_CHILDREN` (20) children, one line each |
  | Summary depth | every row, at every depth | the hovered value only |
  | Detail | expand any row in place | none, the "Open in Debugger" link hands off to `VariableView` |

  The summary depth row follows from the expansion row above it, which is why the popup stops at the
  hovered value.
- Two node values get a thinner label than before: `Object {a: 1}` becomes `Object` and
  `Array(3) [1, 2, 3]` becomes `Array(3)`. That is the same trade IntelliJ makes and the children are
  one click away. A setting to turn it off is the obvious answer if upstream objects.
- The full value is still reachable exactly as before, through click -> **Copy Value**
  (`views/variable.py:52`), which re-evaluates with the `clipboard` context. Editing, the quick panel
  placeholder and the memory view are untouched.
- The panel side has not been watched in a live session yet, only the popup. Every row of the table
  above was run through the function directly.

This is a separate concern from the hover branch and touches upstream files, so it went in as its own
commit and should go up as its own PR.

## Reading a truncated value - not done

Related, from the same session, kept here so it is not lost. There is no way to read a value that does
not fit the row: `text.align` / `code.align` clip with `…`, the callstack panel disables wrapping and
suppresses the horizontal scrollbar on purpose (`output_panel_callstack.py:40`), and the Variables
column is fixed at half the panel width (`output_panel_callstack.py:65`). The only escape hatch is
**Copy Value**, which is undiscoverable and puts the value on the clipboard rather than on screen.

Candidates, cheapest first:

1. `span.html_tag_and_attrbutes` (`ui/html.py:198`) already accepts a `title=` kwarg that nothing in the
   package uses. `ui.code(value, title=value)` would give a native tooltip with the full value, if
   minihtml honours `title` - unverified.
2. An "Open Value" read only view, the IntelliJ *View Text* equivalent. `memory_view.py:30` and
   `disassemble_view.py:21` already open a split to the right with
   `new_file(ADD_TO_SELECTION | CLEAR_TO_RIGHT | SEMI_TRANSIENT)`, so the mechanism exists.
3. The JetBrains layout - frames on the left, variables filling the height on the right. Written up
   separately in `~/Desktop/debugger-ui-redesign.md`, which is where the feasibility work went: what
   the output panel forces, what Sublime 4200 actually offers, and three levels of change from a
   settings knob to `HtmlSheet` panes. The resize question raised here is answered there, the layout
   engine already reflows on viewport change.
4. Cheap interim: make the 0.5 split a setting and add a maximize toggle. This is level 1 of that
   document.

## Trying it in Sublime

Both checkouts *are* the loaded packages: they sit directly in
`~/Library/Application Support/Sublime Text/Packages/`, where their files override the installed
`LSP.sublime-package` / `Debugger.sublime-package`. Package Control leaves a package directory
containing `.git` alone, so editing in place and restarting Sublime is the whole loop. Then start a
debug session and hover a variable.

Notes:

- The installed `LSP.sublime-package` was byte identical to upstream `main` for `hover.py`, so the
  patch matches what was running before.
- `Packages/LSP/popups.css` is a personal customization (rounded corners, own colors) restored from
  `~/Desktop/text-editor-settings/sublime/LSP/popups.css`, plus the `.wrapper` / `.wrapper--spacer` /
  `.m-0` rules that upstream has and the restored copy was missing. It is a tracked file upstream, so
  it will always show as modified in `git status` there. Keep it out of any commit that goes to a PR,
  and copy it back to `~/Desktop/text-editor-settings` so the fix is not lost on the next restore.
- Neither checkout has a push remote for a personal fork yet: `Packages/LSP` has `origin` =
  `sublimelsp/LSP`, `Packages/Debugger` has `origin` = `daveleroy/SublimeDebugger`. Add a fork
  remote before pushing the branches.

## Known gaps, in the order they will show up

1. **Flicker.** The DAP evaluate usually resolves after the server hover, so the popup appears and
   then grows a debug section on top of itself. Correct, but jumpy. A short debounce, or holding the
   first render until the providers settle, is the fix.
2. ~~**Styling.**~~ Fixed 2026-09-07. Two causes: the contributed fragment used `debugger-hover*`
   classes that have no rules anywhere, and the personal `Packages/LSP/popups.css` predates
   `html_wrapper`, so `.wrapper` / `.wrapper--spacer` / `.m-0` had no rules and every contributed
   section rendered flush against the top left corner with no padding. `modules/hover.py` now renders
   the rows as one `mdpopups.syntax_highlight()` block in the syntax of the hovered view, so the
   section is highlighted and mono spaced exactly like the language server content, and the personal
   `popups.css` got the three missing rules back from upstream.
3. **Only works where LSP has a session.** LSP's `on_hover` is `@requires_session` and
   `LspHoverCommand.is_enabled` needs at least one session, so in a file with no language server the
   contributed content never appears. Acceptable for Go/Java/Python, but it is the reason the
   debugger cannot drop its own popup unconditionally.
4. **The non LSP hover lost its inline tree.** `show_popup` is now the flat one line per value
   rendering, matching the LSP popup; the expandable `VariableView` moved behind the
   "Open in Debugger" link. Same trade off as gap 5 below, now in both popups.
5. ~~**The hovered value repeated its children.**~~ Fixed 2026-09-07 in `0a0d195`, see
   *Variable value summaries* above.
6. **No expand/collapse in the merged popup.** v1 flattens one level of children and links out.
   Real expansion means `subl:` toggle links plus provider side state keyed by view and point,
   which is a follow up.

## Unrelated upstream bug: the memory view syntax

Found 2026-09-07 by clicking the `☰` badge on a variable during a debug session, which opens a
memory view (`views/variable.py:214` -> `debugger.py:651` -> `memory_view.py`). It raised
*"Error loading syntax file Packages/Debugger/contributes/Syntax/Memory.sublime-syntax: Unable to
stat"* and rendered the hex dump unstyled.

`memory_view.py:34` assigns that syntax, but the file was never committed to
`daveleroy/SublimeDebugger` - `git ls-files contributes/Syntax` lists only `DebuggerConsole`,
`DebuggerProtocol`, `Disassembly`, `LLDBDisassembly`. Nothing generates it at runtime either, and
there is no `Installed Packages/Debugger.sublime-package` to fall back to, so the checkout is the
only source. Reproduces on clean upstream `master`; nothing to do with the hover work.

Fixed locally by writing `contributes/Syntax/Memory.sublime-syntax`, matching the layout produced by
`InternalMemoryView.line()` (`memory_view.py:212`): an 8+ digit hex address and `:` as `comment`,
byte pairs as `constant.numeric`, `..` for unreadable bytes as `comment`, and the ascii column after
the three space separator as `string.unquoted`. Worth its own upstream issue and PR, separate from
the hover branch.

## The replaced checkout

`Packages/Debugger` used to be the `shubham-dogra-s1/SublimeDebugger` fork; it was deleted and
replaced by the `daveleroy/SublimeDebugger` checkout described above. Its `master` was level with
its `origin/master`, so everything committed there is still on GitHub. What was local to it:

- Two fork-only commits, `78fb1ce` and `10e6649` (background task active signal / cancellation).
  These are **not** in `daveleroy/SublimeDebugger` and do not cherry-pick cleanly onto it - they
  conflict in `modules/tasks.py` and `start.py`. They live on the GitHub fork; porting them was
  deliberately deferred.
- Uncommitted local edits, saved to `~/Desktop/debugger-local-backup/`: `uncommitted.patch` (the
  full `git diff`: a `modules/adapters/go.py` change and the `go_dlv` line in
  `Debugger.sublime-settings`), the two changed files as-is, plus the untracked
  `toggle_debugger_panel.py`, `.idea/` and `java.sublime-workspace`. `git-log.txt` records the old
  branches and commits.

## Next steps

- Comment the provider registry proposal on sublimelsp/LSP#2646 to get the API shape signed off
  before opening the PR.
- Then two PRs: the LSP API, and the debugger consumer.
- Decide whether the fork-only background task commits need porting onto upstream.
- Open a separate issue/PR for the missing `Memory.sublime-syntax`.
- Read `~/Desktop/debugger-ui-redesign.md` and decide how far to take the layout work, level 1 is
  independent of everything else here.
- Watch the value summaries in the variables panel in a live session, the popup is confirmed good.
  Then decide whether `0a0d195` goes upstream as its own PR ahead of the hover work.

## Test bed

`~/Desktop/test` - a minimal Go project for exercising the merged popup:

- `main.go` - a `for` loop that builds `item` structs; breakpoint on **line 26** (the `fmt.Printf`).
  Hover targets: `it` (struct with children, so the "Open in Debugger" link shows), `total`
  (scalar), `items` (slice), `i` (loop counter).
- `test.sublime-project` - one `go` / `launch` configuration named "Debug test", with
  `"buildFlags": "-buildvcs=false"` so `go build` does not fail on VCS stamping.
- `go.mod` - module `test`, go 1.25.

Delve was upgraded from 1.6.1 to 1.27.1 (`go install github.com/go-delve/delve/cmd/dlv@latest`):
1.6.1 refused to run at all against Go 1.25 ("maximum supported version 1.16"). Verified out of
band with `dlv debug --init`: the breakpoint hits and `it`, `total`, `items` all evaluate.

LSP-gopls is installed, so both content sources are present in that file - the hover popup should
show the debug value above the gopls hover.
