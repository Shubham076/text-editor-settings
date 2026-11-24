"""LeetCode for Sublime Text: browse problems, run them against LeetCode's judge, submit.

Sublime only loads modules at the package root, so this file pulls in every command and
event listener from the ``ui`` package. ``core`` holds the logic that needs no editor.

Sublime reloads this file when it changes, but not the modules it imports: Python keeps
those cached. Dropping them first means saving this file reloads the whole package, so a
change under ``core`` or ``ui`` takes effect without restarting Sublime.
"""

import sys

for _name in [name for name in sys.modules if name.startswith(__package__ + ".") and name != __name__]:
    del sys.modules[_name]

from .ui.problems import (  # noqa: F401
    LeetcodeRefreshProblemsCommand,
    LeetcodeSearchCommand,
    LeetcodeShowProblemsCommand,
)
from .ui.solution import (  # noqa: F401
    LeetcodeAddTestCaseCommand,
    LeetcodeOpenProblemCommand,
    LeetcodeRunTestsCommand,
    LeetcodeShowTestCasesCommand,
    LeetcodeSubmitSolutionCommand,
)
from .ui.test_panel import LeetcodeTestPanelListener  # noqa: F401
from .ui.views import LeetcodeReplaceHeaderCommand, LeetcodeSetTextCommand  # noqa: F401
