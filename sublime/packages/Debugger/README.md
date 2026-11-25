# Debugger

Standalone Sublime Text debugger using the new UI only. There is no legacy dashboard or
UI-switching setting.

The debug adapter backend is retained. See [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/).

## Installing locally

Place or symlink this directory into Sublime's Packages directory as `Debugger`, then use
**Debugger: Open** from the Command Palette. It uses the command and settings names of the `Debugger` package on Package Control, so only one
of the two can be installed.
It requires Sublime Text 4199 or later and the Python 3.8 plugin host, and the
[Terminus](https://github.com/randy3k/Terminus) package: tasks and terminals run in it. When
Terminus is missing or disabled the debugger says so as it loads and offers to install it.
Open selects the new debugger dashboard. Console and Terminal tabs appear when the selected
configuration creates the corresponding output; they are not shown unconditionally. Output
remains available after stopping and can be closed manually.

Settings are in **Preferences: Debugger Settings** (`Debugger.sublime-settings`). Startup is
opt-in so installing this package does not automatically open another debugger. Existing project
`debugger_configurations`, `debugger_compounds`, and `debugger_tasks` are supported unchanged.

Adapter installations and saved debugger state are stored under `Package Storage/Debugger`.
Install adapters through **Debugger: Install Adapters** as needed.
Use one active debugger per project window when testing source-gutter interactions.

UI module boundaries and visual checks are described in [Ui.md](Ui.md).
Run the regression suite with `python3 -B tests/run.py`.

# Getting Started
This project attempts to match Visual Studio Code's Debugger fairly closely so their documentation can be pretty helpful. See [https://code.visualstudio.com/docs/editor/debugging](https://code.visualstudio.com/docs/editor/debugging)

## Debuggers
This project comes with some pre-configured debuggers (They can be installed using ```Debugger: Install adapters```)

##### LLDB
- See https://github.com/vadimcn/vscode-lldb

##### Chrome
- See https://github.com/Microsoft/vscode-chrome-debug

##### Firefox
- See https://github.com/firefox-devtools/vscode-firefox-debug

##### Node
- For an overview see https://code.visualstudio.com/docs/nodejs/nodejs-debugging
- See https://github.com/microsoft/vscode-node-debug2

##### Python
- For an overview see https://code.visualstudio.com/docs/python/debugging
- See https://github.com/Microsoft/vscode-python
- The adapter is the `ms-python/debugpy` extension downloaded from Open VSX. Installs made by the
  earlier `vscode-python-debugger` installer are still found at their old path until you reinstall.

##### Go
- For an overview see https://github.com/golang/vscode-go/blob/master/docs/debugging.md
- See https://github.com/golang/vscode-go

##### PHP
- See https://github.com/felixfbecker/vscode-php-debug

##### Java
- Requires [LSP](https://packagecontrol.io/packages/LSP) and [LSP-jdtls](https://packagecontrol.io/packages/LSP-jdtls)
- See https://github.com/redhat-developer/vscode-java

##### Emulicious Debugger
- See https://github.com/Calindro/emulicious-debugger

## Setup
- Open the debug panel
  - from the command palette `Debugger: Open`

- Install a debug adapter by running: ```Debugger: Install adapter``` from the command palette.

- Add a configuration ```Debugger: Add Configuration``` from the command palette (or add one manually, see below).
  - Configurations are added to `debugger_configurations` to your sublime-project and use the same configuration format as Visual Studio Code
  - Consult the debugger specific documentation links above for creating a configuration for your debugger. Most debuggers come with some configuration snippets to choose from but I highly recommend looking at the documentation for the debugger.
  - Variable substitution: variables like `${file}` are supported but the list of supported variables differs from VSCode. The supported values are those listed at http://www.sublimetext.com/docs/build_systems.html#variables plus the VSCode-specific `${workspaceFolder}` that resolves to the path of the first workspace folder.

  - `envFile`: a path, or a list of paths, to dotenv files whose variables are laid under `env` for every adapter. What `env` sets wins, a later file wins over an earlier one, and a relative path is looked for from `cwd` or else the project folder.
  - `log`: `{"file": "${project_path}/logs/api.log", "append": false}` also saves what the program prints, stdout and stderr together, to a file. The file is started again on every run unless `append` is true, a relative path is looked for from `cwd` or else the project folder, and its folder is created. It works for the Console tab and for a Terminus terminal (`"console": "external"`), not for the terminal of the system.
  - `${input:id}` asks for a value when the configuration is started. The inputs are defined beside the configurations, with the names a launch.json uses:
    ```
    "debugger_inputs": [
        {"id": "testName", "type": "promptString", "description": "Test to run", "default": "test_login"},
        {"id": "environment", "type": "pickString", "options": ["local", "staging"]}
    ]
    ```
    `promptString` asks for text and `pickString` offers `options`, each text or `{"label": "shown", "value": "used"}`. An input is asked once per start however often it is used, in a task as well, and the next start is offered the last answer. Escape cancels the start. `"type": "command"` is not supported.

    How often it is asked is the `inputs_ask` setting, `"always"` (every start) or `"once"` (the first start, and the answer is used from then on), and an input can say for itself with `"ask": "once"` or `"ask": "always"`. `Debugger: Ask Inputs Again` forgets the answers, so the next start asks whatever was set.

- Your configuration will look something like the following but with some debugger specific fields.
```
"debugger_configurations" : [
    {
        "name" : "Name of your configuration",
        "request" : "launch"|"attach",
        "type" : "debugger name",
         ...
    }
]
```

- Start debugging
  - click the gear icon to select a configuration to use
  - click the play icon to start the debugger or run `Debugger: Start` (if no configuration is selected it will ask you to select or create one)

## Tasks
Tasks are based on sublime build_systems with more integration so they can be used more seamlessly while debugging. When errors occur while running a task they are reported in the debugger ui (problem detection is the same as sublime, you must add `file_regex` to your task)

see https://www.sublimetext.com/docs/build_systems.html

Tasks are basically the same as sublime builds but there are a few additional parameters.
`name` which will show up in the debugger UI and be the name of the panel

```
"debugger_tasks" : [
    {
        "name" : "Name of your task",
        "cmd" : ["task", "command"],
         ...
    }
]
```
- Tasks can be run with `Debugger: Run Tasks`
- A task that never ends, a server or a watcher, says what it prints once it is up with `ready_regex`. As a `pre_debug_task` the debugger starts on the first line of its output that matches, the task keeps running in a tab of its own, and it is stopped when the session it was started for ends. `ready_timeout` is how many seconds it is given (30, and 0 for no limit). A line the terminal wrapped onto several rows is matched as the line it was.
```
{
    "name" : "api server",
    "shell_cmd" : "npm run dev",
    "ready_regex" : "Listening on port \\d+",
    "ready_timeout" : 30
}
```
- You can run tasks before and after debugging by adding `pre_debug_task` or `post_debug_task` to your configuration specifying the name of the task to run, or a list of names: `"pre_debug_task": ["build", "api server"]`. They run one after the other in the order written; debugging starts after the last, and a `pre_debug_task` that fails stops the ones after it and the start.


## Settings
Settings can be adjusted with `Preferences: Debugger Settings`

for a full list of settings see [debugger.sublime-settings](Debugger.sublime-settings)

## Tests
The variable formatting logic in [modules/variable_format.py](modules/variable_format.py) — what a
variable row shows in the variables panel and the hover popup — runs without sublime, so it can be
tested from a terminal.

```sh
python3 tests/run.py             # run them
python3 tests/run.py --update    # regenerate the expected labels, then run them
```

No sublime, no debug adapter and no network: the values the tests replay were recorded from real
adapters and are checked in under `tests/fixtures/`. The whole suite takes about ten milliseconds,
so there is no reason not to run it on every change to the label logic.

- `--update` is for a deliberate change. Regenerate, **read the diff**, and commit it alongside the
  change: every line of it is a row that will look different in the panel. A diff in a language you
  were not working on is the thing to explain before committing.
- The fixtures cover go (delve), python (debugpy), and C and rust (lldb-dap). Adding a value shape or
  a newer adapter means re-recording — see [tests/README.md](tests/README.md) for how, and for what
  the tests are checking.

## Troubleshooting
- To fix issues with things aligning correctly or the last panel not being visible try adjusting the `internal_font_scale` and `internal_width_modifier` in the settings
- Look in the debug console for errors (usually red)
- Look in the sublime console for errors
- Try the same configuration/adapter in Visual Studio Code (There is a good chance your issue is with the adapter so check out the outstanding issues for it)
