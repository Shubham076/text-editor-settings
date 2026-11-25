"""Input prompts: prints the arguments the configuration was started with.

Expected: starting asks "What to say" and then "Which environment?" as a list. The text is
used twice in the arguments and asked once. Escape on either cancels the start.
"""

import sys

print("arguments:", sys.argv[1:])
