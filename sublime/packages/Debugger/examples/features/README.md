# Feature tour

One project that shows what the debugger does, a configuration per feature, and the same small
program in five languages.

Open it with **Debugger: Example Projects** and pick `features.sublime-project`, or open
[features.sublime-project](features.sublime-project) as a project yourself. Install the adapters
it uses with **Debugger: Install Adapters**: `debugpy` for Python, `js` for Node, `go`, `java`
and `lldb` for Rust.

## The same program in five languages

`languages/` has one file per language. Each adds up an order (`total_price`) and, started with
the argument `fail`, tries to read a port from the text `eighty`.

| Configuration | File | Needs |
| :--- | :--- | :--- |
| Python | [languages/main.py](languages/main.py) | `python3` |
| Node | [languages/main.js](languages/main.js) | `node` |
| Go | [languages/main.go](languages/main.go) | `go`, and delve from the `go` adapter |
| Java | [languages/Main.java](languages/Main.java) | a JDK, and the `LSP` and `LSP-jdtls` packages |
| Rust | [languages/main.rs](languages/main.rs) | `rustc`; built by the `build rust` task into `build/` |

In each, put a breakpoint on the line marked `<- breakpoint here` and start the configuration:

- **Inline values**: every line of the function above the stopped line ends in the values of the
  variables it mentions, `subtotal = 59.97`. Off with `"inline_values": {"enabled": false}`, and drawn as
  the other keys of `inline_values` say.
- **Return values**: step out, and the line that called the function starts with what it
  returned.
- **Hover, watch, set a value**: as in any debugger.

## A configuration per feature

| Configuration | What it shows | What to do, and what to expect |
| :--- | :--- | :--- |
| Exception details (python), (node) | The exception under the line that raised it | Enable "Uncaught Exceptions" in the Breakpoints tab and start. It stops on the `raise`/`throw` with the exception, what caused it and a short trace |
| envFile | `envFile` laid under `env` | Start. `APP_MODE = local` (the second file wins), `APP_SECRET = from the configuration` (`env` wins) |
| Log file (console) | `"log": {"file": ...}` | Start, then open `logs/console.log`: stdout and stderr together, no colour codes |
| Log file (terminal, append) | The same from a terminal, with `"append": true` | Start twice. `logs/terminal.log` has both runs, and the long line is one line |
| Input prompts | `${input:id}` and `debugger_inputs` | Start. It asks for a text, then offers a list. The text is used twice and asked once. Start again: the text is asked for again, the list is not (`"ask": "once"`) until **Debugger: Ask Inputs Again** |
| Restart in place (node) | The adapter's own restart | Start, then press restart. The console says `Restarted` and the program prints a new pid |
| Ready task | A `pre_debug_task` that never ends | Break on the `print` of `tools/client.py` and start. The server gets a tab, debugging starts on `Listening on port 8765`, and the server is stopped when the session ends |
| Ready task (long line) | A ready line wider than the terminal | Start. It is matched as the line it was, however many rows it was drawn on |
| Two servers before one client | `"pre_debug_task": ["api server", "metrics server"]` | Start. The second server starts when the first is ready, the client after both, and each server has a tab under its own name |
| Ready task (too slow), (fails) | The two ways a ready task fails a start | Start. One gives up after `ready_timeout`, the other ends before it is ready. Both say why in the console, and the tab of the task ends on `[Stopped: ...]` or its own error |
| Two clients, one server (compound) | Two configurations sharing a task | Start. One server for both, a console tab for each client, and the server stops when the second client ends |

## What is in the folder

```
features.sublime-project   the configurations, tasks and inputs
languages/                 the same program in Python, Node, Go, Java and Rust
tools/                     what the feature configurations run
  server.py                a server that takes a while to come up (--delay, --port, --long, --fail)
  client.py                asks the servers for a page
  print_env.py             prints the environment variables of the envFile example
  log_output.py            writes to stdout and stderr, in colour, with one very long line
  echo_args.py             prints its arguments
  restart.js               prints its pid and ticks
.env, .env.local           the files of the envFile example
build/, logs/              made by the examples, and ignored by git
```

The servers listen on ports 8765 and 8766.
