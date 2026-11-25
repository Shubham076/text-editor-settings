"""Talks to server.py. Fails with "connection refused" if it is started before the server is up.

    python3 client.py [PORT ...]     one request to each port, 8765 when none is given
"""

import sys
import urllib.request


def main():
    ports = [int(port) for port in sys.argv[1:]] or [8765]
    for port in ports:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            body = response.read().decode()
        print(f"server on {port} said:", body.strip())  # <- a breakpoint here keeps the session, and the servers, alive


if __name__ == "__main__":
    main()
