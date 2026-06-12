# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Headless test entrypoint for the media extension:

    blender --background --factory-startup --python-exit-code 1 \\
        --python tests/bl_run.py -- -v
"""

__all__ = ()

import os
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MEDIA_DIR = os.path.dirname(_TESTS_DIR)

if _MEDIA_DIR not in sys.path:
    sys.path.insert(0, _MEDIA_DIR)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    loader = unittest.TestLoader()
    suite = loader.discover(_TESTS_DIR, pattern="test_*.py", top_level_dir=_MEDIA_DIR)
    runner = unittest.TextTestRunner(verbosity=2 if "-v" in argv else 1)
    result = runner.run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
