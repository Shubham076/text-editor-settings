"""envFile: prints what the configuration's `envFile` and `env` put in the environment.

Expected:
    APP_NAME    = features               (from .env)
    APP_MODE    = local                  (.env.local wins over .env)
    APP_SECRET  = from the configuration (the configuration's `env` wins over both files)
    APP_QUOTED  = two words # not a comment
"""

import os

for key in ("APP_NAME", "APP_MODE", "APP_SECRET", "APP_QUOTED"):
    print(f"{key:<11} = {os.environ.get(key, '<not set>')}")
