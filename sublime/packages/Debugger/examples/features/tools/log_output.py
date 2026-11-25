"""Log file: writes to stdout and stderr, in colour, and one very long line.

Expected in the log file: every line below, in order, without colour codes, and the long
line as one line however narrow the terminal was.
"""

import sys
import time

print("stdout: starting", flush=True)
print("stderr: a warning", file=sys.stderr, flush=True)
print("\033[32mstdout: this line is green in the console\033[0m", flush=True)
print("stdout: a long line " + "0123456789 " * 30 + "end of the long line", flush=True)
for step in range(3):
    print(f"stdout: step {step + 1}/3", flush=True)
    time.sleep(0.5)
print("stderr: done", file=sys.stderr, flush=True)
