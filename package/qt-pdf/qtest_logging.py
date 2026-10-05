# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keep Windows QTest output available to the upstream test child collector."""

import sys


def qtest_child_environment(environment, platform=None):
    """Copy the selected runtime environment without changing its caller."""
    child = dict(environment)
    if (sys.platform if platform is None else platform) == "win32":
        # Qt's plain test logger otherwise may route stdout to OutputDebugString.
        for name in tuple(child):
            if name.upper() == "QT_FORCE_STDERR_LOGGING":
                del child[name]
        child["QT_FORCE_STDERR_LOGGING"] = "1"
    return child
