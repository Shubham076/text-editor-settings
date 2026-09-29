# Sublime Text packages

Source of truth for the Sublime Text packages kept in this settings repo. Each one is
symlinked into Sublime's package directory rather than copied, so editing a file here is
editing the installed package:

```
~/Library/Application Support/Sublime Text/Packages/<Name>
    -> ~/Desktop/text-editor-settings/sublime/packages/<Name>
```

## What is here

| Package | Purpose | Handles |
| :--- | :--- | :--- |
| [UIElements](UIElements/README.md) | Importable floating and anchored dropdowns, plus themed buttons with Python click callbacks. | Any text view — attached by another package or the UIElements demo commands |
| [CsvGridOverlay](CsvGridOverlay) | Sortable, editable grid drawn over the folded source of a delimited file. | `.csv`, `.tsv`, `.tab`, `.psv`, plus any view scoped `text.csv` / `text.tsv` / `text.delimited` |
| [MarkdownPreviewOverlay](MarkdownPreviewOverlay) | Rendered Markdown reading mode drawn over the folded source. | `.md`, `.markdown`, `.mdown`, `.mkd`, plus any view scoped `text.html.markdown` |
| [Terminus](Terminus) | Terminal emulator in a Sublime view or panel. | No file types — opened by command, not by extension |
| [UiProbe](UiProbe/README.md) | Throwaway probe: a fixed header view over a scrollable body view via a two-group row layout, with the findings on tabs and minihtml limits. | No file types — `UI Probe: Open` / `UI Probe: Close` commands |
| [LSP](LSP) | `sublimelsp/LSP` with an API for other packages to contribute hover popup content. | Any language with a server configured |
| [LSP-tsgo](LSP-tsgo) | `sublimelsp/LSP-tsgo` with a Goto Source Definition command (the `.js` behind a `.d.ts`). | `.js`, `.jsx`, `.ts`, `.tsx` |
| [Debugger](Debugger) | `daveleroy/SublimeDebugger` with the hover popup merged into LSP's, value summaries, per-configuration consoles and run icons in the project file. | Any adapter, currently exercised with Go and delve |

Both overlay packages work the same way: fold the buffer, draw a `minihtml` phantom over
it, restore selections, scroll, folds, and read-only state on the way out. Neither one
rewrites the file behind your back.

### LSP and Debugger

Unlike the overlays these are **clones of upstream**, not packages written here, each on a branch of
work that is meant to go back upstream as a pull request:

| Package | Upstream (remote `upstream`) | Fork (remote `origin`) | Branch |
| :--- | :--- | :--- | :--- |
| LSP | `sublimelsp/LSP` | `Shubham076/LSP` | `feat/hover-content-providers` |
| Debugger | `daveleroy/SublimeDebugger` | `Shubham076/SublimeDebugger` | `feat/lsp-hover-integration` |
| LSP-tsgo | `sublimelsp/LSP-tsgo` (cloned at the installed release, 1.1.7) | `shubham-dogra-s1/LSP-tsgo` | `feat/goto-source-definition`, open as [sublimelsp/LSP-tsgo#15](https://github.com/sublimelsp/LSP-tsgo/pull/15) |
| Debugger2 | the `Debugger` clone above | — | `feat/new-ui` |

`Debugger2` is the same upstream code carried on as a separate package (its own settings, menus
and command names) so it can be installed beside `Debugger`; it holds the new live UI.

This repo does **not** record `LSP`, `Debugger` or `MarkdownPreviewOverlay`: each is a plain clone
carried by its own git repo and listed in the root [.gitignore](../../.gitignore). The git that
tracks their future updates is theirs, not this repo's. `LSP-tsgo` and `Debugger2` are the
exception — their nested `.git` was removed, so their files are tracked here directly and upstream
updates for them are manual.

Recreate the three clones on a new machine:

```sh
cd sublime/packages
git clone --branch feat/hover-content-providers https://Shubham076@github.com/Shubham076/LSP.git LSP
git -C LSP remote add upstream git@github.com:sublimelsp/LSP.git
git clone --branch feat/lsp-hover-integration https://Shubham076@github.com/Shubham076/SublimeDebugger.git Debugger
git -C Debugger remote add upstream git@github.com:daveleroy/SublimeDebugger.git
git clone git@github.com:flashmodel/MarkdownPreviewOverlay.git MarkdownPreviewOverlay
ln -sfn ../../LSP/popups.css LSP/popups.css && git -C LSP update-index --skip-worktree popups.css
for n in Debugger LSP MarkdownPreviewOverlay; do
  ln -sfn "$PWD/$n" ~/Library/Application\ Support/Sublime\ Text/Packages/"$n"
done
```

`origin` must keep the `https://Shubham076@github.com/...` form. A global
`url.git@github.com:.insteadOf https://github.com/` rewrites plain GitHub HTTPS URLs to SSH, and the
SSH key here belongs to `shubham-dogra-s1`, which cannot write to the `Shubham076` forks; the
`Shubham076@` prefix stops the rule from matching so the keychain token is used instead. `upstream`
stays on SSH deliberately — read-only access to a public repo works with either key.

Pull a maintainer release inside a clone, keeping local work on top:

```sh
git fetch upstream && git rebase upstream/main      # upstream/master for Debugger
git push --force-with-lease origin <branch>
```

`LSP/popups.css` is a personal customization that is a tracked file upstream and must stay out of
any PR. It is a symlink to [../LSP/popups.css](../LSP/popups.css) flagged `skip-worktree`, so git
keeps upstream's version in the index and reports the clone clean. If a rebase ever refuses because
of it, clear the flag with `git update-index --no-skip-worktree popups.css`, take the upstream
change, and set it again.

Histories bundled before the `LSP-tsgo` and `Debugger2` clones were dissolved are in
`~/git-history-backup-20260929/`. `Debugger2`'s 948-commit `feat/new-ui` branch, and five abandoned
`Debugger` branches, exist only there.

[notes](notes) holds the write-ups that go with the work in them, kept here rather than inside the
clones so they cannot end up in a pull request by accident.

### CsvGridOverlay

Delimiter is sniffed from the extension and then the contents (`,`, `\t`, `;`, `|`), or
forced with the `delimiter` setting. Quoted fields, embedded commas, and records spanning
several lines are parsed and written back correctly. Column names sort on click, cells
open an input panel on click, rows paginate, and columns size to their content.
See [CsvGridOverlay/README.md](CsvGridOverlay/README.md).

### MarkdownPreviewOverlay

Renders through `mdpopups` (a Package Control dependency) with a custom table engine,
syntax-highlighted code blocks, and local image support.
See [MarkdownPreviewOverlay/README.md](MarkdownPreviewOverlay/README.md).

### Terminus

Note that Sublime does **not** load Terminus from this folder. Its symlink points at a
working checkout instead:

```
~/Library/Application Support/Sublime Text/Packages/Terminus
    -> ~/PycharmProjects/Terminus
```

The copy here is a snapshot of that checkout, so the two can drift apart.

## Version check — 2026-09-06

| Package | Local | Upstream | State |
| :--- | :--- | :--- | :--- |
| CsvGridOverlay | written 2026-09-06, not under version control | none | Local only. Nothing to publish or pull. |
| MarkdownPreviewOverlay | `975a84d` | `975a84d` (`github.com/flashmodel/MarkdownPreviewOverlay`) | Up to date, working tree clean. |
| Terminus | snapshot of `~/PycharmProjects/Terminus` | fork `Shubham076/terminus`, `origin/master` at `0cccd3f` | Not published. See below. |

**Update 2026-09-29.** `MarkdownPreviewOverlay` was re-cloned and now sits on `master` at `6222007`
(`v0.1.4`), 11 commits ahead of the `975a84d` in the table above — native keyboard scrolling, scroll
sync and image-path fixes. Update it with a plain `git -C MarkdownPreviewOverlay pull`.

**Terminus is the one to watch.** The checkout Sublime loads sits on branch
`refactored_forward_backward_panel` at `ecbd61b` with uncommitted changes in
`terminus/commands.py` and `terminus/render.py`. Those edits exist only in that working
tree and in the snapshot here — they are not committed, not pushed, and not on
`origin/master`. Commit and push that branch if you want them backed up.

Re-run the check with:

```sh
git -C MarkdownPreviewOverlay fetch && git -C MarkdownPreviewOverlay status -sb
git -C ~/PycharmProjects/Terminus status -sb
diff -rq Terminus ~/PycharmProjects/Terminus -x .git -x '*.pyc' -x __pycache__
```

## Adding a package

1. Put it in this folder.
2. `ln -s "$PWD/<Name>" ~/Library/Application\ Support/Sublime\ Text/Packages/<Name>`
3. Add a row to the table above.
