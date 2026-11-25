"""A server that takes a while to come up, for testing `ready_regex`.

    python3 -u server.py [--delay SECONDS] [--long] [--fail] [--port PORT] [--name NAME]

--delay  seconds of "starting" before it listens (default 3)
--long   prints the ready line after a long prefix, so the terminal wraps it over rows
--fail   exits with an error instead of listening
"""

import argparse
import http.server
import sys
import time

PORT = 8765


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"hello from the api server\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # one write, so two requests handled at the same moment cannot mix their lines
        sys.stdout.write("[request] " + format % args + "\n")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--fail", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--name", default="api")
    options = parser.parse_args()

    print(f"[{options.name}] starting", flush=True)
    steps = max(1, int(options.delay))
    for step in range(steps):
        print(f"[{options.name}] warming up {step + 1}/{steps}", flush=True)
        time.sleep(options.delay / steps)

    if options.fail:
        print(f"[{options.name}] simulated startup failure: this task is meant to fail like this", flush=True)
        sys.exit(1)

    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", options.port), Handler)

    # "routes registered" is at the start of the line and "Listening" at its end, some 230
    # characters later: on a terminal narrower than that they are on different rows
    prefix = f"[{options.name}] routes registered, " + "warming caches, " * 12 if options.long else f"[{options.name}] "
    print(f"{prefix}Listening on port {options.port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"[{options.name}] stopped", flush=True)


if __name__ == "__main__":
    main()
