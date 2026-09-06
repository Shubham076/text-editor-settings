import os
import subprocess

import sublime
import sublime_plugin


class SendSelectionContextCommand(sublime_plugin.TextCommand):
    """Build a context reference for the current selection(s) and copy it
    (or send it to a terminal running Claude Code).

    format:
      "mention"  -> @path lines 58-60        (Claude attaches the whole file)
      "snippet"  -> path lines 58-60: ```...``` (only the selected code, no file read)
      "ref"      -> @path:58-60              (plain text; Claude reads via Bash)
    target:
      "clipboard" | "tmux" | "terminus"
    """

    def run(self, edit, target="clipboard", format="mention",
            tmux_target="claude"):
        view = self.view
        path = view.file_name()
        if not path:
            sublime.status_message("Save the file first")
            return

        # Make the path relative to the project folder when possible
        window = view.window()
        for folder in (window.folders() if window else []):
            if path.startswith(folder + os.sep):
                path = os.path.relpath(path, folder)
                break

        refs = []
        for region in view.sel():
            start_row, _ = view.rowcol(region.begin())
            end_row, end_col = view.rowcol(region.end())
            # Full-line selections end at col 0 of the next line; back off one
            if not region.empty() and end_col == 0 and end_row > start_row:
                end_row -= 1
            start, end = start_row + 1, end_row + 1
            rng = "line %d" % start if start == end else "lines %d-%d" % (start, end)

            if format == "snippet":
                if region.empty():
                    region = view.line(region)
                snippet = view.substr(region).rstrip("\n")
                refs.append("%s %s:\n```\n%s\n```" % (path, rng, snippet))
            elif format == "ref":
                if start == end:
                    refs.append("@%s:%d" % (path, start))
                else:
                    refs.append("@%s:%d-%d" % (path, start, end))
            else:  # mention
                refs.append("@%s %s" % (path, rng))

        sep = "\n\n" if format == "snippet" else " "
        text = sep.join(refs) + ("\n" if format == "snippet" else " ")

        if target == "tmux":
            # Assumes Claude Code runs in a tmux window/session named `tmux_target`
            subprocess.call(["tmux", "send-keys", "-t", tmux_target, "-l", text])
        elif target == "terminus":
            # Requires the Terminus package with a terminal open in Sublime
            try:
                window.run_command("terminus_send_string", {"string": text})
            except Exception:
                sublime.set_clipboard(text)
                sublime.status_message(
                    "No live Terminus terminal - copied to clipboard instead")
                return
            # terminus_send_string reveals the terminal but leaves the caret in
            # the editor; move focus so you can keep typing the prompt.
            sublime.set_timeout(lambda: focus_terminus(window), 0)
        else:
            sublime.set_clipboard(text)

        sublime.status_message("Context: " + text.strip().splitlines()[0])


def focus_terminus(window):
    """Give keyboard focus to the Terminus terminal in `window`, preferring an
    open panel over a tab."""
    if not window:
        return
    active = window.active_panel()
    names = ([active] if active else []) + list(window.panels())
    seen = set()
    for panel in names:
        if panel in seen:
            continue
        seen.add(panel)
        view = window.find_output_panel(panel.replace("output.", ""))
        if view and view.settings().get("terminus_view"):
            window.focus_view(view)
            return
    for view in window.views():
        if view.settings().get("terminus_view"):
            window.focus_view(view)
            return
