"""Run blocking work off the UI thread."""

import threading
import traceback

import sublime

from ..core.errors import LeetCodeError


def run_async(work, on_done, on_error=None):
    """Call ``work()`` on a worker thread, then ``on_done(result)`` on the main thread.

    A failure goes to ``on_error(message)`` on the main thread, or to an error dialog.
    """
    def target():
        try:
            result = work()
        except LeetCodeError as error:
            message = str(error)
        except Exception as error:  # a bug, not a LeetCode failure: keep the traceback
            traceback.print_exc()
            message = ("LeetCode hit an unexpected error: {}\n\nThis is a bug in the package. The "
                       "full traceback is in the console (View > Show Console).".format(error))
        else:
            sublime.set_timeout(lambda: on_done(result))
            return
        sublime.set_timeout(lambda: (on_error or sublime.error_message)(message))

    threading.Thread(target=target, daemon=True).start()
