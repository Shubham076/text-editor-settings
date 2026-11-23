"""Settings and the on-disk cache."""

import json
import os
import time

import sublime

SETTINGS_FILE = "LeetCode.sublime-settings"


def get(key, default=None):
    return sublime.load_settings(SETTINGS_FILE).get(key, default)


def debug(message, *args):
    if get("debug", False):
        print("[LeetCode] " + message.format(*args))


def _cache_file(name):
    directory = os.path.join(sublime.cache_path(), "LeetCode")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name + ".json")


def read_cache(name, max_age=None):
    """The cached value, or None when it is missing, unreadable or older than ``max_age`` seconds."""
    try:
        with open(_cache_file(name), encoding="utf-8") as handle:
            entry = json.load(handle)
    except (OSError, ValueError):
        return None
    if max_age is not None and time.time() - entry.get("saved_at", 0) > max_age:
        return None
    return entry.get("value")


def write_cache(name, value):
    try:
        with open(_cache_file(name), "w", encoding="utf-8") as handle:
            json.dump({"saved_at": time.time(), "value": value}, handle)
    except OSError as error:
        print("[LeetCode] Could not write cache {}: {}".format(name, error))
