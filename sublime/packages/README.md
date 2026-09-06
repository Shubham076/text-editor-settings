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
| [CsvGridOverlay](CsvGridOverlay) | Sortable, editable grid drawn over the folded source of a delimited file. | `.csv`, `.tsv`, `.tab`, `.psv`, plus any view scoped `text.csv` / `text.tsv` / `text.delimited` |
| [MarkdownPreviewOverlay](MarkdownPreviewOverlay) | Rendered Markdown reading mode drawn over the folded source. | `.md`, `.markdown`, `.mdown`, `.mkd`, plus any view scoped `text.html.markdown` |
| [Terminus](Terminus) | Terminal emulator in a Sublime view or panel. | No file types — opened by command, not by extension |

Both overlay packages work the same way: fold the buffer, draw a `minihtml` phantom over
it, restore selections, scroll, folds, and read-only state on the way out. Neither one
rewrites the file behind your back.

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
