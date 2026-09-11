# LSP `popups.css`

Personal restyling of the LSP popups. `popups.css` here is the copy this repo tracks; the file
Sublime actually loads is the same file inside the upstream clone, which is deliberately left
uncommitted so it stays out of any pull request:

```
~/Library/Application Support/Sublime Text/Packages/LSP   -> sublime/packages/LSP   (clone, gitignored)
sublime/LSP/popups.css                                    == sublime/packages/LSP/popups.css
```

Edit both, or the editor and the repo drift apart.

Last updated: 2026-09-08

## The wrapper chain, once

Every mdpopups popup is the same four layers. Nothing in this file matches unless the selector
lives somewhere in this chain:

```html
<style>…</style>                    <!-- 1. stylesheet, assembled by mdpopups              -->
<div class="mdpopups">              <!-- 2. always, mdpopups/__init__.py:368               -->
  <div class="lsp_popup">           <!-- 3. the wrapper_class LSP asked for, css.py:9      -->
    <body>                          <!-- 4. LSP's own wrapper, views.py:494 — id optional  -->
      …content…
    </body>
  </div>
</div>
```

Three things to keep straight:

- **`.mdpopups` is mdpopups', `.lsp_popup` is LSP's.** mdpopups always adds `div.mdpopups`; the
  inner div carries whatever `wrapper_class` the caller passed — `lsp_popup` for popups,
  `notification` for server message requests, `lsp_sheet` for sheets. So a rule written
  `.lsp_popup .wrapper` styles popups but not notifications, and `.mdpopups h2` styles all of them.
- **`<body>` is nested inside those divs.** mdpopups wraps whatever string it is handed
  (`_create_html()`, `mdpopups/__init__.py:368`) and LSP hands it a `<body>` (`views.py:494`).
  minihtml does not care, but it means `body { … }` in this file applies *inside* the wrappers.
- **The stylesheet is a concatenation**, in this order (`mdpopups/__init__.py:309`):

  | # | Source | Note |
  | :--- | :--- | :--- |
  | 1 | `mdpopups/css/default.css` | the `--mdpopups-*` defaults, `.mdpopups` element resets |
  | 2 | the `css=` argument | `popups.css` for popups, `notification.css` / `sheets.css` for the others — **whichever one, only one** |
  | 3 | `mdpopups.user_css` setting | `Packages/User/mdpopups.css`, absent here |

  On top of that, Sublime itself applies the color scheme's `globals.popup_css` to popups and
  phantoms. That is where `--redish` gets remapped — see [Colors](#colors).

Phantoms, annotations and hand-built sheets do **not** go through mdpopups: they are a raw
`<body>` with an inline `<style>`, no `.mdpopups` and no `.lsp_popup`. They are listed below too,
so it is clear why this file cannot reach them.

## Every case, at a glance

| # | What you see | Entry point | Wrapper chain | Stylesheet |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Hover: server docs + diagnostics + code actions + links | `hover.py:348` | `.mdpopups` > `.lsp_popup` > `<body>` | `popups.css` |
| 2 | Diagnostics + code actions from the gutter icon | `documents.py:596` | `.mdpopups` > `.lsp_popup` > `<body>` | `popups.css` |
| 3 | Completion item documentation | `completion.py:330` | `.mdpopups` > `.lsp_popup` > `<body>` | `popups.css` |
| 4 | Signature help | `documents.py:787` | `.mdpopups` > `.lsp_popup` > `<body id="lsp-signature-help">` | `popups.css` |
| 5 | `window/showMessageRequest` prompt | `message_request_handler.py:44` | `.mdpopups` > `.notification` > `<body>` | `notification.css` |
| 6 | Any of 1–5 refreshing in place | `update_lsp_popup()`, `views.py:509` | unchanged, content swapped | unchanged |
| 7 | `LSP: Show Scope Name` popup | `semantic_highlighting.py:182` | `<body id=show-scope>` — raw `view.show_popup()` | none |
| 8 | Inline diagnostic / code lens annotation | `views.py:748`, `session_view.py:415` | `<body id="lsp-annotation" class="osx">` | `annotations.css`, inlined |
| 9 | Inlay hint | `inlay_hint.py:120` | `<body id="lsp-inlay-hint">` | `inlay_hints.css`, inlined |
| 10 | Code lens phantom | `session_view.py:427` | `<body id="lsp-code-lens">` | one inline rule, no file |
| 11 | Color swatch before a color literal | `views.py:709` | `<body id='lsp-color-box'>` | inline only |
| 12 | Apply / Discard on the rename preview panel | `edit.py:72` | `<body id='lsp-buttons'>` | inline only |
| 13 | The `(code)` link in the diagnostics panel | `windows.py:558` | none at all — a bare `<a>` phantom | none |
| 14 | `LSP: Troubleshoot Server` sheet | `tooling.py:326` | `.mdpopups` > `.lsp_sheet` | `sheets.css` |
| 15 | Call / type hierarchy sheet | `tree_view.py:338` | `<body id="lsp-tree-view" class="lsp_sheet">` | `sheets.css`, inlined |

**This file (`popups.css`) reaches cases 1–4 and 6 only.** Case 5 replaces the stylesheet
wholesale, 7–13 never load a file, 14–15 use `sheets.css`.

All LSP popups are built with `md=False` — the content is already minihtml, so mdpopups only strips
frontmatter. Markdown from a server has already been converted by `minihtml()` (`views.py:529`)
before it gets here.

## Case 1 — hover, one diagnostic

Message `E501 line too long (81 > 79 characters)`, source `pycodestyle`, code `E501`, no server
hover content. Whitespace added for reading; the real string has no newlines:

```html
<style>
  /* mdpopups/css/default.css, then popups.css, then user css */
</style>
<div class="mdpopups">
  <div class="lsp_popup">
    <body>
      <div class="diagnostics">
        <div class="wrapper error">
          E501 line too long (81 &gt; 79 characters)
          <span class="color-muted">pycodestyle(E501)</span>
          <a class='copy-icon' title='Copy to clipboard'
             href='subl:lsp_copy_text{"text": "E501 line too long (81 &gt; 79 characters) (pycodestyle[E501])"}'>&#x29C9;</a>
          <div class="wrapper--spacer"></div>
        </div>
      </div>
    </body>
  </div>
</div>
```

| Element | Emitted by |
| :--- | :--- |
| `div.mdpopups` | `mdpopups._create_html()`, `mdpopups/__init__.py:368` |
| `div.lsp_popup` | same call, from `wrapper_class` = `css().popups_classname`, `css.py:9` |
| `<body>` | `show_lsp_popup()`, `views.py:494`. Hover passes no `body_id`, so it is bare |
| `div.diagnostics` | `format_diagnostics_for_html()`, `views.py:906` — one per popup, wrapping every diagnostic, sorted errors first |
| `div.wrapper.error` | `html_wrapper()`, `views.py:860`/`:869`, called with the severity class at `:950`. `wrapper` is always present; the second class is one of `error` / `warning` / `information` / `hint` (`DIAGNOSTIC_STYLES`, `views.py:100`) |
| message text | `_format_diagnostic_message()` -> `text2html()`, `views.py:653`: escapes `& < >`, tabs and runs of 2+ spaces become `&nbsp;`, newlines `<br>`, bare URLs auto-link |
| `span.color-muted` | source and code, `views.py:935`. With a `codeDescription` the code becomes an `<a>` |
| `a.copy-icon` | `views.py:936`, href is a percent-encoded `subl:lsp_copy_text{…}` command url |
| `div.wrapper--spacer` | `html_wrapper()` again — an empty div standing in for bottom padding, because minihtml collapses the last child's bottom margin |

### Case 1, everything at once

Server hover content, two diagnostics, a code action and related information. Sections are joined
with `<hr class="m-0">` by `LspHoverCommand` (`hover.py:291` and `:321`):

```html
<style>…</style>
<div class="mdpopups">
  <div class="lsp_popup">
    <body>
      <div class="wrapper">
        <p>Returns the <code>Foo</code> for a bar.</p>
        <div class="highlight"><pre>def foo(bar: Bar) -&gt; Foo</pre></div>
        <div class="wrapper--spacer"></div>
      </div>
      <hr class="m-0">
      <div class="diagnostics">
        <div class="wrapper error">
          E501 line too long (81 &gt; 79 characters)
          <span class="color-muted">pycodestyle(E501)</span>
          <a class='copy-icon' …>&#x29C9;</a>
          <hr>
          <div><a href="subl:lsp_open_location{…}">foo.py:12:5</a>: first defined here</div>
          <div class="wrapper--spacer"></div>
        </div>
        <div class="wrapper warning">
          W291 trailing whitespace
          <span class="color-muted">pycodestyle(W291)</span>
          <a class='copy-icon' …>&#x29C9;</a>
          <div class="wrapper--spacer"></div>
        </div>
      </div>
      <hr class="m-0">
      <div class="wrapper">
        <span class="lightbulb" title="Preferred Quick Fix"><img src="data:image/png;base64,…"></span>
        <a href='subl:lsp_code_actions{…}' title='Run Code Action'>Remove&nbsp;trailing&nbsp;whitespace</a>
        <div class="wrapper--spacer"></div>
      </div>
    </body>
  </div>
</div>
```

Note the related-information block: a plain `<hr>` and an **unclassed** `<div>` (`views.py:939`),
inside the same severity wrapper. The lightbulb is a base64 PNG tinted by `mdpopups.tint()`
(`views.py:885`). Server markdown contributes `<p>`, `<code>`, `div.highlight`, `<a>` — styled by
mdpopups' defaults unless this file overrides them.

## Case 2 — gutter icon, diagnostics with actions

Identical chain to case 1; only the trigger differs (clicking the gutter marker instead of
hovering). Content starts at `div.diagnostics`, no server hover section:

```html
<style>…</style>
<div class="mdpopups">
  <div class="lsp_popup">
    <body>
      <div class="diagnostics">
        <div class="wrapper error">…<div class="wrapper--spacer"></div></div>
      </div>
    </body>
  </div>
</div>
```

## Case 3 — completion documentation

`detail` and `documentation` as two wrappers with a separator, no severity class anywhere
(`completion.py:320-325`):

```html
<style>…</style>
<div class="mdpopups">
  <div class="lsp_popup">
    <body>
      <div class="wrapper">
        <p><code>def foo(bar: Bar) -&gt; Foo</code></p>
        <div class="wrapper--spacer"></div>
      </div>
      <hr class="m-0">
      <div class="wrapper">
        <p>Returns the <code>Foo</code> for a bar.</p>
        <div class="wrapper--spacer"></div>
      </div>
    </body>
  </div>
</div>
```

## Case 4 — signature help

The one popup with a `body_id`, so `<body id="lsp-signature-help">` is available as a hook for
rules that should apply here and nowhere else. Markup from `SigHelp.render()`
(`core/signature_help.py:77-92`), the label syntax-highlighted with inline colors and the active
parameter bolded:

```html
<style>…</style>
<div class="mdpopups">
  <div class="lsp_popup">
    <body id="lsp-signature-help">
      <div class="wrapper">
        <p class="signature-help-intro">
          <b>1</b> of <b>2</b> overloads
          (use <kbd>&#x2191;</kbd> <kbd>&#x2193;</kbd> to navigate, press <kbd>Esc</kbd> to hide)
        </p>
        <div class="highlight">
          <span style="color: #79619e">f(</span>
          <span style="color: #606060; font-weight: bold">x</span>
          <span style="color: #79619e">)</span>
        </div>
        <span>must be in the frobnicate range</span>
        <div class="wrapper--spacer"></div>
      </div>
      <hr class="m-0">
      <div class="wrapper">
        <span>f does interesting things</span>
        <div class="wrapper--spacer"></div>
      </div>
    </body>
  </div>
</div>
```

(`tests/test_signature_help.py:60-75` asserts this shape, if it ever needs checking.)

## Case 5 — server message request

The one popup that **replaces the stylesheet**: `css=notification.css` and
`wrapper_class='notification'` (`message_request_handler.py:44-50`). `popups.css` is not loaded at
all, so `.lsp_popup` never appears and no rule in this file applies:

```html
<style>
  /* mdpopups/css/default.css, then notification.css, then user css */
</style>
<div class="mdpopups">
  <div class="notification">
    <body>
      <h2>pylsp</h2>
      <div class='message'>&#x26A0; Server crashed 2 times in the last 3 minutes.</div>
      <div class='actions'>
        <a href='0'>Restart</a> <a href='1'>Ignore</a>
      </div>
    </body>
  </div>
</div>
```

This is where `.actions` and `.message` live — `notification.css` styles them as
`.notification .actions`. That is why the `.actions` rule sitting in `popups.css` is dead.

## Case 6 — updating in place

`update_lsp_popup()` (`views.py:509`) calls `mdpopups.update_popup()` with the same `css` and
`wrapper_class`, so the chain is unchanged and only the content inside `<body>` is swapped. Used by
hover when images finish resolving (`hover.py:361`), by signature help when navigating overloads
(`documents.py:800`), and by the hover/diagnostics popups when one is already visible
(`hover.py:346`).

## Cases 7–15 — the ones this file cannot reach

Each is a standalone minihtml document with its `<style>` written inline. No `.mdpopups`, no
wrapper class (except where noted), so scheme `popup_css` still applies to variables but nothing in
`popups.css` does.

Annotation, one per diagnostic (`views.py:754`) — same severity class as the popup, different
stylesheet, which is why the annotation is color-only while the popup carries a band:

```html
<body id="lsp-annotation" class="osx">
  <style>/* annotations.css, inlined */</style>
  <div class="error">
    E501 line too long (81 &gt; 79 characters)
    <span class="color-muted">pycodestyle</span>
  </div>
</body>
```

Inlay hint (`inlay_hint.py:116-131`) — the view's own `font_face` is injected into the style block:

```html
<body id="lsp-inlay-hint">
  <style>
    .inlay-hint { font-family: Mononoki Nerd Font; }
    /* inlay_hints.css, inlined */
  </style>
  <div class="inlay-hint"><a href="…">: Foo</a></div>
</body>
```

Code lens phantom (`session_view.py:427`) — one hardcoded rule, no stylesheet file:

```html
<body id="lsp-code-lens">
  <style>body {font-family: system}</style>
  <small><a href="…">3 references</a> | <a href="…">Run test</a></small>
</body>
```

Color swatch (`views.py:700-711`), Apply/Discard buttons on the rename preview panel
(`edit.py:72`, phantom at `edit.py:401`), and the diagnostics-panel code link (`windows.py:558`, literally
`(<a href='…'>E501</a>)` with no body or style) follow the same pattern.

Troubleshoot-server sheet (`tooling.py:326`) is mdpopups again, but with `sheets.css` and
`wrapper_class='lsp_sheet'`, and `md=True` — the only markdown-rendered surface:

```html
<style>/* default.css, then sheets.css */</style>
<div class="mdpopups">
  <div class="lsp_sheet">
    <h1>Server: pylsp</h1>
    …
  </div>
</div>
```

The hierarchy sheets (`tree_view.py:338`) hand-write the same class *without* mdpopups, so
`.lsp_sheet` is on the `<body>` rather than on a wrapper div:

```html
<body id="lsp-tree-view" class="lsp_sheet">
  <style>/* sheets.css, inlined */</style>
  …
</body>
```

## Selectors in this file, and what they hit

| Selector | Hits |
| :--- | :--- |
| `html`, `body` | the popup document; `body` sits inside the two wrapper divs |
| `.mdpopups` | mdpopups' outer div — also present on notifications and sheets |
| `.lsp_popup` | the wrapper div for cases 1–4 and 6 only |
| `.lsp_popup .wrapper` | every section div; the `padding-bottom: 0` pairs with the spacer div |
| `.lsp_popup .wrapper--spacer` | the empty trailing div, i.e. the popup's bottom padding |
| `.lsp_popup .m-0` | the `<hr class="m-0">` separators between sections |
| `.lsp_popup p`, `.lsp_popup h1…h6`, `.lsp_popup a` | markdown from a server, and action links |
| `.diagnostics` | the block holding all diagnostics; sets the monospace font |
| `.error` / `.warning` / `.information` / `.hint` | the severity class on `div.wrapper` |
| `.color-muted` | the `source(code)` span |
| `.highlight`, `.mdpopups .highlight` | mdpopups code blocks and the signature-help label |

### Rules in this file that match nothing

Harmless, listed so they are not mistaken for live knobs:

| Selector | Why it is dead |
| :--- | :--- |
| `.actions` | only the notification popup emits it, and that popup loads `notification.css` instead of this file (case 5) |
| `pre.related_info` | related information is emitted as an unclassed `<div>`, `views.py:940` |
| `.lsp_popup--spacer` | the class is `wrapper--spacer`; only `.lsp_popup .wrapper--spacer` does anything |
| `.actions a.icon`, `.link.with-padding`, `.lsp_popup .admonition…` | no LSP path emits `a.icon` or `.link`; admonitions come from other packages' popups, not LSP's |

The complete set of classes LSP itself hands to minihtml is: `wrapper`, `wrapper--spacer`,
`diagnostics`, the four severities, `color-muted`, `copy-icon`, `lightbulb`, `m-0`,
`signature-help-intro`, `message`, `actions`, `inlay-hint`, `lsp_sheet`, plus whatever mdpopups
emits for markdown (`highlight`, `admonition`, …).

**Singular, not plural.** `DIAGNOSTIC_STYLES` emits `error`, `warning`, `information`, `hint`.
Earlier versions of this file used `.errors`, `.warnings`, `.info`, `.hints`, which matched nothing —
the `background-color` in those rules never painted. Fixing the names is what made the red band
appear.

## Colors

`--redish` and friends are color-scheme variables, not something this file defines. With
`monokai-light.sublime-color-scheme` active they are declared twice, and inside a popup the second
declaration wins:

| Variable | Editor-wide | Inside `.mdpopups .lsp_popup` |
| :--- | :--- | :--- |
| `--redish` | `#9b362b` (`variables`, line 12) | `#e4bbb2` (`--popup_redish`, remapped by `globals.popup_css`) |
| `--yellowish` | `#B28C00` | `#e4bbb2` — also remapped to `--popup_redish`, so warnings tint pink |
| `--greenish` | `#22863a` | `#BEE6BE` |
| `--bluish` | `#343e5e` | not remapped, stays `#343e5e` |
| `--foreground` | `#606060` (`globals.foreground` -> `var(textcolor)`) | same |

The remap is set on the `.lsp_popup` element, so every descendant inherits the popup value no matter
what order the stylesheets land in. It is scoped to that selector, so cases 5 and 7–15 keep the
editor-wide values — an annotation's `--redish` really is `#9b362b`.

Consequence: `color: var(--redish)` inside `.error` is `#e4bbb2` text on a `#e4bbb2 @ 25%` band —
pale on pale, unreadable. All four severities therefore keep `color: var(--foreground)` and let the
`background-color` carry the severity. To retune the band, change `--popup_redish` in the scheme's
`globals.popup_css`, not `--redish` in `Packages/User/monokai-light.sublime-color-scheme` — the
latter only moves the editor-wide value (squiggly scope `region.redish markup.error.lsp`,
annotations, syntax rules) and is shadowed inside the popup.
